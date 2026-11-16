"""Fixed-window rate limits kept in PostgreSQL (blueprint F.3, H.2).

Each hit is counted in its own short transaction, on its own connection, so
the count survives even when the request it belongs to is rolled back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from markx.core.db import get_engine
from markx.core.errors import RateLimited

_HIT = text(
    """
    insert into rate_limit_counters (bucket, window_start, count)
    values (:bucket, :window_start, 1)
    on conflict (bucket, window_start)
    do update set count = rate_limit_counters.count + 1
    returning count
    """
)
_PEEK = text(
    "select count from rate_limit_counters where bucket = :bucket and window_start = :window_start"
)


def _window_start(now: datetime, window: timedelta) -> datetime:
    seconds = int(window.total_seconds())
    return datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, UTC)


def hit(bucket: str, limit: int, window: timedelta, *, now: datetime | None = None) -> int:
    """Count one event. Raises RateLimited once the limit is passed."""
    now = now or datetime.now(UTC)
    window_start = _window_start(now, window)
    with get_engine().begin() as connection:
        count = connection.execute(
            _HIT, {"bucket": bucket, "window_start": window_start}
        ).scalar_one()
    if count > limit:
        retry_after = int((window_start + window - now).total_seconds()) + 1
        raise RateLimited(
            "rate_limited",
            "Too many requests. Please wait and try again.",
            details={"retry_after_seconds": max(retry_after, 1)},
        )
    return int(count)


def current(bucket: str, window: timedelta, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    with get_engine().connect() as connection:
        count = connection.execute(
            _PEEK, {"bucket": bucket, "window_start": _window_start(now, window)}
        ).scalar_one_or_none()
    return int(count or 0)
