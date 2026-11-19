"""Each backup attempt's outcome in `backup_runs` (D-094), for the watch.

Written with the backup's own database connection, in short transactions of
their own, so a record survives whatever happens to the run. Recording is
best effort in one direction only: if the database cannot be written, the
run still fails or succeeds on its merits, its local status file still
tells the container's health check, and the watch reports the backup as
stale because no fresh verified run appears.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from markx.backup.database import PgServer
from markx.core.ids import uuid7

logger = logging.getLogger("markx.backup.records")


@dataclass(slots=True)
class RunRecord:
    kind: str
    environment: str
    destination: str
    offsite: bool
    started_at: datetime
    id: uuid.UUID = field(default_factory=uuid7)
    backup_id: str | None = None
    status: str = "running"
    verified: bool = False
    finished_at: datetime | None = None
    database_bytes: int | None = None
    object_count: int | None = None
    object_bytes: int | None = None
    new_objects: int | None = None
    error_code: str | None = None
    error_summary: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class Recorder:
    def __init__(self, server: PgServer | None, database: str) -> None:
        self._server = server
        self._database = database

    def _write(self, query: str, params: dict[str, Any]) -> None:
        if self._server is None:
            return
        try:
            with self._server.connect(self._database, autocommit=True, connect_timeout=10) as conn:
                conn.execute(query, params)
        except Exception as exc:  # recorded nowhere else; the run goes on
            logger.error("could not record the backup run", extra={"error": type(exc).__name__})

    def start(self, record: RunRecord) -> None:
        self._write(
            "insert into backup_runs (id, kind, status, backup_id, environment, destination,"
            " offsite, started_at) values (%(id)s, %(kind)s, 'running', %(backup_id)s,"
            " %(environment)s, %(destination)s, %(offsite)s, %(started_at)s)",
            {"id": record.id, "kind": record.kind, "backup_id": record.backup_id,
             "environment": record.environment, "destination": record.destination,
             "offsite": record.offsite, "started_at": record.started_at},
        )  # fmt: skip

    def finish(self, record: RunRecord) -> None:
        assert record.status != "running"
        assert record.finished_at is not None
        self._write(
            "update backup_runs set status = %(status)s, backup_id = %(backup_id)s,"
            " verified = %(verified)s, finished_at = %(finished_at)s,"
            " database_bytes = %(database_bytes)s, object_count = %(object_count)s,"
            " object_bytes = %(object_bytes)s, new_objects = %(new_objects)s,"
            " error_code = %(error_code)s, error_summary = %(error_summary)s,"
            " details = %(details)s::jsonb where id = %(id)s",
            {"id": record.id, "status": record.status, "backup_id": record.backup_id,
             "verified": record.verified, "finished_at": record.finished_at,
             "database_bytes": record.database_bytes, "object_count": record.object_count,
             "object_bytes": record.object_bytes, "new_objects": record.new_objects,
             "error_code": record.error_code,
             "error_summary": (record.error_summary or None) and record.error_summary[:500],
             "details": json.dumps(record.details, default=str)},
        )  # fmt: skip

    def abandon_running(self, kind: str, now: datetime) -> None:
        """Runs left `running` by a process that died. Called only while holding
        the backup lock, so none of them can still be running."""
        self._write(
            "update backup_runs set status = 'abandoned', finished_at = greatest(%(now)s, started_at),"
            " error_code = 'process_died' where kind = %(kind)s and status = 'running'",
            {"kind": kind, "now": now},
        )
