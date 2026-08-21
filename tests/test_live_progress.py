"""Progress: watching a job, losing the connection, and coming back to the truth.

The connection is the least reliable part of the system, so progress is a
projection of what is in the database rather than something that lives in the
worker. These tests drive the stream through the HTTP boundary and never let it
be fed by the process that did the work.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app import progress
from tests.test_generation import CELL_CARDS, GLYCOLYSIS_CARDS
from tests.test_job_state_machine import generate_until_killed
from tests.test_planning import PLAN, upload


@dataclass(frozen=True)
class Event:
    id: str | None
    event: str
    data: dict


def sse_events(response) -> list[Event]:
    """Parse an SSE body the way a browser's EventSource would."""
    events = []
    for block in response.text.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            # A line beginning with a colon is a comment — the heartbeat.
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            fields[name] = value.lstrip(" ")
        if "data" in fields:
            events.append(
                Event(
                    id=fields.get("id"),
                    event=fields.get("event", "message"),
                    data=json.loads(fields["data"]),
                )
            )
    return events


def planned_job(client, claude, plan=PLAN):
    claude.replies_json(plan)
    job_id = upload(client)
    client.post(f"/api/jobs/{job_id}/plan")
    return job_id


def generated_job(client, claude):
    job_id = planned_job(client, claude)
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
    client.post(f"/api/jobs/{job_id}/generate")
    return job_id


def test_a_finished_run_replays_in_full_on_a_machine_that_never_saw_it(boot, claude):
    with boot() as machine:
        job_id = generated_job(machine, claude)

    # A second process: it holds nothing about this job, so anything it can say
    # about the run it read out of the database.
    with boot() as restarted:
        response = restarted.get(f"/api/jobs/{job_id}/events")

    assert response.status_code == 200
    events = sse_events(response)
    assert [e.data["state"] for e in events if e.event == "state"] == [
        "uploaded",
        "planning",
        "plan_ready",
        "generating",
        "complete",
    ]

    glycolysis = [
        e.data for e in events if e.event == "topic" and e.data["topic_id"] == "glycolysis"
    ]
    assert [t["status"] for t in glycolysis] == ["pending", "running", "done"]
    assert glycolysis[-1]["card_count"] == 2
    assert glycolysis[-1]["path"] == "Biology::Metabolism::Glycolysis"

    # Every event carries an id, so a client that drops out knows where it got
    # to; the stream closes itself once the job can produce nothing more.
    assert [int(e.id) for e in events[:-1]] == sorted(int(e.id) for e in events[:-1])
    assert events[-1].event == "end"
    assert events[-1].data["state"] == "complete"


def ids_of(events) -> list[str]:
    return [e.id for e in events if e.id is not None]


def test_a_reconnecting_client_is_sent_what_it_missed_and_nothing_it_already_had(boot, claude):
    # A stream over a job that is between runs has nothing to wait for, so it is
    # given a short life; a browser would reconnect when it ended.
    with boot(event_stream_seconds=0.1) as machine:
        job_id = planned_job(machine, claude)
        watched = sse_events(machine.get(f"/api/jobs/{job_id}/events"))
        assert [e.data["state"] for e in watched if e.event == "state"] == [
            "uploaded",
            "planning",
            "plan_ready",
        ]

        # The connection is dropped here, and the whole of generation happens
        # while nobody is listening.
        claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS)
        machine.post(f"/api/jobs/{job_id}/generate")

        missed = sse_events(
            machine.get(
                f"/api/jobs/{job_id}/events",
                headers={"Last-Event-ID": watched[-1].id},
            )
        )
        replayed = sse_events(machine.get(f"/api/jobs/{job_id}/events"))

    assert [e.data["state"] for e in missed if e.event == "state"] == ["generating", "complete"]
    assert [e.data["status"] for e in missed if e.event == "topic"] == [
        "running",
        "done",
        "running",
        "done",
    ]
    # Handing the id back picks up exactly where the client stopped: the two
    # halves are the whole run, with nothing repeated and nothing dropped.
    assert ids_of(watched) + ids_of(missed) == ids_of(replayed)


def current_view(events) -> dict:
    """Fold a stream the way a watching client would, into what it displays."""
    view = {"state": None, "topics": {}}
    for event in events:
        if event.event == "state":
            view["state"] = event.data["state"]
        elif event.event == "topic":
            view["topics"][event.data["topic_id"]] = event.data
    return view


