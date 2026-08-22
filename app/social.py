"""Friends, and the numbers it is honest to put beside each other.

**Decks are personal.** Two people studying biochemistry uploaded different
PDFs, so they hold different decks, different topics and different cards.
"Who has mastered glycolysis" is not a question this data can answer between
two people, and a leaderboard that showed it anyway would be putting two
numbers side by side that are not the same number.

So the comparison is built out of things that mean the same thing whatever
somebody studies:

- **Reviews in a window.** How much work was done. It is what people enjoy
  competing on, and it is a volume measure — it says nothing about knowing.
- **Streak.** Consecutive days ending today. Consistency is the thing spaced
  repetition actually asks of somebody, so it is the number worth making
  visible.
- **Cards known.** How many cards this person would recall right now, from the
  same retrievability that defines mastery. Subject-independent by
  construction, and unlike a review count it goes down when you stop.

Comparing mastery of one *topic* needs both people to hold the same deck, which
means deck sharing. That is a real feature and a different one; `compare` says
so rather than inventing an answer.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import psycopg

from app import db, study

# Six characters from an alphabet with no O/0 or I/1/l, because this is read
# off one screen and typed into another, sometimes out loud.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

# What a leaderboard is asking about by default. A window rather than all of
# history: a board counting everything ever is one nobody new can join, and it
# stops measuring whether anybody is still studying.
DEFAULT_WINDOW_DAYS = 7

# How confident recall has to be before a card counts as known. FSRS schedules
# toward 0.9 by default, so this is the same bar the scheduler is aiming at
# rather than a second opinion about what knowing means.
KNOWN_THRESHOLD = 0.9

PENDING, ACCEPTED = "pending", "accepted"


class NotFriendable(Exception):
    """A friendship that cannot exist."""


def friend_code(conn: psycopg.Connection, account_id: str) -> str:
    """This account's shareable code, minted once and then stable.

    Deliberately not "add by email". An endpoint that reports whether an
    address has an account is an endpoint that tells anybody whether an address
    has an account, one guess at a time. A code somebody chose to hand over
    leaks nothing they did not hand over.
    """
    row = conn.execute(
        "SELECT friend_code FROM account WHERE id = %s", (account_id,)
    ).fetchone()
    if row and row["friend_code"]:
        return row["friend_code"]

    for _ in range(20):
        candidate = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        claimed = conn.execute(
            "UPDATE account SET friend_code = %s"
            " WHERE id = %s AND NOT EXISTS"
            "       (SELECT 1 FROM account WHERE friend_code = %s)",
            (candidate, account_id, candidate),
        )
        if claimed.rowcount:
            return candidate
    raise NotFriendable("could not mint a code")


def _pair(one: str, other: str) -> tuple[str, str]:
    """One row per friendship, not two.

    Storing both directions means two rows that can disagree, and they will:
    somebody removes a friend and half of it is left behind. Ordering the pair
    makes the row unique whichever way round it was created.
    """
    return (one, other) if str(one) < str(other) else (other, one)


def request(conn: psycopg.Connection, account_id: str, code: str) -> str:
    """Ask to be somebody's friend, by the code they gave you."""
    row = conn.execute(
        "SELECT id FROM account WHERE friend_code = %s", ((code or "").strip().upper(),)
    ).fetchone()
    if row is None:
        raise NotFriendable("no such code")

    other = str(row["id"])
    if other == str(account_id):
        raise NotFriendable("you are already your own best study partner")

    low, high = _pair(account_id, other)
    conn.execute(
        "INSERT INTO friendship (account_low, account_high, state, requested_by, created_at)"
        " VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (account_low, account_high) DO NOTHING",
        (low, high, PENDING, account_id, db.now()),
    )
    return other


def accept(conn: psycopg.Connection, account_id: str, other: str) -> bool:
    """Accept a request somebody else made. Only they can have made it."""
    low, high = _pair(account_id, other)
    accepted = conn.execute(
        "UPDATE friendship SET state = %s"
        " WHERE account_low = %s AND account_high = %s AND state = %s"
        "   AND requested_by <> %s",
        (ACCEPTED, low, high, PENDING, account_id),
    )
    return accepted.rowcount > 0


def remove(conn: psycopg.Connection, account_id: str, other: str) -> bool:
    """Ending a friendship ends it for both. One row, so it cannot half-happen."""
    low, high = _pair(account_id, other)
    return conn.execute(
        "DELETE FROM friendship WHERE account_low = %s AND account_high = %s", (low, high)
    ).rowcount > 0


def listing(conn: psycopg.Connection, account_id: str) -> dict:
    rows = conn.execute(
        "SELECT f.account_low, f.account_high, f.state, f.requested_by,"
        "       a.display_name, a.friend_code"
        "  FROM friendship f"
        "  JOIN account a ON a.id = CASE WHEN f.account_low = %s"
        "                                THEN f.account_high ELSE f.account_low END"
        " WHERE f.account_low = %s OR f.account_high = %s"
        " ORDER BY a.display_name NULLS LAST",
        (account_id, account_id, account_id),
    ).fetchall()

    friends, incoming, outgoing = [], [], []
    for row in rows:
        other = (
            str(row["account_high"])
            if str(row["account_low"]) == str(account_id)
            else str(row["account_low"])
        )
        entry = {
            "account_id": other,
            "display_name": row["display_name"],
            "friend_code": row["friend_code"],
        }
        if row["state"] == ACCEPTED:
            friends.append(entry)
        elif str(row["requested_by"]) == str(account_id):
            outgoing.append(entry)
        else:
            incoming.append(entry)
    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}


