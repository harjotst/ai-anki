"""Job lifecycle: the states, the legal moves between them, and the checkpoints.

Every expensive move is a committed transaction, because the process can die
between any two statements. A run is therefore never resumed from memory — it is
re-derived from the topic rows, which are the only record that survives.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app import db, dedup, ingestion, ledger, packaging

UPLOADED = "uploaded"
CONVERTING = "converting"
PLANNING = "planning"
PLAN_READY = "plan_ready"
GENERATING = "generating"
REVIEWING = "reviewing"
ASSEMBLING = "assembling"
COMPLETE = "complete"
FAILED = "failed"
INTERRUPTED = "interrupted"
DEAD = "dead"
CANCELLED = "cancelled"

# The one place a state change is allowed to be described. Anything not listed
# here is a bug in the caller, not a state the job is allowed to reach.
TRANSITIONS: dict[str, set[str]] = {
    UPLOADED: {CONVERTING, PLANNING, FAILED, CANCELLED},
    CONVERTING: {PLANNING, FAILED, INTERRUPTED, DEAD, CANCELLED},
    PLANNING: {PLAN_READY, FAILED, INTERRUPTED, DEAD, CANCELLED},
    PLAN_READY: {PLANNING, GENERATING, FAILED, CANCELLED},
    GENERATING: {REVIEWING, COMPLETE, FAILED, INTERRUPTED, DEAD, CANCELLED},
    REVIEWING: {GENERATING, ASSEMBLING, FAILED, CANCELLED},
    ASSEMBLING: {COMPLETE, FAILED, INTERRUPTED, DEAD, CANCELLED},
    FAILED: {PLANNING, GENERATING, DEAD, CANCELLED},
    INTERRUPTED: {PLANNING, GENERATING, DEAD, CANCELLED},
    # `dead` is terminal until a human clears it; `complete` and `cancelled`
    # are terminal outright.
    DEAD: {INTERRUPTED},
    COMPLETE: set(),
    CANCELLED: set(),
}

# States only a running worker can be in. A job found in one of these at boot
# was being worked on by a process that no longer exists.
IN_FLIGHT = frozenset({CONVERTING, PLANNING, GENERATING, ASSEMBLING})

# Per-topic status. `running` is as good as `pending` after a restart — the
# process that set it is gone.
TOPIC_PENDING = "pending"
TOPIC_RUNNING = "running"
TOPIC_DONE = "done"
TOPIC_FAILED = "failed"

# Three fruitless runs is the cap. The cost of getting this wrong is not an
# annoying loop but a repeated cache write: roughly $7 a cycle on a large
# document, several times a minute, until someone notices the invoice.
MAX_ATTEMPTS = 3
MIN_RESUME_BACKOFF_SECONDS = 60.0


class IllegalTransition(Exception):
    """A state change the job is not allowed to make."""


class ResumeRefused(Exception):
    """The job may not start an expensive run right now."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# Anki tags are whitespace-separated, so a tag may not contain any.
_UNSAFE_TAG = re.compile(r"[^A-Za-z0-9_-]+")


def safe_filename(name: str) -> str:
    """Reduce an uploaded filename to something that cannot escape its directory.

    Uploaded names are attacker-controlled; only the basename is kept and every
    character outside a conservative allowlist is replaced.
    """
    base = Path(name).name
    cleaned = _UNSAFE.sub("_", base).lstrip(".")
    return cleaned or "upload"


@dataclass(frozen=True)
class Job:
    id: str
    state: str
    error: str | None
    plan: dict | None
    source_filenames: list[str]
    # The Invite Token that created this job, which is who its spend belongs to.
    invite_id: str | None = None
    attempt_count: int = 0
    deck_id: str | None = None


@dataclass(frozen=True)
class Source:
    filename: str
    stored_path: Path
    file_id: str | None = None
    converted_path: str | None = None


@dataclass(frozen=True)
class Event:
    id: int
    kind: str
    data: dict


@dataclass(frozen=True)
class Topic:
    topic_id: str
    status: str
    attempt_count: int
    error: str | None
    topic: dict
    card_count: int


def record_event(conn: sqlite3.Connection, job_id: str, kind: str, data: dict) -> None:
    """Append one progress event.

    Always called from inside the transaction that makes the change it reports,
    so the log can never claim something the database does not also say — and,
    just as importantly, an attempt that rolled back leaves no trace of progress
    it did not make.
    """
    conn.execute(
        "INSERT INTO job_event (job_id, kind, data_json, created_at) VALUES (?, ?, ?, ?)",
        (job_id, kind, json.dumps(data), time.time()),
    )


