"""Deleting what MarkX no longer needs (blueprint H.2; F-08, D-083).

PROVISIONAL: the periods are the engineer's guess, filled in at the founder's
request (D-083). THE FOUNDER MUST CONFIRM OR CHANGE THEM BEFORE MARKX GOES
LIVE. They are settings, so changing them needs no code.

* `search_queries`: one row per first page of a search, for the zero-result
  report. Kept `retention.search_queries_days` (180: two seasons of that
  report). A row holds no name or phone number, but may hold a signed-in
  buyer's id.
* `rate_limit_counters`: one row per bucket and window, useless once its
  window has ended. Kept `retention.rate_limit_counters_days` (1) after the
  longest window could have ended (`ratelimit.LONGEST_WINDOW`), so no count
  that is still being used is deleted.

The daily job `retention.prune` deletes both and, when it deleted anything,
records how many rows of each in the audit log, which nothing can rewrite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.core import ratelimit, settings_store
from markx.core.models import RateLimitCounter
from markx.search.models import SearchQuery


def _deleted(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount or 0)


def prune(db: Session, now: datetime) -> int:
    """The scheduled `retention.prune` job. Returns how many rows it deleted."""
    search_days = settings_store.get_int(db, "retention.search_queries_days")
    counter_days = settings_store.get_int(db, "retention.rate_limit_counters_days")
    search_cutoff = now - timedelta(days=search_days)
    counter_cutoff = now - ratelimit.LONGEST_WINDOW - timedelta(days=counter_days)

    searches = _deleted(
        db.execute(delete(SearchQuery).where(SearchQuery.created_at < search_cutoff))
    )
    counters = _deleted(
        db.execute(delete(RateLimitCounter).where(RateLimitCounter.window_start < counter_cutoff))
    )
    if searches or counters:
        record_by(
            db, Actor.system(), "retention.prune", "retention", now.date().isoformat(),
            after={
                "search_queries": searches, "search_queries_before": search_cutoff.isoformat(),
                "rate_limit_counters": counters,
                "rate_limit_counters_before": counter_cutoff.isoformat(),
            },
        )  # fmt: skip
    return searches + counters
