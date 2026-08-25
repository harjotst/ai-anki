"""Studying somebody else's deck.

The feature that makes "who has mastered this topic" a real question. Until
now a deck belonged to whoever uploaded the material, so two friends studying
the same subject held different cards and their per-topic numbers were not
comparable with each other.

The decision that makes it work: a shared deck is **joined, not copied.** Both
people study the same card identities, so the topics line up — and because
scheduling has always been keyed on (account, card), each of them has their own
review history over those shared cards without anything new being built for it.

Copying would have been easier and would have produced two decks whose cards
merely resembled each other, which is exactly the thing that cannot be compared.
"""

from tests.conftest import SOMEBODY_ELSE, TESTER
from tests.test_social import befriend
from tests.test_study import answer, due, studied_deck


def shared(machine, claude):
    """A deck the owner has shared with one friend, who has accepted."""
    befriend(machine, claude)
    deck_id, job_id = studied_deck(machine, claude)
    given = machine.post(f"/api/decks/{deck_id}/share", json={"account_id": SOMEBODY_ELSE})
    assert given.status_code == 200, given.text
    return deck_id, job_id


# --- giving somebody a deck ----------------------------------------------


def test_a_deck_can_be_shared_with_a_friend(client, boot, claude):
    with boot() as machine:
        deck_id, _ = shared(machine, claude)

        machine.sign_in_as(SOMEBODY_ELSE)
        theirs = machine.get("/api/decks").json()["decks"]

        entry = next(deck for deck in theirs if deck["deck_id"] == deck_id)
        assert entry["shared_with_me"] is True
        assert entry["owner_name"], "who gave it to you is the first thing you want to know"


def test_only_a_friend_can_be_given_a_deck(boot, claude):
    """Sharing with a stranger is how somebody's material gets handed to
    somebody they have never heard of. The friendship is the consent."""
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)

        refused = machine.post(
            f"/api/decks/{deck_id}/share", json={"account_id": SOMEBODY_ELSE}
        )

        assert refused.status_code == 403


def test_only_the_owner_can_share_it_onward(boot, claude):
    with boot() as machine:
        deck_id, _ = shared(machine, claude)

        machine.sign_in_as(SOMEBODY_ELSE)
        refused = machine.post(
            f"/api/decks/{deck_id}/share", json={"account_id": TESTER}
        )

        assert refused.status_code == 403


def test_a_shared_deck_is_studied_on_the_same_cards(boot, claude):
    """Joined rather than copied, which is the whole point.

    Two decks whose cards merely resemble each other cannot be compared, and
    comparison is the reason this feature exists.
    """
    with boot() as machine:
        deck_id, _ = shared(machine, claude)
        mine = {card["card_uuid"] for card in due(machine, deck_id)}

        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/decks/{deck_id}/study")

        assert {card["card_uuid"] for card in due(machine, deck_id)} == mine


def test_two_people_studying_one_deck_keep_separate_histories(boot, claude):
    """Nothing new was needed for this. Scheduling has always been keyed on
    (account, card), so a shared deck gets it for free."""
    with boot() as machine:
        deck_id, _ = shared(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]
        answer(machine, card, "easy", client_uuid="mine")

        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/decks/{deck_id}/study")

        assert card in {c["card_uuid"] for c in due(machine, deck_id)}, "still new to them"
        assert machine.get(f"/api/cards/{card}/reviews").json()["reviews"] == []

        answer(machine, card, "again", client_uuid="theirs")
        assert len(machine.get(f"/api/cards/{card}/reviews").json()["reviews"]) == 1

        machine.sign_in_as(TESTER)
        history = machine.get(f"/api/cards/{card}/reviews").json()["reviews"]
        assert [r["rating"] for r in history] == ["easy"], "untouched by theirs"


# --- what a guest may and may not do -------------------------------------


