"""Adding this week's lecture to a deck you already have.

The whole point of a Deck outliving its Jobs is that week 2 lands on top of
week 1 rather than beside it. That only works if pass 1 knows what is already
there: a plan that invents fresh topic identifiers for material the deck
already covers can never match a slot, so every revised card arrives as a new
note and the user ends up drilling both.
"""

from tests.test_planning import PLAN, upload

WEEK_TWO_PLAN = {
    "topics": [
        {
            "topic_id": "glycolysis",
            "path": "Biology::Metabolism::Glycolysis",
            "difficulty": "hard",
            "rationale": "Revisited with regulation this week.",
            "note_type": "cloze",
            "proposed_card_count": 3,
        }
    ]
}


def exported_deck(client, claude):
    """A deck with one job in it, downloaded, so its cards count as exported."""
    from tests.test_plan_and_review import generated

    job_id = generated(client, claude)
    client.get(f"/api/jobs/{job_id}/deck.apkg")
    return client.get(f"/api/jobs/{job_id}").json()["deck_id"], job_id


def continue_deck(client, deck_id, name="week-two.txt"):
    return client.post(
        "/api/jobs",
        files={"file": (name, b"More material.", "text/plain")},
        data={"deck_id": deck_id},
    ).json()["job_id"]


def test_a_second_job_can_be_pointed_at_a_deck_that_already_exists(client, claude):
    deck_id, first = exported_deck(client, claude)

    second = continue_deck(client, deck_id)

    assert client.get(f"/api/jobs/{second}").json()["deck_id"] == deck_id
    assert second != first
    deck = next(d for d in client.get("/api/decks").json()["decks"] if d["deck_id"] == deck_id)
    assert deck["job_count"] == 2


def test_planning_a_continuation_is_told_what_the_deck_already_covers(client, claude):
    deck_id, _ = exported_deck(client, claude)
    job_id = continue_deck(client, deck_id)

    claude.replies_json(WEEK_TWO_PLAN)
    assert client.post(f"/api/jobs/{job_id}/plan").status_code == 200

    instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"]
    # The existing topic, by the identifier a later plan has to reuse verbatim
    # for a slot match to be possible at all.
    assert "cells" in instruction
    assert "Bio::Cells" in instruction
    assert "reuse" in instruction.lower()


def test_a_fresh_deck_is_not_told_about_topics_that_do_not_exist(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")

    instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"]
    assert "EXISTING TOPICS" not in instruction


def test_a_continuation_that_reuses_a_topic_id_finds_the_cards_to_revise(client, claude):
    """The payoff: pass 2 for a reused topic is handed the existing cards."""
    deck_id, _ = exported_deck(client, claude)
    job_id = continue_deck(client, deck_id)

    claude.replies_json(
        {
            "topics": [
                {
                    "topic_id": "cells",  # the identifier week one used
                    "path": "Bio::Cells",
                    "difficulty": "easy",
                    "rationale": "Same ground, more detail.",
                    "note_type": "basic",
                    "proposed_card_count": 2,
                }
            ]
        }
    )
    client.post(f"/api/jobs/{job_id}/plan")

    from tests.test_slot_matching import card

    claude.replies_json({"cards": [card("Q2?", "A revised answer.")]})
    client.post(f"/api/jobs/{job_id}/generate")

    cards_call = claude.requests[-1]["messages"][0]["content"][-1]["text"]
    assert "EXISTING CARDS already in the user's collection" in cards_call
    # Which is what lets the model declare a revision rather than a new card.
    assert "existing_card_id" in cards_call


def test_a_continuation_of_a_deck_you_do_not_own_is_refused(boot, claude):
    from tests.conftest import SOMEBODY_ELSE, TESTER

    with boot() as machine:


        machine.sign_in_as(TESTER)
        upload(machine)
        her_deck = machine.get("/api/decks").json()["decks"][0]["deck_id"]

        machine.sign_in_as(SOMEBODY_ELSE)
        refused = machine.post(
            "/api/jobs",
            files={"file": ("x.txt", b"Material.", "text/plain")},
            data={"deck_id": her_deck},
        )
        assert refused.status_code == 404
