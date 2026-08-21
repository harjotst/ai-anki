"""The two human checkpoints: the plan, and the cards.

They exist because both of the expensive mistakes are cheap to prevent here. A
wrong plan wastes a generation run; a wrong card gets drilled for weeks before
anyone notices, in a collection where undoing it is hand work.
"""

import pytest

from tests.test_slot_matching import PLAN, card

RICH_PLAN = {
    "topics": [
        {
            "topic_id": "glycolysis",
            "path": "Bio::Metabolism::Glycolysis",
            "difficulty": "hard",
            "rationale": "Dense multi-step pathway.",
            "note_type": "cloze",
            "proposed_card_count": 6,
        },
        {
            "topic_id": "admin",
            "path": "Bio::Course Admin",
            "difficulty": "easy",
            "rationale": "Timetable slides.",
            "note_type": "basic",
            "proposed_card_count": 2,
        },
    ]
}


def planned(client, claude, plan=RICH_PLAN, tokens=200_000):
    claude.counts_tokens(tokens).replies_json(plan)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    return job_id


# --- the plan checkpoint -------------------------------------------------


def test_the_plan_shows_what_it_judged_and_why(client, claude):
    job_id = planned(client, claude)

    topic = client.get(f"/api/jobs/{job_id}").json()["plan"]["topics"][0]

    assert topic["difficulty"] == "hard"
    assert topic["rationale"], "a rating with no reasoning cannot be judged"
    assert topic["note_type"] == "cloze"
    assert topic["proposed_card_count"] == 6


def test_the_plan_can_be_edited_before_anything_expensive_runs(client, claude):
    job_id = planned(client, claude)

    edited = client.put(
        f"/api/jobs/{job_id}/plan",
        json={
            "topics": [
                {**RICH_PLAN["topics"][0], "proposed_card_count": 12, "note_type": "basic"}
            ]
        },
    )

    assert edited.status_code == 200
    plan = client.get(f"/api/jobs/{job_id}").json()["plan"]
    # The administrative topic is gone and the remaining one was re-scoped.
    assert len(plan["topics"]) == 1
    assert plan["topics"][0]["proposed_card_count"] == 12
    assert plan["topics"][0]["note_type"] == "basic"
    assert claude.requests[-1]["output_config"]["format"]["schema"]  # still only the plan call
    assert len(claude.requests) == 1, "editing must not generate anything"


def test_edits_are_validated_where_the_response_schema_could_not_be(client, claude):
    """Structured outputs cannot express numeric bounds, so Python must."""
    job_id = planned(client, claude)

    refused = client.put(
        f"/api/jobs/{job_id}/plan",
        json={"topics": [{**RICH_PLAN["topics"][0], "proposed_card_count": 5000}]},
    )

    assert refused.status_code == 422
    assert "card count" in refused.json()["detail"].lower()


def test_a_plan_with_no_topics_is_refused(client, claude):
    job_id = planned(client, claude)

    refused = client.put(f"/api/jobs/{job_id}/plan", json={"topics": []})

    assert refused.status_code == 422


def test_a_deck_path_that_anki_cannot_use_is_refused(client, claude):
    job_id = planned(client, claude)

    refused = client.put(
        f"/api/jobs/{job_id}/plan",
        json={"topics": [{**RICH_PLAN["topics"][0], "path": ""}]},
    )

    assert refused.status_code == 422


def test_the_estimate_is_available_at_the_checkpoint_where_the_decision_is_made(client, claude):
    job_id = planned(client, claude)

    claude.counts_tokens(200_000)
    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["input_tokens"] == 200_000
    assert estimate["estimated_cost_usd"] > 0


def test_a_plan_is_still_there_when_the_tab_is_reopened(boot, claude):
    with boot() as machine:
        job_id = planned(machine, claude)

    with boot() as reopened:
        assert reopened.get(f"/api/jobs/{job_id}").json()["plan"]["topics"]


# --- the card checkpoint -------------------------------------------------


