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

from app import providers
from app import db, generation, jobs, lessons

# Thirty seconds under Fly's 300s `kill_timeout` ceiling: long enough that a
# topic call already in flight lands rather than being re-billed — its output
# tokens are charged whether or not we keep the bytes — and short enough to
# write the checkpoint before SIGKILL. The margin is generous because
# `kill_timeout` is documented as best-effort; a drain cut shorter than this
# loses nothing that boot recovery does not pick up.
# How many topic calls run at once. Bounded rather than unlimited: the fan-out
# shares one prompt-cache key, and the vendors that publish a figure warn that
# too many requests a minute against one key start missing. It is also the
# number of concurrent SQLite writers this single machine has to survive.
MAX_CONCURRENT_TOPICS = 5

DRAIN_DEADLINE_SECONDS = 270.0

# How a rate limit is survived: wait what the vendor asked (or this default
# when it named nothing), then send again — a bounded number of times, because
# a limit that never lifts is an outage, not a queue. The waiting call holds
# its fan-out slot the whole time, which is the point: the fan-out self-paces
# to whatever tokens-per-minute tier the organization actually has.
MAX_RATE_LIMIT_WAITS = 4
DEFAULT_RATE_LIMIT_PAUSE_SECONDS = 20.0
MAX_RATE_LIMIT_PAUSE_SECONDS = 120.0


class WorkerDraining(Exception):
    """The machine is shutting down and is not accepting new work."""


