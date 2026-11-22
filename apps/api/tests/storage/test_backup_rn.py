"""The pull request #4 review notes RN-1, RN-4 and RN-5 (D-105), against a
real PostgreSQL 17 and MinIO, through the commands and functions that
already existed before them, so each test fails on the old code for what it
does, not for a missing name:

- RN-1: a file of a set written again by the server's key (the dump, the
  index, the manifest, a blob) is verified, restored and drilled from its
  older locked copy; the backup service and the drill report it, and the
  watch raises `backup.overwritten`.
- RN-4: a socket path too long for Linux, or a PostgreSQL that does not
  answer, makes the off-server drill FAILED with the reason, not a traceback.
- RN-5: `record-drill` records a report that says PASSED but does not show a
  passed drill as a FAILED drill (and the watch alerts).

Buckets with a COMPLIANCE lock cannot be removed for a day: tiny, generated
data only; CI's MinIO is discarded after each run.
"""

# The shared fixtures are imported from test_backup_recovery; a test naming one
# as a parameter is not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.backup import crypto
from markx.backup import manifest as manifest_mod
from markx.backup.__main__ import main as backup_main
from markx.backup.drill import run_offsite_drill
from markx.backup.models import BackupRun
from markx.backup.restore import restore_set, verify_set
from markx.backup.runner import run_backup
from markx.core.storage import make_s3_client
from markx.ops import service as ops
from markx.ops.models import OpsAlert
from tests.storage.test_backup_recovery import (  # noqa: F401  (fixtures)
    BOOTSTRAP,
    DATABASE,
    MIGRATOR,
    SUPERUSER,
    Credentials,
    Setup,
    _as,
    _marketplace,
    _runs,
    _targets,
    _watch_on,
    backup_bucket,
    keys,
    restored_db,
    setup,
    tools,
    users,
)
from tests.storage.test_backup_trust import _locked_bucket, _on_bucket, _record, _restricted


def _locked(setup: Setup) -> Setup:
    """The server's setup on a bucket with versioning and a COMPLIANCE lock,
    as staging and production require."""
    _restricted(setup)
    return _on_bucket(setup, _locked_bucket(setup.minio, days=1), lock_min_days=1)


def _overwrite(setup: Setup, key: str, data: bytes) -> None:
    """What someone holding the server's backup key can do: write an object
    again. The key cannot delete; the older version stays, locked."""
    writer = make_s3_client(_as(setup.minio, setup.users.writer))
    writer.put_object(Bucket=setup.bucket, Key=f"markx/test/{key}", Body=data)
    writer.close()


def _blob_keys(setup: Setup, manifest: dict[str, Any]) -> list[str]:
    data = setup.reader.read_bytes(manifest["files"]["blobs_object"], limit=2**24)
    return [manifest_mod.blob_key(b) for b in data.decode().splitlines() if b]


def _offsite(setup: Setup, **kw: Any) -> Any:
    config = setup.ctx.config.model_copy(update={"env": "local"})
    return run_offsite_drill(config, setup.reader, superuser=SUPERUSER, keys=setup.ring,
                             signers=setup.signers, bootstrap_script=BOOTSTRAP, **kw)  # fmt: skip


def _alerts(db: DbSession) -> set[str]:
    db.expire_all()
    return {a.key for a in db.scalars(select(OpsAlert).where(OpsAlert.resolved_at.is_(None)))}


# -- RN-1: an overwritten file is read from its older locked copy -------------------------------


