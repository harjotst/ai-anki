"""Studying, and the log everything else is derived from.

**`review` is append-only and authoritative. `study_card` is a projection.**
That one sentence is what the rest of the product rests on, so it is worth
saying why rather than only saying it.

*Offline sync needs no conflict resolution.* Two devices cannot disagree about
facts that have already happened. Merging two logs is their union, deduplicated
by an id the client chose — no last-write-wins, no vector clocks, no merge
policy to get subtly wrong at three in the morning.

*Leaderboards are recomputable rather than merely stored.* A bug in aggregation
becomes a re-run instead of lost history, and a number nobody can recompute is a
number nobody should trust.

*The scheduler can be replaced.* Run a better FSRS over the same history and
every card reschedules correctly, because the history was never overwritten.

`study_card` exists only because replaying a whole log on every query would be
wasteful. It can be dropped and rebuilt at any moment, and a test asserts
exactly that — it is what notices if the log ever quietly stops being the
record.

The algorithm itself is the `fsrs` package rather than an implementation here.
Spaced repetition scheduling is a fitted model with published parameters, and
the failure mode of getting it subtly wrong is that somebody's schedule decays
for months before anybody can tell.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from fsrs import Card, Rating, Scheduler

from app import db

# The four answers, as a person would say them. The package's own enum is not
# used at the boundary: a client should not have to know that Again is 1.
RATINGS = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}

# What FSRS calls each phase, in words rather than integers, because these
# reach the screen.
STATES = {1: "learning", 2: "review", 3: "relearning"}

_scheduler = Scheduler()


@contextmanager
def _fuzz_seeded_by(card_uuid: str):
    """Make interval fuzzing deterministic for one card.

    FSRS deliberately jitters intervals so that a hundred cards learned on the
    same day do not all come back on the same day. It draws that jitter from
    the global random number generator, which makes a replay produce a
    different schedule from the original -- and "the log is authoritative"
    stops meaning anything if replaying it gives a different answer.

    Seeding from the card's own id keeps both properties. Two cards still get
    different jitter, so reviews still spread; the same card always gets the
    same jitter, so a rebuild reproduces exactly what was there. The generator's
    state is restored afterwards, because this module has no business changing
    the randomness the rest of the process sees.
    """
    state = random.getstate()
    random.seed(card_uuid)
    try:
        yield
    finally:
        random.setstate(state)


class UnknownRating(Exception):
    """A rating the scheduler has no meaning for."""


def rating_of(name: str) -> Rating:
    try:
        return RATINGS[str(name).lower()]
    except KeyError as exc:
        raise UnknownRating(
            f"'{name}' is not a rating; expected one of {', '.join(RATINGS)}"
        ) from exc


# --- enrolling -----------------------------------------------------------


def enrol(conn: psycopg.Connection, account_id: str, deck_id: str) -> int:
    """Make a deck's cards studiable, without disturbing any already are.

    `ON CONFLICT DO NOTHING` is the whole of it, and it is the important line
    in this module after the log itself: a second job against the same deck
    must add its new cards and leave the scheduling of the old ones alone.
    Resetting somebody's review history is the most destructive thing this
    application could do to them.
    """
    # Due at the deck's creation rather than at this moment. A card nobody has
    # answered is due now and always has been, so the exact instant carries no
    # information -- and taking it from the clock would make it the one thing a
    # rebuild could not reproduce, which would quietly break the property this
    # whole design rests on.
    added = conn.execute(
        "INSERT INTO study_card (account_id, card_uuid, deck_id, state, step, due)"
        " SELECT %s, c.card_uuid, c.deck_id, 1, 0, d.created_at"
        "   FROM (SELECT DISTINCT ON (card_uuid) card_uuid, deck_id FROM card"
        "          WHERE deck_id = %s AND retired_at IS NULL"
        "          ORDER BY card_uuid, id DESC) c"
        "   JOIN deck d ON d.id = c.deck_id"
        " ON CONFLICT (account_id, card_uuid) DO NOTHING",
        (account_id, deck_id),
    )
    return added.rowcount


# --- answering -----------------------------------------------------------


def record(conn: psycopg.Connection, account_id: str, reviews: list[dict]) -> int:
    """Append answers to the log, and rebuild what they affect.

    Returns how many were new. A retry of a push whose reply was lost adds
    nothing and says so, which is what lets a client retry without thinking.
    """
    accepted = 0
    touched: set[str] = set()
    for review in reviews:
        rating = rating_of(review["rating"])
        card_uuid = review["card_uuid"]
        written = conn.execute(
            "INSERT INTO review (account_id, client_uuid, card_uuid, rating,"
            "                    reviewed_at, duration_ms, received_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (account_id, client_uuid) DO NOTHING",
            (
                account_id,
                review["client_uuid"],
                card_uuid,
                rating.value,
                _moment(review["reviewed_at"]),
                review.get("duration_ms"),
                # Stamped here, not by the client. Ordering within one person's
                # history uses their own clock; anything competitive uses this
                # one, because a client's clock is a thing a client controls.
                db.now(),
            ),
        )
        if written.rowcount:
            accepted += 1
            touched.add(card_uuid)

    for card_uuid in touched:
        rebuild(conn, account_id, card_uuid)
    return accepted


def rebuild(conn: psycopg.Connection, account_id: str, card_uuid: str) -> None:
    """Replay one card's whole history, in the order it happened.

    In event order, not arrival order. Two devices sync whenever they reconnect
    and yesterday's answer can land after today's; what happened is fixed, when
    we heard about it is not.
    """
    history = conn.execute(
        "SELECT rating, reviewed_at, duration_ms FROM review"
        " WHERE account_id = %s AND card_uuid = %s ORDER BY reviewed_at, id",
        (account_id, card_uuid),
    ).fetchall()

    card = Card()
    with _fuzz_seeded_by(card_uuid):
        for entry in history:
            card, _ = _scheduler.review_card(
                card,
                Rating(entry["rating"]),
                _utc(entry["reviewed_at"]),
                entry["duration_ms"],
            )

    conn.execute(
        "UPDATE study_card SET state = %s, step = %s, stability = %s, difficulty = %s,"
        " due = %s, last_review = %s, reps = %s"
        " WHERE account_id = %s AND card_uuid = %s",
        (
            card.state.value if hasattr(card.state, "value") else int(card.state),
            card.step,
            card.stability,
            card.difficulty,
            card.due,
            card.last_review,
            len(history),
            account_id,
            card_uuid,
        ),
    )


def rebuild_all(conn: psycopg.Connection) -> int:
    """Reconstruct every projection, from ownership and the log.

    Two sources, because two things are being reconstructed. *Which* cards a
    person studies comes from the decks they own -- everybody studies every
    deck they made, so it is derivable rather than a decision that needs
    storing. *What state those cards are in* comes from the review log.

    An earlier version rebuilt only from the log and quietly lost every card
    that had been enrolled and never answered, which is most of a fresh deck.

    Here so the property can be exercised rather than merely believed, and
    because the day a scheduler is replaced, this is the migration.
    """
    owners = conn.execute(
        "SELECT id AS deck_id, account_id FROM deck WHERE account_id IS NOT NULL"
    ).fetchall()
    for owner in owners:
        enrol(conn, str(owner["account_id"]), owner["deck_id"])

    pairs = conn.execute("SELECT DISTINCT account_id, card_uuid FROM review").fetchall()
    for pair in pairs:
        rebuild(conn, str(pair["account_id"]), pair["card_uuid"])
    return len(pairs)


def studiable(conn: psycopg.Connection, account_id: str, card_uuid: str | None) -> bool:
    """Is this a card this person is actually studying?

    Answered from `study_card` rather than from `card`, so somebody who knows a
    uuid but has not enrolled the deck it belongs to gets the same answer as
    somebody asking about a card that does not exist.
    """
    if not card_uuid:
        return False
    return conn.execute(
        "SELECT 1 FROM study_card WHERE account_id = %s AND card_uuid = %s",
        (account_id, card_uuid),
    ).fetchone() is not None


# --- reading -------------------------------------------------------------


def due_cards(
    conn: psycopg.Connection, account_id: str, deck_id: str, at: datetime | None = None
) -> list[dict]:
    moment = at or db.now()
    rows = conn.execute(
        "SELECT s.card_uuid, s.state, s.step, s.due, s.stability, s.difficulty,"
        "       s.last_review, s.reps,"
        "       c.front, c.back, c.note_type, c.deck_path, c.topic_id"
        "  FROM study_card s"
        "  JOIN LATERAL (SELECT front, back, note_type, deck_path, topic_id FROM card"
        "                 WHERE card_uuid = s.card_uuid ORDER BY id DESC LIMIT 1) c ON TRUE"
        " WHERE s.account_id = %s AND s.deck_id = %s AND s.due <= %s"
        " ORDER BY s.due",
        (account_id, deck_id, moment),
    ).fetchall()
    return [{**_as_card(row), "previews": _previews(row, moment)} for row in rows]


def deck_cards(conn: psycopg.Connection, account_id: str, deck_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT s.card_uuid, s.state, s.due, s.stability, s.difficulty, s.reps,"
        "       c.front, c.back, c.note_type, c.deck_path, c.topic_id"
        "  FROM study_card s"
        "  JOIN LATERAL (SELECT front, back, note_type, deck_path, topic_id FROM card"
        "                 WHERE card_uuid = s.card_uuid ORDER BY id DESC LIMIT 1) c ON TRUE"
        " WHERE s.account_id = %s AND s.deck_id = %s"
        " ORDER BY c.deck_path, s.card_uuid",
        (account_id, deck_id),
    ).fetchall()
    return [{**_as_card(row), "difficulty": row["difficulty"]} for row in rows]


def history(conn: psycopg.Connection, account_id: str, card_uuid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT rating, reviewed_at, duration_ms FROM review"
        " WHERE account_id = %s AND card_uuid = %s ORDER BY reviewed_at, id",
        (account_id, card_uuid),
    ).fetchall()
    names = {value.value: name for name, value in RATINGS.items()}
    return [
        {
            "rating": names[row["rating"]],
            "reviewed_at": row["reviewed_at"].isoformat(),
            "duration_ms": row["duration_ms"],
        }
        for row in rows
    ]


def mastery(
    conn: psycopg.Connection, account_id: str, deck_id: str, at: datetime | None = None
) -> dict:
    """Mean chance of recalling this topic's cards, right now.

    Retrievability is what FSRS already computes and is the honest measure:
    it decays when studying stops, so a topic crammed in March does not still
    read as mastered in June, and it compares between two people without
    normalising for how many cards each of them generated.
    """
    moment = at or db.now()
    rows = conn.execute(
        "SELECT s.card_uuid, s.state, s.step, s.stability, s.difficulty, s.due,"
        "       s.last_review, c.deck_path, c.topic_id"
        "  FROM study_card s"
        "  JOIN LATERAL (SELECT deck_path, topic_id FROM card"
        "                 WHERE card_uuid = s.card_uuid"
        "                 ORDER BY id DESC LIMIT 1) c ON TRUE"
        " WHERE s.account_id = %s AND s.deck_id = %s",
        (account_id, deck_id),
    ).fetchall()

    by_path: dict[str, list[float]] = {}
    # The topic behind each path, so a topic row on screen can open its
    # lesson without fishing the id out of whichever cards happen to be due
    # — which is how lessons ended up unreachable on a caught-up deck.
    topic_of: dict[str, str] = {}
    for row in rows:
        by_path.setdefault(row["deck_path"], []).append(_retrievability(row, moment))
        topic_of.setdefault(row["deck_path"], row["topic_id"])

    topics = [
        {
            "deck_path": path,
            "topic_id": topic_of[path],
            "cards": len(scores),
            "mastery": round(sum(scores) / len(scores), 4),
        }
        for path, scores in sorted(by_path.items())
    ]
    every = [score for scores in by_path.values() for score in scores]
    return {
        "deck_id": deck_id,
        "topics": topics,
        "overall": round(sum(every) / len(every), 4) if every else 0.0,
    }


def activity(conn: psycopg.Connection, account_id: str) -> dict:
    """How much work somebody has done. A volume measure, and labelled as one.

    It is what people enjoy competing on, and it says nothing about how much
    they know — that is what mastery is for.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS reviews, COUNT(DISTINCT card_uuid) AS cards_seen,"
        "       COUNT(DISTINCT date_trunc('day', reviewed_at)) AS days_studied"
        "  FROM review WHERE account_id = %s",
        (account_id,),
    ).fetchone()
    # Per-day history, most recent first. The heatmap, the streak ring and
    # banked rest days are all derived from which days somebody studied, and
    # totals alone cannot answer that. Days with nothing are absent rather
    # than zero-filled: the client knows the calendar; the server only knows
    # what happened.
    days = conn.execute(
        "SELECT date_trunc('day', reviewed_at)::date AS day, COUNT(*) AS reviews"
        "  FROM review WHERE account_id = %s"
        " GROUP BY 1 ORDER BY 1 DESC LIMIT 120",
        (account_id,),
    ).fetchall()
    return {
        "reviews": row["reviews"],
        "cards_seen": row["cards_seen"],
        "days_studied": row["days_studied"],
        "days": [
            {"day": entry["day"].isoformat(), "reviews": entry["reviews"]}
            for entry in days
        ],
    }


