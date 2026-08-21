"""What an update will do, before it does it.

Updating is opt-in and add-only is the default, so the destructive path is never
the one taken by accident. Anything skipped is omitted from the package rather
than included and reverted, because an omitted note is one Anki never touches.
"""

from tests.anki_harness import anki_collection
from tests.test_slot_matching import PLAN, card, run


def deck_with_one_exported_card(client, claude):
    job_id = run(client, claude, [card("What makes ATP?", "Mitochondria.")])
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    package = client.get(f"/api/jobs/{job_id}/deck.apkg").content
    uuid = client.get(f"/api/decks/{deck_id}/ledger").json()["cards"][0]["card_uuid"]
    return deck_id, uuid, package


def revised_job(client, claude, deck_id, uuid):
    return run(
        client,
        claude,
        [
            card("What makes most of the cell's ATP?", "The mitochondrion.", existing=uuid),
            card("What is the nucleolus for?", "Ribosomes."),
        ],
        deck_id,
    )


def test_the_diff_counts_what_will_be_updated_added_and_left_alone(client, claude):
    deck_id, uuid, _ = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    diff = client.get(f"/api/jobs/{job_id}/diff").json()

    assert diff["counts"] == {"update": 1, "add": 1, "unchanged": 0}


def test_each_pending_update_shows_what_it_replaces(client, claude):
    deck_id, uuid, _ = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    update = client.get(f"/api/jobs/{job_id}/diff").json()["updates"][0]

    assert update["card_uuid"] == uuid
    assert update["existing_front"] == "What makes ATP?"
    assert update["proposed_front"] == "What makes most of the cell's ATP?"


def test_downloading_adds_only_unless_updating_is_asked_for(client, claude):
    """The safe path is the one you get by doing nothing."""
    deck_id, uuid, first_package = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    default = client.get(f"/api/jobs/{job_id}/deck.apkg")

    assert default.headers["x-notes-added"] == "1"
    assert default.headers["x-notes-updated"] == "0"

    with anki_collection() as col:
        col.import_package(first_package)
        col.set_scheduling(uuid, interval=90, reps=40)
        outcome = col.import_package(default.content)

        assert outcome.new == 1
        assert outcome.updated == 0
        assert col.note(uuid).fields[0] == "What makes ATP?", "untouched, not reverted"


def test_asking_for_updates_includes_them(client, claude):
    deck_id, uuid, _ = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    updated = client.get(f"/api/jobs/{job_id}/deck.apkg?update=true")

    assert updated.headers["x-notes-updated"] == "1"
    assert updated.headers["x-notes-added"] == "1"


def test_a_skipped_update_is_left_out_of_the_package_entirely(client, claude):
    deck_id, uuid, first_package = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    package = client.get(f"/api/jobs/{job_id}/deck.apkg?update=true&skip={uuid}")

    assert package.headers["x-notes-updated"] == "0"
    assert package.headers["x-notes-added"] == "1"

    with anki_collection() as col:
        col.import_package(first_package)
        col.set_scheduling(uuid, interval=90, reps=40)
        outcome = col.import_package(package.content)

        # Omitted, not included-and-reverted: Anki never sees the note, so the
        # user's own edits to it survive along with its scheduling.
        assert outcome.updated == 0
        assert col.scheduling(uuid) == [(90, 40)]


def test_the_diff_warns_that_updating_replaces_hand_added_tags(client, claude):
    deck_id, uuid, _ = deck_with_one_exported_card(client, claude)
    job_id = revised_job(client, claude, deck_id, uuid)

    diff = client.get(f"/api/jobs/{job_id}/diff").json()

    # Tags are replaced wholesale on an updated note — including Anki's own
    # leech marker — while coloured flags survive. The asymmetry is surprising
    # enough that the app has to say it rather than let people find out.
    warning = diff["warning"].lower()
    assert "tag" in warning
    assert "flag" in warning
