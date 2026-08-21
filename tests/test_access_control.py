"""Access control: who gets in, and what one leaked link costs.

Access is a per-person Invite Token rather than one shared password, so a leak
is a revocation rather than a rotation and every job is attributable to
somebody. These tests drive it through the HTTP boundary like everything else.
"""

import pytest

from tests.conftest import OWNER, SESSION_COOKIE


def mint(client, person: str) -> str:
    minted = client.post("/api/invites", json={"person": person}, headers=OWNER)
    assert minted.status_code == 201, minted.text
    return minted.json()["token"]


def sign_in_as(client, token: str):
    client.cookies.clear()
    return client.post("/api/session", json={"token": token})


def upload(client):
    return client.post("/api/jobs", files={"file": ("a.txt", b"Some material.", "text/plain")})


def test_the_owner_mints_an_invite_that_lets_one_person_in(client):
    minted = client.post("/api/invites", json={"person": "alice"}, headers=OWNER)

    assert minted.status_code == 201
    token = minted.json()["token"]

    # Without it the application is shut, not merely unhelpful.
    client.cookies.clear()
    assert client.get("/api/jobs/no-such-job").status_code == 401

    redeemed = client.post("/api/session", json={"token": token})

    assert redeemed.status_code == 200
    assert redeemed.json()["person"] == "alice"
    # Past the door: the job genuinely does not exist, which is a different
    # answer from "you may not ask".
    assert client.get("/api/jobs/no-such-job").status_code == 404
    assert client.cookies[SESSION_COOKIE]


def test_minting_needs_the_owner_credential_not_merely_a_valid_session(client):
    # An invited person is inside the application but is not the owner; if they
    # could mint, one leaked link would become an unlimited supply of them.
    assert client.post("/api/invites", json={"person": "mallory"}).status_code == 401


def test_revoking_one_persons_invite_leaves_everybody_else_alone(boot):
    with boot() as machine:
        alice_token = mint(machine, "alice")
        bob_token = mint(machine, "bob")

        alice_id = alice_token.split(".")[0]
        assert machine.post(f"/api/invites/{alice_id}/revoke", headers=OWNER).status_code == 200

        assert sign_in_as(machine, alice_token).status_code == 401
        assert sign_in_as(machine, bob_token).status_code == 200


def test_a_revoked_invite_stops_working_on_the_request_after_it_not_the_login_after_it(boot):
    """Revocation is the whole point of per-person tokens, so it cannot wait."""
    with boot() as machine:
        token = mint(machine, "alice")
        assert sign_in_as(machine, token).status_code == 200
        assert upload(machine).status_code == 201

        machine.post(f"/api/invites/{token.split('.')[0]}/revoke", headers=OWNER)

        # Same live session, no new sign-in: the door shuts underneath it.
        assert upload(machine).status_code == 401


def test_a_session_stops_working_once_its_absolute_expiry_passes(boot):
    with boot(session_ttl_seconds=-1) as machine:
        token = mint(machine, "alice")
        assert sign_in_as(machine, token).status_code == 200
        # The expiry is stored, not carried by the cookie, so the holder cannot
        # edit it.
        assert upload(machine).status_code == 401


def test_the_session_cookie_carries_the_flags_that_keep_it_out_of_reach(client):
    token = mint(client, "alice")
    client.cookies.clear()

    header = client.post("/api/session", json={"token": token}).headers["set-cookie"].lower()

    assert "httponly" in header, "page script must not be able to read it"
    assert "secure" in header, "it must never travel over plain http"
    assert "samesite=lax" in header
    assert "path=/" in header


def test_a_wrong_token_is_refused_and_repeated_attempts_lock_the_address_out(boot):
    with boot(login_delay_seconds=0) as machine:
        refused = machine.post("/api/session", json={"token": "aaaaaaaa.not-the-secret"})
        assert refused.status_code == 401

        for _ in range(5):
            machine.post("/api/session", json={"token": "aaaaaaaa.not-the-secret"})

        locked = machine.post("/api/session", json={"token": "aaaaaaaa.not-the-secret"})
        assert locked.status_code == 429
        assert int(locked.headers["retry-after"]) > 0

        # The lockout is on guessing, and a real token is not a guess — but it
        # is refused too while the address is locked, which is the safe way round.
        good = mint(machine, "alice")
        assert machine.post("/api/session", json={"token": good}).status_code == 429


@pytest.mark.parametrize("header", [{"sec-fetch-site": "cross-site"}, {"origin": "https://evil.test"}])
def test_a_mutating_request_from_another_site_is_refused_even_with_a_valid_session(client, header):
    # The cookie is SameSite=Lax, so a cross-site POST should not carry it at
    # all — this is the second lock, for the request that arrives anyway.
    assert (
        client.post("/api/jobs", files={"file": ("a.txt", b"x", "text/plain")}, headers=header)
    ).status_code == 403


def test_reading_from_another_site_is_not_treated_as_an_attack(client):
    # Safe methods change nothing, so refusing them buys nothing and breaks
    # ordinary navigation.
    assert client.get("/api/jobs/no-such-job", headers={"sec-fetch-site": "cross-site"}).status_code == 404


def test_emptying_the_session_table_signs_everybody_out_at_once(boot, tmp_path):
    """The break-glass lever, exercised where it actually lives.

    This is the one test that touches the database directly rather than going
    through HTTP, because the operation itself is an operator running SQL. What
    it asserts is still observed from outside: the next request is refused.
    """
    from app import db

    with boot() as machine:
        alice, bob = mint(machine, "alice"), mint(machine, "bob")
        sign_in_as(machine, alice)
        assert upload(machine).status_code == 201

        conn = db.connect(tmp_path / "ai-anki.db")
        try:
            conn.execute("DELETE FROM session")
        finally:
            conn.close()

        assert upload(machine).status_code == 401
        # Sessions are gone; the invites behind them are untouched, so everyone
        # signs back in rather than needing a new link.
        assert sign_in_as(machine, bob).status_code == 200


def test_every_job_records_the_invite_that_created_it(boot):
    """Spend has to be attributable to a person, which starts here."""
    with boot() as machine:
        alice = mint(machine, "alice")
        sign_in_as(machine, alice)
        alice_job = upload(machine).json()["job_id"]

        recorded = machine.get(f"/api/jobs/{alice_job}").json()["invite_id"]
        assert recorded == alice.split(".")[0]


def test_one_persons_job_is_not_visible_to_another_person(boot):
    with boot() as machine:
        alice = mint(machine, "alice")
        bob = mint(machine, "bob")

        sign_in_as(machine, alice)
        alice_job = upload(machine).json()["job_id"]

        sign_in_as(machine, bob)
        # Answered as missing rather than forbidden: which job ids exist is not
        # something another invited person should be able to enumerate.
        assert machine.get(f"/api/jobs/{alice_job}").status_code == 404
