"""Reviewing 164 cards without 164 clicks.

A real run produced 164 cards. Card-at-a-time is the right shape for the ones
that need judgement and the wrong shape for the sixty that obviously pass, and
a review screen nobody finishes is a review screen that does not protect the
collection at all.
"""

from tests.test_plan_and_review import generated


def uuids(client, job_id):
    return [c["card_uuid"] for c in client.get(f"/api/jobs/{job_id}/cards").json()["cards"]]


def test_several_cards_are_rejected_in_one_call(client, claude):
    job_id = generated(client, claude)
    doomed = uuids(client, job_id)

    rejected = client.post(f"/api/jobs/{job_id}/cards/reject", json={"card_uuids": doomed})

    assert rejected.status_code == 200
    assert rejected.json()["rejected"] == 2
    assert uuids(client, job_id) == []


def test_rejecting_a_card_that_is_already_gone_is_not_an_error(client, claude):
    """The screen the user is looking at is always slightly out of date."""
    job_id = generated(client, claude)
    doomed = uuids(client, job_id)
    client.delete(f"/api/cards/{doomed[0]}")

    again = client.post(f"/api/jobs/{job_id}/cards/reject", json={"card_uuids": doomed})

    assert again.status_code == 200
    assert again.json()["rejected"] == 1, "only the one that was still there"


def test_accepting_cards_records_that_they_were_actually_read(client, claude):
    """Accept has to mean something, or the button is a lie.

    It marks the card reviewed, which is what lets somebody stop half way
    through 164 cards and come back to the right place.
    """
    job_id = generated(client, claude)
    first = uuids(client, job_id)[:1]

    accepted = client.post(f"/api/jobs/{job_id}/cards/accept", json={"card_uuids": first})

    assert accepted.status_code == 200
    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert [c["reviewed"] for c in cards] == [True, False]


def test_the_card_screen_says_how_far_through_the_review_is(client, claude):
    job_id = generated(client, claude)
    body = client.get(f"/api/jobs/{job_id}/cards").json()
    assert body["reviewed_count"] == 0
    assert body["total"] == 2

    client.post(f"/api/jobs/{job_id}/cards/accept", json={"card_uuids": uuids(client, job_id)})

    assert client.get(f"/api/jobs/{job_id}/cards").json()["reviewed_count"] == 2


def test_an_edited_card_counts_as_reviewed_because_somebody_clearly_looked(client, claude):
    job_id = generated(client, claude)
    target = uuids(client, job_id)[1]

    client.patch(f"/api/cards/{target}", json={"front": "Corrected?", "back": "Corrected."})

    cards = {c["card_uuid"]: c for c in client.get(f"/api/jobs/{job_id}/cards").json()["cards"]}
    assert cards[target]["reviewed"] is True


def test_bulk_review_of_somebody_elses_job_is_refused(boot, claude):
    from tests.conftest import SOMEBODY_ELSE, TESTER

    with boot() as machine:

        machine.sign_in_as(TESTER)
        job_id = generated(machine, claude)
        hers = uuids(machine, job_id)

        machine.sign_in_as(SOMEBODY_ELSE)
        refused = machine.post(
            f"/api/jobs/{job_id}/cards/reject", json={"card_uuids": hers}
        )
        assert refused.status_code == 404
