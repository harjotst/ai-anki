"""Durability: a job survives the machine dying.

Fly SIGTERMs on deploys, secret changes, scale changes, host migrations and OOM,
and a generation run is far longer than any drain window. These tests drive the
whole machine — checkpoint, resume, backoff, attempt cap — through the HTTP
boundary, faking only the Anthropic transport.
"""

import contextlib
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor

import pytest

from tests.conftest import MachineKilled
from tests.test_generation import CELL_CARDS, GLYCOLYSIS_CARDS
from app import worker
from tests.test_planning import PLAN, upload


# More topics than the fan-out runs at once, so a drain has something it can
# visibly decline to start. Under a bounded fan-out every topic inside the
# window is already in flight when SIGTERM lands and can only be abandoned; the
# invariant that a draining worker takes no NEW work is about the ones past it,
# so a plan has to be bigger than the window for it to bite at all.
def _filler_topic(index: int) -> dict:
    return {
        "topic_id": f"topic-{index}",
        "path": f"Biology::Topic {index}",
        "difficulty": "medium",
        "rationale": "Mechanisms worth relating to each other.",
        "note_type": "basic",
        "proposed_card_count": 3,
    }


BEYOND_THE_WINDOW = worker.MAX_CONCURRENT_TOPICS + 1
OVERSUBSCRIBED_PLAN = {
    "topics": [
        PLAN["topics"][0],  # the pacesetter, which runs alone
        *(_filler_topic(i) for i in range(1, BEYOND_THE_WINDOW + 1)),
    ]
}
# The one topic a drain must never reach.
LAST_TOPIC_PATH = f"Biology::Topic {BEYOND_THE_WINDOW}"


def planned_job(client, claude, plan=PLAN):
    claude.replies_json(plan)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    return job_id


def topics_of(client, job_id):
    return client.get(f"/api/jobs/{job_id}/topics").json()["topics"]


def generate_until_killed(boot, job_id, **settings):
    """Generate on a machine that is killed part-way through.

    The machine does not survive it, so everything after this must be observed
    from a restart — which is the point: only what was committed remains.
    """
    machine = boot(**settings)
    # No shutdown runs on a machine that was killed — the client's own loop went
    # down with the request, and says so on the way out.
    with contextlib.suppress(RuntimeError, CancelledError):
        with machine:
            with pytest.raises(MachineKilled):
                machine.post(f"/api/jobs/{job_id}/generate")


def test_the_attempt_counter_is_committed_before_the_first_call_of_a_run(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)
        assert machine.get(f"/api/jobs/{job_id}").json()["attempt_count"] == 0

    claude.dies()
    generate_until_killed(boot, job_id)

    with boot() as restarted:
        # The run produced nothing at all, and still the attempt is on record.
        # Counting after success instead would let a deterministic crash resume
        # for ever, re-paying the document cache write every time.
        assert restarted.get(f"/api/jobs/{job_id}").json()["attempt_count"] == 1
        assert [t["status"] for t in topics_of(restarted, job_id)] == ["pending", "pending"]
        assert restarted.get(f"/api/jobs/{job_id}/cards").json()["cards"] == []


def test_a_restart_marks_a_job_whose_worker_is_gone_as_interrupted(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)

    claude.replies_json(GLYCOLYSIS_CARDS).dies()
    generate_until_killed(boot, job_id)

    with boot() as restarted:
        job = restarted.get(f"/api/jobs/{job_id}").json()
        assert job["state"] == "interrupted"
        # The finished topic keeps its cards; the one that was in flight when
        # the machine went is waiting to be run again.
        assert [t["status"] for t in topics_of(restarted, job_id)] == ["done", "pending"]
        assert len(restarted.get(f"/api/jobs/{job_id}/cards").json()["cards"]) == 2


def test_a_resume_runs_only_the_topics_that_did_not_finish(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)

    claude.replies_json(GLYCOLYSIS_CARDS).dies()
    generate_until_killed(boot, job_id)
    spent = len(claude.requests)

    claude.replies_json(CELL_CARDS)
    with boot(resume_backoff_seconds=0) as restarted:
        response = restarted.post(f"/api/jobs/{job_id}/generate")

        assert response.status_code == 200
        assert restarted.get(f"/api/jobs/{job_id}").json()["state"] == "complete"

        # One call, for the one topic that had not finished. Re-running the
        # finished one would re-bill the user for work they already paid for.
        assert len(claude.requests) == spent + 1
        resumed = claude.requests[-1]["messages"][0]["content"][-1]["text"]
        # The instruction opens by naming the one topic being generated. Other
        # topics appear further down as exclusions — that is the cross-topic
        # dedup partition, not a second topic being re-run.
        assert resumed.splitlines()[0].endswith("Biology::Cell Structure")
        assert "Glycolysis" not in resumed.split("OTHER TOPICS")[0]

        # The resuming process never saw the plan pass, so it has to rebuild the
        # cached prefix from the stored Source. It must come back carrying the
        # uploaded file, under the name it was uploaded with: a prefix that
        # differs by one byte from the one pass 1 wrote reads no cache at all,
        # and the resume re-pays for the whole document.
        prefix = claude.requests[-1]["messages"][0]["content"][0]
        assert prefix["source"]["data"] == "Glycolysis occurs in the cytosol."
        assert prefix["title"] == "lecture.txt"
        assert claude.requests[-1]["system"] == claude.requests[0]["system"]

        cards = restarted.get(f"/api/jobs/{job_id}/cards").json()["cards"]
        assert [c["front"] for c in cards] == [
            "Glycolysis occurs in the {{c1::cytosol}}.",
            "What is the rate-limiting enzyme of glycolysis?",
            "What organelle produces most ATP?",
        ]


