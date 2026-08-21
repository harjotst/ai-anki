"""The Card Ledger: what a Deck knows about its own cards, permanently.

This is the smallest part of the system and the one that must never be lost. It
is what lets a regeneration months later recognise the cards a user has been
reviewing, instead of handing them a second copy of their own deck.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import sqlite3
import time
import uuid

_WHITESPACE = re.compile(r"\s+")
_MARKUP = re.compile(r"<[^>]+>")
_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}")

# The riskiest number in the system. A claimed match below this is refused and
# the card is treated as new. Too permissive and a long review interval ends up
# attached to a question the user never saw; too strict and their deck quietly
# duplicates. Deliberately a named constant with tests either side of it.
MATCH_THRESHOLD = 0.55


def normalise(front: str) -> str:
    text = _CLOZE.sub(r"\1", front or "")
    text = _MARKUP.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip().lower()


def similarity(left: str, right: str) -> float:
    """How alike two questions are, between 0 and 1.

    A revision rewords the question; a different card asks a different one. This
    separates those two cases, and it is the only thing standing between a
    mistaken claim and corrupted review history.
    """
    return difflib.SequenceMatcher(None, normalise(left), normalise(right)).ratio()


def fingerprint(front: str) -> str:
    """A stable handle for "the question this card asks".

    Normalised so that reformatting, re-wrapping or re-marking a cloze does not
    look like a different question. It anchors identity across regenerations;
    it is deliberately not the card's content hash, because content is expected
    to drift while identity is not.
    """
    return hashlib.sha256(normalise(front).encode("utf-8")).hexdigest()[:32]


def create_deck(conn: sqlite3.Connection, name: str, invite_id: str | None) -> str:
    deck_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO deck (id, invite_id, name, created_at) VALUES (?, ?, ?, ?)",
        (deck_id, invite_id, name, time.time()),
    )
    return deck_id


def deck_exists(conn: sqlite3.Connection, deck_id: str, invite_id: str | None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM deck WHERE id = ? AND (invite_id IS ? OR invite_id = ?)",
        (deck_id, invite_id, invite_id),
    ).fetchone()
    return row is not None


def entries(conn: sqlite3.Connection, deck_id: str) -> list[dict]:
    # One entry per card identity, not per generated row. A card that survives
    # into a later Job appears once, as its most recent generation — the ledger
    # describes the deck, not the history of runs against it.
    rows = conn.execute(
        "SELECT card_uuid, deck_path, note_type, question_fingerprint,"
        " last_exported_front, last_exported_back, exported_at, retired_at, MAX(id) AS row_id"
        " FROM card WHERE deck_id = ? GROUP BY card_uuid"
        " ORDER BY exported_at IS NULL, exported_at, row_id",
        (deck_id,),
    ).fetchall()
    return [{k: v for k, v in dict(row).items() if k != "row_id"} for row in rows]


def existing_by_fingerprint(conn: sqlite3.Connection, deck_id: str) -> dict[str, dict]:
    """Every already-exported card in this deck, keyed by what it asks.

    Only exported cards count: a card that was generated but never packaged has
    never reached the user's collection, so nothing about it is frozen yet.
    """
    rows = conn.execute(
        "SELECT card_uuid, deck_path, note_type, question_fingerprint,"
        " last_exported_front, last_exported_back FROM card"
        " WHERE deck_id = ? AND exported_at IS NOT NULL AND retired_at IS NULL",
        (deck_id,),
    ).fetchall()
    return {row["question_fingerprint"]: dict(row) for row in rows}


def exported_cards(conn: sqlite3.Connection, deck_id: str, topic_id: str | None = None) -> list[dict]:
    """The cards this deck has actually put in front of the user.

    Only exported, non-retired cards. Anything else has never reached their
    collection, so there is nothing there to update or to protect.
    """
    sql = (
        "SELECT card_uuid, topic_id, deck_path, note_type, last_exported_front,"
        " question_fingerprint, last_exported_back, MAX(id) AS row_id FROM card"
        " WHERE deck_id = ? AND exported_at IS NOT NULL AND retired_at IS NULL"
    )
    params: list = [deck_id]
    if topic_id is not None:
        sql += " AND topic_id = ?"
        params.append(topic_id)
    sql += " GROUP BY card_uuid"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def resolve_claim(prior: dict | None, front: str, note_type: str) -> tuple[bool, str | None]:
    """Decide whether a claimed reuse may be honoured.

    Returns `(accepted, reason_if_not)`. Every rejection is a case where
    honouring the claim would have written over a card the user is reviewing.
    """
    if prior is None:
        return False, "claimed card does not belong to this deck and topic"
    if prior["note_type"] != note_type:
        # Anki reports a notetype change as conflicting and updates nothing, so
        # reusing the identity would silently do nothing at all.
        return False, "note type changed; a new card is minted instead"
    score = similarity(prior["last_exported_front"] or "", front)
    if score < MATCH_THRESHOLD:
        return False, f"claimed card asks a different question (similarity {score:.2f})"
    return True, None


def apply_claims(conn: sqlite3.Connection, job_id: str, deck_id: str, topic_id: str) -> None:
    """Honour the model's declared matches, once each has been verified.

    Position is never used. Zipping a new list onto an old one by index is the
    specific mistake that attaches somebody's ninety-day interval to a question
    they have never seen.
    """
    prior_by_uuid = {c["card_uuid"]: c for c in exported_cards(conn, deck_id, topic_id)}

    for row in conn.execute(
        "SELECT id, card_uuid, claimed_card_uuid, front, note_type FROM card"
        " WHERE job_id = ? AND topic_id = ?",
        (job_id, topic_id),
    ).fetchall():
        claimed = row["claimed_card_uuid"]
        if not claimed:
            # No claim, but an identical question is unambiguously the same
            # card — no similarity judgement is being made, so this is safe
            # where a fuzzy match would not be. It is what keeps an unchanged
            # card out of the next package when the model simply did not
            # bother to declare it.
            same = next(
                (
                    prior
                    for prior in prior_by_uuid.values()
                    if prior["question_fingerprint"] == fingerprint(row["front"])
                    and prior["note_type"] == row["note_type"]
                ),
                None,
            )
            if same is not None:
                conn.execute(
                    "UPDATE card SET card_uuid = ?, deck_path = ? WHERE id = ?",
                    (same["card_uuid"], same["deck_path"], row["id"]),
                )
            continue
        accepted, reason = resolve_claim(prior_by_uuid.get(claimed), row["front"], row["note_type"])
        if not accepted:
            conn.execute(
                "UPDATE card SET match_rejected_reason = ? WHERE id = ?", (reason, row["id"])
            )
            continue
        prior = prior_by_uuid[claimed]
        conn.execute(
            "UPDATE card SET card_uuid = ?, deck_path = ? WHERE id = ?",
            (prior["card_uuid"], prior["deck_path"], row["id"]),
        )


def retire_unclaimed(conn: sqlite3.Connection, job_id: str, deck_id: str, topic_id: str) -> int:
    """Stop claiming cards this run did not produce.

    Retired rather than deleted: the card stays in the user's collection and we
    simply never speak for it again. Its identifier is never reissued, because
    reissuing it would silently overwrite whatever it now holds.
    """
    still_here = {
        row["card_uuid"]
        for row in conn.execute(
            "SELECT card_uuid FROM card WHERE job_id = ? AND topic_id = ?", (job_id, topic_id)
        ).fetchall()
    }
    retired = 0
    for prior in exported_cards(conn, deck_id, topic_id):
        if prior["card_uuid"] in still_here:
            continue
        conn.execute(
            "UPDATE card SET retired_at = ? WHERE deck_id = ? AND card_uuid = ?",
            (time.time(), deck_id, prior["card_uuid"]),
        )
        retired += 1
    return retired


def unchanged_since_export(conn: sqlite3.Connection, deck_id: str, job_id: str) -> set[str]:
    """Cards whose text is byte-identical to what was last exported.

    These are omitted from the next package entirely. An omitted note is one
    Anki never sees, so the user's own edits, hand tags, leech flags and
    scheduling all survive without any merge logic existing at all.
    """
    # Scoped to the job being exported. Comparing every row in the deck would
    # match a revised card against its own predecessor — which shares its uuid
    # by design — and silently drop the revision from the package.
    prior_by_uuid = {c["card_uuid"]: c for c in exported_cards(conn, deck_id)}
    unchanged = set()
    for row in conn.execute(
        "SELECT card_uuid, front, back FROM card WHERE job_id = ?", (job_id,)
    ).fetchall():
        prior = prior_by_uuid.get(row["card_uuid"])
        if (
            prior is not None
            and prior["last_exported_front"] == row["front"]
            and prior.get("last_exported_back") == row["back"]
        ):
            unchanged.add(row["card_uuid"])
    return unchanged


TAG_WARNING = (
    "Updating a note replaces its tags wholesale — including any you added by "
    "hand, and Anki's own leech marker. Coloured flags survive an update, so "
    "use a flag for anything you want to keep."
)


def classify(conn: sqlite3.Connection, deck_id: str, job_id: str) -> dict:
    """Split this job's cards into what will update, add, and change nothing.

    Computed once and used by both the diff and the download, so what the user
    is shown and what they get cannot disagree.
    """
    prior_by_uuid = {c["card_uuid"]: c for c in exported_cards(conn, deck_id)}
    updates, additions, unchanged = [], [], []

    for row in conn.execute(
        "SELECT card_uuid, front, back FROM card WHERE job_id = ? ORDER BY position",
        (job_id,),
    ).fetchall():
        prior = prior_by_uuid.get(row["card_uuid"])
        if prior is None:
            additions.append(row["card_uuid"])
        elif (
            prior["last_exported_front"] == row["front"]
            and prior.get("last_exported_back") == row["back"]
        ):
            unchanged.append(row["card_uuid"])
        else:
            updates.append(
                {
                    "card_uuid": row["card_uuid"],
                    "existing_front": prior["last_exported_front"],
                    "existing_back": prior.get("last_exported_back"),
                    "proposed_front": row["front"],
                    "proposed_back": row["back"],
                }
            )

    return {"updates": updates, "additions": additions, "unchanged": unchanged}


def next_export_timestamp(conn: sqlite3.Connection, deck_id: str) -> float:
    """A stamp strictly later than the deck's previous export.

    Anki compares note modification times and treats a non-advancing export as a
    duplicate, changing nothing and reporting no error. Monotonicity is enforced
    here rather than trusted to the wall clock.
    """
    row = conn.execute("SELECT last_exported_at FROM deck WHERE id = ?", (deck_id,)).fetchone()
    previous = row["last_exported_at"] if row else 0.0
    stamp = max(time.time(), previous + 1.0)
    conn.execute("UPDATE deck SET last_exported_at = ? WHERE id = ?", (stamp, deck_id))
    return stamp


def mark_exported(conn: sqlite3.Connection, deck_id: str, cards, stamp: float) -> None:
    """Record what actually went into the package, so the next run can diff."""
    conn.executemany(
        "UPDATE card SET last_exported_front = ?, last_exported_back = ?,"
        " question_fingerprint = ?, exported_at = ? WHERE deck_id = ? AND card_uuid = ?",
        [
            (card.front, card.back, fingerprint(card.front), stamp, deck_id, card.card_uuid)
            for card in cards
        ],
    )
