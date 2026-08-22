"""The topic fan-out, and the one ordering constraint it must respect.

Running every topic call at once looks obviously right and is obviously wrong.
A cache entry only becomes readable once the first response has begun, so a
flat fan-out has all N calls miss, and each pays a cache-creation charge that
costs MORE than not caching at all. The first call therefore runs alone to
write the prefix; the rest read it concurrently.
"""

import time

PLAN = {
    "topics": [
        {
            "topic_id": f"t{n}",
            "path": f"Bio::Topic {n}",
            "difficulty": "easy",
            "rationale": "Mixed.",
            "note_type": "basic",
            "proposed_card_count": 1,
            "claims": [f"Claim {n}."],
        }
        for n in range(1, 7)
    ]
}
CARDS = {"cards": [{"note_type": "basic", "front": "Q?", "back": "A.",
                    "source_page": 1, "existing_card_id": None}]}


def run(client, claude, pause=0.0):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    for _ in PLAN["topics"]:
        claude.replies_json(CARDS, pause=pause)
    started = time.perf_counter()
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id, time.perf_counter() - started


def test_the_first_topic_runs_alone_so_it_can_write_the_cache(client, claude):
    run(client, claude, pause=0.05)

    assert not claude.overlapped_with_first, (
        "a call running alongside the first one misses the cache and pays a "
        "creation charge, which costs more than not caching at all"
    )


def test_the_remaining_topics_run_concurrently(client, claude):
    run(client, claude, pause=0.05)

    # Six topics: one alone, then five together.
    assert claude.peak_in_flight > 1, "the fan-out never actually fanned out"


def test_a_fan_out_finishes_far_faster_than_running_them_one_at_a_time(client, claude):
    _job_id, elapsed = run(client, claude, pause=0.1)

    # Sequential would be 6 x 0.1s of call time alone. Generous bound so this
    # asserts the shape rather than the machine's mood.
    assert elapsed < 0.45, f"took {elapsed:.2f}s, which looks sequential"


def test_every_topic_still_produces_its_cards(client, claude):
    job_id, _ = run(client, claude)

    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "complete"
    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert len(cards) == 6
    # Ordered by the plan, not by which call happened to finish first — a deck
    # whose order changes run to run is a deck that cannot be diffed.
    assert [c["deck_path"] for c in cards] == [t["path"] for t in PLAN["topics"]]


def test_one_topic_failing_does_not_take_the_others_with_it(client, claude):
    claude.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")

    claude.replies_json(CARDS)
    claude.refuses(category="bio")
    for _ in range(4):
        claude.replies_json(CARDS)

    client.post(f"/api/jobs/{job_id}/generate")

    topics = client.get(f"/api/jobs/{job_id}/topics").json()["topics"]
    assert sum(t["status"] == "done" for t in topics) == 5
    assert sum(t["status"] == "failed" for t in topics) == 1