def test_a_resume_is_refused_until_the_backoff_has_elapsed(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)

    claude.dies()
    generate_until_killed(boot, job_id)
    spent = len(claude.requests)

    with boot() as restarted:
        response = restarted.post(f"/api/jobs/{job_id}/generate")

        # A machine that crash-loops on boot would otherwise re-pay the document
        # cache write several times a minute.
        assert response.status_code == 429
        assert 0 < int(response.headers["retry-after"]) <= 61
        assert len(claude.requests) == spent
        assert restarted.get(f"/api/jobs/{job_id}").json()["state"] == "interrupted"


def shut_down_mid_topic(boot, job_id, claude, *, drain_deadline_seconds):
    """Generate, and shut the machine down with the second topic's call open.

    Leaving the client's context is the shutdown the platform's SIGTERM becomes.
    """
    machine = boot(drain_deadline_seconds=drain_deadline_seconds)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with machine:
            generating = pool.submit(machine.post, f"/api/jobs/{job_id}/generate")
            assert claude.wait_for_paused_call(timeout=5)
        generating.exception(timeout=5)


def test_a_shutdown_that_outlasts_its_deadline_checkpoints_and_starts_no_new_topic(
    boot, claude
):
    with boot() as machine:
        job_id = planned_job(machine, claude, plan=OVERSUBSCRIBED_PLAN)

    # The pacesetter lands; every topic in the fan-out window is still open when
    # the shutdown arrives.
    claude.replies_json(GLYCOLYSIS_CARDS)
    for _ in range(worker.MAX_CONCURRENT_TOPICS):
        claude.replies_json(CELL_CARDS, pause=1.0)
    shut_down_mid_topic(boot, job_id, claude, drain_deadline_seconds=0.01)

    with boot() as restarted:
        job = restarted.get(f"/api/jobs/{job_id}").json()
        assert job["state"] == "interrupted"
        # The shutdown said so itself, rather than leaving the job claiming to
        # be generating for the next boot to tidy up. Boot recovery is the net,
        # not the plan: it says "restart", and this job did not need it.
        assert "shutdown" in job["error"]
        statuses = [t["status"] for t in topics_of(restarted, job_id)]
        # The pacesetter is banked. Everything the fan-out had open outlived the
        # deadline and was abandoned rather than waited on — the kill that
        # follows a drain is not negotiable — and comes back as pending.
        assert statuses[0] == "done"
        assert statuses[1:] == ["pending"] * BEYOND_THE_WINDOW

        # Nothing past the window was ever *generated*. Those topics do appear
        # inside the other calls as dedup exclusions, so the check is on which
        # topic each call was for, not on the string appearing anywhere in the
        # payload.
        generated_for = [
            request["messages"][0]["content"][-1]["text"].splitlines()[0]
            for request in claude.requests[1:]
        ]
        assert not any(LAST_TOPIC_PATH in line for line in generated_for)
        # A ceiling rather than an equality: how many of the window had reached
        # the transport when SIGTERM landed is a scheduling detail. That none
        # started beyond it is the invariant.
        assert len(claude.requests) <= worker.MAX_CONCURRENT_TOPICS + 2


def test_a_shutdown_lets_a_topic_already_in_flight_land_before_it_stops(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude, plan=OVERSUBSCRIBED_PLAN)

    claude.replies_json(GLYCOLYSIS_CARDS)
    for _ in range(worker.MAX_CONCURRENT_TOPICS):
        claude.replies_json(CELL_CARDS, pause=0.1)
    began = time.monotonic()
    shut_down_mid_topic(boot, job_id, claude, drain_deadline_seconds=30.0)
    # Within the deadline, not at the end of it: the drain waits for the work,
    # not for the clock.
    assert time.monotonic() - began < 5.0

    with boot() as restarted:
        # What was in flight was paid for and kept. The topic past the window
        # freed a slot only after the drain began, and was declined.
        assert restarted.get(f"/api/jobs/{job_id}").json()["state"] == "interrupted"
        statuses = [t["status"] for t in topics_of(restarted, job_id)]
        assert statuses[-1] == "pending"
        assert statuses.count("done") >= 1


REVISED_GLYCOLYSIS_CARDS = {
    "cards": [
        {
            "note_type": "basic",
            "front": "Where in the cell does glycolysis occur?",
            "back": "The cytosol.",
        }
    ]
}


