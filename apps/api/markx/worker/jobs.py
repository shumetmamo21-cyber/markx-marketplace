"""Scheduled jobs (blueprint F.8, and `expire_stale` in G.7).

A job is a service function that is safe to run twice. Each runs in its own
transaction, under the lock of its `scheduled_jobs` row:

* two workers never run the same job at once (`FOR UPDATE SKIP LOCKED`);
* a job that raises loses only its own work, waits a growing delay and never
  stops another job;
* a worker that dies mid-run changed nothing, so the job is still due.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.core.db import session_scope
from markx.offers import service as offers
from markx.orders import service as orders
from markx.sellers import service as sellers
from markx.worker.models import ScheduledJob

logger = logging.getLogger("markx.worker.jobs")

RETRY_BASE = timedelta(minutes=1)
RETRY_MAX = timedelta(hours=1)
# Blueprint F.8: "a job that keeps failing raises an alert".
ALERT_AFTER_FAILURES = 3


@dataclass(frozen=True, slots=True)
class Job:
    name: str
    every: timedelta
    # Does the work inside the given transaction; returns how many rows it changed.
    run: Callable[[Session, datetime], int]


@dataclass(frozen=True, slots=True)
class JobOutcome:
    name: str
    ok: bool
    result: int | None = None
    error: str | None = None


JOBS: tuple[Job, ...] = (
    # First, and often: an unanswered order holds stock other buyers want.
    Job(
        "orders.expire_unanswered",
        timedelta(minutes=1),
        lambda db, now: orders.expire_unanswered_orders(db, now=now),
    ),
    Job(
        "offers.mark_stale",
        timedelta(hours=1),
        lambda db, now: offers.mark_stale_offers(db, now=now),
    ),
    Job(
        "sellers.activate_due_payout_accounts",
        timedelta(minutes=5),
        lambda db, now: sellers.activate_due_payout_accounts(db, now=now),
    ),
)


def retry_delay(failures: int) -> timedelta:
    """One minute, then two, four ... up to an hour."""
    return min(RETRY_BASE * (1 << min(max(failures - 1, 0), 30)), RETRY_MAX)


def _run_if_due(job: Job, now: datetime) -> JobOutcome | None:
    # A job seen for the first time is due at once. Its row is created in a
    # short transaction of its own, and only when it is missing: an insert,
    # even one that does nothing on conflict, waits for a worker that is
    # running the job, and a second worker must skip it instead.
    with session_scope() as db:
        known = db.scalar(select(ScheduledJob.name).where(ScheduledJob.name == job.name))
        if known is None:
            db.execute(
                insert(ScheduledJob)
                .values(name=job.name, next_run_at=now)
                .on_conflict_do_nothing(index_elements=[ScheduledJob.name])
            )
    with session_scope() as db:
        row = db.scalar(
            select(ScheduledJob)
            .where(ScheduledJob.name == job.name, ScheduledJob.next_run_at <= now)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None  # not due yet, or another worker is running it
        row.last_started_at = now
        try:
            # A savepoint: a failed job's partial work is undone, and this
            # transaction lives on to record the failure.
            with db.begin_nested():
                result = job.run(db, now)
        except Exception as exc:
            row.consecutive_failures += 1
            row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            row.next_run_at = now + retry_delay(row.consecutive_failures)
            alert = row.consecutive_failures >= ALERT_AFTER_FAILURES
            logger.log(
                logging.CRITICAL if alert else logging.ERROR,
                "scheduled job keeps failing" if alert else "scheduled job failed",
                exc_info=exc,
                extra={"job": job.name, "consecutive_failures": row.consecutive_failures},
            )
            return JobOutcome(job.name, ok=False, error=row.last_error)
        row.consecutive_failures = 0
        row.last_error = None
        row.last_result = result
        row.last_succeeded_at = datetime.now(UTC)
        row.next_run_at = now + job.every
        logger.info("scheduled job ran", extra={"job": job.name, "result": result})
        return JobOutcome(job.name, ok=True, result=result)


def run_due_jobs(now: datetime | None = None, jobs: Sequence[Job] = JOBS) -> list[JobOutcome]:
    """Run every job that is due. Returns what ran; a job that was not due, or
    that another worker holds, is left out."""
    now = now or datetime.now(UTC)
    outcomes: list[JobOutcome] = []
    for job in jobs:
        try:
            outcome = _run_if_due(job, now)
        except Exception as exc:
            # The bookkeeping itself failed (the database went away, say).
            # Nothing was committed; the job is still due. Carry on.
            logger.exception("could not run scheduled job", extra={"job": job.name})
            outcome = JobOutcome(job.name, ok=False, error=f"{type(exc).__name__}: {exc}"[:1000])
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes
