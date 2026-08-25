"""The production entrypoint.

Everything configurable is read from the environment here and nowhere else, so
`create_app` stays a function the tests can call with explicit arguments and the
deployment has exactly one place that knows about the outside world.
"""

from __future__ import annotations

import os
from pathlib import Path

from app import budget
from app.main import create_app


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _allowed_emails() -> frozenset[str] | None:
    """AI_ANKI_ALLOWED_EMAILS: comma-separated addresses, or unset for open.

    The private-build switch: set it and only those verified addresses get
    past the door — everyone else is 403 before an account row exists.
    """
    raw = os.environ.get("AI_ANKI_ALLOWED_EMAILS", "").strip()
    if not raw:
        return None
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


app = create_app(
    database_url=os.environ["AI_ANKI_DATABASE_URL"],
    allowed_emails=_allowed_emails(),
    data_dir=Path(os.environ.get("AI_ANKI_DATA_DIR", "/data/uploads")),
    daily_budget_usd=_float("AI_ANKI_DAILY_BUDGET_USD", budget.DAILY_BUDGET_USD),
    global_daily_budget_usd=_float(
        "AI_ANKI_GLOBAL_DAILY_BUDGET_USD", budget.GLOBAL_DAILY_BUDGET_USD
    ),
)
