"""Taking a deck down.

The one destructive act in the product, so its edges are the point: only the
owner can do it, it disappears for the recipient too, and the review log —
the append-only record every leaderboard is computed from — survives it.
"""

from tests.conftest import SOMEBODY_ELSE, TESTER, account_id
from tests.test_deck_sharing import shared
from tests.test_study import answer, due, studied_deck


def test_the_owner_can_delete_a_deck_and_it_is_gone_everywhere(boot, claude):
    with boot() as machine:
        deck_id, job_id = shared(machine, claude)

        reply = machine.delete(f"/api/decks/{deck_id}")
        assert reply.status_code == 200

        assert machine.get("/api/decks").json()["decks"] == []
        assert machine.get("/api/jobs").json()["jobs"] == []
        assert machine.get(f"/api/jobs/{job_id}").status_code == 404
        assert machine.get(f"/api/decks/{deck_id}/due").status_code == 404

        # Gone for the person it was shared with, too.
        machine.sign_in_as(SOMEBODY_ELSE)
        assert machine.get("/api/decks").json()["decks"] == []


def test_only_the_owner_can_delete_it(boot, claude):
    with boot() as machine:
        deck_id, _ = shared(machine, claude)

        machine.sign_in_as(SOMEBODY_ELSE)
        # A recipient may leave; they may not take the author's material down.
        assert machine.delete(f"/api/decks/{deck_id}").status_code == 403

        machine.sign_in_as(TESTER)
        still = machine.get("/api/decks").json()["decks"]
        assert any(deck["deck_id"] == deck_id for deck in still)


def test_a_stranger_cannot_even_learn_the_deck_existed(boot, claude):
    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)

        machine.sign_in_as(account_id(77))
        assert machine.delete(f"/api/decks/{deck_id}").status_code == 404


def test_the_review_log_survives_the_deck(boot, claude, pg_dsn):
    """Reviews record work somebody actually did, and the leaderboard already
    counted it. Deleting a deck must not rewrite that history."""
    import psycopg

    with boot() as machine:
        deck_id, _ = studied_deck(machine, claude)
        card = due(machine, deck_id)[0]["card_uuid"]
        assert answer(machine, card, "good").status_code == 200

        machine.delete(f"/api/decks/{deck_id}")

        kept = psycopg.connect(pg_dsn, autocommit=True).execute(
            "SELECT COUNT(*) FROM review"
        ).fetchone()[0]
        assert kept == 1
