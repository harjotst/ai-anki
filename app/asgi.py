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


app = create_app(
    database_url=os.environ["AI_ANKI_DATABASE_URL"],
    data_dir=Path(os.environ.get("AI_ANKI_DATA_DIR", "/data/uploads")),
    # Runtime secrets, never baked into the image. An unset owner token closes
    # minting rather than opening it.
    owner_token=os.environ.get("AI_ANKI_OWNER_TOKEN"),
    daily_budget_usd=_float("AI_ANKI_DAILY_BUDGET_USD", budget.DAILY_BUDGET_USD),
    global_daily_budget_usd=_float(
        "AI_ANKI_GLOBAL_DAILY_BUDGET_USD", budget.GLOBAL_DAILY_BUDGET_USD
    ),
)