def events_since(conn: sqlite3.Connection, job_id: str, after_id: int) -> list[Event]:
    """Everything the job has said since event `after_id`."""
    rows = conn.execute(
        "SELECT id, kind, data_json FROM job_event WHERE job_id = ? AND id > ? ORDER BY id",
        (job_id, after_id),
    ).fetchall()
    return [
        Event(id=row["id"], kind=row["kind"], data=json.loads(row["data_json"])) for row in rows
    ]


def record_topic_event(conn: sqlite3.Connection, job_id: str, topic_id: str) -> None:
    """Report a topic as the database now has it.

    The row is read back rather than assembled from what the caller meant to
    write, so the event describes the stored topic and not the intention.
    """
    row = conn.execute(
        "SELECT t.topic_id, t.status, t.attempt_count, t.error, t.topic_json,"
        " (SELECT COUNT(*) FROM card c WHERE c.job_id = t.job_id"
        "  AND c.topic_id = t.topic_id) AS card_count"
        " FROM topic t WHERE t.job_id = ? AND t.topic_id = ?",
        (job_id, topic_id),
    ).fetchone()
    if row is None:
        return
    record_event(
        conn,
        job_id,
        "topic",
        {
            "topic_id": row["topic_id"],
            "path": json.loads(row["topic_json"])["path"],
            "status": row["status"],
            "attempt_count": row["attempt_count"],
            "error": row["error"],
            "card_count": row["card_count"],
        },
    )


