"""Bounded spend, at every layer that can bound it.

Four layers, deliberately. The provider-side monthly cap is the only one that
survives a bug in this application, so it is documented as the backstop rather
than relied on as the control: it stops everybody at once, with no explanation
and no way to tell whose job did it.
"""

from __future__ import annotations

import os
import psycopg
import time

from app import db, ingestion

# Defaults. Each is a knob rather than a constant because the right value
# depends on who is using it and how much the owner will spend finding out.
PER_JOB_TOKEN_CEILING = ingestion.TOKEN_CEILING
DAILY_BUDGET_USD = 25.00
GLOBAL_DAILY_BUDGET_USD = 100.00

KILL_SWITCH_ENV = "AI_ANKI_GENERATION_DISABLED"


class GenerationDisabled(Exception):
    """The kill switch is on."""


class BudgetExceeded(Exception):
    """A spend limit was reached. It says which one, because "no" is not an answer."""


def generation_disabled() -> bool:
    """Read at call time, never cached: the point is to work without a redeploy."""
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def spend_since(conn: psycopg.Connection, since: float, invite_id: str | None = None) -> float:
    """What has been spent in a window, from recorded usage rather than estimates."""
    sql = (
        "SELECT c.input_tokens, c.cache_creation_input_tokens, c.cache_read_input_tokens,"
        " c.output_tokens FROM api_call c JOIN job j ON j.id = c.job_id"
        " WHERE c.created_at >= %s"
    )
    params: list = [db.at(since)]
    if invite_id is not None:
        sql += " AND j.invite_id = %s"
        params.append(invite_id)
    return round(
        sum(ingestion.cost_of(dict(row)) for row in conn.execute(sql, params).fetchall()), 6
    )


def spend_by_person(conn: psycopg.Connection) -> list[dict]:
    """Who has spent what. Attribution is the reason invites are per-person."""
    rows = conn.execute(
        "SELECT i.id AS invite_id, i.person, c.input_tokens, c.cache_creation_input_tokens,"
        " c.cache_read_input_tokens, c.output_tokens FROM api_call c"
        " JOIN job j ON j.id = c.job_id JOIN invite i ON i.id = j.invite_id"
    ).fetchall()
    totals: dict[str, dict] = {}
    for row in rows:
        entry = totals.setdefault(
            row["invite_id"],
            {"invite_id": row["invite_id"], "person": row["person"], "cost_usd": 0.0},
        )
        entry["cost_usd"] = round(entry["cost_usd"] + ingestion.cost_of(dict(row)), 6)
    return sorted(totals.values(), key=lambda entry: -entry["cost_usd"])


def check(
    conn: psycopg.Connection,
    invite_id: str | None,
    *,
    daily_budget_usd: float,
    global_daily_budget_usd: float,
) -> None:
    """Refuse expensive work before it starts, naming the limit that stopped it."""
    if generation_disabled():
        raise GenerationDisabled(
            "Generation is disabled by the operator kill switch. No work will start."
        )

    day_ago = time.time() - 86400
    global_spend = spend_since(conn, day_ago)
    if global_spend >= global_daily_budget_usd:
        raise BudgetExceeded(
            f"The global daily budget of ${global_daily_budget_usd:.2f} is spent "
            f"(${global_spend:.2f} in the last 24 hours). Nothing new will start today."
        )

    if invite_id is None:
        return
    personal = spend_since(conn, day_ago, invite_id)
    if personal >= daily_budget_usd:
        raise BudgetExceeded(
            f"Your rolling 24-hour budget of ${daily_budget_usd:.2f} is spent "
            f"(${personal:.2f}). It frees up as older jobs age out of the window."
        )
