"""The backup command line on a real server (D-096): what must never run
there refuses (BK-1, BK-2), the service never deletes anything, and it does
not start against a bucket without the required object lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from markx.backup import __main__ as cli
from markx.backup.config import BackupConfig
from markx.backup.destination import DestinationError, DestinationUnavailable
from markx.backup.drill import DrillRefused, refuse_on_a_server
from markx.backup.runner import BackupOutcome

REAL = {
    "MARKX_ENV": "production",
    "MARKX_RELEASE": "abc1234",
    "MARKX_BACKUP_DESTINATION": "r2",
    "MARKX_BACKUP_DESTINATION_ENDPOINT_URL": "https://0123456789abcdef.r2.cloudflarestorage.com",
    "MARKX_BACKUP_DESTINATION_BUCKET": "markx-backups",
    "MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID": "test-only-backup-key-id",
    "MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY": "test-only-backup-secret",
    "MARKX_BACKUP_SOURCE_PROVIDER": "r2",
    "MARKX_BACKUP_SOURCE_ENDPOINT_URL": "https://0123456789abcdef.r2.cloudflarestorage.com",
    "MARKX_BACKUP_SOURCE_PRIVATE_BUCKET": "markx-private",
    "MARKX_BACKUP_SOURCE_PUBLIC_BUCKET": "markx-public",
    "MARKX_BACKUP_SOURCE_ACCESS_KEY_ID": "test-only-read-only-key-id",
    "MARKX_BACKUP_SOURCE_SECRET_ACCESS_KEY": "test-only-read-only-secret",
    "MARKX_BACKUP_RETENTION_DAYS": "30",
    "MARKX_BACKUP_RETENTION_MIN_SETS": "7",
    "MARKX_BACKUP_PUBLIC_KEY_FILE": "/run/secrets/backup-public.key",
    "MARKX_BACKUP_SIGNING_KEY_FILE": "/run/secrets/backup-signing.key",
}


@pytest.fixture
def on_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REAL.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "argv",
    [
        ["verify", "--set", "20261118T230000Z-3fa2c1d0", "--recovery-key", "r", "--signer", "s"],
        ["restore", "--set", "20261118T230000Z-3fa2c1d0", "--recovery-key", "r", "--signer", "s",
         "--target-db", "markx_restored", "--confirm-target", "markx_restored", "--no-files"],
        ["drill", "--recovery-key", "r", "--signer", "s"],
        ["drill", "--from-destination", "--recovery-key", "r", "--signer", "s"],
        ["prune", "--execute", "--signer", "s"],
        ["prune"],
    ],
)  # fmt: skip
@pytest.mark.parametrize("env", ["staging", "production"])
def test_what_needs_the_recovery_key_or_deletes_never_runs_on_a_server(
    on_a_server: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    argv: list[str], env: str,
) -> None:  # fmt: skip
    monkeypatch.setenv("MARKX_ENV", env)
    assert cli.main(argv) == cli.EXIT_USAGE
    error = capsys.readouterr().err
    assert f"never runs on {env}" in error
    assert "BK-1" in error or "BK-2" in error


def test_the_drill_library_refuses_a_server_too() -> None:
    with pytest.raises(DrillRefused, match="BK-2"):
        refuse_on_a_server(BackupConfig(**_real_settings()))
    refuse_on_a_server(BackupConfig(env="local"))


def test_retention_off_the_server_needs_the_founders_explicit_period(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in REAL.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MARKX_ENV", "local")  # the retention machine
    monkeypatch.delenv("MARKX_BACKUP_RETENTION_DAYS")
    assert cli.main(["prune", "--signer", "s"]) == cli.EXIT_USAGE
    assert "F-20" in capsys.readouterr().err


class _Destination:
    """Records every call; any delete would be a failure of BK-1."""

    identity, offsite, lock = "stub", True, None

    def __init__(self, error: DestinationError | None = None) -> None:
        self.calls: list[str] = []
        self._error = error

    def check_access(self) -> None:
        self.calls.append("check_access")
        if self._error is not None:
            raise self._error

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(f"the service called {name}")

        return record


def _serve_once(monkeypatch: pytest.MonkeyPatch, destination: _Destination) -> list[str]:
    config = BackupConfig(env="local")
    ctx = type("Ctx", (), {"destination": destination})()
    monkeypatch.setattr(cli, "_config", lambda service: config)
    monkeypatch.setattr(cli, "_context", lambda config: ctx)
    runs: list[str] = []

    def one_backup(context: Any) -> BackupOutcome:
        runs.append("backup")
        return BackupOutcome("succeeded", "20261118T230000Z-3fa2c1d0")

    monkeypatch.setattr(cli, "run_backup", one_backup)

    def no_retention(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the service ran retention")

    monkeypatch.setattr(cli, "prune", no_retention)

    def stop(seconds: float) -> None:
        cli._stop = True

    monkeypatch.setattr(cli, "_sleep", stop)
    monkeypatch.setattr(cli, "_stop", False)
    monkeypatch.setattr(cli.signal, "signal", lambda *a: None)
    assert cli.cmd_serve(None) == 0  # type: ignore[arg-type]
    return runs


def test_the_service_backs_up_and_never_deletes_or_runs_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = _Destination()
    assert _serve_once(monkeypatch, destination) == ["backup"]
    assert destination.calls == ["check_access"]


@pytest.mark.parametrize(
    "reason", ["object_lock_missing", "object_lock_not_compliance:GOVERNANCE",
               "object_lock_too_short:7<30", "bucket_is_public", "provider:NoSuchBucket"],
)  # fmt: skip
def test_the_service_does_not_start_against_an_unsafe_bucket(
    monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    with pytest.raises(SystemExit, match=f"backup destination refused: {reason}"):
        _serve_once(monkeypatch, _Destination(DestinationError(reason)))


def test_the_service_starts_when_the_bucket_only_does_not_answer_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retried by each run instead (and recorded failed while it lasts)."""
    assert _serve_once(monkeypatch, _Destination(DestinationUnavailable("timeout"))) == ["backup"]


# -- the settings ----------------------------------------------------------------------------


def _real_settings(**overrides: Any) -> dict[str, Any]:
    settings = {name.removeprefix("MARKX_BACKUP_").lower(): value for name, value in REAL.items()
                if name.startswith("MARKX_BACKUP_")}  # fmt: skip
    settings.update({"env": "production", "release": "abc1234"})
    settings.update(overrides)
    return settings


def test_staging_and_production_always_require_an_object_lock() -> None:
    for env in ("staging", "production"):
        config = BackupConfig(**_real_settings(env=env))
        assert config.object_lock_required
        assert config.object_lock_min_days == 30  # PROVISIONAL (F-16, F-20)
    assert not BackupConfig(env="local").object_lock_required


def test_a_laptop_may_ask_for_the_lock_but_a_folder_cannot_hold_one(tmp_path: Path) -> None:
    config = BackupConfig(env="test", destination="minio", require_object_lock=True,
                          destination_endpoint_url="http://127.0.0.1:9000",
                          destination_bucket="markx-backups", destination_access_key_id="k",
                          destination_secret_access_key="s")  # fmt: skip
    assert config.object_lock_required
    with pytest.raises(ValidationError, match="a folder has no object lock"):
        BackupConfig(env="local", require_object_lock=True, destination_dir=tmp_path)


def test_the_destination_a_real_server_builds_checks_the_lock() -> None:
    from markx.backup.destination import S3Destination, make_destination

    destination = make_destination(BackupConfig(**_real_settings()))
    assert isinstance(destination, S3Destination)
    assert destination._lock_min_days == 30
