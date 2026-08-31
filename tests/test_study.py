"""Studying inside the application, and the log everything is derived from.

The decision this file exists to protect: **`review` is append-only and
authoritative, and scheduling state is derived from it.** Three hard problems
dissolve because of that, and each has a test here.

Offline sync needs no conflict resolution, because two devices cannot disagree
about facts that have already happened — merging is the union of two logs,
deduplicated by an id the client chose. Leaderboards become recomputable rather
than merely stored, so a bug in aggregation is a re-run and not lost history.
And the scheduler can be replaced: run a better one over the same history and
every card reschedules correctly.

If `study_card` ever becomes the source of truth, all three of those go away
quietly. `test_scheduling_can_be_thrown_away_and_rebuilt_from_the_log` is what
notices.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.test_generation import CELL_CARDS
from tests.test_lessons import LESSON
from tests.test_planning import PLAN, upload

# Anchored to the real clock, not a calendar date: scheduling and the
# leaderboard window measure against actual now, so a pinned date quietly
# starts failing the day it drifts out of range — observed 2026-08-31, when
# an "easy" answer pinned ten days back had already come due again.
NOW = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)


def studied_deck(client, claude):
    """A deck with generated cards, enrolled for study."""
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.answers(lesson=LESSON, cards=CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")

    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    enrolled = client.post(f"/api/decks/{deck_id}/study")
    assert enrolled.status_code == 200, enrolled.text
    return deck_id, job_id


def due(client, deck_id, at=None):
    params = {"at": at.isoformat()} if at else None
    return client.get(f"/api/decks/{deck_id}/due", params=params).json()["cards"]


def answer(client, card_uuid, rating, *, at=NOW, client_uuid="r1", ms=3000):
    return client.post(
        "/api/reviews",
        json={
            "reviews": [
                {
                    "client_uuid": client_uuid,
                    "card_uuid": card_uuid,
                    "rating": rating,
                    "reviewed_at": at.isoformat(),
                    "duration_ms": ms,
                }
            ]
        },
    )


# --- becoming something to study -----------------------------------------


def test_enrolling_a_deck_makes_its_cards_studiable(client, claude):
    deck_id, _ = studied_deck(client, claude)

    waiting = due(client, deck_id)

    # Every generated card, due now. A card nobody has answered has nothing to
    # wait for -- scheduling it into the future would mean a fresh deck that
    # cannot be studied on the day it was made.
    assert len(waiting) == len(client.get(f"/api/decks/{deck_id}/cards").json()["cards"])
    assert waiting, "a deck with no studiable cards is a deck nobody can use"
    assert all(card["state"] == "learning" for card in waiting)
    assert all(card["reps"] == 0 for card in waiting)


def test_enrolling_twice_does_not_reset_what_you_have_already_learned(client, claude):
    """A second job against the same deck enrols the new cards and must leave
    the scheduling of the old ones alone. Losing it is the single most
    destructive thing this application could do to somebody."""
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]
    answer(client, card["card_uuid"], "good")

    client.post(f"/api/decks/{deck_id}/study")

    again = client.get(f"/api/decks/{deck_id}/cards").json()["cards"]
    reviewed = next(c for c in again if c["card_uuid"] == card["card_uuid"])
    assert reviewed["reps"] == 1, "the review survived being re-enrolled"
    assert reviewed["stability"] is not None


# --- answering -----------------------------------------------------------


def test_answering_well_pushes_the_card_into_the_future(client, claude):
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]

    answer(client, card["card_uuid"], "easy")

    assert card["card_uuid"] not in {c["card_uuid"] for c in due(client, deck_id, at=NOW)}
    much_later = due(client, deck_id, at=NOW + timedelta(days=365))
    assert card["card_uuid"] in {c["card_uuid"] for c in much_later}


def test_answering_again_keeps_the_card_close(client, claude):
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]

    answer(client, card["card_uuid"], "again")

    soon = due(client, deck_id, at=NOW + timedelta(hours=1))
    assert card["card_uuid"] in {c["card_uuid"] for c in soon}


def test_a_rating_the_scheduler_does_not_know_is_refused(client, claude):
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]

    refused = answer(client, card["card_uuid"], "brilliant")

    assert refused.status_code == 422


# --- the properties the whole design rests on ----------------------------


def test_the_same_review_pushed_twice_is_counted_once(client, claude):
    """The property that makes offline sync trivial.

    A device that pushed, lost the connection before the reply, and pushed
    again must not have answered twice. Idempotency is on an id the client
    chose, because the client is the only thing that knows the two pushes were
    the same event.
    """
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]

    first = answer(client, card["card_uuid"], "good", client_uuid="same-id")
    second = answer(client, card["card_uuid"], "good", client_uuid="same-id")

    assert first.status_code == second.status_code == 200
    assert second.json()["accepted"] == 0, "the retry added nothing"
    history = client.get(f"/api/cards/{card['card_uuid']}/reviews").json()["reviews"]
    assert len(history) == 1


def test_scheduling_can_be_thrown_away_and_rebuilt_from_the_log(client, claude, pg_dsn):
    """`study_card` is a projection, not a record.

    If this ever fails, the log has stopped being authoritative — and with it
    go conflict-free sync, recomputable leaderboards, and any hope of changing
    the scheduler later.
    """
    from app import db, study

    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]["card_uuid"]
    for index, (rating, day) in enumerate([("good", 0), ("again", 1), ("good", 2), ("easy", 5)]):
        answer(
            client, card, rating, at=NOW + timedelta(days=day), client_uuid=f"r{index}"
        )

    before = client.get(f"/api/decks/{deck_id}/cards").json()["cards"]

    conn = db.connect(pg_dsn)
    try:
        conn.execute("DELETE FROM study_card")
        study.rebuild_all(conn)
    finally:
        conn.close()

    assert client.get(f"/api/decks/{deck_id}/cards").json()["cards"] == before


def test_reviews_that_arrive_out_of_order_are_replayed_in_the_order_they_happened(
    client, claude
):
    """Two devices sync in whatever order they reconnect. What happened is
    fixed; when we heard about it is not."""
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]["card_uuid"]

    # Yesterday's answer arrives after today's.
    answer(client, card, "easy", at=NOW + timedelta(days=1), client_uuid="second")
    late = client.get(f"/api/decks/{deck_id}/cards").json()["cards"]
    answer(client, card, "again", at=NOW, client_uuid="first")

    settled = client.get(f"/api/decks/{deck_id}/cards").json()["cards"]
    assert settled != late, "the earlier review changed the outcome"
    history = client.get(f"/api/cards/{card}/reviews").json()["reviews"]
    assert [r["rating"] for r in history] == ["again", "easy"], "replayed in event order"


# --- what the social features will be built on ---------------------------


def test_mastery_of_a_topic_is_the_mean_chance_of_recalling_its_cards(client, claude):
    """Defined, rather than asserted.

    Retrievability is what FSRS already computes: the probability this card
    would be recalled right now. Averaged over a topic it decays if you stop
    studying, which is the honest answer, and it compares between two people
    without normalising for how many cards each of them generated.
    """
    deck_id, _ = studied_deck(client, claude)
    fresh = client.get(f"/api/decks/{deck_id}/mastery").json()

    assert fresh["topics"][0]["mastery"] == 0.0, "nothing recalled is nothing mastered"
    # The topic's identity rides along: it is how a topic row on screen opens
    # its lesson, so its absence makes lessons unreachable from a caught-up deck.
    assert fresh["topics"][0]["topic_id"]

    for index, card in enumerate(due(client, deck_id)):
        answer(client, card["card_uuid"], "easy", client_uuid=f"m{index}")

    learned = client.get(f"/api/decks/{deck_id}/mastery").json()
    assert learned["topics"][0]["mastery"] > 0.9
    assert learned["overall"] == pytest.approx(learned["topics"][0]["mastery"], abs=0.001)

    # And it decays. A topic crammed in March is not still mastered in June.
    stale = client.get(
        f"/api/decks/{deck_id}/mastery",
        params={"at": (NOW + timedelta(days=400)).isoformat()},
    ).json()
    assert stale["topics"][0]["mastery"] < learned["topics"][0]["mastery"]


def test_how_much_has_been_answered_is_counted_from_the_log(client, claude):
    """The number people actually enjoy competing on. A volume measure, and
    labelled as one — it says how much work was done, not how much is known."""
    deck_id, _ = studied_deck(client, claude)
    for index, card in enumerate(due(client, deck_id)):
        answer(client, card["card_uuid"], "good", client_uuid=f"c{index}")

    counted = client.get("/api/me/activity").json()

    assert counted["reviews"] == 2
    assert counted["cards_seen"] == 2
    assert counted["days_studied"] == 1


# --- one person's history is not another's -------------------------------


def test_studying_is_per_person_even_on_the_same_card(boot, claude):
    from tests.conftest import SOMEBODY_ELSE, TESTER

    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]
        answer(machine, card, "easy", client_uuid="mine")

        machine.sign_in_as(SOMEBODY_ELSE)

        assert machine.get(f"/api/decks/{deck_id}/due").status_code == 404
        assert machine.get(f"/api/cards/{card}/reviews").status_code == 404
        assert machine.get("/api/me/activity").json()["reviews"] == 0

        machine.sign_in_as(TESTER)
        assert machine.get("/api/me/activity").json()["reviews"] == 1


def test_a_review_of_a_card_you_do_not_own_is_skipped_not_recorded(boot, claude):
    """Skipped and named, rather than failing the batch: a 404 for one dead
    row used to jam a client's whole queue behind it forever. The security
    property is unchanged — nothing is recorded for a card that is not
    yours — but the reply now says so instead of refusing everything."""
    from tests.conftest import SOMEBODY_ELSE

    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]

        machine.sign_in_as(SOMEBODY_ELSE)
        reply = answer(machine, card, "good", client_uuid="theirs")

        assert reply.status_code == 200
        assert reply.json()["accepted"] == 0
        assert reply.json()["skipped"] == ["theirs"]


def test_a_cloze_card_is_asked_rather_than_shown(client, claude):
    """Showing the markup does not merely make it hard to judge — the answer is
    written in it."""
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.answers(
        lesson=LESSON,
        cards={
            "cards": [
                {
                    "note_type": "cloze",
                    "front": "Glycolysis happens in the {{c1::cytosol}}.",
                    "back": "",
                    "source_page": 1,
                    "existing_card_id": None,
                }
            ]
        },
    )
    client.post(f"/api/jobs/{job_id}/generate")
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]
    client.post(f"/api/decks/{deck_id}/study")

    card = due(client, deck_id)[0]

    assert card["front"] == "Glycolysis happens in the {{c1::cytosol}}."
    assert card["rendered_front"] == "Glycolysis happens in the [...]."
    assert "cytosol" not in card["rendered_front"]


# --- what the redesigned Today screen reads --------------------------------


def test_activity_carries_the_per_day_history_the_heatmap_is_built_from(client, claude):
    """The heatmap, the streak ring and banked rest days are all derived from
    which days somebody studied. Totals alone cannot answer that."""
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]["card_uuid"]
    for index, days_ago in enumerate([2, 2, 0]):
        answer(
            client, card, "good",
            at=NOW - timedelta(days=days_ago), client_uuid=f"h{index}",
        )

    counted = client.get("/api/me/activity").json()

    assert counted["reviews"] == 3
    by_day = {entry["day"]: entry["reviews"] for entry in counted["days"]}
    assert by_day[(NOW - timedelta(days=2)).date().isoformat()] == 2
    assert by_day[NOW.date().isoformat()] == 1
    # Days with nothing are absent rather than zero-filled: the client knows
    # the calendar; the server only knows what happened.
    assert (NOW - timedelta(days=1)).date().isoformat() not in by_day


def test_every_due_card_says_what_each_rating_would_schedule(client, claude):
    """The interval previews under the rating buttons.

    Served from the same scheduler that will actually apply the rating, not
    mirrored client-side — a mirror that drifted from the real parameters
    would print numbers the next day proves wrong.
    """
    deck_id, _ = studied_deck(client, claude)

    card = due(client, deck_id)[0]

    previews = card["previews"]
    assert set(previews) == {"again", "hard", "good", "easy"}
    assert all(isinstance(v, str) and v for v in previews.values())

    # And they are honest about order: a better answer never schedules sooner.
    def minutes(text):
        units = {"m": 1, "h": 60, "d": 1440, "mo": 43200}
        for suffix in ["mo", "m", "h", "d"]:
            if text.endswith(suffix):
                return float(text[: -len(suffix)]) * units[suffix]
        raise AssertionError(f"unparseable interval {text!r}")

    assert minutes(previews["again"]) <= minutes(previews["hard"])
    assert minutes(previews["hard"]) <= minutes(previews["good"])
    assert minutes(previews["good"]) <= minutes(previews["easy"])


def test_previews_reflect_the_cards_actual_history(client, claude):
    """A mature card's Good is measured in days; a fresh card's in minutes."""
    deck_id, _ = studied_deck(client, claude)
    card = due(client, deck_id)[0]["card_uuid"]
    for index, day in enumerate([0, 2, 6]):
        answer(client, card, "easy", at=NOW + timedelta(days=day), client_uuid=f"m{index}")

    matured = next(
        c for c in due(client, deck_id, at=NOW + timedelta(days=400))
        if c["card_uuid"] == card
    )

    assert matured["previews"]["good"].endswith(("d", "mo")), matured["previews"]


def test_reviews_record_whatever_the_database_calls_utc(client, claude, pg_dsn):
    """The scheduler insists on `timezone.utc` exactly; psycopg hands back
    whatever the session's timezone is spelled as. On a server whose default
    is 'Etc/UTC' — the Docker image's default — every read-back datetime
    arrives as ZoneInfo("Etc/UTC"), which is the same moment and a different
    object. Recording a review must not care.
    """
    import psycopg

    base = pg_dsn.split("?")[0]
    schema = pg_dsn.split("search_path%3D")[1]
    admin = psycopg.connect(base, autocommit=True)
    dbname = admin.execute("SELECT current_database()").fetchone()[0]
    admin.execute(f'ALTER DATABASE "{dbname}" SET timezone TO \'Etc/UTC\'')
    admin.close()
    try:
        deck_id, _ = studied_deck(client, claude)
        first = due(client, deck_id)[0]
        replied = answer(client, first["card_uuid"], "easy")
        assert replied.status_code == 200, replied.text
        assert replied.json()["accepted"] == 1
        # And the projection actually moved — the rebuild ran over the
        # read-back history, which is where the wrong spelling used to land.
        remaining = due(client, deck_id)
        assert first["card_uuid"] not in [c["card_uuid"] for c in remaining]
    finally:
        admin = psycopg.connect(base, autocommit=True)
        admin.execute(f'ALTER DATABASE "{dbname}" RESET timezone')
        admin.close()


def test_a_finished_deck_is_already_studiable_for_its_owner(client, claude):
    """The screen after generation shows topics and cards, not an enrolment
    gate. Observed live 2026-08-26: a 132-card deck read as "no cards yet"
    because the deck screen reads the study projection and nothing had
    enrolled the owner."""
    claude.replies_json(PLAN)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    claude.answers(lesson=LESSON, cards=CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")
    deck_id = client.get(f"/api/jobs/{job_id}").json()["deck_id"]

    # No POST /study anywhere above: completion itself did the enrolling.
    assert due(client, deck_id), "a completed deck should be studiable at once"
    assert client.get(f"/api/decks/{deck_id}/mastery").json()["topics"]
