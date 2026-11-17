"""Operations routes (blueprint F.12, D.18; D-064).

`/healthz/worker`       for an outside uptime monitor: is the worker running?
`/admin/ops/status`     for staff: open alerts, the scheduled jobs, the outbox
`/admin/ops/alerts`     for staff: recent alerts, open and resolved
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from markx.accounts.deps import Principal, require_staff
from markx.accounts.permissions import StaffCapability
from markx.core.http import Db
from markx.notifications.models import Outbox
from markx.ops import service
from markx.ops.schemas import AlertOut, JobOut, OpsStatusOut, OutboxCountOut
from markx.worker.models import ScheduledJob

public_router = APIRouter(tags=["health"])
admin_router = APIRouter(prefix="/admin/ops", tags=["admin: operations"])
# Counts and job names only, no personal data: every staff role that finds
# orders may read it (super administrator, operations, support, finance).
OpsReader = Annotated[Principal, Depends(require_staff(StaffCapability.FIND_ORDERS))]

# The fastest job runs every minute; five quiet minutes means no worker.
WORKER_LATE_AFTER = timedelta(minutes=5)


@public_router.get("/healthz/worker")
def worker_health(db: Db) -> JSONResponse:
    """503 when no scheduled job has started for five minutes: the worker is
    down or stuck (F.12; P2: "an outage alerts the founder"). Point the
    outside uptime monitor here as well as at `/healthz`."""
    last = db.scalar(select(func.max(ScheduledJob.last_started_at)))
    now = datetime.now(UTC)
    if last is None or now - last > WORKER_LATE_AFTER:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "worker": "late",
                     "last_job_started_at": last.isoformat() if last else None},
        )  # fmt: skip
    return JSONResponse(
        content={"status": "ok", "worker": "up", "last_job_started_at": last.isoformat()}
    )


@admin_router.get("/status", response_model=OpsStatusOut)
def ops_status(staff: OpsReader, db: Db) -> OpsStatusOut:
    """What is wrong now, and the machinery behind it."""
    jobs = [
        JobOut(
            name=job.name,
            next_run_at=job.next_run_at,
            last_started_at=job.last_started_at,
            last_succeeded_at=job.last_succeeded_at,
            last_result=job.last_result,
            consecutive_failures=job.consecutive_failures,
            last_error=(job.last_error or None) and job.last_error[:300],
        )
        for job in db.scalars(select(ScheduledJob).order_by(ScheduledJob.name))
    ]
    outbox = [
        OutboxCountOut(topic=topic, status=status, count=count)
        for topic, status, count in db.execute(
            select(Outbox.topic, Outbox.status, func.count())
            .where(Outbox.status != "done")
            .group_by(Outbox.topic, Outbox.status)
            .order_by(Outbox.topic, Outbox.status)
        ).all()
    ]
    return OpsStatusOut(
        open_alerts=[AlertOut.model_validate(a) for a in service.open_alerts(db)],
        jobs=jobs,
        outbox=outbox,
    )


@admin_router.get("/alerts", response_model=list[AlertOut])
def recent_alerts(
    staff: OpsReader, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[AlertOut]:
    return [AlertOut.model_validate(a) for a in service.recent_alerts(db, limit=limit)]
