"""Postgres access.

The datastore moved off SQLite when the application grew accounts. One file on
one machine was the right shape while a Deck was regenerable and a lost volume
cost nothing but a re-run; it stopped being the right shape when the same volume
started holding people's logins and payment state.

Two deliberate choices about how this differs from the SQLite module it
replaces:

`row["column"]` still works, because the connection uses `dict_row`. Ninety-five
call sites read rows that way and none of them should have had to care which
database answered.

Placeholders are `%s` rather than `?`, rewritten at every one of the two hundred
call sites rather than translated at runtime. A wrapper that rewrote `?` on the
way past would have been a smaller diff and would have corrupted any query
holding a `?` inside a string literal, a LIKE pattern or a JSON operator.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

# Every moment in time is TIMESTAMPTZ. The SQLite schema stored some as float
# epochs and one as a `datetime('now')` string, and compared them in both Python
# and SQL -- which worked only because SQLite does not type-check. A single
# representation is the point: a timezone bug here surfaces as backups pruned
# early or a budget window resetting at the wrong hour, months later.
SCHEMA = """
-- One person. The id is the auth provider's own user id rather than a second
-- identifier of our own, because two identifiers for one person is how accounts
-- get orphaned: the day they disagree, one of them owns the decks and the other
-- owns the login.
--
-- Credentials are not here and never will be. The provider holds those; this
-- table holds everything about a person that is not a credential, which is what
-- makes a copy of this database useless as a set of working logins.
CREATE TABLE IF NOT EXISTS account (
    id                UUID PRIMARY KEY,
    email             TEXT,
    display_name      TEXT,
    -- Owner surfaces -- spend, purge, backup -- are a role on the account
    -- rather than a second credential carried separately. The first account in
    -- an empty database gets it; every promotion after that is a deliberate
    -- SQL statement, because an in-app "make admin" button is a
    -- privilege-escalation feature nobody asked for.
    is_admin          BOOLEAN NOT NULL DEFAULT FALSE,
    -- Short, shareable, and how somebody is added as a friend. Deliberately
    -- not their email: an endpoint that reports whether an address has an
    -- account tells anybody whether an address has an account, one guess at a
    -- time.
    friend_code       TEXT UNIQUE,
    created_at        TIMESTAMPTZ NOT NULL
);

