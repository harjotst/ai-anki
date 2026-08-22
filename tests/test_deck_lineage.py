"""A Deck outlives the Jobs that build it.

The retention contradiction is settled here: uploaded sources are the bulk and
they are purged; the Card Ledger is a few hundred bytes a card and is never
purged. Losing it would mean every later regeneration duplicates the user's
whole deck instead of updating it.
"""

import shutil

import pytest

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

FIRST_CARDS = {
    "cards": [
        {"note_type": "basic", "front": "What makes ATP?", "back": "Mitochondria.", "source_page": 1}
    ]
}

SAME_CARD_PLUS_A_NEW_ONE = {
    "cards": [
        # Byte-identical to what was exported before.
        {"note_type": "basic", "front": "What makes ATP?", "back": "Mitochondria.", "source_page": 1},
        {"note_type": "basic", "front": "What is the nucleolus for?", "back": "Ribosomes.", "source_page": 2},
    ]
}


def run(client, claude, cards=FIRST_CARDS, deck_id=None):
    claude.counts_tokens(1000).replies_json(PLAN)
    body = {"deck_id": deck_id} if deck_id else {}
    job_id = client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Material.", "text/plain")},
        data=body,
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(cards)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_a_job_runs_against_a_deck_that_outlives_it(client, claude):
    first = run(client, claude)
    deck_id = client.get(f"/api/jobs/{first}").json()["deck_id"]
    assert deck_id

    second = run(client, claude, cards=SAME_CARD_PLUS_A_NEW_ONE, deck_id=deck_id)

    assert client.get(f"/api/jobs/{second}").json()["deck_id"] == deck_id
    # Two jobs, one deck: the deck is the thing being built up over a term.
    assert first != second


def test_the_ledger_keeps_what_makes_a_reimport_non_destructive(client, claude):
    job_id = run(client, claude)
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    client.get(f"/api/jobs/{job_id}/deck.apkg")

    entries = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]

    entry = entries[0]
    assert entry["card_uuid"]
    assert entry["deck_path"] == "Bio::Cells"
    assert entry["note_type"] == "basic"
    assert entry["question_fingerprint"], "the anchor a later run matches against"
    assert entry["last_exported_front"] == "What makes ATP?"


def test_regeneration_adds_new_cards_and_leaves_existing_ones_completely_alone(client, claude):
    first = run(client, claude)
    deck_id = client.get(f"/api/jobs/{first}").json()["deck_id"]
    client.get(f"/api/jobs/{first}/deck.apkg")

    original = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"][0]["card_uuid"]

    second = run(client, claude, cards=SAME_CARD_PLUS_A_NEW_ONE, deck_id=deck_id)
    package = client.get(f"/api/jobs/{second}/deck.apkg")

    # The unchanged card keeps its identity rather than being minted afresh.
    ledger = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]
    assert original in {entry["card_uuid"] for entry in ledger}
    assert len(ledger) == 2

    # An omitted note is an untouched note, which is what protects the user's
    # own edits, tags and scheduling without any merge logic at all.
    assert package.headers["x-notes-added"] == "1"
    assert package.headers["x-notes-omitted-unchanged"] == "1"


def test_an_unchanged_card_never_reaches_the_users_collection_a_second_time(client, claude):
    """Proven in a real collection, because this is the promise that matters."""
    first = run(client, claude)
    deck_id = client.get(f"/api/jobs/{first}").json()["deck_id"]
    first_package = client.get(f"/api/jobs/{first}/deck.apkg").content

    with anki_collection() as col:
        col.import_package(first_package)
        guid = col.notes[0].guid
        col.set_scheduling(guid, interval=90, reps=40)

        second = run(client, claude, cards=SAME_CARD_PLUS_A_NEW_ONE, deck_id=deck_id)
        outcome = col.import_package(client.get(f"/api/jobs/{second}/deck.apkg").content)

        assert outcome.new == 1, "only the genuinely new card arrives"
        assert outcome.updated == 0, "the unchanged card is not in the file at all"
        assert col.scheduling(guid) == [(90, 40)]
        # Tags survive because Anki never saw the note again.
        assert "aianki::downgraded-cloze" not in col.note(guid).tags


def test_the_deck_path_and_note_type_are_frozen_once_a_card_has_been_exported(client, claude):
    first = run(client, claude)
    deck_id = client.get(f"/api/jobs/{first}").json()["deck_id"]
    client.get(f"/api/jobs/{first}/deck.apkg")

    moved_plan = {
        "topics": [{**PLAN["topics"][0], "path": "Bio::Reorganised::Cells", "note_type": "cloze"}]
    }
    claude.counts_tokens(1000).replies_json(moved_plan)
    job_id = client.post(
        "/api/jobs",
        files={"file": ("lecture.txt", b"Material.", "text/plain")},
        data={"deck_id": deck_id},
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    claude.replies_json(FIRST_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")

    entry = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"][0]
    # Anki matches decks by name and never moves an existing card, and a changed
    # notetype makes the note "conflicting" and updates nothing. Both are frozen
    # rather than promised and quietly not delivered.
    assert entry["deck_path"] == "Bio::Cells"
    assert entry["note_type"] == "basic"


def test_every_export_stamps_a_strictly_later_time_than_the_one_before(client, claude):
    """Carried finding from ticket 02, and a silent failure if it regresses.

    Anki's default is "update if newer", compared on note modification time. An
    export stamped at or before the previous one is filed as a duplicate and
    changes nothing, with no error anywhere.
    """
    first = run(client, claude)
    deck_id = client.get(f"/api/jobs/{first}").json()["deck_id"]
    first_stamp = float(client.get(f"/api/jobs/{first}/deck.apkg").headers["x-export-timestamp"])

    second = run(client, claude, cards=SAME_CARD_PLUS_A_NEW_ONE, deck_id=deck_id)
    second_stamp = float(client.get(f"/api/jobs/{second}/deck.apkg").headers["x-export-timestamp"])

    assert second_stamp > first_stamp


def test_purging_removes_the_uploaded_sources_and_never_the_ledger(client, claude):
    job_id = run(client, claude)
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    client.get(f"/api/jobs/{job_id}/deck.apkg")

    purged = client.post("/api/maintenance/purge", json={"older_than_days": 0})

    assert purged.status_code == 200
    assert purged.json()["sources_removed"] >= 1
    # The ledger is what makes the next regeneration non-destructive. Purging it
    # would guarantee the user's whole deck duplicates.
    assert len(client.get(f"/api/decks/{deck_id}/ledger").json()["cards"]) == 1


@pytest.mark.skipif(
    shutil.which("pg_dump") is None,
    reason="pg_dump is not installed on this machine; the runtime image has it",
)
def test_a_backup_can_be_taken_while_the_application_is_running(client, tmp_path):

    taken = client.post("/api/maintenance/backup")

    assert taken.status_code == 200
    backup = tmp_path / taken.json()["path"].split("/")[-1]
    # A real copy, not a snapshot promise: platform volume snapshots are
    # documented as not being a backup.
    assert taken.json()["bytes"] > 0
