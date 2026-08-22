"""The datastore under everything else.

These are the only tests that know Postgres exists. Every other test drives the
application through HTTP and should not be able to tell which database answered
— which is the property that made this migration possible at all.
"""

import psycopg

from app import db_pg


def test_the_schema_initialises(pg_dsn):
    db_pg.initialise(pg_dsn)

    conn = db_pg.connect(pg_dsn)
    tables = {
        row["table_name"]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema()"
        ).fetchall()
    }

    assert {"invite", "deck", "job", "source", "topic", "card", "job_event", "api_call"} <= tables
    conn.close()


def test_rows_are_still_read_by_column_name(pg_dsn):
    """Ninety-five call sites do `row["column"]`. None of them should have had
    to care which database answered."""
    db_pg.initialise(pg_dsn)
    conn = db_pg.connect(pg_dsn)

    conn.execute(
        "INSERT INTO deck (id, name, created_at) VALUES (%s, %s, now())", ("d1", "Bio")
    )
    row = conn.execute("SELECT id, name FROM deck").fetchone()

    assert row["name"] == "Bio"
    assert dict(row) == {"id": "d1", "name": "Bio"}
    conn.close()


def test_a_transaction_rolls_back_as_a_unit(pg_dsn):
    db_pg.initialise(pg_dsn)
    conn = db_pg.connect(pg_dsn)

    try:
        with db_pg.transaction(conn):
            conn.execute(
                "INSERT INTO deck (id, name, created_at) VALUES (%s, %s, now())", ("d1", "Bio")
            )
            raise RuntimeError("something went wrong half way through")
    except RuntimeError:
        pass

    assert conn.execute("SELECT COUNT(*) AS n FROM deck").fetchone()["n"] == 0
    conn.close()


def test_every_moment_in_time_is_timezone_aware(pg_dsn):
    """A naive datetime coming back out is the bug this asserts against.

    The SQLite schema stored some moments as float epochs and one as a string,
    and compared them in both Python and SQL. A single aware representation is
    what stops a timezone bug surfacing months later as a budget window
    resetting at the wrong hour.
    """
    db_pg.initialise(pg_dsn)
    conn = db_pg.connect(pg_dsn)

    conn.execute("INSERT INTO deck (id, name, created_at) VALUES ('d1', 'Bio', now())")
    created = conn.execute("SELECT created_at FROM deck").fetchone()["created_at"]

    assert created.tzinfo is not None
    conn.close()


def test_identity_columns_hand_back_the_row_they_made(pg_dsn):
    """SQLite had `lastrowid`; Postgres has RETURNING, and five call sites need it."""
    db_pg.initialise(pg_dsn)
    conn = db_pg.connect(pg_dsn)
    conn.execute("INSERT INTO deck (id, name, created_at) VALUES ('d1', 'Bio', now())")
    conn.execute(
        "INSERT INTO job (id, deck_id, state) VALUES ('j1', 'd1', 'uploaded')"
    )

    made = conn.execute(
        "INSERT INTO job_event (job_id, kind, data_json, created_at)"
        " VALUES ('j1', 'state', '{}', now()) RETURNING id"
    ).fetchone()

    assert isinstance(made["id"], int)
    conn.close()