# --- helpers -------------------------------------------------------------


def _as_card(row) -> dict:
    from app.planning import render_cloze

    return {
        "card_uuid": row["card_uuid"],
        "front": row["front"],
        # A cloze card shown as its markup is not merely hard to judge -- it
        # has the answer written in it. Rendering is the difference between
        # being asked a question and being shown one.
        "rendered_front": (
            render_cloze(row["front"]) if row["note_type"] == "cloze" else row["front"]
        ),
        "back": row["back"],
        "note_type": row["note_type"],
        "deck_path": row["deck_path"],
        "topic_id": row["topic_id"],
        "state": STATES.get(row["state"], "learning"),
        "due": row["due"].isoformat(),
        "stability": row["stability"],
        "reps": row["reps"],
    }


def _previews(row, at: datetime) -> dict:
    """What each answer would schedule, from the scheduler that will apply it.

    Served rather than mirrored client-side: a mirror whose parameters drifted
    from the real ones would print numbers the next day proves wrong, and a
    wrong number under a rating button erodes trust in all of them.

    Inside the same per-card fuzz seed as `rebuild`, so the preview is the
    schedule the rating would actually produce, not an unfuzzed cousin of it.
    """
    def fresh():
        if row["last_review"] is None or row["stability"] is None:
            return Card()
        return Card(
            state=row["state"], step=row["step"], stability=row["stability"],
            difficulty=row["difficulty"], due=_utc(row["due"]),
            last_review=_utc(row["last_review"]),
        )

    out = {}
    with _fuzz_seeded_by(row["card_uuid"]):
        for name, rating in RATINGS.items():
            scheduled, _ = _scheduler.review_card(fresh(), rating, at)
            out[name] = _humanize(scheduled.due - at)
    return out


