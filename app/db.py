"""SQLite access.

One database file on a mounted volume is the only datastore. Connections are
opened per request rather than shared, so the worker and the API never contend
on a single handle.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
-- An Invite Token is one person's credential, minted and revoked on its own.
-- Only the digest of the secret half is kept: the token is shown once, when it
-- is minted, and the database can never give it back.
CREATE TABLE IF NOT EXISTS invite (
    id                TEXT PRIMARY KEY,
    person            TEXT NOT NULL,
    secret_hash       TEXT NOT NULL,
    revoked_at        REAL,
    created_at        REAL NOT NULL
);

-- Sessions live here rather than in the process, so that a restart does not
-- sign everybody out and truncating this table does.
CREATE TABLE IF NOT EXISTS session (
    id_hash           TEXT PRIMARY KEY,
    invite_id         TEXT NOT NULL REFERENCES invite(id) ON DELETE CASCADE,
    created_at        REAL NOT NULL,
    -- Absolute, and never extended by use.
    expires_at        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS session_invite_idx ON session(invite_id);

-- Failed sign-ins, per address. In the database with everything else because a
-- lockout held in memory is lifted by the restart an attacker can cause.
CREATE TABLE IF NOT EXISTS login_failure (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    address           TEXT NOT NULL,
    failed_at         REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS login_failure_address_idx ON login_failure(address, failed_at);

-- A Deck is the long-lived thing a user builds up over a term. Jobs come and go
-- against it; it owns the Card Ledger and outlives all of them.
CREATE TABLE IF NOT EXISTS deck (
    id                TEXT PRIMARY KEY,
    invite_id         TEXT REFERENCES invite(id),
    name              TEXT NOT NULL,
    -- Every export stamps strictly later than the last. Anki's default import
    -- is "update if newer" on note modification time, so an export that does
    -- not advance is filed as a duplicate and silently changes nothing.
    last_exported_at  REAL NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS job (
    deck_id           TEXT REFERENCES deck(id),
    id                TEXT PRIMARY KEY,
    -- Which Invite Token created it. Attribution is the point: it is what makes
    -- spend somebody's rather than the application's.
    invite_id         TEXT REFERENCES invite(id),
    state             TEXT NOT NULL,
    error             TEXT,
    plan_json         TEXT,
    -- Consecutive expensive runs that produced nothing. Incremented before the
    -- first Anthropic call of a run and reset when the job actually advances,
    -- so a crash-loop is bounded even though the crash itself runs no code.
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt_at   REAL,
    -- What the admission gate measured. Tokens, because that is what is
    -- billed; pages are neither available for every format nor predictive.
    input_tokens      INTEGER,
    -- The process instance that last claimed this job. On one machine, a job
    -- claimed by anyone other than the booting process has no live worker.
    worker_id         TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A Source is one uploaded file belonging to a Job.
CREATE TABLE IF NOT EXISTS source (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    filename          TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    byte_size         INTEGER NOT NULL,
    -- Set once the source has been uploaded to the Files API. Kept so a resumed
    -- job references the file it already sent instead of uploading it again --
    -- and so the document block is byte-identical across attempts, which is
    -- what keeps the cached prefix readable.
    file_id           TEXT,
    -- Where the converted PDF landed, if this source needed converting.
    -- Converted once and remembered, so a resumed job rebuilds a byte-identical
    -- document block rather than a fresh conversion the cache cannot match.
    converted_path    TEXT,
    position          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS source_job_idx ON source(job_id, position);

-- Pass 2's unit of work and unit of recovery: one row per (job_id, topic_id),
-- carrying its own status and attempt count. Its card payload is the card rows
-- keyed by the same pair, replaced transactionally on every attempt.
CREATE TABLE IF NOT EXISTS topic (
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    topic_id          TEXT NOT NULL,
    position          INTEGER NOT NULL,
    status            TEXT NOT NULL,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    -- The planned Topic itself, so a retry can be built without re-reading a
    -- plan the user may since have edited.
    topic_json        TEXT NOT NULL,
    PRIMARY KEY (job_id, topic_id)
);

-- The Card Ledger in embryo. `card_uuid` is passed to genanki as the note GUID,
-- which is what makes a re-import update in place rather than duplicate.
CREATE TABLE IF NOT EXISTS card (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    -- Not globally unique: a card that survives into a later Job keeps its
    -- uuid, because that identity is exactly what makes the re-import land
    -- on the note the user has been reviewing. Unique within a Job.
    card_uuid         TEXT NOT NULL,
    topic_id          TEXT NOT NULL,
    deck_path         TEXT NOT NULL,
    note_type         TEXT NOT NULL,
    front             TEXT NOT NULL,
    back              TEXT NOT NULL,
    -- Self-reported by the model. It cannot be verified: citations and
    -- structured outputs are mutually exclusive, and this pipeline needs the
    -- schema more than it needs provenance.
    source_page       INTEGER,
    difficulty        TEXT NOT NULL DEFAULT 'medium',
    -- Ledger columns. These are the part that is never purged: a few hundred
    -- bytes a card, and the only thing that makes a re-import update rather
    -- than duplicate.
    deck_id           TEXT REFERENCES deck(id),
    -- Normalised question text. The anchor a later run is matched against, kept
    -- separately from `front` so that an edit does not move the anchor.
    question_fingerprint TEXT,
    -- What was last actually written into an .apkg. A card whose text still
    -- equals this is omitted from the next export entirely, and an omitted note
    -- is an untouched note.
    last_exported_front  TEXT,
    last_exported_back   TEXT,
    exported_at          REAL,
    -- What the model said this card revises, before the server checked it.
    -- Kept alongside the verdict so a rejected claim is visible rather than
    -- merely absent.
    claimed_card_uuid    TEXT,
    match_rejected_reason TEXT,
    -- The card this one repeats, if any. Flagged rather than deleted: telling a
    -- genuine duplicate from two questions that merely read alike is a
    -- judgement the user is better placed to make.
    duplicate_of         TEXT,
    retired_at           REAL,
    -- True when the model asked for a cloze card but gave no deletion marker.
    -- Kept rather than silently corrected: a topic that keeps doing this is a
    -- prompt problem, and hiding it hides the signal.
    downgraded        INTEGER NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL,
    UNIQUE (job_id, card_uuid)
);

CREATE INDEX IF NOT EXISTS card_deck_idx ON card(deck_id, card_uuid);

CREATE INDEX IF NOT EXISTS card_job_idx ON card(job_id, position);

-- Progress, as a durable record rather than a live one. A row is appended in
-- the same transaction as the change it reports, so an event exists exactly
-- when the change it describes survived — which is what lets a client that was
-- never connected reconstruct the whole run. `id` is the SSE event id, handed
-- back by a reconnecting client as `Last-Event-ID`.
CREATE TABLE IF NOT EXISTS job_event (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    data_json         TEXT NOT NULL,
    created_at        REAL NOT NULL
);

-- One row per Anthropic call. Cost is derived from these rather than estimated,
-- so "what did this job cost" is answered from what the API reported and not
-- from what we hoped it would be.
CREATE TABLE IF NOT EXISTS api_call (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                        TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    pass_name                     TEXT NOT NULL,
    topic_id                      TEXT,
    model                         TEXT NOT NULL,
    input_tokens                  INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens                 INTEGER NOT NULL DEFAULT 0,
    created_at                    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS api_call_job_idx ON api_call(job_id, id);

CREATE INDEX IF NOT EXISTS job_event_job_idx ON job_event(job_id, id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # The worker writes checkpoints on its own connection while requests read on
    # theirs; without this a checkpoint racing a read fails instantly instead of
    # waiting the few milliseconds the other statement needs.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Run a unit of work atomically.

    Connections are opened in autocommit mode, so anything that must be
    all-or-nothing — a checkpoint, an attempt claim — has to say so explicitly.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def backup_to(db_path: Path, destination: Path) -> int:
    """Copy the database consistently while it is in use.

    `VACUUM INTO` takes its own read transaction, so the copy is a coherent
    point-in-time image rather than a torn file — which a plain file copy of a
    WAL-mode database is not.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    conn = connect(db_path)
    try:
        conn.execute("VACUUM INTO ?", (str(destination),))
    finally:
        conn.close()
    return destination.stat().st_size


def initialise(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