class Worker:
    def __init__(
        self,
        database_url: str,
        provider,
        *,
        drain_deadline_seconds: float = DRAIN_DEADLINE_SECONDS,
        rate_limit_pause_seconds: float = DEFAULT_RATE_LIMIT_PAUSE_SECONDS,
    ):
        # Identifies this process instance. A job claimed by any other id is a
        # job whose machine is gone.
        self.id = uuid.uuid4().hex
        self._database_url = database_url
        self._provider = provider
        self._drain_deadline_seconds = drain_deadline_seconds
        self._rate_limit_pause_seconds = rate_limit_pause_seconds
        self._draining = False
        self._runs: dict[str, asyncio.Task] = {}

    async def _send_waiting_out_rate_limits(self, request):
        for waits in range(MAX_RATE_LIMIT_WAITS + 1):
            try:
                return await asyncio.to_thread(self._provider.send, request)
            except providers.RateLimited as exc:
                if waits == MAX_RATE_LIMIT_WAITS or self._draining:
                    # Out of patience (or out of time): recorded like any
                    # other refusal, and retryable by the person later.
                    raise providers.Unusable(str(exc)) from exc
                pause = exc.retry_after
                if pause is None:
                    pause = self._rate_limit_pause_seconds
                await asyncio.sleep(min(pause + 1.0, MAX_RATE_LIMIT_PAUSE_SECONDS))

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

        def checkpoint() -> None:
            with db.borrowed(self._database_url) as conn:
                for job_id in stranded:
                    jobs.interrupt_job(conn, job_id, "interrupted by a shutdown")

        await asyncio.to_thread(checkpoint)
        for job_id in stranded:
            running[job_id].cancel()
        await asyncio.gather(*(running[job_id] for job_id in stranded), return_exceptions=True)

    async def _generate(self, job_id: str) -> str:
        """Write the cards for every topic that has not finished yet.

        The first topic runs ALONE, then the rest fan out concurrently. That
        ordering is not a detail: a cache entry only becomes readable once the
        first response has begun, so a flat fan-out has every call miss and each
        one pays a cache-creation charge — which costs more than not caching at
        all. One call ahead of the pack turns N-1 misses into N-1 reads.
        """
        # Every database touch goes through a thread: this coroutine shares
        # the event loop with every request the server is answering, and a
        # read stuck on a dead socket once froze all of them at once. The
        # connection is the pool's, held for the run and given back.
        pool = db.pool(self._database_url)
        conn = await asyncio.to_thread(pool.getconn)
        try:
            documents = await asyncio.to_thread(
                jobs.documents_for, conn, job_id, self._provider
            )
            job = await asyncio.to_thread(jobs.load_job, conn, job_id)
            detail = job.detail_level if job else None
            pending = await asyncio.to_thread(jobs.unfinished_topics, conn, job_id)
            if not pending:
                return await asyncio.to_thread(jobs.settle_job, conn, job_id)

            # The pacesetter writes the shared prefix.
            first, rest = pending[0], pending[1:]
            if await self._one_topic(job_id, first, documents, detail) is None:
                return jobs.INTERRUPTED

            if rest:
                limit = asyncio.Semaphore(MAX_CONCURRENT_TOPICS)

                async def bounded(topic):
                    async with limit:
                        return await self._one_topic(job_id, topic, documents, detail)

                results = await asyncio.gather(*(bounded(t) for t in rest))
                if any(outcome is None for outcome in results):
                    return jobs.INTERRUPTED

            return await asyncio.to_thread(jobs.settle_job, conn, job_id)
        finally:
            await asyncio.to_thread(pool.putconn, conn)

    async def _one_topic(
        self, job_id: str, topic, documents, detail_level: int | None = None
    ) -> bool | None:
        """Teach one topic, then write its cards.

        The lesson comes first because that is the order the material has to be
        met in: cards reinforce comprehension rather than creating it. It also
        means the pacesetter warms BOTH cache lineages -- lessons and cards have
        different schemas and therefore separate lineages -- before the rest of
        the topics fan out and read them.

        On a connection of its own, opened here rather than passed in: five of
        these run at once with their database work on threads, and concurrent
        transactions interleaved over one shared connection would nest into
        each other rather than commit independently.

        None means a shutdown cut it short.
        """
        pool = db.pool(self._database_url)
        conn = await asyncio.to_thread(pool.getconn)
        try:
            if self._draining:
                await asyncio.to_thread(
                    jobs.interrupt_job, conn, job_id, "interrupted by a shutdown"
                )
                return None

            await asyncio.to_thread(jobs.start_topic, conn, job_id, topic.topic_id)

            taught = await self._teach(conn, job_id, topic, documents, detail_level)
            if taught is False:
                return False

            def build_request():
                return generation.build_cards_request(
                    documents,
                    topic.topic,
                    self._provider,
                    jobs.existing_cards_for_topic(conn, job_id, topic.topic_id),
                    jobs.sibling_topics(conn, job_id, topic.topic_id),
                    detail_level=detail_level,
                )

            request = await asyncio.to_thread(build_request)
            try:
                # The SDK is synchronous and a topic call takes many seconds. On the
                # event loop it would block every other request, and the shutdown
                # handler along with them.
                result = await self._send_waiting_out_rate_limits(request)
            except providers.Unusable as exc:
                # One topic refusing is not the job failing. The rest still run, and
                # this one can be retried on its own.
                await asyncio.to_thread(
                    jobs.fail_topic, conn, job_id, topic.topic_id, str(exc)
                )
                return False

            def record():
                jobs.record_usage(
                    conn, job_id, "cards", result.usage,
                    topic_id=topic.topic_id, model=self._provider.model,
                )
                jobs.save_topic_cards(conn, job_id, topic.topic, result.data["cards"])

            await asyncio.to_thread(record)
            return True
        finally:
            await asyncio.to_thread(pool.putconn, conn)

    async def _teach(
        self, conn, job_id: str, topic, documents, detail_level: int | None = None
    ) -> bool:
        """Write the lesson for one topic.

        A refused lesson fails the topic rather than being skipped. A topic that
        produced cards and no lesson would look complete on screen and be the
        one thing this application is for, missing.
        """
        request = lessons.build_lesson_request(
            documents, topic.topic, self._provider, detail_level=detail_level
        )
        try:
            result = await self._send_waiting_out_rate_limits(request)
        except providers.Unusable as exc:
            await asyncio.to_thread(
                jobs.fail_topic, conn, job_id, topic.topic_id, str(exc)
            )
            return False

        def record():
            jobs.record_usage(
                conn, job_id, "lesson", result.usage,
                topic_id=topic.topic_id, model=self._provider.model,
            )
            jobs.save_lesson(conn, job_id, topic.topic, lessons.clean(result.data))

        await asyncio.to_thread(record)
        return True
