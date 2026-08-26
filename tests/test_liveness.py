"""The server stays alive while one request is stuck.

Every handler used to run its database work directly on the event loop, which
worked until the database moved across the internet: the first TCP connection
to die mid-read froze the entire server, because the thread stuck in that read
was the thread every other request needed. The fix is structural — handlers
run on the threadpool, the guard and the worker read on threads — and this
file is what keeps it structural: a request pinned inside a slow query must
cost only itself.
"""

import threading
import time

from app import study


def test_a_hung_query_on_one_request_does_not_block_another(client, monkeypatch):
    """One request sleeps inside the database; a second one still answers.

    The sleep stands in for the real failure — a dead socket, a slow query, a
    lock — because what matters is not why one request is stuck but that its
    being stuck is not contagious. Before the threadpool move, the second
    request here waited out the full sleep.
    """
    real = study.activity
    reached_the_sleep = threading.Event()

    def stuck(conn, account_id, *, tz_offset_minutes=0):
        reached_the_sleep.set()
        conn.execute("SELECT pg_sleep(2)")
        return real(conn, account_id, tz_offset_minutes=tz_offset_minutes)

    monkeypatch.setattr(study, "activity", stuck)

    slow = threading.Thread(target=lambda: client.get("/api/me/activity"))
    slow.start()
    try:
        assert reached_the_sleep.wait(timeout=5), "the slow request never started"

        begun = time.monotonic()
        reply = client.get("/api/decks")
        waited = time.monotonic() - begun

        assert reply.status_code == 200
        # Well under the two seconds the other request is pinned for. The
        # margin is generous because CI machines are slow, not because the
        # bound is soft — serialized behind the sleep, this would be >= 2s.
        assert waited < 1.5, f"a healthy request waited {waited:.2f}s behind a stuck one"
    finally:
        slow.join()
