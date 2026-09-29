# 05 — Job state machine

**What to build:** Jobs survive the machine dying. Fly SIGTERMs on deploys, secret changes, scale changes, host migrations and OOM — and a generation run is far longer than the maximum drain window — so a job must checkpoint and resume rather than restart. This also protects cache economics: an unbounded resume loop re-pays the document cache write on every attempt.

**Blocked by:** 01 — Walking skeleton

**Status:** done — closed by ticket 03

> The outstanding SIGTERM criterion is now met: the image runs uvicorn with
> `--timeout-graceful-shutdown 240`, inside fly.toml's 300s `kill_timeout`, and a real
> container was sent SIGTERM and drained cleanly to exit 0.

> Note on the unticked criterion: the drain itself is built and tested — it stops
> taking work, gives the call in flight until a deadline (270s, 30s under Fly's
> 300s `kill_timeout` ceiling), then checkpoints and abandons the rest. It hangs off
> lifespan shutdown, which is what a server turns SIGTERM into. What is *not*
> demonstrated is that SIGTERM reaches it in time: uvicorn drains open
> connections before running lifespan shutdown, and generation currently runs on
> the request path, so a client waiting on `/generate` holds the shutdown up.
> Closing it needs `--timeout-graceful-shutdown` well below `kill_timeout`
> (ticket 03, which owns the exec-form `CMD` and `fly.toml`) or generation moved
> off the request path (ticket 06). Nothing is lost meanwhile: a job left
> claiming to be `generating` is recovered by the next boot, which is tested.
>
> On criterion 2, the topic row carries `status` and `attempt_count` as columns;
> its card payload is the `card` rows keyed by the same `(job_id, topic_id)`,
> written and replaced together with the row's status in one transaction. A
> second, denormalised copy of the same cards on the row was rejected.
>
> 36 tests green (14 new, one added in review). Nothing is committed.

- [x] Job states are explicit and persisted, and illegal transitions are rejected
- [x] Pass 2 has one row per topic carrying its own status, attempt count and card payload
- [x] A topic result is written in a transaction that first removes any prior attempt's cards for that topic, so retries replace rather than accumulate
- [x] Retry re-runs only failed topics, never completed ones
- [x] The attempt counter increments in a committed transaction before the first Anthropic call of a resume, not after success
- [x] At the attempt cap the job moves to a terminal dead state requiring explicit manual clearing
- [x] A minimum backoff is enforced between resume attempts
- [x] SIGTERM stops accepting new work and checkpoints within a deadline comfortably below the kill timeout
- [x] On boot, non-terminal jobs with no live worker are resumed or marked interrupted
- [x] A test kills the worker mid-generation and asserts the job resumes without re-running completed topics