-- A Deck is the long-lived thing a user builds up over a term. Jobs come and go
-- against it; it owns the Card Ledger and outlives all of them.
CREATE TABLE IF NOT EXISTS deck (
    id                TEXT PRIMARY KEY,
    account_id        UUID REFERENCES account(id),
    name              TEXT NOT NULL,
    -- Every export stamps strictly later than the last. Anki's default import
    -- is "update if newer" on note modification time, so an export that does
    -- not advance is filed as a duplicate and silently changes nothing.
    --
    -- NULL, not zero, for a deck nothing has been exported from. Zero would be
    -- 1970 once this column became a real timestamp, which reads as a date.
    last_exported_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS job (
    deck_id           TEXT REFERENCES deck(id),
    id                TEXT PRIMARY KEY,
    -- Whose job it is. Attribution is the point: it is what makes spend
    -- somebody's rather than the application's.
    account_id        UUID REFERENCES account(id),
    state             TEXT NOT NULL,
    error             TEXT,
    plan_json         TEXT,
    -- Consecutive expensive runs that produced nothing. Incremented before the
    -- first Anthropic call of a run and reset when the job actually advances,
    -- so a crash-loop is bounded even though the crash itself runs no code.
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt_at   TIMESTAMPTZ,
    -- What the admission gate measured. Tokens, because that is what is
    -- billed; pages are neither available for every format nor predictive.
    input_tokens      INTEGER,
    -- The process instance that last claimed this job. On one machine, a job
    -- claimed by anyone other than the booting process has no live worker.
    worker_id         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A Source is one uploaded file belonging to a Job.
CREATE TABLE IF NOT EXISTS source (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    filename          TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    byte_size         BIGINT NOT NULL,
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
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    exported_at          TIMESTAMPTZ,
    -- What the model said this card revises, before the server checked it.
    -- Kept alongside the verdict so a rejected claim is visible rather than
    -- merely absent.
    claimed_card_uuid    TEXT,
    match_rejected_reason TEXT,
    -- The card this one repeats, if any. Flagged rather than deleted: telling a
    -- genuine duplicate from two questions that merely read alike is a
    -- judgement the user is better placed to make.
    duplicate_of         TEXT,
    retired_at           TIMESTAMPTZ,
    -- When somebody actually read this card on the review screen. Null until
    -- they did, which is what lets a review of 164 cards be stopped half way
    -- through and resumed.
    reviewed_at          TIMESTAMPTZ,
    -- True when the model asked for a cloze card but gave no deletion marker.
    -- Kept rather than silently corrected: a topic that keeps doing this is a
    -- prompt problem, and hiding it hides the signal.
    downgraded        BOOLEAN NOT NULL DEFAULT FALSE,
    position          INTEGER NOT NULL,
    UNIQUE (job_id, card_uuid)
);

CREATE INDEX IF NOT EXISTS card_deck_idx ON card(deck_id, card_uuid);

CREATE INDEX IF NOT EXISTS card_job_idx ON card(job_id, position);

-- What the application taught for one Topic. One row per (job_id, topic_id),
-- the same key the cards use, because a lesson and the cards that reinforce it
-- are regenerated together or not at all.
--
-- Stored as JSON rather than shredded into columns. Nothing queries inside a
-- lesson -- it is read whole, by one person, for one topic -- and a schema
-- change would otherwise mean a migration for what is really a document.
CREATE TABLE IF NOT EXISTS lesson (
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    topic_id          TEXT NOT NULL,
    deck_path         TEXT NOT NULL,
    lesson_json       TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job_id, topic_id)
);

-- Every answer anybody has ever given, and the record everything about
-- studying is derived from. Append-only: a row is never updated and never
-- deleted, because the moment it is, offline sync needs conflict resolution,
-- leaderboards stop being recomputable, and the scheduler can never be
-- replaced.
--
-- `client_uuid` is chosen by the device that recorded the answer. It is what
-- makes a push idempotent: a client that lost the connection before the reply
-- can push again without answering twice, and the client is the only thing
-- that knows the two pushes were the same event.
CREATE TABLE IF NOT EXISTS review (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id        UUID NOT NULL REFERENCES account(id),
    client_uuid       TEXT NOT NULL,
    card_uuid         TEXT NOT NULL,
    -- FSRS's own scale: 1 again, 2 hard, 3 good, 4 easy.
    rating            SMALLINT NOT NULL,
    -- The device's clock, which orders one person's own history.
    reviewed_at       TIMESTAMPTZ NOT NULL,
    duration_ms       INTEGER,
    -- Ours. Anything competitive uses this one, because a client's clock is a
    -- thing a client controls.
    received_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (account_id, client_uuid)
);

CREATE INDEX IF NOT EXISTS review_card_idx ON review(account_id, card_uuid, reviewed_at);

-- One person's scheduling for one card. A projection of `review` and nothing
-- more: it exists because replaying a whole log on every query would be
-- wasteful, not because it is the record. It can be dropped and rebuilt at any
-- moment, and a test asserts precisely that.
CREATE TABLE IF NOT EXISTS study_card (
    account_id        UUID NOT NULL REFERENCES account(id),
    card_uuid         TEXT NOT NULL,
    deck_id           TEXT REFERENCES deck(id),
    -- FSRS state: 1 learning, 2 review, 3 relearning.
    state             SMALLINT NOT NULL DEFAULT 1,
    step              INTEGER,
    stability         DOUBLE PRECISION,
    difficulty        DOUBLE PRECISION,
    due               TIMESTAMPTZ NOT NULL,
    last_review       TIMESTAMPTZ,
    reps              INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, card_uuid)
);

CREATE INDEX IF NOT EXISTS study_due_idx ON study_card(account_id, deck_id, due);

-- Who studies a deck they did not make. The deck's own `account_id` is still
-- the owner -- whoever uploaded the material and can add more of it -- and this
-- is everybody else.
--
-- Joined, not copied. Both people study the same card identities, which is the
-- only arrangement in which "who has mastered this topic" is a question about
-- one thing rather than two things that resemble each other. Scheduling has
-- always been keyed on (account, card), so separate histories over shared cards
-- needed nothing new.
CREATE TABLE IF NOT EXISTS deck_member (
    deck_id           TEXT NOT NULL REFERENCES deck(id) ON DELETE CASCADE,
    account_id        UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    shared_by         UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    created_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (deck_id, account_id)
);