def circle(conn: psycopg.Connection, account_id: str) -> list[str]:
    """Everybody whose numbers this person may see: their friends, and them.

    Accepted only. A request is not consent to be measured.
    """
    rows = conn.execute(
        "SELECT account_low, account_high FROM friendship"
        " WHERE state = %s AND (account_low = %s OR account_high = %s)",
        (ACCEPTED, account_id, account_id),
    ).fetchall()
    others = [
        str(row["account_high"])
        if str(row["account_low"]) == str(account_id)
        else str(row["account_low"])
        for row in rows
    ]
    return [str(account_id), *others]


def leaderboard(
    conn: psycopg.Connection,
    account_id: str,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    at: datetime | None = None,
) -> dict:
    moment = at or db.now()
    since = moment - timedelta(days=days)
    people = circle(conn, account_id)

    rows = []
    for other in people:
        counted = conn.execute(
            "SELECT COUNT(*) AS reviews,"
            "       COUNT(DISTINCT date_trunc('day', reviewed_at)) AS days_studied"
            "  FROM review WHERE account_id = %s AND reviewed_at >= %s AND reviewed_at <= %s",
            (other, since, moment),
        ).fetchone()
        named = conn.execute(
            "SELECT display_name FROM account WHERE id = %s", (other,)
        ).fetchone()
        rows.append(
            {
                "account_id": other,
                "display_name": named["display_name"] if named else None,
                "is_you": other == str(account_id),
                "reviews": counted["reviews"],
                "days_studied": counted["days_studied"],
                "streak_days": streak(conn, other, moment),
                "cards_known": cards_known(conn, other, moment),
            }
        )

    rows.sort(key=lambda row: (-row["reviews"], -row["cards_known"], row["account_id"]))
    return {"window_days": days, "rows": rows}


def streak(conn: psycopg.Connection, account_id: str, at: datetime) -> int:
    """Consecutive days ending today, or yesterday if today is not done yet.

    Yesterday counts so that somebody who has not studied at nine in the
    morning is not told their streak is already broken. Anything stricter
    punishes them for the time of day.
    """
    rows = conn.execute(
        "SELECT DISTINCT date_trunc('day', reviewed_at) AS day FROM review"
        " WHERE account_id = %s AND reviewed_at <= %s ORDER BY day DESC LIMIT 400",
        (account_id, at),
    ).fetchall()
    if not rows:
        return 0

    days = [row["day"].date() for row in rows]
    today = at.date()
    if days[0] not in (today, today - timedelta(days=1)):
        return 0

    run, expected = 0, days[0]
    for day in days:
        if day != expected:
            break
        run += 1
        expected = expected - timedelta(days=1)
    return run


def cards_known(conn: psycopg.Connection, account_id: str, at: datetime) -> int:
    """Cards this person would recall right now.

    Computed rather than stored, because retrievability decays continuously and
    a stored copy would be wrong the moment after it was written.

    Only cards that have been answered are considered, which is also the
    cheap filter: it is the reps that make a card a candidate. At the scale this
    is written for -- a person and a handful of friends -- that is a few
    thousand rows. If a leaderboard ever spans hundreds of people, this is the
    thing that needs a materialised summary, and the summary will be derivable
    from the log like everything else.
    """
    rows = conn.execute(
        "SELECT state, step, stability, difficulty, due, last_review FROM study_card"
        " WHERE account_id = %s AND last_review IS NOT NULL AND stability IS NOT NULL",
        (account_id,),
    ).fetchall()
    return sum(1 for row in rows if study._retrievability(row, at) >= KNOWN_THRESHOLD)


def compare(conn: psycopg.Connection, account_id: str, deck_id: str) -> dict:
    """Per-topic mastery beside a friend's, for a deck you both hold.

    Almost always empty today, and that is the honest answer rather than a
    missing feature quietly filled in with something else. A deck belongs to
    whoever uploaded the material; until decks can be shared, two friends
    studying the same subject hold different cards and their per-topic numbers
    are not comparable.
    """
    mine = study.mastery(conn, account_id, deck_id)
    friends = []
    for other in circle(conn, account_id):
        if other == str(account_id):
            continue
        holds = conn.execute(
            "SELECT 1 FROM study_card WHERE account_id = %s AND deck_id = %s LIMIT 1",
            (other, deck_id),
        ).fetchone()
        if holds:
            friends.append({"account_id": other, **study.mastery(conn, other, deck_id)})

    return {
        "deck_id": deck_id,
        "you": mine,
        "friends": friends,
        "why_empty": (
            ""
            if friends
            else "Nobody you study with holds this deck. Topic-by-topic comparison "
            "needs a shared deck: a deck belongs to whoever uploaded the material, "
            "so two people studying the same subject have different cards."
        ),
    }