def test_a_guest_can_read_the_lessons_and_study_but_not_change_the_deck(boot, claude):
    with boot() as machine:
        deck_id, job_id = shared(machine, claude)

        machine.sign_in_as(SOMEBODY_ELSE)

        assert machine.get(f"/api/jobs/{job_id}/lessons").status_code == 200
        assert machine.post(f"/api/decks/{deck_id}/study").status_code == 200
        assert machine.get(f"/api/decks/{deck_id}/due").status_code == 200
        # Renaming, and adding material, stay with whoever uploaded it.
        assert machine.patch(f"/api/decks/{deck_id}", json={"name": "Mine now"}).status_code == 403
        added = machine.post(
            "/api/jobs",
            files={"file": ("x.txt", b"Material.", "text/plain")},
            data={"deck_id": deck_id},
        )
        assert added.status_code == 403


def test_taking_a_deck_back_stops_them_studying_it(boot, claude):
    with boot() as machine:
        deck_id, _ = shared(machine, claude)
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/decks/{deck_id}/study")
        card = due(machine, deck_id)[0]["card_uuid"]
        answer(machine, card, "good", client_uuid="theirs")

        machine.sign_in_as(TESTER)
        machine.delete(f"/api/decks/{deck_id}/share/{SOMEBODY_ELSE}")

        machine.sign_in_as(SOMEBODY_ELSE)
        assert machine.get(f"/api/decks/{deck_id}/due").status_code == 404
        # Their history is theirs. Unsharing takes away the deck, not the record
        # of the work they did on it -- which is what a leaderboard counted.
        assert machine.get("/api/me/activity").json()["reviews"] == 1


# --- the comparison this existed for -------------------------------------


def test_topic_mastery_can_finally_be_compared(boot, claude):
    with boot() as machine:
        deck_id, _ = shared(machine, claude)
        for index, card in enumerate(due(machine, deck_id)):
            answer(machine, card["card_uuid"], "easy", client_uuid=f"mine{index}")

        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/decks/{deck_id}/study")

        machine.sign_in_as(TESTER)
        compared = machine.get(f"/api/decks/{deck_id}/compare").json()

        assert compared["why_empty"] == ""
        assert [friend["account_id"] for friend in compared["friends"]] == [SOMEBODY_ELSE]

        mine = {topic["deck_path"]: topic["mastery"] for topic in compared["you"]["topics"]}
        theirs = {
            topic["deck_path"]: topic["mastery"]
            for topic in compared["friends"][0]["topics"]
        }
        assert mine.keys() == theirs.keys(), "the same topics, which is the point"
        for path in mine:
            assert mine[path] > theirs[path], "studied against not studied"


def test_a_comparison_names_the_person_it_is_comparing_against(boot, claude):
    """A column headed with a uuid is a column nobody reads."""
    with boot() as machine:
        deck_id, _ = shared(machine, claude)
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/decks/{deck_id}/study")

        machine.sign_in_as(TESTER)
        friend = machine.get(f"/api/decks/{deck_id}/compare").json()["friends"][0]

        assert friend["display_name"]
        assert friend["display_name"] != friend["account_id"]


def test_a_member_can_reach_the_jobs_that_built_a_shared_deck(boot, claude):
    """The lessons live under jobs, and /api/jobs lists only your own — so
    without this endpoint a share recipient could study the cards but never
    read the teaching behind them."""
    from tests.conftest import SOMEBODY_ELSE, TESTER
    from tests.test_study import studied_deck

    with boot() as machine:
        deck_id, job_id = studied_deck(machine, claude)
        machine.sign_in_as(SOMEBODY_ELSE)
        code = machine.get("/api/me").json()["friend_code"]
        machine.sign_in_as(TESTER)
        machine.post("/api/friends", json={"code": code})
        machine.sign_in_as(SOMEBODY_ELSE)
        machine.post(f"/api/friends/{TESTER}/accept")
        machine.sign_in_as(TESTER)
        machine.post(f"/api/decks/{deck_id}/share", json={"account_id": SOMEBODY_ELSE})

        machine.sign_in_as(SOMEBODY_ELSE)
        listed = machine.get(f"/api/decks/{deck_id}/jobs")
        assert listed.status_code == 200, listed.text
        assert [j["job_id"] for j in listed.json()["jobs"]] == [job_id]

        # A stranger still sees nothing.
        machine.sign_in_as("00000000-0000-0000-0000-000000000003")
        assert machine.get(f"/api/decks/{deck_id}/jobs").status_code == 404
