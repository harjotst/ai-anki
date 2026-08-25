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


# --- one person, however they signed in ----------------------------------


def test_the_account_follows_the_subject_not_the_email(client, pg_dsn):
    """The invariant that makes linking work at all.

    When somebody attaches a second sign-in method, the auth provider keeps one
    user and adds an identity to it — the subject claim does not change. So the
    account is keyed on `sub` and nothing else. Keying on email instead would
    mint a second account the moment anybody changed their address, or the
    moment Apple handed over a private relay one.
    """
    from app import db

    client.sign_in_as(TESTER, email="first@example.com")
    assert client.get("/api/jobs").status_code == 200

    # The same person, a different address: changed it, or signed in with Apple
    # and let it hide the real one.
    client.sign_in_as(TESTER, email="xyz@privaterelay.appleid.com")
    assert client.get("/api/jobs").status_code == 200

    conn = db.connect(pg_dsn)
    try:
        rows = conn.execute("SELECT id, email FROM account").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, "a changed email must not mint a second account"
    assert str(rows[0]["id"]) == TESTER


def test_two_subjects_are_two_people_however_alike_they_look(client, pg_dsn):
    """The other half of it. Same email, different subject, is two accounts —
    which is exactly what happens when somebody signs in with Apple instead of
    Google without linking, and why the linking screen exists."""
    from app import db

    client.sign_in_as(TESTER, email="same@example.com")
    client.get("/api/jobs")
    client.sign_in_as(SOMEBODY_ELSE, email="same@example.com")
    client.get("/api/jobs")

    conn = db.connect(pg_dsn)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM account").fetchone()["n"]
    finally:
        conn.close()
    assert count == 2


def test_only_the_author_edits_deletes_or_rerolls_a_card(boot, claude):
    """A card uuid travels — due lists carry them, share recipients see them.
    Holding one must grant nothing: these three endpoints used to take any
    authenticated account, which let a stranger rewrite an owner's card, or
    spend the owner's budget re-rolling it."""
    from tests.conftest import SOMEBODY_ELSE, TESTER
    from tests.test_study import studied_deck

    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = machine.get(f"/api/decks/{deck_id}/cards").json()["cards"][0]

        machine.sign_in_as(SOMEBODY_ELSE)
        for attempt in (
            machine.patch(f"/api/cards/{card['card_uuid']}", json={"front": "mine now", "back": "x"}),
            machine.delete(f"/api/cards/{card['card_uuid']}"),
            machine.post(f"/api/cards/{card['card_uuid']}/reroll"),
        ):
            assert attempt.status_code == 404, attempt.text

        # Being shared the deck grants studying, never authorship.
        code = machine.get("/api/me").json()["friend_code"]
        machine.sign_in_as(TESTER)
        machine.post("/api/friends", json={"code": code})
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/friends/{TESTER}/accept")
        machine.sign_in_as(TESTER)
        machine.post(f"/api/decks/{deck_id}/share", json={"account_id": SOMEBODY_ELSE})
        machine.sign_in_as(SOMEBODY_ELSE)
        still = machine.patch(f"/api/cards/{card['card_uuid']}", json={"front": "mine", "back": "x"})
        assert still.status_code == 404, still.text

        # And the author still can.
        machine.sign_in_as(TESTER)
        fine = machine.patch(f"/api/cards/{card['card_uuid']}", json={"front": card["front"], "back": card["back"]})
        assert fine.status_code == 200, fine.text


def test_a_private_build_admits_exactly_its_named_addresses(boot):
    """The household deployment: two verified emails in, everybody else 403
    — plainly, before any account row exists, so a stranger's sign-in
    neither reaches the API key nor leaves a trace."""
    with boot(allowed_emails=frozenset({"harjot@example.test", "gf@example.test"})) as machine:
        machine.sign_in_as(TESTER, email="harjot@example.test")
        assert machine.get("/api/decks").status_code == 200

        machine.sign_in_as(SOMEBODY_ELSE, email="stranger@example.test")
        refused = machine.get("/api/decks")
        assert refused.status_code == 403
        assert refused.json()["detail"] == "this build is private"

        # Case never decides access.
        machine.sign_in_as("00000000-0000-0000-0000-000000000003", email="GF@Example.Test")
        assert machine.get("/api/decks").status_code == 200


def test_an_unset_allowlist_means_open(client):
    assert client.get("/api/decks").status_code == 200
