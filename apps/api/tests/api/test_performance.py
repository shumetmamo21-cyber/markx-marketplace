"""A store's performance in numbers and its weekly message (blueprint D.4,
S-17, S-26, K.5; D-069): exact counts from real orders, readable by every
member and nobody else, one message per store and week, Monday to Sunday in
Addis Ababa time, never sent twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.core import settings_store
from markx.core.db import session_scope
from markx.notifications.models import Notification
from markx.orders.deadlines import ADDIS_ABABA
from markx.performance import service as performance
from markx.performance.models import SellerWeeklyReport
from tests.api.test_reviews import Bought
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout

PROBLEM = {"problem_type": "not_as_described", "description": "The box says 128 GB, the phone 64."}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _alpha_week(bazaar: Bazaar) -> None:
    """Alpha: one order completed, one declined, one with a reported problem."""
    Bought(bazaar, [(bazaar.a128, 1)])
    declined_buyer, address_id = bazaar.buyer()
    add_to_cart(declined_buyer, bazaar.a256["id"], 1)
    placed = checkout(declined_buyer, address_id, {"alpha": "shop_collection"}).json()
    part = placed["seller_orders"][0]["id"]
    declined = bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{part}/decline",
                             json={"reason": "out_of_stock"})  # fmt: skip
    assert declined.status_code == 200, declined.text
    problem = Bought(bazaar, [(bazaar.a128, 1)], complete=False)
    so_id = problem.order["seller_orders"][0]["id"]
    reported = problem.buyer.post(
        f"/me/orders/{problem.order['id']}/seller-orders/{so_id}/problem", json=PROBLEM
    )
    assert reported.status_code == 200, reported.text


def test_the_performance_page_counts_what_really_happened(bazaar: Bazaar) -> None:
    _alpha_week(bazaar)
    page = bazaar.a.get(f"/seller/{bazaar.a_id}/performance", params={"days": 1})
    assert page.status_code == 200, page.text
    numbers = page.json()
    assert {k: numbers[k] for k in (
        "orders_received", "orders_confirmed", "orders_declined", "orders_unanswered",
        "delivered", "completed", "completed_value_santim", "problems_reported",
        "delivery_failed", "active_offers",
    )} == {
        "orders_received": 3, "orders_confirmed": 2, "orders_declined": 1,
        "orders_unanswered": 0, "delivered": 2, "completed": 1,
        "completed_value_santim": 1_850_000, "problems_reported": 1, "delivery_failed": 0,
        "active_offers": 2,
    }  # fmt: skip
    assert numbers["confirmation_share"] == 0.6667
    assert numbers["delivery_success_share"] == 1.0
    assert numbers["median_minutes_to_confirm"] is not None
    # Beta's page knows nothing of Alpha's orders, and Beta cannot read Alpha's.
    beta = bazaar.b.get(f"/seller/{bazaar.b_id}/performance").json()
    assert (beta["orders_received"], beta["completed"]) == (0, 0)
    assert error_code(bazaar.b.get(f"/seller/{bazaar.a_id}/performance")) == "seller_not_found"
    assert ApiClient().get(f"/seller/{bazaar.a_id}/performance").status_code == 401
    assert (
        bazaar.a.get(f"/seller/{bazaar.a_id}/performance", params={"days": 91}).status_code == 422
    )


def test_the_weekly_message_goes_once_to_every_trading_store(bazaar: Bazaar, db: DbSession) -> None:
    _alpha_week(bazaar)
    next_week = datetime.now(UTC) + timedelta(days=7)
    week = performance.last_complete_week(next_week)
    with session_scope() as session:
        assert performance.send_weekly_reports(session, next_week) == 2  # Alpha and Beta
    with session_scope() as session:
        assert performance.send_weekly_reports(session, next_week) == 0  # never twice
    db.rollback()
    assert db.scalar(select(func.count()).select_from(SellerWeeklyReport)) == 2

    reports = bazaar.a.get(f"/seller/{bazaar.a_id}/weekly-reports").json()
    (alpha,) = reports
    assert alpha["week_start"] == week.isoformat()
    assert (alpha["figures"]["orders_received"], alpha["figures"]["completed"]) == (3, 1)
    # Each store reads only its own.
    assert error_code(bazaar.b.get(f"/seller/{bazaar.a_id}/weekly-reports")) == "seller_not_found"
    (beta,) = bazaar.b.get(f"/seller/{bazaar.b_id}/weekly-reports").json()
    assert beta["figures"]["orders_received"] == 0

    told = db.scalars(
        select(Notification).where(Notification.template == "seller.weekly_report")
    ).all()
    assert len(told) == 2  # each store's owner
    alpha_note = next(n for n in told if n.params["seller_id"] == bazaar.a_id)
    assert alpha_note.params["orders_received"] == 3
    assert alpha_note.params["completed_value_santim"] == 1_850_000
    assert "0911" not in str(alpha_note.params)


def test_no_message_for_a_suspended_store_or_when_switched_off(
    bazaar: Bazaar, db: DbSession
) -> None:
    suspended = bazaar.staff.post(f"/admin/sellers/{bazaar.b_id}/suspend",
                                  json={"reason": "Fake documents"})  # fmt: skip
    assert suspended.status_code == 200, suspended.text
    next_week = datetime.now(UTC) + timedelta(days=7)
    settings_store.set_setting(db, "sellers.weekly_report_enabled", False)
    db.commit()
    with session_scope() as session:
        assert performance.send_weekly_reports(session, next_week) == 0
    settings_store.set_setting(db, "sellers.weekly_report_enabled", True)
    db.commit()
    with session_scope() as session:
        assert performance.send_weekly_reports(session, next_week) == 1
    db.rollback()
    (only,) = db.scalars(select(SellerWeeklyReport.seller_id))
    assert only == uuid.UUID(bazaar.a_id)
    # A store that did not exist during the week gets nothing for it.
    with session_scope() as session:
        assert performance.send_weekly_reports(session, datetime.now(UTC)) == 0


def test_weeks_run_monday_to_sunday_in_addis_ababa() -> None:
    monday_morning = datetime(2026, 11, 23, 0, 30, tzinfo=ADDIS_ABABA)
    sunday_night = datetime(2026, 11, 22, 23, 59, tzinfo=ADDIS_ABABA)
    assert performance.last_complete_week(monday_morning) == date(2026, 11, 16)
    assert performance.last_complete_week(sunday_night) == date(2026, 11, 9)
    # 21:30 UTC on Sunday is already Monday in Addis Ababa.
    assert performance.last_complete_week(datetime(2026, 11, 22, 21, 30, tzinfo=UTC)) == date(
        2026, 11, 16
    )
    start, end = performance.week_bounds(date(2026, 11, 16))
    assert (start, end - start) == (datetime(2026, 11, 15, 21, 0, tzinfo=UTC), timedelta(days=7))


def test_the_store_page_shows_its_track_record(bazaar: Bazaar) -> None:
    """Blueprint D.4 and I.5: a store page shows confirmation speed and
    delivery success, from the performance figures (D-080)."""
    page = ApiClient().get("/catalog/stores/beta").json()
    assert (page["figures_days"], page["confirmation_share"], page["delivery_success_share"]) == (
        90, None, None,
    )  # fmt: skip
    assert page["median_minutes_to_confirm"] is None  # no order yet: nothing to count

    Bought(bazaar, [(bazaar.a128, 1)])
    page = ApiClient().get("/catalog/stores/alpha").json()
    assert page["confirmation_share"] == 1.0
    assert page["delivery_success_share"] == 1.0
    assert page["median_minutes_to_confirm"] is not None
    assert page["median_minutes_to_confirm"] >= 0