def test_an_overwritten_set_is_verified_restored_and_drilled_from_its_locked_copies(
    setup: Setup, db: DbSession, restored_db: str, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    s = _locked(setup)
    _marketplace(db)
    made = run_backup(s.ctx)
    assert made.status == "succeeded", made.error_code
    backup_id, manifest = str(made.backup_id), made.manifest
    blobs = _blob_keys(s, manifest)
    # Garbage over the dump, the index, the manifest and one file's blob.
    victims = [manifest["database"]["object"], manifest["files"]["index_object"],
               manifest_mod.manifest_key(backup_id), blobs[0]]  # fmt: skip
    for key in victims:
        _overwrite(s, key, b"garbage written over a backup file")

    report = verify_set(destination=s.reader, backup_id=backup_id, signers=s.signers,
                        keys=s.ring, deep=True)  # fmt: skip
    assert report.passed, report.text()
    assert set(victims) <= set(report.facts["overwritten"])
    assert "written again after the set was made" in report.text()

    files = _targets(s.minio)
    restored = restore_set(
        destination=s.reader, backup_id=backup_id, signers=s.signers, keys=s.ring,
        server=SUPERUSER, target_db=restored_db, confirm=restored_db, files=files,
        bootstrap_script=BOOTSTRAP, psql_command=s.tools.psql,
        pg_restore_command=s.tools.pg_restore,
    )  # fmt: skip
    assert restored.passed, restored.text()
    assert sum(restored.facts["restored_files"].values()) == manifest["files"]["object_count"]

    drill = _offsite(s)
    assert drill.passed, drill.text()
    assert drill.backup_id == backup_id  # the overwritten manifest did not hide the set
    assert len(drill.injections) == 7
    assert all(ok for _, ok, _ in drill.injections)
    assert set(victims) <= set(drill.overwritten)

    # Its report, entered on the server, raises the alert there.
    path = tmp_path / "drill.json"
    path.write_text(json.dumps(drill.as_dict(), default=str))
    assert _record(s, path) == 0
    (row,) = _runs(db, "drill")
    assert row.status == "succeeded"
    assert row.details["overwritten"]["count"] >= len(victims)
    _watch_on(monkeypatch)
    ops.watch(db, datetime.now(UTC))
    assert "backup.overwritten" in _alerts(db)


def test_the_backup_service_notices_an_overwritten_file_and_the_watch_alerts(
    setup: Setup, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _locked(setup)
    _marketplace(db)
    first = run_backup(s.ctx)
    assert first.status == "succeeded"
    (clean,) = _runs(db)
    assert clean.details["overwritten"] == {"count": 0, "keys": []}
    assert clean.details["overwrite_check"] == "ok"
    _watch_on(monkeypatch)
    ops.watch(db, datetime.now(UTC))
    assert "backup.overwritten" not in _alerts(db)

    blob = _blob_keys(s, first.manifest)[0]
    dump = first.manifest["database"]["object"]
    _overwrite(s, dump, b"garbage")
    _overwrite(s, blob, b"garbage")
    later = datetime.now(UTC) + timedelta(minutes=1)
    second = run_backup(replace(s.ctx, clock=lambda: later))
    assert second.status == "succeeded", second.error_code  # it uploads the blob again
    found = _runs(db)[-1].details["overwritten"]
    assert {dump, blob} <= set(found["keys"])
    ops.watch(db, datetime.now(UTC))
    assert "backup.overwritten" in _alerts(db)
    alert = db.scalars(select(OpsAlert).where(OpsAlert.key == "backup.overwritten")).one()
    assert alert.severity == "critical"
    assert "server's backup key" in alert.summary


# -- RN-5: record-drill does not believe the report's own "passed" --------------------------------


def test_record_drill_records_a_report_that_does_not_show_a_pass_as_failed(
    setup: Setup, db: DbSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _marketplace(db)
    assert run_backup(setup.ctx).status == "succeeded"
    genuine = _offsite(setup)
    assert genuine.passed, genuine.text()
    report = genuine.as_dict()
    path = tmp_path / "drill.json"

    def enter(changed: dict[str, Any]) -> tuple[int, BackupRun]:
        path.write_text(json.dumps(changed, default=str))
        code = _record(setup, path)
        return code, _runs(db, "drill")[-1]

    tampered = json.loads(json.dumps(report, default=str))
    tampered["restore"]["checks"][-1]["ok"] = False  # a failed check, "passed" left true
    code, row = enter(tampered)
    assert (code, row.status, row.verified) == (1, "failed", False)
    assert row.error_code == "drill_report_not_a_pass"

    no_faults = {**json.loads(json.dumps(report, default=str)), "injections": []}
    code, row = enter(no_faults)
    assert (code, row.status) == (1, "failed")
    assert "injected faults not tried" in str(row.error_summary)

    fewer = json.loads(json.dumps(report, default=str))
    fewer["restore"]["facts"]["restored_files"]["private"] -= 1
    code, row = enter(fewer)
    assert (code, row.status) == (1, "failed")

    _watch_on(monkeypatch)
    ops.watch(db, datetime.now(UTC))
    assert "backup.drill_failed" in _alerts(db)

    code, row = enter(report)  # the genuine report still counts
    assert (code, row.status, row.verified) == (0, "succeeded", True)


# -- RN-4: a drill that cannot reach its PostgreSQL fails clearly ---------------------------------


@contextmanager
def _environment(values: dict[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _key_files(setup: Setup, folder: Path) -> tuple[Path, Path, Path, Path]:
    folder.mkdir(exist_ok=True)
    k = setup.keys
    files = (folder / "recovery.key", folder / "signer.key", folder / "public.key",
             folder / "signing.key")  # fmt: skip
    if not files[0].exists():
        crypto.write_key_file(files[0], crypto.encode_recovery(k.recovery), secret=True)
        crypto.write_key_file(files[1], crypto.encode_signer(k.signing.signer), secret=False)
        crypto.write_key_file(files[2], crypto.encode_recipient(k.recovery.recipient), secret=False)
        crypto.write_key_file(files[3], crypto.encode_signing(k.signing), secret=True)
    return files


def _machine(setup: Setup, who: Credentials, **extra: str) -> dict[str, str]:
    """The settings of a machine using this backup bucket with key `who`."""
    return {
        "MARKX_ENV": "local", "MARKX_BACKUP_DATABASE": DATABASE,
        "MARKX_BACKUP_DESTINATION": "minio",
        "MARKX_BACKUP_DESTINATION_ENDPOINT_URL": str(setup.minio.endpoint_url),
        "MARKX_BACKUP_DESTINATION_BUCKET": setup.bucket,
        "MARKX_BACKUP_DESTINATION_PREFIX": "markx/test",
        "MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID": who.access_key,
        "MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY": who.secret_key,
        "MARKX_BACKUP_PSQL_COMMAND": setup.tools.psql,
        "MARKX_BACKUP_PG_RESTORE_COMMAND": setup.tools.pg_restore,
        "PGHOST": SUPERUSER.host or "", "PGPORT": SUPERUSER.port or "",
        "PGUSER": SUPERUSER.user or "", "PGPASSWORD": SUPERUSER.password or "",
        **extra,
    }  # fmt: skip


@pytest.mark.parametrize("where", ["a socket path too long", "a PostgreSQL that does not answer"])
def test_the_off_server_drill_reports_failed_when_it_cannot_reach_postgresql(
    setup: Setup, db: DbSession, tmp_path: Path, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    assert run_backup(setup.ctx).status == "succeeded"
    recovery, signer, _, _ = _key_files(setup, tmp_path / "keys")
    pg = ({"PGHOST": str(tmp_path / ("x" * 110))} if where.startswith("a socket")
          else {"PGHOST": "127.0.0.1", "PGPORT": "9"})  # fmt: skip
    report = tmp_path / "drill.json"
    with _environment(_machine(setup, setup.users.reader, **pg)):
        code = backup_main(["drill", "--from-destination", "--recovery-key", str(recovery),
                            "--signer", str(signer), "--report", str(report)])  # fmt: skip
    said = capsys.readouterr().out
    assert code == 1
    assert "DRILL FAILED" in said
    assert ("at most 107" in said) if where.startswith("a socket") else ("could not" in said)
    assert json.loads(report.read_text())["passed"] is False
