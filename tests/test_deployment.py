"""The shape of the deployment, checked without deploying.

Every claim here is one that fails silently in production: a shell wrapper that
swallows SIGTERM, an auto-stop that kills a running job, a proxy timeout that
cuts the progress stream, a secret baked into an image layer.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
FLY = tomllib.loads((ROOT / "fly.toml").read_text())


def test_python_is_pinned_so_a_rebuild_cannot_drift_to_a_new_interpreter():
    assert "python:3.12-slim" in DOCKERFILE


def test_the_command_is_exec_form_so_the_app_is_pid_1_and_gets_sigterm():
    # Under a shell wrapper the shell is PID 1, SIGTERM never reaches uvicorn,
    # and the drain simply does not run before the platform's SIGKILL.
    command = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD"))
    assert command.startswith('CMD ["'), "exec form, not shell form"


def test_the_graceful_shutdown_window_sits_under_the_platform_kill_timeout():
    graceful = int(DOCKERFILE.split('"--timeout-graceful-shutdown", "')[1].split('"')[0])
    kill_timeout = int(FLY["kill_timeout"].removesuffix("s"))
    # The drain has to finish inside the window the platform allows, or it is
    # killed mid-checkpoint and the bound it promises is not real.
    assert graceful < kill_timeout


def test_no_secret_is_baked_into_the_image():
    for forbidden in ("ANTHROPIC_API_KEY", "AI_ANKI_OWNER_TOKEN", "sk-ant"):
        assert forbidden not in DOCKERFILE, f"{forbidden} must be a runtime secret"


def test_the_volume_is_mounted_where_the_uploads_live():
    mount = FLY["mounts"][0]
    assert mount["destination"] == "/data"
    assert FLY["env"]["AI_ANKI_DATA_DIR"].startswith("/data")
    # The database is not here any more. Baking a path for it into the config
    # would be a path nothing reads, which is worse than absent -- somebody
    # would eventually believe it.
    assert "AI_ANKI_DB_PATH" not in FLY["env"]
    # Starlette spools large uploads to TMPDIR; on the default that is the slow
    # ephemeral rootfs rather than the volume.
    assert FLY["env"]["TMPDIR"].startswith("/data")


def test_the_machine_does_not_stop_itself_while_a_job_is_running():
    service = FLY["http_service"]
    assert service["auto_stop_machines"] == "off"
    assert service["auto_start_machines"] is True
    assert service["min_machines_running"] >= 1


def test_the_proxy_idle_timeout_outlasts_the_progress_stream_heartbeat():
    from app import progress

    idle = FLY["http_service"]["http_options"]["idle_timeout"]
    assert idle >= 600
    assert idle > progress.HEARTBEAT_SECONDS * 4


def test_the_machine_is_large_enough_for_a_document_conversion():
    # One conversion peaks around 218MB, measured. A 256MB machine OOMs on a
    # single file.
    assert FLY["vm"][0]["memory"] == "1gb"


def test_the_shutdown_signal_is_the_one_the_drain_listens_for():
    assert FLY["kill_signal"] == "SIGTERM"
    assert FLY["kill_timeout"] == "300s"


def test_the_entrypoint_reads_every_secret_from_the_environment():
    """One place knows about the outside world, so `create_app` stays a
    function the tests call with explicit arguments."""
    entry = (ROOT / "app" / "asgi.py").read_text()
    assert "AI_ANKI_DATABASE_URL" in entry
    assert "os.environ" in entry
    # Nothing baked into the image, and nothing defaulted to a value that would
    # quietly work: an unset database URL must stop the process, not start it
    # against something else.
    assert 'os.environ["AI_ANKI_DATABASE_URL"]' in entry

    identity_module = (ROOT / "app" / "identity.py").read_text()
    assert "AI_ANKI_JWT_ISSUER" in identity_module


def test_ci_runs_strict_config_validation():
    """Plain validation silently accepts unrecognised keys.

    A typo'd `auto_stop_machines` would pass, do nothing, and the machine would
    stop itself under a running job.
    """
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    assert workflow.exists()
    text = workflow.read_text()
    assert "fly config validate --strict" in text
    assert "pytest" in text


def test_operations_documents_the_secret_restart_hazard():
    docs = (ROOT / "docs" / "operations.md").read_text()
    assert "--stage" in docs
    assert "restart" in docs.lower()


def test_an_unknown_api_path_is_a_json_404(client):
    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("escape", ["/%2e%2e/%2e%2e/pyproject.toml", "/..%2f..%2fpyproject.toml"])
def test_nothing_outside_the_api_is_served(client, escape):
    """The server is the API and nothing else; the app lives on the phone.

    Percent-encoded, because the plain `/../../` form is normalised away by the
    client before it ever reaches the server. A static-file route that once
    sat here decoded `..` and reached the repository root, `.env` with it.
    """
    response = client.get(escape)

    assert response.status_code == 404
    assert "[project]" not in response.text


def test_the_provider_choice_is_documented_with_its_gate_and_its_assumptions():
    docs = (ROOT / "docs" / "providers.md").read_text()

    assert "AI_ANKI_PROVIDER" in docs
    # The gate is the whole point; a rate table without it invites picking the
    # cheapest row and paying more.
    assert "20,000 tokens" in docs, "the Nova caching cap must be recorded"
    assert "assumptions, not facts" in docs.lower()
