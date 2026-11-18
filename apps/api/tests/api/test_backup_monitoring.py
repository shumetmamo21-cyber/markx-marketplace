"""Backup monitoring in the worker's watch (D-094): failed, incomplete and
stale backups and failed or overdue restore drills raise alerts, which go
through the outbox to the alert channel. The record itself is protected: the
application's role can read it and cannot write it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from markx.backup.models import BackupRun
from markx.core.config import get_config
from markx.ops import checks
from markx.ops import service as ops
from markx.ops.alerts import read_dev_alerts
from markx.ops.models import OpsAlert
from markx.worker.runner import run_once

NOW = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)


@pytest.fixture
def watched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backup monitoring on, as on a real server ("auto" there)."""
    config = get_config().model_copy(update={"backup_monitoring": "on"})
    monkeypatch.setattr(checks, "get_config", lambda: config)


def _run(engine: Engine, **fields: Any) -> None:
    """A row as the backup service writes it, as the schema owner."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(), "kind": "backup", "status": "succeeded", "backup_id": None,
        "environment": "production", "destination": "r2:example.invalid/markx-backups/markx",
        "offsite": True, "verified": True, "started_at": NOW - timedelta(hours=1),
        "finished_at": NOW - timedelta(minutes=50), "error_code": None, "object_count": 10,
        "object_bytes": 1000, "database_bytes": 5000,
    }  # fmt: skip
    row.update(fields)
    columns = ", ".join(row)
    values = ", ".join(f":{k}" for k in row)
    with engine.begin() as conn:
        conn.execute(text(f"insert into backup_runs ({columns}) values ({values})"), row)


def _open(db: DbSession) -> dict[str, OpsAlert]:
    db.expire_all()
    return {a.key: a for a in db.scalars(select(OpsAlert).where(OpsAlert.resolved_at.is_(None)))}


def _watch(db: DbSession, now: datetime = NOW) -> dict[str, OpsAlert]:
    ops.watch(db, now)
    db.commit()
    return {k: v for k, v in _open(db).items() if k.startswith("backup.")}


def test_nothing_is_watched_where_no_backup_service_runs(db: DbSession) -> None:
    """A laptop and the tests run no backup service ("auto" is off there)."""
    assert not get_config().backup_watched
    assert _watch(db) == {}


def test_no_backup_at_all_is_an_alert(db: DbSession, watched: None) -> None:
    alerts = _watch(db)
    assert alerts["backup.stale"].severity == "critical"
    assert "No verified off-server backup exists" in alerts["backup.stale"].summary
    assert alerts["backup.drill_overdue"].severity == "warning"


def test_a_fresh_verified_off_server_backup_and_a_recent_drill_are_quiet(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(migrator_engine)
    _run(migrator_engine, kind="drill", finished_at=NOW - timedelta(days=3),
         started_at=NOW - timedelta(days=3, minutes=5))  # fmt: skip
    assert _watch(db) == {}


def test_a_backup_on_this_server_is_not_an_off_server_backup(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(migrator_engine, offsite=False, destination="local:/var/backups/markx")
    assert "backup.stale" in _watch(db)


def test_a_stale_backup_is_reported_with_its_age(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(
        migrator_engine, started_at=NOW - timedelta(hours=31), finished_at=NOW - timedelta(hours=30)
    )
    alert = _watch(db)["backup.stale"]
    assert "30 hours old" in alert.summary
    assert alert.details["age_hours"] == 30.0
    assert alert.details["object_count"] == 10


def test_a_failed_backup_alerts_and_resolves_when_one_succeeds(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(
        migrator_engine, started_at=NOW - timedelta(hours=20), finished_at=NOW - timedelta(hours=20)
    )
    _run(migrator_engine, status="failed", verified=False, error_code="destination:unreachable",
         started_at=NOW - timedelta(minutes=30), finished_at=NOW - timedelta(minutes=29))  # fmt: skip
    alerts = _watch(db)
    assert set(alerts) == {"backup.failed", "backup.drill_overdue"}
    assert "destination:unreachable" in alerts["backup.failed"].summary
    assert "previous verified backup is kept" in alerts["backup.failed"].summary

    _run(
        migrator_engine,
        started_at=NOW - timedelta(minutes=10),
        finished_at=NOW - timedelta(minutes=5),
    )
    assert set(_watch(db, NOW + timedelta(minutes=5))) == {"backup.drill_overdue"}


def test_an_incomplete_set_alerts(db: DbSession, migrator_engine: Engine, watched: None) -> None:
    _run(migrator_engine, status="incomplete", verified=False, error_code="missing_references")
    alerts = _watch(db)
    assert {"backup.incomplete", "backup.stale"} <= set(alerts)


def test_an_abandoned_run_counts_as_failed(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(migrator_engine, started_at=NOW - timedelta(hours=2), finished_at=NOW - timedelta(hours=2))
    _run(migrator_engine, status="abandoned", verified=False, error_code="process_died")
    assert "backup.failed" in _watch(db)


def test_a_skipped_run_is_not_a_failure(
    db: DbSession, migrator_engine: Engine, watched: None
) -> None:
    _run(migrator_engine)
    _run(migrator_engine, status="skipped", verified=False, started_at=NOW - timedelta(minutes=5),
         finished_at=NOW - timedelta(minutes=5))  # fmt: skip
    assert "backup.failed" not in _watch(db)


def test_a_failed_drill_alerts(db: DbSession, migrator_engine: Engine, watched: None) -> None:
    _run(migrator_engine)
    _run(migrator_engine, kind="drill", finished_at=NOW - timedelta(days=40),
         started_at=NOW - timedelta(days=40))  # fmt: skip
    _run(migrator_engine, kind="drill", status="failed", verified=False, error_code="drill_failed",
         error_summary="every file restored, read back and matched its checksum")  # fmt: skip
    alerts = _watch(db)
    assert set(alerts) == {"backup.drill_failed", "backup.drill_overdue"}
    assert "matched its checksum" in alerts["backup.drill_failed"].summary


def test_the_alert_goes_through_the_outbox_to_the_alert_channel(
    db: DbSession, watched: None
) -> None:
    """Generated is not received: the alert is queued, and the worker hands it
    to the channel (here the development file; on a server the founder's
    Telegram group once it is configured, otherwise only the log)."""
    report = run_once()
    assert report.outbox.done >= 2
    assert any(j.name == "ops.watch" and j.ok for j in report.jobs)
    sent = {m["key"]: m for m in read_dev_alerts()}
    assert sent["backup.stale"]["state"] == "opened"
    assert sent["backup.stale"]["severity"] == "critical"


def test_the_application_role_can_read_but_never_write_backup_records(
    db: DbSession, migrator_engine: Engine
) -> None:
    _run(migrator_engine)
    assert db.scalar(select(BackupRun.status)) == "succeeded"
    for statement in (
        "update backup_runs set status = 'failed', error_code = 'x'",
        "delete from backup_runs",
        "insert into backup_runs (id, kind, status, environment, destination, offsite, verified,"
        " finished_at) values (gen_random_uuid(), 'backup', 'succeeded', 'production', 'x', true,"
        " true, now())",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            db.execute(text(statement))
        db.rollback()


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"status": "running", "finished_at": NOW}, "finished_unless_running"),
        ({"status": "failed", "verified": False, "error_code": None}, "failure_has_a_code"),
        ({"status": "incomplete", "verified": True}, "verified_only_if_succeeded"),
        ({"kind": "anything"}, "kind_allowed"),
    ],
)
def test_the_record_cannot_say_something_impossible(
    migrator_engine: Engine, fields: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(DBAPIError, match=constraint):
        _run(migrator_engine, **fields)
