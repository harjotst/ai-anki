"""Alembic's entry point.

The database URL comes from the environment rather than from `alembic.ini`,
matching the rule the rest of the application follows: exactly one place knows
about the outside world, and a copy of this repository is never a way into
anybody's data.

There is no SQLAlchemy metadata here and no autogenerate. The schema is raw
SQL, deliberately -- it carries comments explaining why each column exists, and
a model layer would either lose them or duplicate them. Migrations are written
by hand as `op.execute`, which is more typing and says exactly what will run.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine


def _url() -> str:
    """The application's DSN, spelled the way SQLAlchemy needs it.

    One environment variable serves both drivers. psycopg speaks the plain
    `postgresql://` form; SQLAlchemy reads that as a request for psycopg2,
    which is not installed and never will be. Normalising here means the
    deployment sets one URL rather than two that must be kept in step.
    """
    url = os.environ["AI_ANKI_DATABASE_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=None, future=True)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
