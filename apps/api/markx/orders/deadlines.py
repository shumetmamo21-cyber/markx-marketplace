"""When a seller must answer by (blueprint D.11, C-09). Pure, no database.

The response window counts business hours only, in Addis Ababa time: an order
placed at night is due some minutes after the shops open, not at 3 a.m.
Ethiopia keeps UTC+3 all year, so a fixed offset is exact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

ADDIS_ABABA = timezone(timedelta(hours=3), "EAT")


def response_deadline(
    placed_at: datetime, *, window_minutes: int, open_hour: int, close_hour: int
) -> datetime:
    """`window_minutes` of open time after `placed_at`. Returns UTC.

    If the opening hours are not a real span (closing not after opening), the
    business day is taken to be the whole day.
    """
    if placed_at.tzinfo is None:
        raise ValueError("placed_at must carry a time zone")
    if window_minutes <= 0:
        raise ValueError("the response window must be longer than zero")
    remaining = timedelta(minutes=window_minutes)
    if not 0 <= open_hour < close_hour <= 24:
        return (placed_at + remaining).astimezone(UTC)

    moment = placed_at.astimezone(ADDIS_ABABA)
    while True:
        midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        opens = midnight + timedelta(hours=open_hour)
        closes = midnight + timedelta(hours=close_hour)
        if moment < opens:
            moment = opens
        if moment >= closes:
            moment = midnight + timedelta(days=1, hours=open_hour)
            continue
        if moment + remaining <= closes:
            return (moment + remaining).astimezone(UTC)
        remaining -= closes - moment
        moment = midnight + timedelta(days=1, hours=open_hour)
