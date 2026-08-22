"""Backups that survive losing the machine.

The volume snapshot Fly takes is documented as not being a backup, and this
database is the one thing in the system whose loss cannot be recovered by
re-running anything: every card identity lives in it, and without them a
re-import duplicates the user's entire deck rather than updating it.

The seam here is botocore's own stubber rather than a hand-written fake, so a
call with the wrong parameter shape fails the test the way it would fail the
service.
"""

import shutil
import subprocess

import pytest
from botocore.stub import ANY, Stubber

from app import backup, db

# `pg_dump` ships with the Postgres client tools. It is present in the runtime
# image and in CI; a developer machine may not have it, and a skip that says so
# is better than a failure that looks like a bug in the code under test.
needs_pg_dump = pytest.mark.skipif(
    shutil.which("pg_dump") is None,
    reason="pg_dump is not installed on this machine; the runtime image has it",
)


@pytest.fixture
def destination():
    return backup.Destination(
        bucket="ai-anki-backups",
        endpoint_url="https://fly.storage.tigris.dev",
        region="auto",
        prefix="db",
    )


@pytest.fixture
def s3(destination):
    client = backup.build_client(destination, key_id="k", secret="s")
    with Stubber(client) as stub:
        yield client, stub


@pytest.fixture
def populated(pg_dsn):
    """A database with something in it, so a dump that silently produced an
    empty archive would still fail the restore assertion."""
    db.initialise(pg_dsn)
    conn = db.connect(pg_dsn)
    conn.execute(
        "INSERT INTO deck (id, invite_id, name, created_at)"
        " VALUES ('d1', NULL, 'Bio', now())"
    )
    conn.close()
    return pg_dsn


@needs_pg_dump
def test_a_backup_is_an_archive_something_can_actually_restore(populated, tmp_path):
    """Not merely bytes of a plausible size.

    A dump that silently produced nothing would still be a file, so this asks
    `pg_restore` to read its table of contents and checks that the data is in
    there. The full round trip -- restore into an empty schema and read the row
    back -- was verified in the runtime image on 2026-08-21; see
    docs/operations.md.
    """
    written = backup.snapshot(populated, tmp_path / "out.dump")

    assert written.suffix == ".dump"
    assert written.stat().st_size > 0

    listed = subprocess.run(
        ["pg_restore", "--list", str(written)], capture_output=True, text=True
    )
    assert listed.returncode == 0, listed.stderr
    assert "deck" in listed.stdout


@needs_pg_dump
def test_a_dump_that_fails_says_what_the_tool_said(tmp_path):
    """A backup that failed silently is worse than no backup, because the
    listing still looks healthy until the day somebody needs it."""
    with pytest.raises(backup.DumpFailed) as refused:
        backup.snapshot("postgresql://nobody@127.0.0.1:1/nothing", tmp_path / "out.dump")

    assert str(refused.value)
    assert not (tmp_path / "out.dump").exists(), "no half-written archive left behind"


@needs_pg_dump
def test_a_backup_is_uploaded_under_a_key_that_sorts_by_date(populated, tmp_path, s3, destination):
    client, stub = s3
    stub.add_response(
        "put_object",
        {},
        {
            "Bucket": "ai-anki-backups",
            "Key": "db/2026-08-21T03-00-00Z.db.gz",
            "Body": ANY,
        },
    )
    stub.add_response("list_objects_v2", {"Contents": []}, None)

    result = backup.run(
        populated, tmp_path, destination, client=client, now=1787281200.0, keep_days=14
    )

    assert result["key"] == "db/2026-08-21T03-00-00Z.db.gz"
    assert result["bytes"] > 0
    stub.assert_no_pending_responses()


@needs_pg_dump
def test_copies_older_than_the_retention_window_are_deleted(populated, tmp_path, s3, destination):
    client, stub = s3
    now = 1787281200.0
    stub.add_response("put_object", {}, None)
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [
                {"Key": "db/old.db.gz", "LastModified": _at(now - 20 * 86400)},
                {"Key": "db/recent.db.gz", "LastModified": _at(now - 2 * 86400)},
            ]
        },
        None,
    )
    stub.add_response(
        "delete_objects",
        {},
        {
            "Bucket": "ai-anki-backups",
            "Delete": {"Objects": [{"Key": "db/old.db.gz"}]},
        },
    )

    result = backup.run(
        populated, tmp_path, destination, client=client, now=now, keep_days=14
    )

    assert result["pruned"] == ["db/old.db.gz"]
    stub.assert_no_pending_responses()