def generated(client, claude):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(
        {"cards": [card("What makes {{c1::ATP}}?", "", note_type="cloze"), card("Q2?", "A2.")]}
    )
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_a_cloze_card_is_offered_rendered_as_well_as_raw(client, claude):
    job_id = generated(client, claude)

    first = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][0]

    assert first["front"] == "What makes {{c1::ATP}}?"
    # Judging a cloze card from its markup is judging the wrong thing.
    assert first["rendered_front"] == "What makes [...]?"


def test_a_card_can_be_corrected_by_hand(client, claude):
    job_id = generated(client, claude)
    uuid = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][1]["card_uuid"]

    client.patch(f"/api/cards/{uuid}", json={"front": "Corrected?", "back": "Corrected."})

    cards = {c["card_uuid"]: c for c in client.get(f"/api/jobs/{job_id}/cards").json()["cards"]}
    assert cards[uuid]["front"] == "Corrected?"


def test_a_rejected_card_never_reaches_the_package(client, claude):
    job_id = generated(client, claude)
    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]

    client.delete(f"/api/cards/{cards[0]['card_uuid']}")

    remaining = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert len(remaining) == 1
    package = client.get(f"/api/jobs/{job_id}/deck.apkg")
    assert package.headers["x-notes-added"] == "1"


def test_a_whole_topic_can_be_rejected_at_once(client, claude):
    job_id = generated(client, claude)

    client.delete(f"/api/jobs/{job_id}/topics/cells/cards")

    assert client.get(f"/api/jobs/{job_id}/cards").json()["cards"] == []


def test_one_card_can_be_rerolled_without_regenerating_the_topic(client, claude):
    job_id = generated(client, claude)
    uuid = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][1]["card_uuid"]
    before = len(claude.requests)

    claude.replies_json({"cards": [card("A better question?", "A better answer.")]})
    rerolled = client.post(f"/api/cards/{uuid}/reroll")

    assert rerolled.status_code == 200
    assert len(claude.requests) == before + 1, "one card, one call"
    cards = {c["card_uuid"]: c for c in client.get(f"/api/jobs/{job_id}/cards").json()["cards"]}
    assert cards[uuid]["front"] == "A better question?"


def test_a_reroll_is_billed_like_any_other_call(client, claude):
    job_id = generated(client, claude)
    uuid = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][1]["card_uuid"]

    claude.replies_json(
        {"cards": [card("Better?", "Yes.")]},
        usage={"input_tokens": 10, "cache_read_input_tokens": 5000, "output_tokens": 100},
    )
    client.post(f"/api/cards/{uuid}/reroll")

    passes = [c["pass_name"] for c in client.get(f"/api/jobs/{job_id}/usage").json()["calls"]]
    assert "reroll" in passes


def test_the_download_page_carries_what_the_user_needs_to_undo_the_import(client, claude):
    job_id = generated(client, claude)

    guidance = client.get(f"/api/jobs/{job_id}/download-info").json()

    # One search finds the whole batch, which is the only practical undo once an
    # import has landed in a 14,000-note collection.
    assert guidance["anki_search"] == f"tag:aianki::job::{job_id}"
    assert "default" in guidance["import_advice"].lower()


def test_the_estimate_prices_the_plan_the_user_is_actually_looking_at(client, claude):
    """A fixed topic assumption misprices the decision it is there to inform.

    Seen live: a 52k-token PDF produced 24 topics, and the screen quoted $1.11
    against a real cost near $2.48 — at the exact moment the user was deciding
    whether to spend it.
    """
    job_id = planned(client, claude)  # RICH_PLAN has 2 topics

    claude.counts_tokens(200_000)
    estimate = client.get(f"/api/jobs/{job_id}/estimate").json()

    assert estimate["topics"] == 2, "the real topic count, not the assumption"

    from app import ingestion

    assert estimate["estimated_cost_usd"] == ingestion.estimate_cost(200_000, topics=2)
    # And that is materially below the eight-topic assumption, which is the
    # whole point: the number moves with the plan.
    assert estimate["estimated_cost_usd"] < ingestion.estimate_cost(200_000, topics=8)