def create_job(
    conn: sqlite3.Connection,
    data_dir: Path,
    filename: str,
    content: bytes,
    *,
    invite_id: str,
    deck_id: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    stored_name = safe_filename(filename)
    job_dir = data_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    stored_path = job_dir / stored_name
    stored_path.write_bytes(content)

    # The job, its Sources and the first thing it says about itself land
    # together: a job the progress stream cannot account for from its first
    # state onwards is a job a reconnecting client would have to guess about.
    with db.transaction(conn):
        # A Job always runs against a Deck. Without one named, it starts a new
        # lineage; naming one continues the deck the user is already building.
        if deck_id is None:
            deck_id = ledger.create_deck(conn, name=safe_filename(filename), invite_id=invite_id)
        conn.execute(
            "INSERT INTO job (id, invite_id, deck_id, state) VALUES (?, ?, ?, ?)",
            (job_id, invite_id, deck_id, UPLOADED),
        )
        conn.execute(
            "INSERT INTO source (job_id, filename, stored_path, byte_size, position)"
            " VALUES (?, ?, ?, ?, ?)",
            (job_id, filename, str(stored_path), len(content), 0),
        )
        record_event(conn, job_id, "state", {"state": UPLOADED, "error": None})
    return job_id


def load_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute(
        "SELECT id, invite_id, deck_id, state, error, plan_json, attempt_count"
        " FROM job WHERE id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    sources = conn.execute(
        "SELECT filename FROM source WHERE job_id = ? ORDER BY position", (job_id,)
    ).fetchall()
    return Job(
        id=row["id"],
        state=row["state"],
        error=row["error"],
        deck_id=row["deck_id"],
        plan=json.loads(row["plan_json"]) if row["plan_json"] else None,
        source_filenames=[s["filename"] for s in sources],
        invite_id=row["invite_id"],
        attempt_count=row["attempt_count"],
    )


def list_jobs(conn: sqlite3.Connection, invite_id: str | None) -> list[dict]:
    """Every job this person started, newest first.

    Scoped to the invite rather than filtered client-side: the list is the only
    handle on a run once its tab is gone, so it is also the only place a job
    could leak from.
    """
    rows = conn.execute(
        "SELECT j.id, j.state, j.error, j.created_at, j.deck_id, d.name AS deck_name,"
        "       (SELECT filename FROM source s WHERE s.job_id = j.id"
        "         ORDER BY s.position LIMIT 1) AS source_filename,"
        "       (SELECT COUNT(*) FROM card c WHERE c.job_id = j.id) AS card_count"
        "  FROM job j LEFT JOIN deck d ON d.id = j.deck_id"
        " WHERE j.invite_id IS ?"
        " ORDER BY j.created_at DESC, j.rowid DESC",
        (invite_id,),
    ).fetchall()
    return [
        {
            "job_id": row["id"],
            "state": row["state"],
            "error": row["error"],
            "created_at": row["created_at"],
            "deck_id": row["deck_id"],
            "deck_name": row["deck_name"],
            "source_filename": row["source_filename"],
            "card_count": row["card_count"],
        }
        for row in rows
    ]


def transition(
    conn: sqlite3.Connection, job_id: str, new_state: str, *, error: str | None
) -> None:
    """Move a job to `new_state`, refusing any move the machine does not allow.

    `error` is written unconditionally so that clearing it is as explicit as
    setting it — a job that recovers must not keep displaying the reason it
    once failed.
    """
    row = conn.execute("SELECT state FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise IllegalTransition(f"no such job: {job_id}")
    current = row["state"]
    if new_state not in TRANSITIONS[current]:
        raise IllegalTransition(f"a job in '{current}' cannot move to '{new_state}'")
    conn.execute("UPDATE job SET state = ?, error = ? WHERE id = ?", (new_state, error, job_id))
    record_event(conn, job_id, "state", {"state": new_state, "error": error})


def begin_attempt(
    conn: sqlite3.Connection,
    job_id: str,
    state: str,
    *,
    worker_id: str,
    backoff_seconds: float,
    now: float | None = None,
) -> None:
    """Claim a job for a run that is about to spend money.

    Everything that guards the spend happens here, in one committed
    transaction, *before* the first Anthropic call: the transition, the
    crash-loop cap, the backoff, and the increment. A resume that counted itself
    afterwards would never count at all, because the failure mode this exists
    for kills the process mid-call.
    """
    now = time.time() if now is None else now
    with db.transaction(conn):
        row = conn.execute(
            "SELECT state, attempt_count, last_attempt_at FROM job WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise IllegalTransition(f"no such job: {job_id}")

        if row["state"] == DEAD:
            raise ResumeRefused(
                f"this job was abandoned after {row['attempt_count']} attempts and must be "
                "cleared explicitly before it runs again"
            )
        if state not in TRANSITIONS[row["state"]]:
            raise IllegalTransition(f"a job in '{row['state']}' cannot move to '{state}'")

        if row["attempt_count"] >= MAX_ATTEMPTS:
            transition(
                conn, job_id, DEAD, error=f"abandoned after {row['attempt_count']} attempts"
            )
            raise ResumeRefused(
                f"this job has used all {MAX_ATTEMPTS} attempts and must be cleared "
                "explicitly before it runs again"
            )

        waited = now - (row["last_attempt_at"] or 0.0)
        if row["attempt_count"] > 0 and waited < backoff_seconds:
            raise ResumeRefused(
                "too soon after the last attempt", retry_after=backoff_seconds - waited
            )

        transition(conn, job_id, state, error=None)
        conn.execute(
            "UPDATE job SET attempt_count = attempt_count + 1, last_attempt_at = ?,"
            " worker_id = ? WHERE id = ?",
            (now, worker_id, job_id),
        )


def recover_orphans(conn: sqlite3.Connection, worker_id: str) -> list[str]:
    """Deal with jobs left mid-flight by a machine that is no longer here.

    One machine, one worker: any job still claiming to be running that this
    process did not claim itself has no worker behind it. A job with attempts to
    spare becomes `interrupted` and can be resumed; one that has exhausted them
    is dead, because boot is exactly where a crash-loop would start its next
    lap.
    """
    orphans = conn.execute(
        "SELECT id, attempt_count FROM job WHERE state IN"
        f" ({','.join('?' * len(IN_FLIGHT))}) AND (worker_id IS NULL OR worker_id != ?)",
        (*sorted(IN_FLIGHT), worker_id),
    ).fetchall()

    for orphan in orphans:
        exhausted = orphan["attempt_count"] >= MAX_ATTEMPTS
        with db.transaction(conn):
            transition(
                conn,
                orphan["id"],
                DEAD if exhausted else INTERRUPTED,
                error=(
                    f"abandoned after {orphan['attempt_count']} attempts"
                    if exhausted
                    else "interrupted by a restart"
                ),
            )
            # A topic the dead machine had claimed was never finished by it.
            release_running_topics(conn, orphan["id"])
    return [orphan["id"] for orphan in orphans]


def release_running_topics(conn: sqlite3.Connection, job_id: str) -> None:
    """Hand back every topic claimed by a process that will not finish it.

    The ids are read before the update so each released topic can report itself:
    a client watching a restart must see the topic go back to pending, not be
    left displaying work that nobody is doing.
    """
    released = conn.execute(
        "SELECT topic_id FROM topic WHERE job_id = ? AND status = ?", (job_id, TOPIC_RUNNING)
    ).fetchall()
    conn.execute(
        "UPDATE topic SET status = ? WHERE job_id = ? AND status = ?",
        (TOPIC_PENDING, job_id, TOPIC_RUNNING),
    )
    for row in released:
        record_topic_event(conn, job_id, row["topic_id"])


def clear_dead_job(conn: sqlite3.Connection, job_id: str) -> None:
    """The explicit manual clearing a dead job requires before it runs again."""
    with db.transaction(conn):
        transition(conn, job_id, INTERRUPTED, error=None)
        conn.execute("UPDATE job SET attempt_count = 0 WHERE id = ?", (job_id,))


def load_sources(conn: sqlite3.Connection, job_id: str) -> list[Source]:
    rows = conn.execute(
        "SELECT filename, stored_path, file_id, converted_path FROM source"
        " WHERE job_id = ? ORDER BY position",
        (job_id,),
    ).fetchall()
    return [
        Source(
            filename=r["filename"],
            stored_path=Path(r["stored_path"]),
            file_id=r["file_id"],
            converted_path=r["converted_path"],
        )
        for r in rows
    ]


def replace_plan(conn: sqlite3.Connection, job_id: str, plan: dict) -> None:
    """Store an edited plan and rebuild the topic rows it implies."""
    with db.transaction(conn):
        conn.execute("UPDATE job SET plan_json = ? WHERE id = ?", (json.dumps(plan), job_id))
        conn.execute("DELETE FROM topic WHERE job_id = ?", (job_id,))
        conn.executemany(
            "INSERT INTO topic (job_id, topic_id, position, status, topic_json)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (job_id, topic["topic_id"], position, TOPIC_PENDING, json.dumps(topic))
                for position, topic in enumerate(plan["topics"])
            ],
        )
        record_event(conn, job_id, "plan", {"topics": len(plan["topics"])})


def update_card(conn: sqlite3.Connection, card_uuid: str, front: str, back: str) -> bool:
    updated = conn.execute(
        # Correcting a card is the strongest evidence there is that somebody
        # read it, so it counts as reviewed without a second click.
        "UPDATE card SET front = ?, back = ?, question_fingerprint = ?,"
        " reviewed_at = COALESCE(reviewed_at, ?) WHERE card_uuid = ?",
        (front, back, ledger.fingerprint(front), time.time(), card_uuid),
    )
    return updated.rowcount > 0


def delete_card(conn: sqlite3.Connection, card_uuid: str) -> bool:
    return conn.execute("DELETE FROM card WHERE card_uuid = ?", (card_uuid,)).rowcount > 0


def delete_topic_cards(conn: sqlite3.Connection, job_id: str, topic_id: str) -> int:
    return conn.execute(
        "DELETE FROM card WHERE job_id = ? AND topic_id = ?", (job_id, topic_id)
    ).rowcount


def reject_cards(conn: sqlite3.Connection, job_id: str, card_uuids: list[str]) -> int:
    """Drop several cards at once, and report how many were actually there.

    Scoped to the job so a uuid from somewhere else cannot ride along, and
    tolerant of uuids that have already gone: the screen the user clicked was
    always slightly out of date, and refusing the whole batch over one stale id
    would make the button unreliable exactly when it is most useful.
    """
    if not card_uuids:
        return 0
    marks = ",".join("?" * len(card_uuids))
    return conn.execute(
        f"DELETE FROM card WHERE job_id = ? AND card_uuid IN ({marks})",
        [job_id, *card_uuids],
    ).rowcount


def accept_cards(conn: sqlite3.Connection, job_id: str, card_uuids: list[str]) -> int:
    """Mark cards read. Idempotent: the first time is the one that counts."""
    if not card_uuids:
        return 0
    marks = ",".join("?" * len(card_uuids))
    return conn.execute(
        f"UPDATE card SET reviewed_at = COALESCE(reviewed_at, ?)"
        f" WHERE job_id = ? AND card_uuid IN ({marks})",
        [time.time(), job_id, *card_uuids],
    ).rowcount


def find_card(conn: sqlite3.Connection, card_uuid: str) -> dict | None:
    row = conn.execute(
        "SELECT job_id, topic_id, front, back, note_type FROM card WHERE card_uuid = ?",
        (card_uuid,),
    ).fetchone()
    return dict(row) if row else None


def topic_of(conn: sqlite3.Connection, job_id: str, topic_id: str) -> dict | None:
    row = conn.execute(
        "SELECT topic_json FROM topic WHERE job_id = ? AND topic_id = ?", (job_id, topic_id)
    ).fetchone()
    return json.loads(row["topic_json"]) if row else None


def sibling_topics(conn: sqlite3.Connection, job_id: str, topic_id: str) -> list[dict]:
    """The other topics in this plan, and what they own."""
    rows = conn.execute(
        "SELECT topic_json FROM topic WHERE job_id = ? AND topic_id != ? ORDER BY position",
        (job_id, topic_id),
    ).fetchall()
    return [json.loads(row["topic_json"]) for row in rows]


def existing_cards_for_topic(conn: sqlite3.Connection, job_id: str, topic_id: str) -> list[dict]:
    """What this job's Deck already has for this topic."""
    row = conn.execute("SELECT deck_id FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None or not row["deck_id"]:
        return []
    return ledger.exported_cards(conn, row["deck_id"], topic_id)


def purge_sources(conn: sqlite3.Connection, data_dir: Path, *, older_than_days: float) -> int:
    """Delete stored uploads older than the window. The ledger is untouched."""
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for row in conn.execute("SELECT id, stored_path FROM source").fetchall():
        path = Path(row["stored_path"])
        if not path.exists() or path.stat().st_mtime > cutoff:
            continue
        path.unlink()
        conn.execute("UPDATE source SET stored_path = ? WHERE id = ?", ("", row["id"]))
        removed += 1
    return removed


def record_usage(
    conn: sqlite3.Connection,
    job_id: str,
    pass_name: str,
    usage,
    *,
    topic_id: str | None = None,
    model: str | None = None,
) -> None:
    """Keep what one call actually cost, as the API reported it."""
    conn.execute(
        "INSERT INTO api_call (job_id, pass_name, topic_id, model, input_tokens,"
        " cache_creation_input_tokens, cache_read_input_tokens, output_tokens, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job_id,
            pass_name,
            topic_id,
            model or planning_model(),
            usage.input_tokens,
            usage.cache_write_tokens,
            usage.cache_read_tokens,
            usage.output_tokens,
            time.time(),
        ),
    )


def planning_model() -> str:
    """Fallback label when a caller did not name the model that was billed."""
    return "unknown"


def load_usage(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT pass_name, topic_id, model, input_tokens, cache_creation_input_tokens,"
        " cache_read_input_tokens, output_tokens FROM api_call WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def record_input_tokens(conn: sqlite3.Connection, job_id: str, input_tokens: int) -> None:
    conn.execute("UPDATE job SET input_tokens = ? WHERE id = ?", (input_tokens, job_id))


def documents_for(conn: sqlite3.Connection, job_id: str, provider) -> list[dict]:
    """Rebuild the document blocks both passes share.

    A resume happens in a process that never saw the first attempt, so this has
    to come from the stored Sources — and byte-identically, or the cached prefix
    pass 1 paid for is not the one pass 2 sends. An upload therefore happens at
    most once per source, ever, and its id is committed before it is used.
    """
    sources = load_sources(conn, job_id)
    known = {s.filename: s.file_id for s in sources if s.file_id}
    converted = {s.filename: s.converted_path for s in sources if s.converted_path}
    before_ids, before_converted = dict(known), dict(converted)

    blocks = ingestion.document_blocks(provider, sources, known, converted)

    for filename, file_id in known.items():
        if before_ids.get(filename) != file_id:
            conn.execute(
                "UPDATE source SET file_id = ? WHERE job_id = ? AND filename = ?",
                (file_id, job_id, filename),
            )
    for filename, path in converted.items():
        if before_converted.get(filename) != path:
            conn.execute(
                "UPDATE source SET converted_path = ? WHERE job_id = ? AND filename = ?",
                (path, job_id, filename),
            )
    return blocks


def interrupt_job(conn: sqlite3.Connection, job_id: str, reason: str) -> None:
    """Record a job as stopped by something outside it.

    A topic still marked `running` is released with it: the checkpoint is the
    last thing this process will say, so it must not leave a topic claiming to
    be worked on by nobody. Idempotent, because both the run loop and the drain
    that outran it may arrive here for the same job.
    """
    row = conn.execute("SELECT state FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None or row["state"] not in IN_FLIGHT:
        return
    with db.transaction(conn):
        transition(conn, job_id, INTERRUPTED, error=reason)
        release_running_topics(conn, job_id)


@dataclass(frozen=True)
class Card:
    card_uuid: str
    topic_id: str
    deck_path: str
    note_type: str
    front: str
    back: str
    source_page: int | None = None
    difficulty: str = "medium"
    downgraded: bool = False
    match_rejected_reason: str | None = None
    duplicate_of: str | None = None
    job_id: str | None = None
    reviewed: bool = False

    @property
    def tags(self) -> list[str]:
        """The searchable handles this card carries into Anki.

        Anki splits tags on whitespace, so every component is a slug, and `::`
        nests them the way it nests decks. The job tag is the one that matters
        operationally: it is how a whole bad batch is found and removed again.
        """
        tags = [f"topic::{_slug(self.topic_id)}", f"difficulty::{_slug(self.difficulty)}"]
        if self.source_page is not None:
            tags.append(f"page::{self.source_page}")
        if self.job_id:
            tags.append(f"aianki::job::{self.job_id}")
        if self.downgraded:
            tags.append("aianki::downgraded-cloze")
        return tags


def _slug(value: str) -> str:
    return _UNSAFE_TAG.sub("-", str(value).strip().lower()).strip("-") or "unknown"


def save_topic_cards(
    conn: sqlite3.Connection, job_id: str, topic: dict, cards: list[dict]
) -> None:
    """Checkpoint one topic: its cards and its status, or neither.

    The delete is what makes a retry a replacement. Without it a topic that runs
    twice — after a restart, or after the plan was revised — leaves both
    attempts in the deck.
    """
    topic_id = topic["topic_id"]
    deck_id = conn.execute("SELECT deck_id FROM job WHERE id = ?", (job_id,)).fetchone()["deck_id"]
    with db.transaction(conn):
        conn.execute("DELETE FROM card WHERE job_id = ? AND topic_id = ?", (job_id, topic_id))
        conn.executemany(
            "INSERT INTO card (job_id, deck_id, card_uuid, topic_id, deck_path, note_type,"
            " front, back, source_page, difficulty, downgraded, question_fingerprint,"
            " claimed_card_uuid, position)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    job_id,
                    deck_id,
                    uuid.uuid4().hex,
                    topic_id,
                    topic["path"],
                    packaging.effective_note_type(card["note_type"], card["front"]),
                    card["front"],
                    card["back"],
                    card.get("source_page"),
                    topic.get("difficulty", "medium"),
                    int(
                        card["note_type"] == "cloze"
                        and not packaging.has_cloze_marker(card["front"])
                    ),
                    ledger.fingerprint(card["front"]),
                    card.get("existing_card_id"),
                    position,
                )
                for position, card in enumerate(cards)
            ],
        )
        conn.execute(
            "UPDATE topic SET status = ?, error = NULL WHERE job_id = ? AND topic_id = ?",
            (TOPIC_DONE, job_id, topic_id),
        )
        # Cards asking a question this deck already exported take over that
        # card's identity, so the export updates rather than duplicates.
        if deck_id:
            # Declared by the model, then verified here. An unverified claim is
            # refused and the card becomes new rather than overwriting one the
            # user is already reviewing.
            ledger.apply_claims(conn, job_id, deck_id, topic_id)
            ledger.retire_unclaimed(conn, job_id, deck_id, topic_id)
        # Run over the whole job, because a repeat only exists relative to what
        # the other topics wrote.
        dedup.flag_duplicates(conn, job_id)
        record_topic_event(conn, job_id, topic_id)


def load_cards(conn: sqlite3.Connection, job_id: str) -> list[Card]:
    # Cards are ordered by their topic's place in the plan, then by their own
    # place within the topic, so a re-run of one topic cannot reshuffle the deck.
    rows = conn.execute(
        "SELECT c.card_uuid, c.topic_id, c.deck_path, c.note_type, c.front, c.back,"
        " c.source_page, c.difficulty, c.downgraded, c.match_rejected_reason,"
        " c.duplicate_of, c.reviewed_at"
        " FROM card c JOIN topic t ON t.job_id = c.job_id AND t.topic_id = c.topic_id"
        " WHERE c.job_id = ? ORDER BY t.position, c.position",
        (job_id,),
    ).fetchall()
    return [
        Card(
            **{
                **{k: v for k, v in dict(row).items() if k != "reviewed_at"},
                "downgraded": bool(row["downgraded"]),
                "reviewed": row["reviewed_at"] is not None,
                "job_id": job_id,
            }
        )
        for row in rows
    ]


def load_topics(conn: sqlite3.Connection, job_id: str) -> list[Topic]:
    rows = conn.execute(
        "SELECT t.topic_id, t.status, t.attempt_count, t.error, t.topic_json,"
        " (SELECT COUNT(*) FROM card c WHERE c.job_id = t.job_id"
        "  AND c.topic_id = t.topic_id) AS card_count"
        " FROM topic t WHERE t.job_id = ? ORDER BY t.position",
        (job_id,),
    ).fetchall()
    return [
        Topic(
            topic_id=row["topic_id"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            error=row["error"],
            topic=json.loads(row["topic_json"]),
            card_count=row["card_count"],
        )
        for row in rows
    ]


def unfinished_topics(conn: sqlite3.Connection, job_id: str) -> list[Topic]:
    return [t for t in load_topics(conn, job_id) if t.status != TOPIC_DONE]


def start_topic(conn: sqlite3.Connection, job_id: str, topic_id: str) -> None:
    """Claim a topic before its Anthropic call, never after it."""
    with db.transaction(conn):
        conn.execute(
            "UPDATE topic SET status = ?, attempt_count = attempt_count + 1"
            " WHERE job_id = ? AND topic_id = ?",
            (TOPIC_RUNNING, job_id, topic_id),
        )
        record_topic_event(conn, job_id, topic_id)


def fail_topic(conn: sqlite3.Connection, job_id: str, topic_id: str, error: str) -> None:
    with db.transaction(conn):
        conn.execute(
            "UPDATE topic SET status = ?, error = ? WHERE job_id = ? AND topic_id = ?",
            (TOPIC_FAILED, error, job_id, topic_id),
        )
        record_topic_event(conn, job_id, topic_id)


def fail_job(conn: sqlite3.Connection, job_id: str, error: str) -> None:
    # A state change and the event that reports it always commit together, so a
    # watching client can never be shown a job in a state the database has left.
    with db.transaction(conn):
        transition(conn, job_id, FAILED, error=error)


def save_plan(conn: sqlite3.Connection, job_id: str, plan: dict) -> None:
    """Store the Deck Plan and lay down one topic row per Topic.

    A new plan supersedes the old one, so topics start again from `pending` and
    cards belonging to topics the plan no longer contains are dropped. Cards of
    surviving topics are left for the per-topic transaction to replace.
    """
    topics = plan["topics"]
    with db.transaction(conn):
        conn.execute("UPDATE job SET plan_json = ? WHERE id = ?", (json.dumps(plan), job_id))
        transition(conn, job_id, PLAN_READY, error=None)
        # Reaching a plan is progress, so the crash-loop counter starts again.
        conn.execute("UPDATE job SET attempt_count = 0 WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM topic WHERE job_id = ?", (job_id,))
        conn.executemany(
            "INSERT INTO topic (job_id, topic_id, position, status, topic_json)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (job_id, topic["topic_id"], position, TOPIC_PENDING, json.dumps(topic))
                for position, topic in enumerate(topics)
            ],
        )
        placeholders = ",".join("?" * len(topics))
        conn.execute(
            f"DELETE FROM card WHERE job_id = ? AND topic_id NOT IN ({placeholders})",
            (job_id, *[topic["topic_id"] for topic in topics]),
        )
        # The plan reaching the client as events is what lets a watcher build the
        # topic list without asking for it, and a revised plan replace it.
        for topic in topics:
            record_topic_event(conn, job_id, topic["topic_id"])


def settle_job(conn: sqlite3.Connection, job_id: str) -> str:
    """Close out a generation run against what the topic rows actually say."""
    unfinished = unfinished_topics(conn, job_id)
    if unfinished:
        errors = [t.error for t in unfinished if t.error]
        fail_job(conn, job_id, "; ".join(errors) or "topics did not finish")
        return FAILED
    with db.transaction(conn):
        transition(conn, job_id, COMPLETE, error=None)
        conn.execute("UPDATE job SET attempt_count = 0 WHERE id = ?", (job_id,))
    return COMPLETE
