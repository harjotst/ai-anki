"""The in-process worker that runs pass 2.

One machine, one process, no queue: generation runs in the application's own
event loop. What makes that survivable is that the loop owns nothing. Every
topic is committed before the next one starts, so the process can be taken away
between any two of them and lose only the call that was in flight.

It is taken away often. Deploys, `fly secrets set`, scale changes, host
migrations and OOM all SIGTERM the machine, and `kill_timeout` caps at 300s and
is documented as best-effort — while a generation run is minutes per topic. So
the worker does not try to finish on the way out. It stops taking work, gives
the call in flight a bounded chance to land, and records where it got to.

The drain hangs off lifespan shutdown, which is what the server turns SIGTERM
into. That reaches us promptly only once generation is off the request path —
until then a client waiting on `/generate` holds the connection the server
drains first. Nothing is lost either way, because a job left claiming to be
`generating` is recovered by the next boot; the drain is what makes the good
case tidy rather than what makes the bad case safe.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app import providers
from app import db, generation, jobs

# Thirty seconds under Fly's 300s `kill_timeout` ceiling: long enough that a
# topic call already in flight lands rather than being re-billed — its output
# tokens are charged whether or not we keep the bytes — and short enough to
# write the checkpoint before SIGKILL. The margin is generous because
# `kill_timeout` is documented as best-effort; a drain cut shorter than this
# loses nothing that boot recovery does not pick up.
DRAIN_DEADLINE_SECONDS = 270.0


class WorkerDraining(Exception):
    """The machine is shutting down and is not accepting new work."""


class Worker:
    def __init__(
        self,
        db_path: Path,
        provider,
        *,
        drain_deadline_seconds: float = DRAIN_DEADLINE_SECONDS,
    ):
        # Identifies this process instance. A job claimed by any other id is a
        # job whose machine is gone.
        self.id = uuid.uuid4().hex
        self._db_path = db_path
        self._provider = provider
        self._drain_deadline_seconds = drain_deadline_seconds
        self._draining = False
        self._runs: dict[str, asyncio.Task] = {}

    @property
    def draining(self) -> bool:
        return self._draining

    async def generate(self, job_id: str) -> str:
        """Run pass 2 for a job and return the state it settled in.

        The run is a task of the worker's rather than of the request's, so a
        client that hangs up does not take the generation with it.
        """
        if self._draining:
            raise WorkerDraining("the machine is shutting down")
        task = asyncio.create_task(self._generate(job_id))
        self._runs[job_id] = task
        try:
            return await task
        finally:
            self._runs.pop(job_id, None)

    async def drain(self) -> None:
        """Stop taking work, then checkpoint whatever is still going.

        Called on shutdown, which is what the platform's SIGTERM becomes. A call
        already in flight is given until the deadline to land, because it has
        been paid for either way — but only until then. What is still going
        after that is abandoned rather than waited on: the kill that follows is
        not negotiable, and a run allowed to keep writing would leave the
        database saying something other than the checkpoint.
        """
        self._draining = True
        running = dict(self._runs)
        if not running:
            return

        await asyncio.wait(running.values(), timeout=self._drain_deadline_seconds)

        stranded = [job_id for job_id, task in running.items() if not task.done()]
        if not stranded:
            return

        conn = db.connect(self._db_path)
        try:
            for job_id in stranded:
                jobs.interrupt_job(conn, job_id, "interrupted by a shutdown")
        finally:
            conn.close()
        for job_id in stranded:
            running[job_id].cancel()
        await asyncio.gather(*(running[job_id] for job_id in stranded), return_exceptions=True)

    async def _generate(self, job_id: str) -> str:
        conn = db.connect(self._db_path)
        try:
            documents = jobs.documents_for(conn, job_id, self._provider)
            # Only topics that are not already done are run, which is what makes
            # a resume cost the remainder of the job rather than all of it.
            for topic in jobs.unfinished_topics(conn, job_id):
                if self._draining:
                    jobs.interrupt_job(conn, job_id, "interrupted by a shutdown")
                    return jobs.INTERRUPTED
                jobs.start_topic(conn, job_id, topic.topic_id)
                try:
                    # The SDK is synchronous and a topic call takes minutes. On
                    # the event loop it would block every other request, and the
                    # shutdown handler along with them.
                    result = await asyncio.to_thread(
                        self._provider.send,
                        generation.build_cards_request(
                            documents,
                            topic.topic,
                            self._provider,
                            jobs.existing_cards_for_topic(conn, job_id, topic.topic_id),
                            jobs.sibling_topics(conn, job_id, topic.topic_id),
                        ),
                    )
                except providers.Unusable as exc:
                    jobs.fail_topic(conn, job_id, topic.topic_id, str(exc))
                    continue
                jobs.record_usage(
                    conn, job_id, "cards", result.usage,
                    topic_id=topic.topic_id, model=self._provider.model,
                )
                jobs.save_topic_cards(conn, job_id, topic.topic, result.data["cards"])

            return jobs.settle_job(conn, job_id)
        finally:
            conn.close()
