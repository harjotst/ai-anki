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


def run(client, llm, pause=0.0):
    llm.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")
    for _ in PLAN["topics"]:
        llm.replies_json(CARDS, pause=pause)
    started = time.perf_counter()
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id, time.perf_counter() - started


def test_the_first_topic_runs_alone_so_it_can_write_the_cache(client, llm):
    run(client, llm, pause=0.05)

    assert not llm.overlapped_with_first, (
        "a call running alongside the first one misses the cache and pays a "
        "creation charge, which costs more than not caching at all"
    )


def test_the_remaining_topics_run_concurrently(client, llm):
    run(client, llm, pause=0.05)

    # Six topics: one alone, then five together.
    assert llm.peak_in_flight > 1, "the fan-out never actually fanned out"


def test_a_fan_out_finishes_far_faster_than_running_them_one_at_a_time(client, llm):
    _job_id, elapsed = run(client, llm, pause=0.1)

    # Sequential would be 6 x 0.1s of call time alone, plus each topic's own
    # connection setup — well over a second end to end. The bound asserts the
    # shape, not the machine's mood: it sits far above concurrent's ~0.2s of
    # call time plus per-topic connections, and far below sequential.
    assert elapsed < 0.7, f"took {elapsed:.2f}s, which looks sequential"


def test_every_topic_still_produces_its_cards(client, llm):
    job_id, _ = run(client, llm)

    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "complete"
    cards = client.get(f"/api/jobs/{job_id}/cards").json()["cards"]
    assert len(cards) == 6
    # Ordered by the plan, not by which call happened to finish first — a deck
    # whose order changes run to run is a deck that cannot be diffed.
    assert [c["deck_path"] for c in cards] == [t["path"] for t in PLAN["topics"]]


def test_one_topic_failing_does_not_take_the_others_with_it(client, llm):
    llm.counts_tokens(1000).replies_json(PLAN)
    job_id = client.post(
        "/api/jobs", files={"file": ("lecture.txt", b"Material.", "text/plain")}, data={"deck_name": "Lecture"}
    ).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/plan")

    llm.replies_json(CARDS)
    llm.refuses()
    for _ in range(4):
        llm.replies_json(CARDS)

    client.post(f"/api/jobs/{job_id}/generate")

    topics = client.get(f"/api/jobs/{job_id}/topics").json()["topics"]
    assert sum(t["status"] == "done" for t in topics) == 5
    assert sum(t["status"] == "failed" for t in topics) == 1
