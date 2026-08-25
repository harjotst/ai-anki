"""Getting back to work you have already paid for.

Every job here costs real money and takes minutes. Before this, the only handle
on a run was the URL in the tab that started it: close the tab and the job kept
going, kept spending, and became unreachable. That is not a missing convenience
— it is the difference between an application somebody uses twice and one they
trust with a term's material.
"""

from tests.conftest import SOMEBODY_ELSE, TESTER
from tests.test_planning import PLAN, upload




# --- jobs ----------------------------------------------------------------


def test_a_job_is_findable_again_once_the_tab_that_started_it_is_gone(client, claude):
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")

    listed = client.get("/api/jobs").json()["jobs"]

    assert [job["job_id"] for job in listed] == [job_id]
    entry = listed[0]
    # Enough to recognise it by without opening it: nobody remembers a hex id.
    assert entry["source_filename"] == "lecture.txt"
    assert entry["state"] == "plan_ready"
    assert entry["deck_name"]
    assert entry["created_at"]


def test_the_job_list_puts_the_most_recent_first(client, claude):
    first = upload(client)
    second = upload(client)

    listed = [job["job_id"] for job in client.get("/api/jobs").json()["jobs"]]

    assert listed == [second, first]


def test_the_job_list_reports_how_many_cards_are_waiting(client, claude):
    from tests.test_plan_and_review import generated

    job_id = generated(client, claude)

    entry = next(j for j in client.get("/api/jobs").json()["jobs"] if j["job_id"] == job_id)
    assert entry["card_count"] == 2


def test_one_persons_job_list_never_shows_another_persons_jobs(boot, claude):
    with boot() as machine:

        machine.sign_in_as(TESTER)
        hers = upload(machine)

        machine.sign_in_as(SOMEBODY_ELSE)
        his = upload(machine)

        assert [j["job_id"] for j in machine.get("/api/jobs").json()["jobs"]] == [his]
        # And the list is the only handle he has; the id alone still gets him
        # nowhere.
        assert machine.get(f"/api/jobs/{hers}").status_code == 404


# --- decks ---------------------------------------------------------------


def test_a_deck_says_how_much_is_in_it_and_when_it_was_last_exported(client, claude):
    from tests.test_plan_and_review import generated

    job_id = generated(client, claude)
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]

    deck = next(d for d in client.get("/api/decks").json()["decks"] if d["deck_id"] == deck_id)

    assert deck["card_count"] == 2
    assert deck["job_count"] == 1
    # Never exported, so there is nothing in the user's collection yet and the
    # screen must not imply otherwise.
    assert deck["last_exported_at"] is None

    client.get(f"/api/jobs/{job_id}/deck.apkg")

    after = next(d for d in client.get("/api/decks").json()["decks"] if d["deck_id"] == deck_id)
    assert after["last_exported_at"] is not None


def test_a_deck_can_be_renamed_because_a_filename_is_not_a_deck_name(client, claude):
    job_id = upload(client)
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    # The default name is now already human (extension and underscores
    # gone), and renaming still beats any default.
    assert client.get("/api/decks").json()["decks"][0]["name"] == "lecture"

    renamed = client.patch(f"/api/decks/{deck_id}", json={"name": "Biochem 301"})

    assert renamed.status_code == 200
    assert client.get("/api/decks").json()["decks"][0]["name"] == "Biochem 301"


def test_a_deck_name_that_anki_cannot_use_is_refused(client, claude):
    job_id = upload(client)
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]

    assert client.patch(f"/api/decks/{deck_id}", json={"name": "   "}).status_code == 422


def test_one_persons_deck_list_never_shows_another_persons_decks(boot, claude):
    with boot() as machine:

        machine.sign_in_as(TESTER)
        upload(machine)
        her_deck = machine.get("/api/decks").json()["decks"][0]["deck_id"]

        machine.sign_in_as(SOMEBODY_ELSE)
        upload(machine)

        assert her_deck not in [d["deck_id"] for d in machine.get("/api/decks").json()["decks"]]
        assert machine.patch(f"/api/decks/{her_deck}", json={"name": "mine"}).status_code == 404