def test_reopening_the_tab_shows_where_a_job_that_lost_its_machine_got_to(boot, claude):
    with boot() as machine:
        job_id = planned_job(machine, claude)

    # The machine dies with the second topic's call in flight. Whatever the
    # worker knew about that run died with the process.
    claude.replies_json(GLYCOLYSIS_CARDS).dies()
    generate_until_killed(boot, job_id)

    with boot(event_stream_seconds=0.1) as restarted:
        view = current_view(sse_events(restarted.get(f"/api/jobs/{job_id}/events")))

    assert view["state"] == "interrupted"
    # The banked topic is still banked, and the one the dead machine had claimed
    # is shown as waiting rather than as being worked on by nobody.
    assert view["topics"]["glycolysis"]["status"] == "done"
    assert view["topics"]["glycolysis"]["card_count"] == 2
    assert view["topics"]["cell-basics"]["status"] == "pending"
    assert view["topics"]["cell-basics"]["card_count"] == 0


def test_the_stream_refuses_the_encoding_and_buffering_the_platform_would_apply(boot, claude):
    with boot(event_stream_seconds=0.1) as machine:
        job_id = planned_job(machine, claude)
        response = machine.get(f"/api/jobs/{job_id}/events")

    assert response.headers["content-type"].startswith("text/event-stream")
    # Fly's proxy buffers a response before compressing it, which holds a stream
    # back until it has finished — the one thing a progress stream must not do.
    # So encoding is refused by name rather than left to negotiation, and
    # buffering is refused alongside it.
    assert response.headers["content-encoding"] == "none"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "content-length" not in response.headers


def test_watching_a_job_that_does_not_exist_is_refused(client):
    assert client.get("/api/jobs/no-such-job/events").status_code == 404


def test_a_heartbeat_keeps_the_connection_open_while_there_is_nothing_to_report(boot, claude):
    with boot(heartbeat_seconds=0.05, event_stream_seconds=0.4) as machine:
        job_id = planned_job(machine, claude)
        response = machine.get(f"/api/jobs/{job_id}/events")

    # Nothing happens to this job for the life of the connection, and it stays
    # alive anyway: a single topic call can run well past a minute with nothing
    # to report, and a silent connection is one the platform closes.
    assert response.text.count(": heartbeat") >= 4
    # The shipped interval, which no test can wait out, has to sit inside the
    # same window.
    assert progress.HEARTBEAT_SECONDS <= 20


def watch_mid_run(machine, claude, job_id) -> list[Event]:
    """Open the stream with a topic call genuinely in flight, and watch to the end.

    The second topic's call is held open, the way a real one is for minutes at a
    time, so the client connects mid-run rather than over a finished job.
    """
    claude.replies_json(GLYCOLYSIS_CARDS).replies_json(CELL_CARDS, pause=0.5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        generating = pool.submit(machine.post, f"/api/jobs/{job_id}/generate")
        assert claude.wait_for_paused_call(timeout=5)
        events = sse_events(machine.get(f"/api/jobs/{job_id}/events"))
        assert generating.result(timeout=10).status_code == 200
    return events


def test_a_topic_finishing_reaches_a_client_that_is_already_watching(boot, claude):
    with boot(event_stream_seconds=5.0) as machine:
        job_id = planned_job(machine, claude)
        events = watch_mid_run(machine, claude, job_id)

    # The second topic was still being paid for when this client connected: it
    # was already claimed, and everything after that did not exist yet at
    # connection time. It arrived because it was committed, not because it was
    # there to be read.
    assert [(e.event, e.data.get("topic_id") or e.data["state"]) for e in events[-4:]] == [
        ("topic", "cell-basics"),
        ("topic", "cell-basics"),
        ("state", "complete"),
        ("end", "complete"),
    ]
    assert [e.data["status"] for e in events if e.event == "topic"][-2:] == ["running", "done"]


def test_what_a_client_watched_live_is_reproduced_by_a_machine_that_only_has_the_database(
    boot, claude
):
    with boot(event_stream_seconds=5.0) as machine:
        job_id = planned_job(machine, claude)
        watched = watch_mid_run(machine, claude, job_id)

    # A different process, holding nothing but the file the last one wrote.
    with boot(event_stream_seconds=0.1) as restarted:
        replayed = sse_events(restarted.get(f"/api/jobs/{job_id}/events"))

    # Event for event, id for id. The stream is a projection of persisted state
    # and nothing else: had any of it been assembled from what the worker knew
    # at the time, the process that never ran the job could not reproduce it.
    assert replayed == watched
    assert len(watched) > 1
