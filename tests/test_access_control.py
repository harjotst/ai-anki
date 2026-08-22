"""Access control: who gets in, and what one leaked token costs.

Credentials moved to the auth provider when the application grew accounts, and
most of what this file used to assert moved with them — minting, revoking,
session expiry and login lockout are the provider's problem now, and testing
them here would be testing somebody else's code.

What remains is everything the provider cannot do for us: refusing a request
that proves nothing, refusing a state-changing request another site made, and
keeping one person's decks away from another's. That last one is the reason
this file exists at all — it is the only thing standing between two users.
"""

import pytest

from tests.conftest import SOMEBODY_ELSE, TESTER


def upload(client):
    return client.post("/api/jobs", files={"file": ("a.txt", b"Some material.", "text/plain")})


# --- the door ------------------------------------------------------------


def test_the_api_is_shut_to_a_request_that_proves_nothing(client):
    """Default-deny, and it is the whole surface rather than route by route.

    An endpoint added later is shut until somebody names it public, because the
    failure mode of the alternative is a forgotten decorator on the one route
    that spends money.
    """
    client.sign_out()

    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/decks").status_code == 401
    assert upload(client).status_code == 401
    # A job that genuinely does not exist is still 401, not 404: which ids exist
    # is not something a stranger gets to learn.
    assert client.get("/api/jobs/no-such-job").status_code == 401


def test_a_token_this_issuer_did_not_sign_gets_nowhere(client, identities):
    """The forged-credential case, end to end through the guard."""
    from tests.conftest import Identities

    forger = Identities()
    client.headers.update({"authorization": f"Bearer {forger.token(TESTER)}"})

    assert client.get("/api/jobs").status_code == 401


def test_past_the_door_a_missing_job_is_missing_rather_than_forbidden(client):
    assert client.get("/api/jobs/no-such-job").status_code == 404


@pytest.mark.parametrize(
    "header",
    [{"sec-fetch-site": "cross-site"}, {"origin": "https://evil.example"}],
)
def test_a_mutating_request_from_another_site_is_refused(client, header):
    """Belt and braces.

    The credential is a header rather than a cookie, so another site's page
    cannot attach it in the first place — this is the second lock, not the
    first, and it costs nothing to keep.
    """
    assert upload(client).status_code == 201  # same-origin, allowed

    client.headers.update(header)
    assert upload(client).status_code == 403


def test_reading_from_another_site_is_not_treated_as_an_attack(client):
    client.headers.update({"sec-fetch-site": "cross-site"})

    assert client.get("/api/jobs/no-such-job").status_code == 404


# --- accounts ------------------------------------------------------------


def test_a_first_visit_creates_the_account_and_a_second_does_not(client, pg_dsn):
    """Created lazily on a verified request, not by a trigger on the provider's
    user table — a trigger would fire for people this application has never
    heard from, and would live where the tests cannot reach it."""
    from app import db

    for _ in range(3):
        assert client.get("/api/jobs").status_code == 200

    conn = db.connect(pg_dsn)
    try:
        rows = conn.execute("SELECT id FROM account").fetchall()
    finally:
        conn.close()
    assert [str(row["id"]) for row in rows] == [TESTER]


def test_the_first_account_in_an_empty_database_is_the_administrator(boot):
    """Somebody has to be able to see spend on a fresh deployment, and it
    cannot be a second credential carried separately."""
    with boot() as machine:
        assert machine.get("/api/spend").status_code == 200

        machine.sign_in_as(SOMEBODY_ELSE)
        assert machine.get("/api/jobs").status_code == 200, "an ordinary person is let in"
        assert machine.get("/api/spend").status_code == 403, "but not to the admin surfaces"
        assert machine.post("/api/maintenance/purge", json={}).status_code == 403


def test_signing_in_again_after_a_restart_needs_nothing_stored(boot):
    """The credential is held by the client. Nothing on the server has to
    survive a restart for somebody to still be signed in — which is exactly
    what moving sessions to the provider bought."""
    with boot() as machine:
        job_id = upload(machine).json()["job_id"]

    with boot() as restarted:
        assert restarted.get(f"/api/jobs/{job_id}").status_code == 200


# --- one person's decks are not another's --------------------------------


def test_every_job_records_the_account_that_created_it(boot):
    """Spend has to be attributable to a person, which starts here."""
    with boot() as machine:
        machine.sign_in_as(TESTER)
        mine = upload(machine).json()["job_id"]

        machine.sign_in_as(SOMEBODY_ELSE)
        theirs = upload(machine).json()["job_id"]

        assert machine.get(f"/api/jobs/{theirs}").json()["account_id"] == SOMEBODY_ELSE
        machine.sign_in_as(TESTER)
        assert machine.get(f"/api/jobs/{mine}").json()["account_id"] == TESTER


def test_one_persons_job_is_not_visible_to_another_person(boot):
    """Answered as missing rather than as forbidden, so that a stranger cannot
    learn which job ids exist by asking."""
    with boot() as machine:
        machine.sign_in_as(TESTER)
        mine = upload(machine).json()["job_id"]

        machine.sign_in_as(SOMEBODY_ELSE)

        assert machine.get(f"/api/jobs/{mine}").status_code == 404
        assert machine.get(f"/api/jobs/{mine}/estimate").status_code == 404
        assert machine.get(f"/api/jobs/{mine}/usage").status_code == 404
        assert machine.get(f"/api/jobs/{mine}/diff").status_code == 404
        assert machine.post(f"/api/jobs/{mine}/cards/reject", json={"card_uuids": []}).status_code == 404