def _humanize(delta) -> str:
    minutes = max(1, round(delta.total_seconds() / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours = round(minutes / 60)
    if hours < 24:
        return f"{hours}h"
    days = round(hours / 24)
    if days < 30:
        return f"{days}d"
    return f"{round(days / 30)}mo"


def _retrievability(row, at: datetime) -> float:
    """Zero for a card never answered. It has not been recalled, so it is not
    known — treating an unseen card as mastered would make a fresh deck look
    finished."""
    if row["last_review"] is None or row["stability"] is None:
        return 0.0
    card = Card(
        state=row["state"],
        step=row["step"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due=_utc(row["due"]),
        last_review=_utc(row["last_review"]),
    )
    return float(_scheduler.get_card_retrievability(card, at))


def _utc(value: datetime | None) -> datetime | None:
    """The exact UTC the scheduler insists on.

    psycopg hands back TIMESTAMPTZ in the session's timezone -- `timezone.utc`
    when the server says "UTC", but `ZoneInfo("Etc/UTC")` when it says
    "Etc/UTC", which is the Docker image's default. FSRS compares `tzinfo`
    against `timezone.utc` by equality, so the same moment in the second
    spelling is rejected. Normalising here makes recording reviews independent
    of how the database's timezone happens to be spelled.
    """
    return None if value is None else value.astimezone(timezone.utc)


def _moment(value) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
