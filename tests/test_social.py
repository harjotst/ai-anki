"""Friends, and competing with them.

One thing has to be said before any of it, because it shapes what a leaderboard
can honestly show: **decks are personal.** Two people studying biochemistry
uploaded different PDFs, so they have different decks, different topics and
different cards. "Who has mastered glycolysis" is not a question this data can
answer between two people, and a leaderboard that pretended otherwise would be
comparing numbers that are not the same number.

What does compare, whatever anybody studies:

- **Reviews** in a window — how much work was done.
- **Days studied** and the current streak — consistency, which is the thing
  spaced repetition actually asks of somebody.
- **Cards known** — how many cards this person would recall right now. It is
  subject-independent by construction, and unlike a review count it goes down
  when you stop.

Comparing mastery of a *topic* needs both people to hold the same deck, which
means deck sharing. That is a real feature and a different one; see
`test_topic_comparison_needs_a_shared_deck_and_says_so`.
"""

from datetime import datetime, timedelta, timezone

from tests.conftest import SOMEBODY_ELSE, TESTER
from tests.test_study import answer, due, studied_deck

# Anchored to the real clock for the same reason test_study's NOW is: the
# ranking window ends at actual now, and a pinned date ages out of it.
NOW = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
A_THIRD_PERSON = "00000000-0000-0000-0000-000000000003"


def code_of(client) -> str:
    return client.get("/api/me").json()["friend_code"]


def befriend(machine, claude, *, accept=True):
    """Two accounts that know each other, as the application would make them."""
    machine.sign_in_as(SOMEBODY_ELSE)
    theirs = code_of(machine)

    machine.sign_in_as(TESTER)
    asked = machine.post("/api/friends", json={"code": theirs})
    assert asked.status_code == 200, asked.text

    if accept:
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/friends/{TESTER}/accept")
        machine.sign_in_as(TESTER)
    return theirs


# --- finding each other --------------------------------------------------


def test_every_account_has_a_code_it_can_share(client):
    me = client.get("/api/me").json()

    assert me["account_id"] == TESTER
    assert len(me["friend_code"]) >= 6
    assert me["friend_code"] == code_of(client), "stable, or it cannot be shared"


def test_a_code_is_how_you_are_found_rather_than_an_email(boot):
    """Deliberately not "add by email".

    An endpoint that says whether an address has an account is an endpoint that
    tells anybody whether an address has an account, one guess at a time. A code
    somebody chose to give you leaks nothing they did not hand over.
    """
    with boot() as machine:
        machine.sign_in_as(SOMEBODY_ELSE)
        theirs = code_of(machine)

        machine.sign_in_as(TESTER)

        assert machine.post("/api/friends", json={"code": "nonsense"}).status_code == 404
        assert machine.post("/api/friends", json={"code": theirs}).status_code == 200


def test_you_cannot_befriend_yourself(client):
    refused = client.post("/api/friends", json={"code": code_of(client)})

    assert refused.status_code == 422


def test_a_request_is_not_a_friendship_until_it_is_accepted(boot):
    with boot() as machine:
        befriend(machine, None, accept=False)

        mine = machine.get("/api/friends").json()
        assert [f["account_id"] for f in mine["outgoing"]] == [SOMEBODY_ELSE]
        assert mine["friends"] == []

        machine.sign_in_as(SOMEBODY_ELSE)
        theirs = machine.get("/api/friends").json()
        assert [f["account_id"] for f in theirs["incoming"]] == [TESTER]
        assert theirs["friends"] == []


def test_accepting_makes_it_mutual_without_the_other_side_asking_again(boot):
    with boot() as machine:
        befriend(machine, None)

        assert [f["account_id"] for f in machine.get("/api/friends").json()["friends"]] == [
            SOMEBODY_ELSE
        ]
        machine.sign_in_as(SOMEBODY_ELSE)
        assert [f["account_id"] for f in machine.get("/api/friends").json()["friends"]] == [
            TESTER
        ]


def test_asking_twice_does_not_make_two_requests(boot):
    with boot() as machine:
        machine.sign_in_as(SOMEBODY_ELSE)
        theirs = code_of(machine)
        machine.sign_in_as(TESTER)

        machine.post("/api/friends", json={"code": theirs})
        machine.post("/api/friends", json={"code": theirs})

        assert len(machine.get("/api/friends").json()["outgoing"]) == 1


def test_removing_a_friend_is_mutual(boot):
    with boot() as machine:
        befriend(machine, None)

        machine.delete(f"/api/friends/{SOMEBODY_ELSE}")

        assert machine.get("/api/friends").json()["friends"] == []
        machine.sign_in_as(SOMEBODY_ELSE)
        assert machine.get("/api/friends").json()["friends"] == []


# --- competing -----------------------------------------------------------


def test_the_leaderboard_is_you_and_the_people_who_accepted_you(boot, claude):
    with boot() as machine:
        befriend(machine, claude)

        board = machine.get("/api/leaderboard").json()

        assert {row["account_id"] for row in board["rows"]} == {TESTER, SOMEBODY_ELSE}
        assert next(r for r in board["rows"] if r["account_id"] == TESTER)["is_you"]


def test_somebody_who_only_asked_is_not_on_it(boot, claude):
    """A request is not consent to be measured."""
    with boot() as machine:
        befriend(machine, claude, accept=False)

        board = machine.get("/api/leaderboard").json()

        assert {row["account_id"] for row in board["rows"]} == {TESTER}


