"""In-place updating: the feature the whole Card Ledger exists to serve.

The danger here is specific and worth stating. If a regenerated card is matched
to the wrong existing card, Anki dutifully updates that note and leaves its
scheduling alone — so a ninety-day review interval ends up attached to a
question the user has never seen. That is worse than duplicating, because it
corrupts silently rather than merely cluttering. Every match is therefore
declared by the model and then *verified* by the server before it is honoured.
"""

from app import ledger
from tests.anki_harness import anki_collection

PLAN = {
    "topics": [
        {
            "topic_id": "cells",
            "path": "Bio::Cells",
            "difficulty": "easy",
            "rationale": "Definitions.",
            "note_type": "basic",
            "proposed_card_count": 2,
        }
    ]
}


def card(front, back="A.", *, existing=None, note_type="basic"):
    return {
        "note_type": note_type,
        "front": front,
        "back": back,
        "source_page": 1,
        "existing_card_id": existing,
    }


def run(client, claude, cards, deck_id=None):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Material.", "text/plain")},
        data={"deck_id": deck_id} if deck_id else {},
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json({"cards": cards})
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def first_run(client, claude):
    job_id = run(client, claude, [card("What makes ATP?", "Mitochondria.")])
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    client.get(f"/api/jobs/{job_id}/deck.apkg")
    entry = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"][0]
    return deck_id, entry["card_uuid"]


def test_a_topic_call_is_told_which_cards_already_exist(client, claude):
    deck_id, uuid = first_run(client, claude)

    run(client, claude, [card("What makes ATP?", "Mitochondria.", existing=uuid)], deck_id)

    instruction = claude.requests[-1]["messages"][0]["content"][-1]["text"]
    assert uuid in instruction
    assert "What makes ATP?" in instruction
    # After the breakpoint, so the per-topic varying text never disturbs the
    # cached document prefix.
    content = claude.requests[-1]["messages"][0]["content"]
    assert content[-1]["type"] == "text"
    assert "cache_control" not in content[-1]


def test_a_claimed_revision_keeps_the_existing_identity(client, claude):
    deck_id, uuid = first_run(client, claude)

    run(
        client,
        claude,
        [card("What makes most of the cell's ATP?", "The mitochondrion.", existing=uuid)],
        deck_id,
    )

    entries = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]
    assert len(entries) == 1, "a revision is the same card, not a second one"
    assert entries[0]["card_uuid"] == uuid


def test_a_claim_on_an_unrelated_question_is_rejected_and_the_card_becomes_new(client, claude):
    """The corruption guard, and the reason claims are verified rather than trusted."""
    deck_id, uuid = first_run(client, claude)

    run(
        client,
        claude,
        [card("In which compartment does glycolysis occur?", "Cytosol.", existing=uuid)],
        deck_id,
    )

    entries = {e["card_uuid"]: e for e in client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]}
    # The original keeps its identity and its text; the impostor gets its own.
    assert entries[uuid]["last_exported_front"] == "What makes ATP?"
    assert len(entries) == 2


def test_a_claim_on_a_card_from_another_topic_is_rejected(client, claude):
    deck_id, uuid = first_run(client, claude)

    other_topic = {
        "topics": [{**PLAN["topics"][0], "topic_id": "metabolism", "path": "Bio::Metabolism"}]
    }
    claude.counts_tokens(1000).replies_json(other_topic)
    job_id = client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Material.", "text/plain")},
        data={"deck_id": deck_id},
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json({"cards": [card("What makes ATP?", "Mitochondria.", existing=uuid)]})
    client.post(f"/api/jobs/{job_id}/generate")

    rejected = client.get(f"/api/jobs/{job_id}/cards").json()["cards"][0]
    assert rejected["card_uuid"] != uuid
    assert rejected["match_rejected_reason"]


def test_a_card_the_model_stops_producing_is_retired_and_its_identifier_never_returns(
    client, claude
):
    deck_id, uuid = first_run(client, claude)

    run(client, claude, [card("A completely different question?", "Yes.")], deck_id)

    entries = {e["card_uuid"]: e for e in client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]}
    assert entries[uuid]["retired_at"] is not None
    # Retired, not deleted: the card stays in the user's collection, we simply
    # stop claiming it. Reissuing the identifier would silently overwrite it.
    assert len(entries) == 2


def test_changing_a_cards_note_type_mints_a_new_identity_instead_of_reusing_the_old(
    client, claude
):
    """Anki reports a notetype change as conflicting and updates nothing at all."""
    deck_id, uuid = first_run(client, claude)

    run(
        client,
        claude,
        [
            card(
                "What makes {{c1::ATP}}?",
                "",
                existing=uuid,
                note_type="cloze",
            )
        ],
        deck_id,
    )

    entries = {e["card_uuid"]: e for e in client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]}
    assert entries[uuid]["note_type"] == "basic", "the old identity keeps its old type"
    minted = [e for guid, e in entries.items() if guid != uuid]
    assert len(minted) == 1
    assert minted[0]["note_type"] == "cloze"


def test_regenerating_twice_leaves_an_unchanged_slot_on_the_same_identifier(client, claude):
    """Stability across runs is the whole promise; drift here is silent."""
    deck_id, uuid = first_run(client, claude)

    for _ in range(2):
        run(client, claude, [card("What makes ATP?", "Mitochondria.", existing=uuid)], deck_id)

    entries = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]
    assert [e["card_uuid"] for e in entries] == [uuid]


def test_an_updated_card_lands_on_the_existing_note_and_keeps_its_scheduling(client, claude):
    # Built inline rather than via first_run, because this test needs the bytes
    # of that first export to put into the collection.
    first_job = run(client, claude, [card("What makes ATP?", "Mitochondria.")])
    deck_id = client.get(f"/api/jobs/{first_job}").json()["deck_id"]
    first_package = client.get(f"/api/jobs/{first_job}/deck.apkg").content
    uuid = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"][0]["card_uuid"]

    with anki_collection() as col:
        col.import_package(first_package)
        col.set_scheduling(uuid, interval=90, reps=40)

        revised = run(
            client,
            claude,
            [card("What makes most of the cell's ATP?", "The mitochondrion.", existing=uuid)],
            deck_id,
        )
        # Updating is opt-in as of the pre-download diff; this test is about
        # what an accepted update does, so it asks for one.
        outcome = col.import_package(
            client.get(f"/api/jobs/{revised}/deck.apkg?update=true").content
        )

        assert outcome.updated == 1
        assert outcome.new == 0
        assert col.note(uuid).fields[0] == "What makes most of the cell's ATP?"
        assert col.scheduling(uuid) == [(90, 40)], "six weeks of review survives a correction"


def test_similarity_is_measured_rather_than_assumed():
    """The riskiest tunable in the system, exercised directly.

    Too permissive attaches old review history to a new question; too strict
    silently duplicates. It is a named threshold with tests either side of it,
    not a number buried in a conditional.
    """
    assert ledger.similarity("What makes ATP?", "What makes ATP?") == 1.0
    assert ledger.similarity("What makes ATP?", "What makes most of the cell's ATP?") > (
        ledger.MATCH_THRESHOLD
    )
    assert ledger.similarity(
        "What makes ATP?", "In which compartment does glycolysis occur?"
    ) < ledger.MATCH_THRESHOLD
