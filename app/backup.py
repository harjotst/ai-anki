"""Off-platform copies of the one file that cannot be regenerated.

Everything else in this system can be rebuilt by running something again:
uploads can be re-uploaded, plans re-planned, cards re-generated. The card
identities cannot. They are what makes a re-import land on the note the user
has been reviewing for six weeks instead of beside it, and losing them turns
every future download into a duplicate of the user's entire deck.

Fly's own documentation says volume snapshots are not a backup, and a copy on
the same volume protects against nothing that actually happens — a corrupted
file, a bad migration, a destroyed machine. So the copy leaves the platform.

Object storage is spoken to through boto3 rather than hand-rolled SigV4. The
signing is the part that is easy to get subtly wrong and impossible to notice
until a restore is needed, which is the worst moment to find out.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import db

log = logging.getLogger("ai-anki.backup")

# Fourteen daily copies. Long enough that damage introduced quietly — a bad
# migration, a slow corruption — is still recoverable after somebody notices,
# and short enough that the bill stays trivial: this database is single-digit
# megabytes compressed.
KEEP_DAYS = 14

# 03:00 UTC. Nothing is generating then, so the VACUUM INTO read transaction
# contends with nothing.
HOUR_UTC = 3


@dataclass(frozen=True)
class Destination:
    bucket: str
    endpoint_url: str | None = None
    region: str = "auto"
    prefix: str = "db"


def destination_from_env() -> Destination | None:
    """Read the bucket from the environment, or report that there is not one.

    Absent configuration is a supported state, not an error. Local development
    and a first deploy both run without a bucket, and a nightly task that
    raises every night is a task whose alarms get muted — after which a real
    failure is invisible too.
    """
    bucket = os.environ.get("AI_ANKI_BACKUP_BUCKET", "").strip()
    if not bucket:
        return None
    return Destination(
        bucket=bucket,
        # The names Fly's Tigris integration already sets, so a bucket created
        # with `fly storage create` needs no further configuration.
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3") or None,
        region=os.environ.get("AWS_REGION", "auto"),
        prefix=os.environ.get("AI_ANKI_BACKUP_PREFIX", "db").strip("/"),
    )


def build_client(destination: Destination, key_id: str | None = None, secret: str | None = None):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=destination.endpoint_url,
        region_name=destination.region,
        aws_access_key_id=key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret or os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def snapshot(db_path: Path, into: Path) -> Path:
    """A consistent, compressed copy of the database.

    `VACUUM INTO` takes its own read transaction, so the result is a coherent
    point-in-time image rather than the torn file a plain copy of a WAL-mode
    database would be. Compressed because SQLite pages are mostly empty space
    and the wire is the expensive part.
    """
    into.parent.mkdir(parents=True, exist_ok=True)
    raw = into.with_suffix(into.suffix + ".raw")
    db.backup_to(db_path, raw)
    try:
        with open(raw, "rb") as source, gzip.open(into, "wb") as target:
            shutil.copyfileobj(source, target)
    finally:
        raw.unlink(missing_ok=True)
    return into


def key_for(prefix: str, now: float) -> str:
    """A key that sorts by date, so a listing reads as a history."""
    stamp = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{prefix}/{stamp}.db.gz" if prefix else f"{stamp}.db.gz"


def prune(client, destination: Destination, now: float, keep_days: int) -> list[str]:
    """Delete copies past the retention window.

    Driven by what the listing actually reports rather than by a key naming
    convention: a key that failed to parse would otherwise be either kept for
    ever or, far worse, treated as ancient and deleted.
    """
    cutoff = now - keep_days * 86400
    listed = client.list_objects_v2(Bucket=destination.bucket, Prefix=destination.prefix)
    doomed = [
        item["Key"]
        for item in listed.get("Contents", [])
        if item["LastModified"].timestamp() < cutoff
    ]
    if not doomed:
        return []
    client.delete_objects(
        Bucket=destination.bucket, Delete={"Objects": [{"Key": key} for key in doomed]}
    )
    return doomed


def run(
    db_path: Path,
    work_dir: Path,
    destination: Destination,
    *,
    client=None,
    now: float | None = None,
    keep_days: int = KEEP_DAYS,
) -> dict:
    """Take one backup and enforce the retention window."""
    now = time.time() if now is None else now
    client = client or build_client(destination)
    key = key_for(destination.prefix, now)
    local = work_dir / Path(key).name

    written = snapshot(db_path, local)
    try:
        size = written.stat().st_size
        with open(written, "rb") as body:
            client.put_object(Bucket=destination.bucket, Key=key, Body=body)
    finally:
        # The volume is the thing that is short of space, and it is the wrong
        # place for the copy in the first place.
        written.unlink(missing_ok=True)

    return {"key": key, "bytes": size, "pruned": prune(client, destination, now, keep_days)}


def seconds_until_next_run(now: float, hour_utc: int = HOUR_UTC) -> float:
    """How long to sleep before the next scheduled hour."""
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    target = moment.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target.timestamp() <= now:
        target = datetime.fromtimestamp(target.timestamp() + 86400, tz=timezone.utc)
    return target.timestamp() - now


async def nightly(db_path: Path, work_dir: Path, destination: Destination) -> None:
    """Run a backup once a day, for ever, without taking the process down.

    Every failure is logged and slept off rather than raised. A backup task that
    kills the application converts "last night's copy is missing" into "the
    service is down", which is a strictly worse outcome than the thing it is
    insuring against.
    """
    import asyncio

    while True:
        await asyncio.sleep(seconds_until_next_run(time.time()))
        try:
            result = await asyncio.to_thread(run, db_path, work_dir, destination)
            log.info("backup uploaded %s (%d bytes), pruned %d",
                     result["key"], result["bytes"], len(result["pruned"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("nightly backup failed; the next one is still scheduled")
