"""The progress stream.

SSE here is a read-only view over the job's persisted event log, never the
transport of record. The connection is the least reliable part of the system —
tabs close, phones sleep, the platform recycles the machine — so nothing is
allowed to exist only in the stream. Every frame is read out of the database,
which means a client can miss the entire run and still reconstruct it, either
from `Last-Event-ID` or from the beginning.

The response fights two things that are not the application's fault. Fly's proxy
buffers a response before compressing it, which holds a stream back until it is
finished, so content encoding is turned off explicitly. And a single topic call
can run for well over a minute with nothing to report, which any proxy would
read as an idle connection, so a comment is sent when there is no news.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from app import db, jobs

# Comfortably inside the fifteen-to-twenty-second window a proxy is happy with,
# and far inside the platform's raised 600s idle timeout.
HEARTBEAT_SECONDS = 15.0

# How often the log is re-read. It is an indexed lookup of a handful of rows on
# a local file, so the cost of being this eager is negligible next to a stream
# that lags the work it is describing.
POLL_SECONDS = 0.05

# A connection is recycled long before anything in the path decides to do it for
# us. Nothing is lost when it happens: the client reconnects with the last id it
# saw and the log replays whatever it missed.
MAX_STREAM_SECONDS = 300.0

# Content encoding is disabled rather than merely unset, and buffering is
# refused by name, because the default behaviour of the proxy in front of this
# app is to hold a streaming response until it ends.
STREAM_HEADERS = {
    "cache-control": "no-cache",
    "content-encoding": "none",
    "x-accel-buffering": "no",
}

# States a job cannot leave without a person doing something. The stream says so
# and closes, rather than holding a connection open for news that needs a new
# request to happen at all.
FINISHED = frozenset({jobs.COMPLETE, jobs.CANCELLED, jobs.DEAD})


def last_event_id(header: str | None) -> int:
    """Where a reconnecting client got to, or the beginning.

    Anything unparseable is treated as "start again": a client whose id we
    cannot read is better served by the whole history than by silence.
    """
    try:
        return max(int(header), 0)
    except (TypeError, ValueError):
        return 0


def frame(event: str, data: dict, *, id: int | None = None) -> str:
    identifier = f"id: {id}\n" if id is not None else ""
    return f"{identifier}event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream(
    db_path: Path,
    job_id: str,
    *,
    after_id: int = 0,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    max_seconds: float = MAX_STREAM_SECONDS,
) -> AsyncIterator[str]:
    """Frames for one watching client, from `after_id` onwards.

    The connection gets its own database handle rather than the request's: it
    outlives the handler that created it, and the worker is writing on a handle
    of its own the whole time.
    """
    conn = db.connect(db_path)
    deadline = time.monotonic() + max_seconds
    last_id = after_id
    last_frame_at = time.monotonic()
    try:
        while True:
            # The state is read before the events, never after. Read the other
            # way round, a job that finishes between the two reads would be
            # declared over on this connection before the events that say how it
            # ended had been sent.
            state = _state_of(conn, job_id)
            events = jobs.events_since(conn, job_id, last_id)
            for event in events:
                yield frame(event.kind, event.data, id=event.id)
                last_id = event.id
                last_frame_at = time.monotonic()

            if state is None or state in FINISHED:
                yield frame("end", {"state": state})
                return
            if time.monotonic() >= deadline:
                return
            if time.monotonic() - last_frame_at >= heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_frame_at = time.monotonic()
            if is_disconnected is not None and await is_disconnected():
                return
            await asyncio.sleep(POLL_SECONDS)
    finally:
        conn.close()


def _state_of(conn, job_id: str) -> str | None:
    row = conn.execute("SELECT state FROM job WHERE id = ?", (job_id,)).fetchone()
    return None if row is None else row["state"]
