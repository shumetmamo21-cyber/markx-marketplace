"""A part with a recorded direct payment never ends undelivered without staff
(D-086): the buyer's cancel, the overdue-fulfilment job and "returned" are
refused, the database refuses the same ends, and the operations watch asks
staff to settle such parts with the shop. Nothing here moves money.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.core.db import session_scope
from markx.offers.models import InventoryReservation
from markx.ops import checks
from markx.orders import service
from markx.orders.models import Order, OrderItem, SellerOrder
from tests.bazaar import Bazaar
from tests.conftest import error_code
from tests.db.test_fulfilment_contention import Parcel

FAR_FUTURE = datetime.now(UTC) + timedelta(days=30)


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def _pay(bazaar: Bazaar, parcel: Parcel, method: str = "bank_transfer") -> None:
    paid = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/payment", json={"method": method}
    )
    assert paid.status_code == 200, paid.text


def _cancel(parcel: Parcel):  # type: ignore[no-untyped-def]
    return parcel.buyer.post(
        f"/me/orders/{parcel.order_id}/seller-orders/{parcel.so_id}/cancel", json={}
    )


def _can_cancel(parcel: Parcel) -> bool:
    order = parcel.buyer.get(f"/me/orders/{parcel.order_id}").json()
    return bool(order["seller_orders"][0]["can_cancel"])


def _code(db: Session, parcel: Parcel) -> str:
    db.rollback()
    return str(db.scalar(select(Order.code).where(Order.id == parcel.order_id)))


# -- the buyer ---------------------------------------------------------------------------


def test_the_buyer_cannot_cancel_a_part_they_have_paid_for(bazaar: Bazaar, db: Session) -> None:
    parcel = Parcel(db, bazaar, state="confirmed")
    assert _can_cancel(parcel) is True
    _pay(bazaar, parcel)
    assert _can_cancel(parcel) is False  # the page offers no button that would fail
    refused = _cancel(parcel)
    assert refused.status_code == 409
    assert error_code(refused) == "order_paid_contact_support"
    assert parcel.status(db) == "confirmed"  # kept as it was, stock still held


def test_an_unpaid_part_is_still_cancelled_as_before(bazaar: Bazaar, db: Session) -> None:
    parcel = Parcel(db, bazaar, state="confirmed")
    assert _cancel(parcel).status_code == 200
    assert parcel.status(db) == "cancelled"


# -- the overdue-fulfilment job -------------------------------------------------------------


def test_the_overdue_job_cancels_unpaid_parts_and_keeps_paid_ones(
    bazaar: Bazaar, db: Session
) -> None:
    unpaid = Parcel(db, bazaar, state="confirmed")
    paid = Parcel(db, bazaar, state="ready")
    _pay(bazaar, paid, "cash")
    with session_scope() as session:
        assert service.cancel_overdue_fulfilment(session, now=FAR_FUTURE) == 1
    assert unpaid.status(db) == "cancelled"
    assert paid.status(db) == "ready"
    held = db.scalars(
        select(InventoryReservation.status)
        .join(OrderItem, OrderItem.id == InventoryReservation.order_item_id)
        .where(OrderItem.seller_order_id == paid.so_id)
    ).all()
    assert held
    assert set(held) == {"held"}

    # Staff are told, by order code; "stuck hold" (a failing job) is not raised.
    db.rollback()
    findings = {f.key: f for f in checks.paid_orders_waiting(db, FAR_FUTURE)}
    assert set(findings) == {"orders.paid_past_hold"}
    assert findings["orders.paid_past_hold"].details == {
        "count": 1, "order_codes": [_code(db, paid)],
    }  # fmt: skip
    assert "orders.stuck_hold" not in {f.key for f in checks.stuck_orders(db, FAR_FUTURE)}


# -- "returned" ----------------------------------------------------------------------------


def test_a_paid_part_cannot_be_marked_returned(bazaar: Bazaar, db: Session) -> None:
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    _pay(bazaar, parcel, "telebirr")
    base = f"/seller/{bazaar.a_id}/orders/{parcel.so_id}"
    assert (
        bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Nobody home"}).status_code == 200
    )
    refused = bazaar.a.post(f"{base}/return", json={"reason": "Buyer unreachable twice"})
    assert refused.status_code == 409
    assert error_code(refused) == "paid_order_needs_staff"
    assert parcel.status(db) == "delivery_failed"
    # A retry is still possible.
    assert bazaar.a.post(f"{base}/dispatch", json={}).status_code == 200

    # Back to failed, and left for a day: staff are told.
    assert (
        bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Still nobody"}).status_code == 200
    )
    db.rollback()
    assert checks.paid_orders_waiting(db, datetime.now(UTC)) == []
    later = checks.paid_orders_waiting(db, datetime.now(UTC) + timedelta(days=2))
    assert [f.key for f in later] == ["orders.paid_delivery_failed"]
    assert later[0].details["order_codes"] == [_code(db, parcel)]


def test_an_unpaid_failed_part_still_goes_back_to_the_shop(bazaar: Bazaar, db: Session) -> None:
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    base = f"/seller/{bazaar.a_id}/orders/{parcel.so_id}"
    assert (
        bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Nobody home"}).status_code == 200
    )
    assert bazaar.a.post(f"{base}/return", json={"reason": "Buyer unreachable"}).status_code == 200
    assert parcel.status(db) == "returned"


# -- the database ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "end"),
    [
        ("confirmed", "cancelled"),
        ("confirmed", "expired"),
        ("ready", "cancelled"),
        ("delivery_failed", "returned"),
    ],
)
def test_the_database_refuses_a_paid_part_ending_undelivered(
    bazaar: Bazaar, db: Session, state: str, end: str
) -> None:
    """Each end from a state the life cycle allows it from, so the payment rule
    is what refuses it (declined is reachable only from placed, which cannot
    be paid)."""
    parcel = Parcel(db, bazaar, state="out_for_delivery" if state == "delivery_failed" else state)
    _pay(bazaar, parcel)
    if state == "delivery_failed":
        failed = bazaar.a.post(
            f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/delivery-failed", json={"reason": "Gone"}
        )
        assert failed.status_code == 200
    db.rollback()
    with pytest.raises(IntegrityError, match="ck_seller_orders_paid_order_not_ended_undelivered"):
        db.execute(update(SellerOrder).where(SellerOrder.id == parcel.so_id).values(status=end))
    db.rollback()
