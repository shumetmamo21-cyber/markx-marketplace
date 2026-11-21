"""The pre-deployment check and the worker's container health check (D-091)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from markx.core.config import get_config
from markx.ops import health, preflight
from markx.worker import outbox, runner
from tests.conftest import API_DIR


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """A fresh interpreter, as in a container: the configuration is read anew."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=API_DIR,
        env={k: v for k, v in env.items() if not k.startswith("PYTEST")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# -- preflight ---------------------------------------------------------------------------


def test_preflight_passes_against_the_test_database(capsys: pytest.CaptureFixture[str]) -> None:
    health.storage_probe.reset()
    assert preflight.main([]) == 0
    out = capsys.readouterr().out
    assert "database: up" in out
    assert "schema: current" in out
    assert "preflight: PASSED" in out


def test_preflight_fails_when_a_migration_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The database is at the real head; a release that knows one more is ahead of it.
    current = health.expected_schema_heads()
    monkeypatch.setattr(health, "expected_schema_heads", lambda: frozenset({"9999"}))
    monkeypatch.setattr(health, "known_revisions", lambda: frozenset({"9999", *current}))
    assert preflight.main([]) == 1
    assert "schema: behind" in capsys.readouterr().out
    # Before the migration step, pending migrations are expected.
    assert preflight.main(["--allow-pending-migrations"]) == 0


def test_preflight_refuses_a_newer_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(health, "expected_schema_heads", lambda: frozenset({"0001"}))
    monkeypatch.setattr(health, "known_revisions", lambda: frozenset({"0001"}))
    assert preflight.main(["--allow-pending-migrations"]) == 1
    assert "do not start it" in capsys.readouterr().out


def test_preflight_names_every_refused_setting_and_no_value() -> None:
    env = {
        **os.environ,
        "MARKX_ENV": "production",
        "MARKX_DATABASE_URL": "postgresql+psycopg://markx_app:test-only-pw-8d1e@db/markx",
        "MARKX_SECRET_KEY": "test-only-secret-value-that-is-long-enough-3f9a",
    }
    result = _run(["-m", "markx.ops.preflight", "--config-only"], env)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "configuration: REFUSED" in result.stdout
    for named in ("MARKX_SMS_PROVIDER", "MARKX_BOT_CHECK_PROVIDER", "MARKX_FILE_STORAGE_PROVIDER"):
        assert named in result.stdout
    assert "test-only-pw-8d1e" not in result.stdout + result.stderr
    assert "test-only-secret-value" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_the_api_refuses_to_start_with_development_settings_on_a_real_server() -> None:
    """What a production container does when its environment is incomplete:
    exit before serving anything, naming the settings and no value."""
    env = {
        **os.environ,
        "MARKX_ENV": "production",
        "MARKX_DATABASE_URL": "postgresql+psycopg://markx_app:test-only-pw-8d1e@db/markx",
    }
    result = _run(["-c", "import markx.main"], env)
    assert result.returncode != 0
    assert "MARKX_SMS_PROVIDER must be a real SMS provider" in result.stderr
    assert "test-only-pw-8d1e" not in result.stderr


def test_the_worker_refuses_to_start_with_development_settings_on_a_real_server() -> None:
    env = {**os.environ, "MARKX_ENV": "staging"}
    result = _run(["-m", "markx.worker", "--once"], env)
    assert result.returncode != 0
    assert "MARKX_BOT_CHECK_PROVIDER must be a real bot check" in result.stderr


# -- the worker heartbeat ----------------------------------------------------------------


def test_the_heartbeat_is_fresh_after_a_pass_and_stale_later(tmp_path: Path) -> None:
    beat = tmp_path / "run" / "worker.heartbeat"
    assert not runner.heartbeat_is_fresh(beat)
    runner.touch_heartbeat(beat)
    assert runner.heartbeat_is_fresh(beat)
    later = time.time() + runner.HEARTBEAT_STALE_AFTER_SECONDS + 1
    assert not runner.heartbeat_is_fresh(beat, now=later)


def test_a_heartbeat_that_cannot_be_written_does_not_stop_the_worker(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x")
    runner.touch_heartbeat(blocked / "worker.heartbeat")  # a file is not a folder: no raise
    runner.touch_heartbeat(None)


def test_the_running_worker_touches_its_heartbeat_after_every_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = tmp_path / "worker.heartbeat"
    monkeypatch.setenv("MARKX_WORKER_HEARTBEAT_FILE", str(beat))
    monkeypatch.setenv("MARKX_WORKER_POLL_SECONDS", "0.01")
    get_config.cache_clear()
    stop = threading.Event()
    passes: list[int] = []

    def one_pass() -> runner.PassReport:
        passes.append(1)
        if len(passes) == 3:
            stop.set()
        return runner.PassReport(jobs=[], outbox=outbox.DrainReport())

    monkeypatch.setattr(runner, "run_once", one_pass)
    try:
        runner.run_forever(stop)
    finally:
        monkeypatch.undo()
        get_config.cache_clear()
    assert len(passes) == 3
    assert beat.exists()
    assert runner.heartbeat_is_fresh(beat)


def test_check_heartbeat_exit_codes(tmp_path: Path) -> None:
    beat = tmp_path / "worker.heartbeat"
    env = {**os.environ, "MARKX_WORKER_HEARTBEAT_FILE": str(beat)}
    assert _run(["-m", "markx.worker", "--check-heartbeat"], env).returncode == 1
    beat.touch()
    assert _run(["-m", "markx.worker", "--check-heartbeat"], env).returncode == 0
    stale = time.time() - runner.HEARTBEAT_STALE_AFTER_SECONDS - 5
    os.utime(beat, (stale, stale))
    assert _run(["-m", "markx.worker", "--check-heartbeat"], env).returncode == 1
    unset = {k: v for k, v in os.environ.items() if k != "MARKX_WORKER_HEARTBEAT_FILE"}
    assert _run(["-m", "markx.worker", "--check-heartbeat"], unset).returncode == 1


def test_preflight_accepts_a_newer_database_only_for_an_acknowledged_rollback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(health, "expected_schema_heads", lambda: frozenset({"0001"}))
    monkeypatch.setattr(health, "known_revisions", lambda: frozenset({"0001"}))
    monkeypatch.setenv("MARKX_ALLOW_NEWER_SCHEMA", "true")
    get_config.cache_clear()
    try:
        assert preflight.main([]) == 0
        assert "an acknowledged rollback" in capsys.readouterr().out
    finally:
        monkeypatch.undo()
        get_config.cache_clear()


@pytest.mark.parametrize("arguments", [["--config-only", "--deploying"], ["--deploying"]])
def test_preflight_refuses_a_deployment_while_newer_schema_is_allowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    """D-103: a deployment never runs with MARKX_ALLOW_NEWER_SCHEMA on; the new
    release refuses it itself, wherever the setting comes from."""
    monkeypatch.setenv("MARKX_ALLOW_NEWER_SCHEMA", "true")
    get_config.cache_clear()
    try:
        assert preflight.main(arguments) == 1
        out = capsys.readouterr().out
        assert "deployment: REFUSED: MARKX_ALLOW_NEWER_SCHEMA is on" in out
        assert "preflight: FAILED" in out
    finally:
        monkeypatch.undo()
        get_config.cache_clear()


def test_preflight_for_a_deployment_passes_with_the_setting_off(
    capsys: pytest.CaptureFixture[str],
) -> None:
    health.storage_probe.reset()
    assert preflight.main(["--deploying"]) == 0
    assert "preflight: PASSED" in capsys.readouterr().out
