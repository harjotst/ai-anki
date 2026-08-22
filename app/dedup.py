"""Catching the same fact written twice.

Two layers, and the order matters. Pass 1 partitions the material so each topic
owns a disjoint set of claims — that is the mechanism. This module is the safety
net for what gets through anyway, because parallel topic calls each see the whole
corpus and none of them sees what the others are writing.

Nothing is deleted. A near-duplicate is flagged and shown, because the
difference between "the same fact twice" and "two questions that read alike" is
a judgement the user is better placed to make.
"""

from __future__ import annotations

import psycopg

from app.ledger import normalise


def same_question(left: str, right: str) -> bool:
    """Exact match once formatting is normalised away.

    Deliberately exact rather than fuzzy at this layer: a false positive here
    would flag two genuinely different questions as redundant, and the cost of
    missing one is only that the user reviews a fact twice.
    """
    return normalise(left) == normalise(right)


def specificity(deck_path: str) -> int:
    """How deep a topic sits. A fact belongs with the most specific one."""
    return len((deck_path or "").split("::"))


def flag_duplicates(conn: psycopg.Connection, job_id: str) -> int:
    """Mark each repeat of a question, keeping the most specific copy.

    Returns how many were flagged.
    """
    rows = conn.execute(
        "SELECT card_uuid, deck_path, front FROM card WHERE job_id = %s ORDER BY position",
        (job_id,),
    ).fetchall()

    keepers: dict[str, dict] = {}
    flagged = 0
    for row in rows:
        key = normalise(row["front"])
        held = keepers.get(key)
        if held is None:
            keepers[key] = dict(row)
            continue

        # The deeper topic keeps the card; the shallower one is the repeat.
        if specificity(row["deck_path"]) > specificity(held["deck_path"]):
            loser, winner = held, dict(row)
            keepers[key] = winner
        else:
            loser, winner = dict(row), held

        conn.execute(
            "UPDATE card SET duplicate_of = %s WHERE card_uuid = %s",
            (winner["card_uuid"], loser["card_uuid"]),
        )
        conn.execute(
            "UPDATE card SET duplicate_of = NULL WHERE card_uuid = %s", (winner["card_uuid"],)
        )
        flagged += 1

    return flagged