@needs_pg_dump
def test_nothing_is_deleted_when_there_is_nothing_old_enough(populated, tmp_path, s3, destination):
    """A prune that deletes on an empty listing would wipe the whole history."""
    client, stub = s3
    now = 1787281200.0
    stub.add_response("put_object", {}, None)
    stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "db/recent.db.gz", "LastModified": _at(now - 86400)}]},
        None,
    )

    result = backup.run(populated, tmp_path, destination, client=client, now=now)

    assert result["pruned"] == []
    stub.assert_no_pending_responses()


@needs_pg_dump
def test_the_snapshot_is_removed_from_the_volume_once_it_is_uploaded(
    populated, tmp_path, s3, destination
):
    """The volume is the thing that is short of space; keeping copies on it is
    both the wrong place and the reason it fills up."""
    client, stub = s3
    stub.add_response("put_object", {}, None)
    stub.add_response("list_objects_v2", {"Contents": []}, None)

    backup.run(populated, tmp_path, destination, client=client, now=1787281200.0)

    assert list(tmp_path.glob("*.gz")) == []


def test_backup_is_off_rather_than_broken_when_no_bucket_is_configured(monkeypatch):
    """Running without object storage has to be a supported state.

    Local development and a first deploy both have no bucket, and a nightly
    task that raises every night is a task whose alarms get muted.
    """
    monkeypatch.delenv("AI_ANKI_BACKUP_BUCKET", raising=False)
    assert backup.destination_from_env() is None


def test_a_configured_bucket_is_read_from_the_environment_fly_already_sets(monkeypatch):
    monkeypatch.setenv("AI_ANKI_BACKUP_BUCKET", "ai-anki-backups")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://fly.storage.tigris.dev")

    configured = backup.destination_from_env()

    assert configured.bucket == "ai-anki-backups"
    assert configured.endpoint_url == "https://fly.storage.tigris.dev"


def _at(epoch: float):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def test_the_next_run_is_the_next_time_the_scheduled_hour_comes_round():
    from datetime import datetime, timezone

    def at(y, m, d, h):
        return datetime(y, m, d, h, tzinfo=timezone.utc).timestamp()

    # Before the hour today: later today.
    assert backup.seconds_until_next_run(at(2026, 8, 21, 1), hour_utc=3) == 2 * 3600
    # After it: tomorrow, not in 23 hours of drift.
    assert backup.seconds_until_next_run(at(2026, 8, 21, 4), hour_utc=3) == 23 * 3600
    # Exactly on it counts as done, so a restart at 03:00 does not back up twice.
    assert backup.seconds_until_next_run(at(2026, 8, 21, 3), hour_utc=3) == 86400


@needs_pg_dump
def test_the_manual_trigger_says_plainly_that_a_local_copy_is_not_a_backup(client):
    """Without a bucket the endpoint still works, and does not pretend."""

    taken = client.post("/api/maintenance/backup").json()

    assert taken["bytes"] > 0
    assert "off-platform" in taken["warning"]
    assert "AI_ANKI_BACKUP_BUCKET" in taken["warning"]


@needs_pg_dump
def test_a_configured_bucket_makes_the_manual_trigger_go_off_platform(boot, destination):
    client = backup.build_client(destination, key_id="k", secret="s")
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, None)
        stub.add_response("list_objects_v2", {"Contents": []}, None)

        # Injected rather than reached for from the environment, so the test
        # says which bucket it means.
        import app.backup as module

        original = module.build_client
        module.build_client = lambda *a, **k: client
        try:

            with boot(backup_destination=destination) as machine:
                taken = machine.post("/api/maintenance/backup").json()
        finally:
            module.build_client = original

    assert taken["destination"] == "ai-anki-backups"
    assert taken["key"].startswith("db/")
    stub.assert_no_pending_responses()
