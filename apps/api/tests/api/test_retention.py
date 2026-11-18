"""Deleting old search logs and rate-limit counters (blueprint H.2; F-08, D-083).

The periods are PROVISIONAL: the founder must confirm them before going live.
These tests pin what the job does with whatever periods are set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.audit.models import AuditLog
from markx.core import ratelimit, settings_store
from markx.core.models import RateLimitCounter
from markx.ops import retention
from markx.search.models import SearchQuery
from markx.worker import jobs as scheduled
from markx.worker.runner import run_once

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _search(db: Session, age: timedelta, text: str) -> None:
    db.add(
        SearchQuery(
            query=text, normalized=text, script="latin", result_count=0, created_at=NOW - age
        )
    )


def _counter(db: Session, bucket: str, window_start: datetime) -> None:
    db.add(RateLimitCounter(bucket=bucket, window_start=window_start, count=3))


def _left(db: Session) -> tuple[set[str], set[str]]:
    db.rollback()
    return (
        set(db.scalars(select(SearchQuery.query))),
        set(db.scalars(select(RateLimitCounter.bucket))),
    )


def test_old_searches_and_finished_counters_go_and_the_rest_stays(db: Session) -> None:
    _search(db, timedelta(days=181), "older than 180 days")
    _search(db, timedelta(days=179), "younger than 180 days")
    # The longest window is a day; a counter is kept a day after it could end.
    _counter(db, "ended over a day ago", NOW - timedelta(days=2, minutes=1))
    _counter(db, "daily window maybe still open", NOW - timedelta(hours=23))
    _counter(db, "this hour", NOW.replace(minute=0))
    db.commit()

    assert retention.prune(db, NOW) == 2
    db.commit()
    assert _left(db) == (
        {"younger than 180 days"},
        {"daily window maybe still open", "this hour"},
    )
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "retention.prune"))
    assert entry is not None
    assert (entry.actor_type, entry.target_type) == ("system", "retention")
    assert entry.after is not None
    assert (entry.after["search_queries"], entry.after["rate_limit_counters"]) == (1, 1)


def test_the_periods_are_settings(db: Session) -> None:
    _search(db, timedelta(days=45), "45 days old")
    _counter(db, "began four days ago", NOW - timedelta(days=4))
    db.commit()

    # Longer periods keep both ...
    settings_store.set_setting(db, "retention.search_queries_days", 60)
    settings_store.set_setting(db, "retention.rate_limit_counters_days", 5)
    db.commit()
    assert retention.prune(db, NOW) == 0
    db.commit()
    assert _left(db) == ({"45 days old"}, {"began four days ago"})

    # ... shorter ones delete both.
    settings_store.set_setting(db, "retention.search_queries_days", 30)
    settings_store.set_setting(db, "retention.rate_limit_counters_days", 2)
    db.commit()
    assert retention.prune(db, NOW) == 2
    db.commit()
    assert _left(db) == (set(), set())


def test_with_nothing_to_delete_nothing_is_written(db: Session) -> None:
    _search(db, timedelta(days=1), "yesterday")
    db.commit()
    assert retention.prune(db, NOW) == 0
    db.commit()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_the_worker_runs_it_once_a_day(db: Session) -> None:
    job = next(j for j in scheduled.JOBS if j.name == "retention.prune")
    assert job.every == timedelta(days=1)
    _search(db, timedelta(days=400), "a year old")
    db.commit()
    report = run_once(NOW, jobs=(job,))
    assert [(o.name, o.ok, o.result) for o in report.jobs] == [("retention.prune", True, 1)]
    assert _left(db)[0] == set()


def test_no_rate_limit_may_use_a_window_longer_than_the_job_allows_for() -> None:
    """Otherwise the job could delete a count that is still being used."""
    with pytest.raises(ValueError, match="at most"):
        ratelimit.hit("test:too-long", 5, ratelimit.LONGEST_WINDOW + timedelta(seconds=1))
