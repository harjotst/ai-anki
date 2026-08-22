"""The schema as it stood when migrations were introduced.

Everything before this point was `CREATE TABLE IF NOT EXISTS` run at boot,
which is correct for a database that does not exist yet and cannot express a
rename, a backfill or a rollback. This revision is the last free moment to
start versioning: it runs the same statements that boot used to, so a database
created either way is the same database.

`app.db.SCHEMA` is executed rather than copied. One source, so the two cannot
drift -- and a test asserts that a database built by migration matches one
built by `initialise`.

Revision ID: 0001_baseline
Revises:
"""

from alembic import op

from app import db

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "api_call",
    "job_event",
    "lesson",
    "friendship",
    "deck_member",
    "study_card",
    "review",
    "card",
    "topic",
    "source",
    "job",
    "deck",
    "account",
)


def upgrade() -> None:
    op.execute(db.SCHEMA)


def downgrade() -> None:
    # Dropped in dependency order rather than with CASCADE, so that a table
    # somebody added outside these migrations is left alone rather than taken
    # down with everything else.
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
