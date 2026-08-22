"""Backups that survive losing the machine.

The volume snapshot Fly takes is documented as not being a backup, and this
database is the one thing in the system whose loss cannot be recovered by
re-running anything: every card identity lives in it, and without them a
re-import duplicates the user's entire deck rather than updating it.

The seam here is botocore's own stubber rather than a hand-written fake, so a
call with the wrong parameter shape fails the test the way it would fail the
service.
"""

import gzip
import time

import pytest
from botocore.stub import ANY, Stubber

from app import backup, db


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
def populated(tmp_path):
    path = tmp_path / "ai-anki.db"
    db.initialise(path)
    conn = db.connect(path)
    conn.execute(
        "INSERT INTO deck (id, invite_id, name, created_at) VALUES ('d1', NULL, 'Bio', 1.0)"
    )
    conn.close()
    return path


def test_a_backup_is_a_consistent_compressed_copy_of_the_live_database(populated, tmp_path):
    written = backup.snapshot(populated, tmp_path / "out.db.gz")

    assert written.name.endswith(".gz")
    # Readable as a database, not merely as bytes: a torn copy of a WAL-mode
    # file would still have a plausible size.
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(written.read_bytes()))
    conn = db.connect(restored)
    assert conn.execute("SELECT name FROM deck").fetchone()["name"] == "Bio"
    conn.close()


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


def test_the_manual_trigger_says_plainly_that_a_local_copy_is_not_a_backup(client):
    """Without a bucket the endpoint still works, and does not pretend."""
    from tests.conftest import OWNER

    taken = client.post("/api/maintenance/backup", headers=OWNER).json()

    assert taken["bytes"] > 0
    assert "off-platform" in taken["warning"]
    assert "AI_ANKI_BACKUP_BUCKET" in taken["warning"]


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
            from tests.conftest import OWNER

            with boot(backup_destination=destination) as machine:
                taken = machine.post("/api/maintenance/backup", headers=OWNER).json()
        finally:
            module.build_client = original

    assert taken["destination"] == "ai-anki-backups"
    assert taken["key"].startswith("db/")
    stub.assert_no_pending_responses()
