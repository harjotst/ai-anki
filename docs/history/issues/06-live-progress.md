# 06 — Live progress

**What to build:** The user can watch a job progress, close the tab, and come back to a correct view. Progress is a projection of persisted state rather than something that lives only in the worker, because the connection is the least reliable part of the system.

**Blocked by:** 05 — Job state machine

**Status:** done — closed by ticket 03

> `idle_timeout = 600` is set in fly.toml, asserted against the heartbeat interval.

> Note on the unticked criterion: `idle_timeout` is a `fly.toml` setting and
> there is no `fly.toml` in the repository yet — ticket 03 owns that file, along
> with `kill_timeout`, the volume mount and the strict-config CI check. Writing a
> partial one here would collide with it and could not be tested from this
> ticket. The requirement has been added to ticket 03's checklist so it is not
> lost, and the value it must clear (600s, against a 15s heartbeat) is recorded
> in `app/progress.py`.
>
> How it is built: every state change already happened inside a committed
> transaction, so the transaction now also appends a `job_event` row describing
> it. The stream is nothing but a reader of that table — which is what makes the
> live stream and a replay on a machine that never ran the job byte-identical,
> asserted directly. The stream ends of its own accord when the job reaches a
> state it cannot leave without a person (`complete`, `cancelled`, `dead`); at
> any other time it is held open with heartbeats and recycled after
> `MAX_STREAM_SECONDS`, from which a browser reconnects with `Last-Event-ID` and
> loses nothing.
>
> Generation was deliberately left on the request path: moving it off would
> change what `POST /generate` returns and break ticket 05's tests, and it is not
> needed here — the worker already runs it as its own task, so a client that
> hangs up does not take the run with it.
>
> 44 tests green (8 new). Nothing is committed.

- [x] Progress is served over SSE derived from job state in the database, never from in-memory worker state
- [x] Reconnecting with a last-event identifier replays missed events from the database
- [x] The response disables content encoding, since the platform proxy buffers responses before compressing them and that breaks streaming
- [x] A heartbeat is emitted at least every 20 seconds, because a single topic call can exceed a minute with nothing to report
- [x] The platform idle timeout is raised well beyond the default
- [x] Closing and reopening the tab shows correct current state
- [x] A test asserts the stream is fully reconstructible from persisted state alone