def test_it_ranks_on_work_done_in_the_window(boot, claude):
    with boot() as machine:
        befriend(machine, claude)

        deck_id, _ = studied_deck(machine, claude)
        for index, card in enumerate(due(machine, deck_id)):
            answer(machine, card["card_uuid"], "good", client_uuid=f"mine{index}")

        board = machine.get("/api/leaderboard").json()

        assert board["rows"][0]["account_id"] == TESTER, "most work first"
        assert board["rows"][0]["reviews"] == 2
        assert board["rows"][1]["reviews"] == 0


def test_work_outside_the_window_does_not_count(boot, claude):
    """A leaderboard that counts everything ever is a leaderboard nobody new can
    join, and it stops measuring whether anyone is still studying."""
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]

        answer(machine, card, "good", at=NOW - timedelta(days=90), client_uuid="ancient")

        recent = machine.get("/api/leaderboard?days=7").json()["rows"][0]
        assert recent["reviews"] == 0

        forever = machine.get("/api/leaderboard?days=36500").json()["rows"][0]
        assert forever["reviews"] == 1


def test_cards_known_measures_what_is_held_rather_than_what_was_done(boot, claude):
    """The measure that is comparable between two people studying different
    material — and unlike a review count, it goes down when you stop."""
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        for index, card in enumerate(due(machine, deck_id)):
            answer(machine, card["card_uuid"], "easy", client_uuid=f"k{index}")

        now = machine.get("/api/leaderboard").json()["rows"][0]
        assert now["cards_known"] == 2

        much_later = machine.get(
            "/api/leaderboard", params={"at": (NOW + timedelta(days=400)).isoformat()}
        ).json()["rows"][0]
        assert much_later["cards_known"] == 0, "knowledge decays; the review count does not"


def test_a_streak_counts_consecutive_days_up_to_today(boot, claude):
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]
        for days_ago in [2, 1, 0]:
            answer(
                machine,
                card,
                "good",
                at=NOW - timedelta(days=days_ago),
                client_uuid=f"d{days_ago}",
            )

        row = machine.get(
            "/api/leaderboard", params={"at": NOW.isoformat()}
        ).json()["rows"][0]

        assert row["streak_days"] == 3


def test_a_streak_broken_by_a_missed_day_starts_again(boot, claude):
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]
        for days_ago in [5, 4, 0]:  # a gap at days 3, 2 and 1
            answer(
                machine,
                card,
                "good",
                at=NOW - timedelta(days=days_ago),
                client_uuid=f"g{days_ago}",
            )

        row = machine.get(
            "/api/leaderboard", params={"at": NOW.isoformat()}
        ).json()["rows"][0]

        assert row["streak_days"] == 1


# --- what the data cannot honestly say -----------------------------------


def test_topic_comparison_needs_a_shared_deck_and_says_so(boot, claude):
    """Named rather than faked.

    Two people who both study biochemistry uploaded different PDFs, so their
    decks, topics and cards are different. Putting their per-topic mastery side
    by side would be comparing two numbers that are not the same number.
    """
    with boot() as machine:
        befriend(machine, claude)
        deck_id, _ = studied_deck(machine, claude)

        compared = machine.get(f"/api/decks/{deck_id}/compare")

        assert compared.status_code == 200
        body = compared.json()
        assert body["friends"] == [], "nobody else holds this deck"
        assert "share" in body["why_empty"].lower()


# --- one person's numbers are not public ---------------------------------


def test_a_stranger_cannot_read_your_numbers(boot, claude):
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        for index, card in enumerate(due(machine, deck_id)):
            answer(machine, card["card_uuid"], "good", client_uuid=f"p{index}")

        machine.sign_in_as(A_THIRD_PERSON)
        board = machine.get("/api/leaderboard").json()

        assert [row["account_id"] for row in board["rows"]] == [A_THIRD_PERSON]
        assert board["rows"][0]["reviews"] == 0


def test_accepting_a_request_nobody_made_is_refused(boot):
    with boot() as machine:
        refused = machine.post(f"/api/friends/{SOMEBODY_ELSE}/accept")

        assert refused.status_code == 404


# --- usernames ------------------------------------------------------------


def test_a_username_is_claimed_normalised_and_shown(client):
    claimed = client.patch("/api/me", json={"username": "  HarJot_22 "})
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["username"] == "harjot_22", "lowercased and trimmed"
    assert client.get("/api/me").json()["username"] == "harjot_22"


def test_a_username_the_system_will_not_print(client):
    for bad in ["ab", "x" * 21, "har jot", "har@jot", ""]:
        refused = client.patch("/api/me", json={"username": bad})
        assert refused.status_code == 422, f"{bad!r}: {refused.text}"


def test_a_taken_username_is_taken_in_any_case(boot):
    with boot() as machine:
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.patch("/api/me", json={"username": "maya"})
        machine.sign_in_as(TESTER)
        refused = machine.patch("/api/me", json={"username": "MAYA"})
        assert refused.status_code == 409, refused.text


def test_a_username_is_how_a_friend_finds_you(boot):
    """The public handle replaces the code as the human path — the code
    still works, but nobody should have to say 'friend code' out loud."""
    with boot() as machine:
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.patch("/api/me", json={"username": "maya"})
        machine.sign_in_as(TESTER)
        asked = machine.post("/api/friends", json={"username": "@Maya"})
        assert asked.status_code == 200, asked.text

        machine.sign_in_as(SOMEBODY_ELSE)
        incoming = machine.get("/api/friends").json()["incoming"]
        assert len(incoming) == 1

        machine.post(f"/api/friends/{TESTER}/accept")
        board = machine.get("/api/leaderboard").json()
        by_id = {row["account_id"]: row for row in board["rows"]}
        assert by_id[str(machine.get("/api/me").json()["account_id"])]["username"] == "maya"


def test_a_typo_username_is_a_404_not_an_invitation(client):
    missed = client.post("/api/friends", json={"username": "nobody_here"})
    assert missed.status_code == 404
