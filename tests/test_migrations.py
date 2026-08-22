"""Migrations and the schema module cannot be allowed to disagree.

Boot used to run `CREATE TABLE IF NOT EXISTS`, which is right for a database
that does not exist yet and cannot express a rename, a backfill or a rollback.
Migrations replace that for anything with data in it — and the moment there are
two ways to build the schema, the interesting failure is that they drift, so
that a fresh deployment and a migrated one differ in a column nobody looked at.
"""

import subprocess
import sys

import psycopg
import pytest

from app import db


def alembic(dsn: str, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "AI_ANKI_DATABASE_URL": dsn, "PYTHONPATH": "."},
    )


def shape(dsn: str) -> dict:
    """Every column of every table, as the server reports it."""
    conn = psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)
    try:
        rows = conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default"
            "  FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name <> 'alembic_version'"
            " ORDER BY table_name, column_name"
        ).fetchall()
    finally:
        conn.close()
    return {(r["table_name"], r["column_name"]): dict(r) for r in rows}


@pytest.fixture
def second_schema(pg_container):
    """A second empty schema, so the two ways of building can be compared."""
    import uuid

    base = pg_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    name = "m_" + uuid.uuid4().hex[:16]
    admin = psycopg.connect(base, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{name}"')
    admin.close()
    try:
        yield f"{base}?options=-csearch_path%3D{name}"
    finally:
        admin = psycopg.connect(base, autocommit=True)
        admin.execute(f'DROP SCHEMA "{name}" CASCADE')
        admin.close()


def test_a_migrated_database_matches_one_built_from_the_schema(pg_dsn, second_schema):
    db.initialise(pg_dsn)

    upgraded = alembic(second_schema, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    assert shape(second_schema) == shape(pg_dsn)


def test_the_baseline_can_be_rolled_back(second_schema):
    assert alembic(second_schema, "upgrade", "head").returncode == 0
    assert shape(second_schema), "something was created"

    rolled_back = alembic(second_schema, "downgrade", "base")

    assert rolled_back.returncode == 0, rolled_back.stderr
    assert shape(second_schema) == {}


def test_there_is_exactly_one_head(second_schema):
    """Two heads is a merge nobody noticed, and `upgrade head` then fails at the
    worst moment — during a deploy."""
    heads = alembic(second_schema, "heads")

    assert heads.returncode == 0, heads.stderr
    assert len([line for line in heads.stdout.splitlines() if line.strip()]) == 1
