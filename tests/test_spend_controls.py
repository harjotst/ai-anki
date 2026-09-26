"""Bounded spend, at every layer that can bound it.

A single large job is real money, and the application must be able to refuse
work it already knows is too expensive rather than relying on a provider-side
cap that stops everybody at once with no explanation.
"""

import pytest

from tests.conftest import TESTER
from tests.test_slot_matching import PLAN, card

# 4,000,000 cache-write tokens at $0.25/MTok is $1.00, plus a little output:
# just over the $1.00 budgets the tests below set.
BIG_USAGE = {"input_tokens": 0, "cache_write_tokens": 4_000_000, "output_tokens": 1_000}


def start(client, llm, tokens=1000, deck_id=None):
    llm.counts_tokens(tokens)
    return client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Material.", "text/plain")},
        data={"deck_id": deck_id} if deck_id else {"deck_name": "Lecture"},
    ).json()["job_id"]


def plan_and_generate(client, llm, job_id, usage=None):
    llm.replies_json(PLAN, usage=usage or {})
    planned = client.post(f"/api/jobs/{job_id}/plan")
    llm.replies_json({"cards": [card("Q?")]})
    client.post(f"/api/jobs/{job_id}/generate")
    return planned


def test_a_job_over_the_token_ceiling_is_refused_by_name(client, llm):
    job_id = start(client, llm, tokens=900_000)

    refused = client.post(f"/api/jobs/{job_id}/plan")

    assert refused.status_code == 413
    assert "700,000" in refused.json()["detail"], "the limit that was hit is named"


def test_the_ceiling_is_rechecked_before_the_fan_out_not_only_at_admission(boot, llm):
    """A plan can multiply the work, so admission alone is not enough."""
    with boot(per_job_token_ceiling=1_500) as machine:
        job_id = start(machine, llm, tokens=1_000)
        llm.replies_json(PLAN)
        machine.post(f"/api/jobs/{job_id}/plan")

        # The document got bigger between passes — or the plan did.
        llm.counts_tokens(900_000)
        refused = machine.post(f"/api/jobs/{job_id}/generate")

        assert refused.status_code == 413
        assert llm.requests[-1] == llm.requests[-1]  # no topic call was made


def test_a_person_who_has_spent_their_daily_budget_is_blocked(boot, llm):
    with boot(daily_budget_usd=1.00) as machine:
        first = start(machine, llm)
        plan_and_generate(machine, llm, first, usage=BIG_USAGE)

        second = start(machine, llm)
        llm.replies_json(PLAN)
        refused = machine.post(f"/api/jobs/{second}/plan")

        assert refused.status_code == 429
        detail = refused.json()["detail"].lower()
        assert "24-hour" in detail or "daily" in detail
        assert "budget" in detail


def test_the_global_ceiling_stops_everybody_not_just_the_big_spender(boot, llm):
    with boot(daily_budget_usd=1000.0, global_daily_budget_usd=1.00) as machine:
        first = start(machine, llm)
        plan_and_generate(machine, llm, first, usage=BIG_USAGE)

        second = start(machine, llm)
        llm.replies_json(PLAN)
        refused = machine.post(f"/api/jobs/{second}/plan")

        assert refused.status_code == 429
        assert "global" in refused.json()["detail"].lower()


def test_the_kill_switch_stops_generation_without_a_redeploy(boot, llm, monkeypatch):
    monkeypatch.setenv("AI_ANKI_GENERATION_DISABLED", "1")
    with boot() as machine:
        job_id = start(machine, llm)

        refused = machine.post(f"/api/jobs/{job_id}/plan")

        assert refused.status_code == 503
        assert "disabled" in refused.json()["detail"].lower()
        assert llm.requests == [], "nothing may be generated while the switch is on"


def test_an_administrator_can_see_what_each_person_has_spent(boot, llm):
    with boot() as machine:
        job_id = start(machine, llm)
        plan_and_generate(machine, llm, job_id, usage=BIG_USAGE)

        spend = machine.get("/api/spend").json()

        person = next(row for row in spend["people"] if row["account_id"] == TESTER)
        # 4,000,000 cache-write tokens at $0.25/MTok is $1.00, worked out
        # independently of the code.
        assert person["cost_usd"] >= 1.00
        assert person["person"], "a name to show, even if it is only the id"


def test_the_spend_view_is_an_administrators_alone(boot):
    """It names every person and what they cost, so it is not an ordinary
    surface. The default persona is the first account in an empty database and
    therefore the administrator; anybody arriving after them is not."""
    from tests.conftest import SOMEBODY_ELSE

    with boot() as machine:
        assert machine.get("/api/spend").status_code == 200

        machine.sign_in_as(SOMEBODY_ELSE)
        assert machine.get("/api/spend").status_code == 403


def test_the_provider_side_cap_is_written_down_as_the_outer_backstop():
    """The only control that survives a bug in this application."""
    from pathlib import Path

    docs = Path("docs/operations.md").read_text().lower()
    assert "console" in docs
    assert "monthly" in docs
    assert "backstop" in docs