def test_a_failed_topic_is_the_only_one_retried_and_the_job_then_completes(boot, claude):
    with boot(resume_backoff_seconds=0) as machine:
        job_id = planned_job(machine, claude)
        claude.replies_json(GLYCOLYSIS_CARDS).refuses(category="bio")
        machine.post(f"/api/jobs/{job_id}/generate")

        failed = machine.get(f"/api/jobs/{job_id}").json()
        assert failed["state"] == "failed"
        assert [t["status"] for t in topics_of(machine, job_id)] == ["done", "failed"]
        spent = len(claude.requests)

        claude.replies_json(CELL_CARDS)
        machine.post(f"/api/jobs/{job_id}/generate")

        assert len(claude.requests) == spent + 1
        assert machine.get(f"/api/jobs/{job_id}").json()["state"] == "complete"
        assert [t["attempt_count"] for t in topics_of(machine, job_id)] == [1, 2]
        assert len(machine.get(f"/api/jobs/{job_id}/cards").json()["cards"]) == 3


def test_a_topic_run_again_replaces_its_earlier_cards_rather_than_adding_to_them(boot, claude):
    with boot(resume_backoff_seconds=0) as machine:
        job_id = planned_job(machine, claude)
        claude.replies_json(GLYCOLYSIS_CARDS).refuses(category="bio")
        machine.post(f"/api/jobs/{job_id}/generate")

        # The user revises the plan, which puts every topic back in the queue —
        # including the one that already produced cards.
        claude.replies_json(PLAN)
        machine.post(f"/api/jobs/{job_id}/plan")
        assert [t["status"] for t in topics_of(machine, job_id)] == ["pending", "pending"]

        claude.replies_json(REVISED_GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
        machine.post(f"/api/jobs/{job_id}/generate")

        cards = machine.get(f"/api/jobs/{job_id}/cards").json()["cards"]
        assert [c["front"] for c in cards] == [
            "Where in the cell does glycolysis occur?",
            "What organelle produces most ATP?",
        ]


def crash_loop(boot, claude, job_id, times=3):
    """A deterministic bug: every resume dies in the same place."""
    for _ in range(times):
        claude.dies()
        generate_until_killed(boot, job_id, resume_backoff_seconds=0)


def test_a_job_that_keeps_dying_ends_up_dead_and_stops_resuming(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)

    crash_loop(boot, claude, job_id)
    spent = len(claude.requests)

    with boot(resume_backoff_seconds=0) as restarted:
        job = restarted.get(f"/api/jobs/{job_id}").json()
        assert job["state"] == "dead"
        assert job["attempt_count"] == 3

        refused = restarted.post(f"/api/jobs/{job_id}/generate")

        # Dead is terminal on purpose: a human has to look at it, because the
        # alternative is an invoice.
        assert refused.status_code == 409
        assert "cleared" in refused.json()["detail"]
        assert len(claude.requests) == spent
        assert restarted.get(f"/api/jobs/{job_id}").json()["state"] == "dead"


def test_clearing_a_dead_job_by_hand_lets_it_run_again(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)
    crash_loop(boot, claude, job_id)

    with boot(resume_backoff_seconds=0) as restarted:
        assert restarted.post(f"/api/jobs/{job_id}/clear").status_code == 200
        cleared = restarted.get(f"/api/jobs/{job_id}").json()
        assert cleared["state"] == "interrupted"
        assert cleared["attempt_count"] == 0

        claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
        assert restarted.post(f"/api/jobs/{job_id}/generate").status_code == 200
        assert restarted.get(f"/api/jobs/{job_id}").json()["state"] == "complete"


def test_clearing_a_job_that_is_not_dead_is_refused(client, claude):
    job_id = planned_job(client, claude)

    response = client.post(f"/api/jobs/{job_id}/clear")

    # Clearing resets the crash-loop counter, so it must be reachable only from
    # the state that counter stopped — otherwise the bound it enforces can be
    # rubbed out by a request that looks harmless.
    assert response.status_code == 409
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "plan_ready"


def test_a_completed_job_refuses_a_second_generation_run(client, claude):
    job_id = planned_job(client, claude)
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")
    spent = len(claude.requests)

    response = client.post(f"/api/jobs/{job_id}/generate")

    assert response.status_code == 409
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "complete"
    # The point of rejecting the transition is that it costs nothing.
    assert len(claude.requests) == spent


def test_planning_is_refused_once_a_job_has_completed(client, claude):
    job_id = planned_job(client, claude)
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")
    spent = len(claude.requests)

    response = client.post(f"/api/jobs/{job_id}/plan")

    assert response.status_code == 409
    assert len(claude.requests) == spent


def test_each_topic_carries_its_own_status_and_attempt_count(client, claude):
    job_id = planned_job(client, claude)

    planned = topics_of(client, job_id)
    assert [t["topic_id"] for t in planned] == ["glycolysis", "cell-basics"]
    assert [t["status"] for t in planned] == ["pending", "pending"]
    assert [t["attempt_count"] for t in planned] == [0, 0]

    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")

    generated = topics_of(client, job_id)
    assert [t["status"] for t in generated] == ["done", "done"]
    assert [t["attempt_count"] for t in generated] == [1, 1]
    assert [t["card_count"] for t in generated] == [2, 1]
