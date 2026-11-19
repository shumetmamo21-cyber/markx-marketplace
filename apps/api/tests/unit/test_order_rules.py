"""The seller order life cycle, the derived order status and the response
deadline (blueprint G.6, D.11). Pure logic, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from markx.orders.deadlines import ADDIS_ABABA, response_deadline
from markx.orders.models import SellerOrderStatus as S
from markx.orders.status import (
    ALLOWED_MOVES,
    FINAL,
    OPEN,
    PAYABLE,
    contact_visible,
    derive_order_status,
    move_allowed,
)


def test_the_table_is_the_state_diagram_arrow_for_arrow() -> None:
    assert set(ALLOWED_MOVES) == set(S)
    assert sum(len(moves) for moves in ALLOWED_MOVES.values()) == 21
    assert {"declined", "expired", "cancelled", "returned", "completed", "refunded"} == FINAL
    assert set(S) == OPEN | FINAL
    assert not OPEN & FINAL


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        ("placed", "confirmed", True),
        ("placed", "declined", True),
        ("placed", "expired", True),
        ("placed", "cancelled", True),
        ("placed", "ready", False),
        ("placed", "delivered", False),
        ("confirmed", "placed", False),
        ("confirmed", "declined", False),
        ("declined", "confirmed", False),
        ("expired", "placed", False),
        ("completed", "refunded", False),
        ("delivery_failed", "out_for_delivery", True),
        ("placed", "placed", False),
        ("placed", "no_such_state", False),
        ("no_such_state", "placed", False),
    ],
)
def test_only_the_arrows_are_moves(current: str, new: str, allowed: bool) -> None:
    assert move_allowed(current, new) is allowed


@pytest.mark.parametrize(
    ("statuses", "derived"),
    [
        (["placed"], "placed"),
        (["confirmed", "confirmed"], "confirmed"),
        (["placed", "confirmed"], "awaiting_seller"),
        (["placed", "declined"], "awaiting_seller"),
        (["confirmed", "declined"], "in_progress"),
        (["ready", "out_for_delivery"], "in_progress"),
        (["delivered", "out_for_delivery"], "partly_delivered"),
        (["completed", "confirmed"], "partly_delivered"),
        (["completed", "declined"], "completed"),
        (["delivered", "expired", "cancelled"], "completed"),
        (["declined", "expired"], "cancelled"),
        (["cancelled", "declined", "expired"], "cancelled"),
    ],
)
def test_an_orders_status_is_read_off_its_seller_orders(statuses: list[str], derived: str) -> None:
    assert derive_order_status(statuses) == derived
    assert derive_order_status(reversed(statuses)) == derived


def test_an_order_without_seller_orders_is_a_bug() -> None:
    with pytest.raises(ValueError, match="at least one seller order"):
        derive_order_status([])


@pytest.mark.parametrize("status", list(S))
def test_phone_numbers_show_only_after_confirmation(status: S) -> None:
    """Blueprint C.5. Never before the seller confirms, and not for an order
    that ended without a handover."""
    assert contact_visible(status, confirmed=False) is False
    expected = status not in (S.DECLINED, S.EXPIRED, S.CANCELLED)
    assert contact_visible(status, confirmed=True) is expected


def _addis(hour: int, minute: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ADDIS_ABABA)


@pytest.mark.parametrize(
    ("placed", "due"),
    [
        (_addis(10, 0), _addis(10, 30)),  # in the middle of the day
        (_addis(8, 0), _addis(8, 30)),  # the moment the shops open
        (_addis(19, 30), _addis(20, 0)),  # ends exactly at closing
        (_addis(19, 45), _addis(8, 15, day=21)),  # 15 minutes today, 15 tomorrow
        (_addis(20, 0), _addis(8, 30, day=21)),  # at closing time
        (_addis(23, 0), _addis(8, 30, day=21)),  # at night
        (_addis(3, 0), _addis(8, 30)),  # before opening, the same day
    ],
)
def test_the_response_window_counts_business_hours_only(placed: datetime, due: datetime) -> None:
    deadline = response_deadline(placed, window_minutes=30, open_hour=8, close_hour=20)
    assert deadline == due
    assert deadline.tzinfo is UTC


def test_a_window_longer_than_a_business_day_spans_days() -> None:
    # 12 open hours a day; 25 hours of window from 10:00 is two full days and an hour.
    deadline = response_deadline(_addis(10), window_minutes=25 * 60, open_hour=8, close_hour=20)
    assert deadline == _addis(11, day=22)


def test_a_utc_time_is_read_in_addis_ababa_time() -> None:
    placed = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)  # 23:00 in Addis Ababa
    deadline = response_deadline(placed, window_minutes=30, open_hour=8, close_hour=20)
    assert deadline == datetime(2026, 11, 21, 5, 30, tzinfo=UTC)


def test_opening_hours_that_make_no_sense_mean_always_open() -> None:
    placed = _addis(23)
    for open_hour, close_hour in ((20, 8), (9, 9)):
        deadline = response_deadline(
            placed, window_minutes=30, open_hour=open_hour, close_hour=close_hour
        )
        assert deadline == placed + timedelta(minutes=30)


def test_bad_input_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        response_deadline(datetime(2026, 11, 20, 10), window_minutes=30, open_hour=8, close_hour=20)
    with pytest.raises(ValueError, match="longer than zero"):
        response_deadline(_addis(10), window_minutes=0, open_hour=8, close_hour=20)


def test_a_payment_is_recorded_only_from_the_handover_on() -> None:
    """F-09, option 2 (D-087): never in advance; the web app's copy of this
    list (SellerOrderActions.tsx) must say the same."""
    assert {S.DELIVERED, S.COMPLETED, S.DISPUTED} == PAYABLE