CREATE INDEX IF NOT EXISTS deck_member_account_idx ON deck_member(account_id);

-- One row per friendship, never two. Storing both directions means two rows
-- that can disagree, and eventually they do: somebody removes a friend and half
-- of it is left behind. The pair is ordered so the row is unique whichever way
-- round it was created, and `requested_by` is what stops somebody accepting
-- their own request.
CREATE TABLE IF NOT EXISTS friendship (
    account_low       UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    account_high      UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    state             TEXT NOT NULL,
    requested_by      UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    created_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_low, account_high),
    CHECK (account_low < account_high)
);

CREATE INDEX IF NOT EXISTS friendship_high_idx ON friendship(account_high);

-- Progress, as a durable record rather than a live one. A row is appended in
-- the same transaction as the change it reports, so an event exists exactly
-- when the change it describes survived -- which is what lets a client that was
-- never connected reconstruct the whole run. `id` is the SSE event id, handed
-- back by a reconnecting client as `Last-Event-ID`.
CREATE TABLE IF NOT EXISTS job_event (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id            TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    data_json         TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

-- One row per Anthropic call. Cost is derived from these rather than estimated,
-- so "what did this job cost" is answered from what the API reported and not
-- from what we hoped it would be.
CREATE TABLE IF NOT EXISTS api_call (
    id                            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id                        TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    pass_name                     TEXT NOT NULL,
    topic_id                      TEXT,
    model                         TEXT NOT NULL,
    input_tokens                  INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens                 INTEGER NOT NULL DEFAULT 0,
    created_at                    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS api_call_job_idx ON api_call(job_id, id);

CREATE INDEX IF NOT EXISTS job_event_job_idx ON job_event(job_id, id);
"""


def dsn() -> str:
    """Where the database is. One place reads the environment."""
    return os.environ["AI_ANKI_DATABASE_URL"]


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection shaped like the one the application already expects.

    Autocommit, because the code opens connections per request and says
    explicitly when something must be atomic -- the same contract the SQLite
    module had, so `db.transaction` still means what it meant.
    """
    return psycopg.connect(url or dsn(), autocommit=True, row_factory=dict_row)


@contextmanager
def transaction(conn: psycopg.Connection):
    """Run a unit of work atomically.

    Plain `BEGIN`, where SQLite needed `BEGIN IMMEDIATE`. The escalation existed
    to take the write lock up front, because SQLite would otherwise fail a
    deferred transaction that turned out to want one. Postgres takes row locks
    as it goes and has no such failure mode.
    """
    with conn.transaction():
        yield conn


def initialise(url: str | None = None) -> None:
    conn = connect(url)
    try:
        conn.execute(SCHEMA)
    finally:
        conn.close()


# --- the boundary between float seconds and real timestamps --------------
#
# The application's own vocabulary is float epoch seconds: a TTL is a number of
# seconds, a lockout window is a number of seconds, and Anki's note modification
# time is an epoch. The database's vocabulary is TIMESTAMPTZ. These two convert
# between them, and they are the ONLY place that conversion happens -- which is
# what makes "is this value a moment or a duration" answerable by reading one
# line rather than by tracing a variable.


def now() -> datetime:
    """This moment, timezone-aware. Never `datetime.now()` without a tzinfo."""
    return datetime.now(timezone.utc)


def at(epoch: float) -> datetime:
    """A float epoch, as the database wants to see it."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def epoch(moment: datetime | None) -> float | None:
    """A stored moment, as the application's arithmetic wants to see it."""
    return None if moment is None else moment.timestamp()


def executemany(conn: psycopg.Connection, sql: str, params) -> None:
    """Run one statement over many parameter sets.

    psycopg puts `executemany` on the cursor rather than the connection, where
    SQLite offered both. Four call sites want it, and none of them should have
    to know that -- so it lives here rather than as a `with conn.cursor()` block
    repeated four times.
    """
    with conn.cursor() as cursor:
        cursor.executemany(sql, params)
