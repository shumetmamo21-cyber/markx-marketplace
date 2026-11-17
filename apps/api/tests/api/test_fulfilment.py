"""From confirmed to completed (blueprint G.6, G.7, J.9, J.10, P10)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.audit.models import AuditLog
from markx.delivery.models import Shipment, TrackingEvent
from markx.offers.models import InventoryMovement, InventoryReservation
from markx.orders.models import OrderStatusEvent, SellerOrder
from markx.payments.models import CommissionRule, FeeCharge, PaymentAttempt, PaymentIntent
from markx.worker.runner import run_once
from tests.api.test_checkout import _part, _two_seller_order
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _confirmed(bazaar: Bazaar) -> tuple[ApiClient, dict[str, Any], str, str]:
    buyer, _, order = _two_seller_order(bazaar)
    a_id, b_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{a_id}/confirm").status_code == 200
    assert bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{b_id}/confirm").status_code == 200
    return buyer, order, a_id, b_id


def _mine(buyer: ApiClient, order: dict[str, Any], store: str) -> dict[str, Any]:
    return _part(buyer.get(f"/me/orders/{order['id']}").json(), store)


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def _tracking(db: DbSession, seller_order_id: str) -> list[str]:
    db.rollback()
    return list(
        db.scalars(
            select(TrackingEvent.status)
            .join(Shipment, Shipment.id == TrackingEvent.shipment_id)
            .where(Shipment.seller_order_id == uuid.UUID(seller_order_id))
            .order_by(TrackingEvent.occurred_at, TrackingEvent.id)
        )
    )


def _moves(db: DbSession, seller_order_id: str) -> list[tuple[str, str]]:
    db.rollback()
    return [
        (e.to_status, e.actor_type)
        for e in db.scalars(
            select(OrderStatusEvent)
            .where(OrderStatusEvent.seller_order_id == uuid.UUID(seller_order_id))
            .order_by(OrderStatusEvent.occurred_at, OrderStatusEvent.id)
        )
    ]


# -- P10 criterion 1 --------------------------------------------------------------------


def test_a_two_seller_order_completes_end_to_end(bazaar: Bazaar, db: DbSession) -> None:
    """Alpha delivers by rider and the buyer closes it; Beta is collected at
    the shop and the worker closes it when the problem window passes."""
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(bazaar.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    buyer, order, a_id, b_id = _confirmed(bazaar)
    alpha, beta = f"/seller/{bazaar.a_id}/orders/{a_id}", f"/seller/{bazaar.b_id}/orders/{b_id}"
    assert _mine(buyer, order, "alpha")["handover_code"] is None  # not before it is on its way

    ready = bazaar.a.post(f"{alpha}/ready")
    assert ready.status_code == 200, ready.text
    assert (ready.json()["status"], ready.json()["delivery_status"]) == ("ready", "ready")
    code = _mine(buyer, order, "alpha")["handover_code"]
    assert re.fullmatch(r"[0-9]{6}", code)
    # A rider order is handed over on the road, so it must be dispatched first.
    assert error_code(bazaar.a.post(f"{alpha}/deliver", json={"code": code})) == (
        "order_not_dispatched"
    )
    out = bazaar.a.post(
        f"{alpha}/dispatch", json={"rider_name": "Dawit", "rider_phone": "0911777001"}
    )
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "out_for_delivery"
    mine = _mine(buyer, order, "alpha")
    assert (mine["rider_name"], mine["rider_phone"]) == ("Dawit", "+251911777001")
    assert mine["handover_code"] == code  # the same code all the way

    wrong = bazaar.a.post(f"{alpha}/deliver", json={"code": _wrong(code)})
    assert wrong.status_code == 403
    assert error_code(wrong) == "handover_code_wrong"
    assert wrong.json()["error"]["details"] == {"attempts_left": 4}
    assert bazaar.a.get(alpha).json()["handover_attempts"] == 1  # kept although the request failed
    delivered = bazaar.a.post(f"{alpha}/deliver", json={"code": code})
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"
    assert delivered.json()["delivered_at"] is not None
    mine = _mine(buyer, order, "alpha")
    assert (mine["can_confirm_receipt"], mine["handover_code"]) == (True, None)
    window = datetime.fromisoformat(mine["problem_window_ends_at"])
    assert window - datetime.fromisoformat(mine["delivered_at"]) == timedelta(hours=72)
    assert stock(db, bazaar.a128["id"]) == (5, 2)  # still held until completion

    paid = bazaar.a.post(f"{alpha}/payment", json={"method": "telebirr"})
    assert paid.status_code == 200, paid.text
    assert (paid.json()["paid_method"], paid.json()["paid_at"] is not None) == ("telebirr", True)
    intent = db.scalar(
        select(PaymentIntent).where(PaymentIntent.seller_order_id == uuid.UUID(a_id))
    )
    assert intent is not None
    assert (intent.status, intent.method, intent.settled_at is not None) == (
        "succeeded",
        "telebirr",
        True,
    )
    assert db.scalar(
        select(PaymentAttempt.status).where(PaymentAttempt.intent_id == intent.id)
    ) == ("succeeded")
    assert _mine(buyer, order, "alpha")["paid_method"] == "telebirr"

    done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{a_id}/confirm-receipt")
    assert done.status_code == 200, done.text
    assert _part(done.json(), "alpha")["status"] == "completed"
    assert _part(done.json(), "alpha")["completed_at"] is not None
    # The held stock left the shop; the fee is 3% of the goods, never of delivery.
    assert stock(db, bazaar.a128["id"]) == (3, 0)
    assert (
        db.scalar(
            select(InventoryReservation.status).where(
                InventoryReservation.offer_id == uuid.UUID(bazaar.a128["id"])
            )
        )
        == "committed"
    )
    fee = db.scalar(select(FeeCharge).where(FeeCharge.seller_order_id == uuid.UUID(a_id)))
    assert fee is not None
    assert (fee.item_value_santim, fee.amount_santim, fee.cap_applied) == (
        3_700_000,
        111_000,
        False,
    )
    assert bazaar.a.get(alpha).json()["fee_charged_santim"] == 111_000
    assert [m.reason for m in db.scalars(
        select(InventoryMovement).where(InventoryMovement.offer_id == uuid.UUID(bazaar.a128["id"]))
        .order_by(InventoryMovement.created_at)
    )] == ["initial", "reserve", "commit"]  # fmt: skip
    assert _moves(db, a_id) == [
        ("placed", "buyer"), ("confirmed", "seller"), ("ready", "seller"),
        ("out_for_delivery", "seller"), ("delivered", "seller"), ("completed", "buyer"),
    ]  # fmt: skip
    assert _tracking(db, a_id) == ["ready", "out_for_delivery", "delivered"]

    # Beta: collected at the shop, closed by the clock.
    assert bazaar.b.post(f"{beta}/ready").status_code == 200
    assert error_code(bazaar.b.post(f"{beta}/dispatch", json={})) == "collection_is_not_dispatched"
    code_b = _mine(buyer, order, "beta")["handover_code"]
    assert code_b != code
    assert bazaar.b.post(f"{beta}/deliver", json={"code": code_b}).json()["status"] == "delivered"
    ends = datetime.fromisoformat(_mine(buyer, order, "beta")["problem_window_ends_at"])
    early = {o.name: o.result for o in run_once(ends - timedelta(seconds=1)).jobs}
    assert early["orders.complete_delivered"] == 0
    late = {o.name: o.result for o in run_once(ends + timedelta(minutes=6)).jobs}
    assert late["orders.complete_delivered"] == 1
    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert mine["status"] == "completed"
    assert _part(mine, "beta")["events"][-1]["actor_type"] == "system"
    assert stock(db, bazaar.b128["id"]) == (4, 0)
    assert _tracking(db, b_id) == ["ready", "delivered"]
    assert (
        db.scalar(
            select(FeeCharge.amount_santim).where(FeeCharge.seller_order_id == uuid.UUID(b_id))
        )
        == 53_700
    )
    assert_stock_is_consistent(db)
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 2


# -- the handover code (C-15) ----------------------------------------------------------


def test_the_code_is_the_buyers_alone_and_locks_after_five_wrong_tries(
    bazaar: Bazaar, db: DbSession
) -> None:
    buyer, order, a_id, _ = _confirmed(bazaar)
    alpha = f"/seller/{bazaar.a_id}/orders/{a_id}"
    bazaar.a.post(f"{alpha}/ready")
    bazaar.a.post(f"{alpha}/dispatch", json={})
    code = _mine(buyer, order, "alpha")["handover_code"]
    other, _ = bazaar.buyer()
    assert other.get(f"/me/orders/{order['id']}").status_code == 404
    assert code not in bazaar.a.get(alpha).text  # the seller never sees it
    assert code not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders").text

    for attempt in range(5):
        wrong = bazaar.a.post(f"{alpha}/deliver", json={"code": _wrong(code)})
        assert error_code(wrong) == "handover_code_wrong"
        assert wrong.json()["error"]["details"] == {"attempts_left": 4 - attempt}
    for tried in (_wrong(code), code):
        locked = bazaar.a.post(f"{alpha}/deliver", json={"code": tried})
        assert locked.status_code == 403
        assert error_code(locked) == "handover_locked"
    assert bazaar.a.get(alpha).json()["status"] == "out_for_delivery"
    assert bazaar.a.get(alpha).json()["handover_attempts"] == 5
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "shipment.handover_code_wrong")
        )
        == 5
    )
    assert bazaar.a.post(f"{alpha}/deliver", json={"code": "12345"}).status_code == 422
    assert stock(db, bazaar.a128["id"]) == (5, 2)


def test_a_failed_delivery_is_retried_or_returned(bazaar: Bazaar, db: DbSession) -> None:
    buyer, order, a_id, _ = _confirmed(bazaar)
    alpha = f"/seller/{bazaar.a_id}/orders/{a_id}"
    bazaar.a.post(f"{alpha}/ready")
    bazaar.a.post(f"{alpha}/dispatch", json={"rider_name": "Dawit"})
    failed = bazaar.a.post(f"{alpha}/delivery-failed", json={"reason": "Nobody at the gate"})
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "delivery_failed"
    assert _mine(buyer, order, "alpha")["delivery_status"] == "delivery_failed"
    assert error_code(bazaar.a.post(f"{alpha}/deliver", json={"code": "123456"})) == (
        "order_not_deliverable"
    )
    # Retry.
    assert bazaar.a.post(f"{alpha}/dispatch", json={}).json()["status"] == "out_for_delivery"
    bazaar.a.post(f"{alpha}/delivery-failed", json={"reason": "Phone switched off"})
    returned = bazaar.a.post(f"{alpha}/return", json={"reason": "Buyer unreachable twice"})
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "returned"
    assert returned.json()["closed_reason"] == "Buyer unreachable twice"
    assert stock(db, bazaar.a128["id"]) == (5, 0)  # the stock is back on the shelf
    assert stock(db, bazaar.b128["id"]) == (5, 1)
    assert_stock_is_consistent(db)
    assert _tracking(db, a_id) == [
        "ready", "out_for_delivery", "delivery_failed", "out_for_delivery", "delivery_failed",
        "returned",
    ]  # fmt: skip
    assert [m for m, _ in _moves(db, a_id)] == [
        "placed", "confirmed", "ready", "out_for_delivery", "delivery_failed", "out_for_delivery",
        "delivery_failed", "returned",
    ]  # fmt: skip
    assert (
        db.scalar(
            select(PaymentIntent.status).where(PaymentIntent.seller_order_id == uuid.UUID(a_id))
        )
        == "cancelled"
    )
    assert error_code(bazaar.a.post(f"{alpha}/payment", json={"method": "cash"})) == (
        "order_not_payable"
    )
    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert mine["status"] == "in_progress"  # Beta's part is still confirmed
    assert _part(mine, "alpha")["seller_contact"] is not None  # it was handed to a rider once


# -- only the arrows ------------------------------------------------------------------


def test_moves_out_of_order_are_refused_at_every_step(bazaar: Bazaar, db: DbSession) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    a_id = _part(order, "alpha")["id"]
    alpha = f"/seller/{bazaar.a_id}/orders/{a_id}"
    me = f"/me/orders/{order['id']}/seller-orders/{a_id}"
    assert error_code(bazaar.a.post(f"{alpha}/ready")) == "order_move_not_allowed"
    assert error_code(bazaar.a.post(f"{alpha}/deliver", json={"code": "123456"})) == (
        "order_not_deliverable"
    )
    assert error_code(bazaar.a.post(f"{alpha}/payment", json={"method": "cash"})) == (
        "order_not_payable"
    )
    assert error_code(buyer.post(f"{me}/confirm-receipt")) == "order_not_delivered"

    bazaar.a.post(f"{alpha}/confirm")
    bazaar.a.post(f"{alpha}/ready")
    assert error_code(buyer.post(f"{me}/cancel", json={})) == "order_cannot_be_cancelled"
    assert error_code(bazaar.a.post(f"{alpha}/return", json={"reason": "Changed my mind"})) == (
        "order_move_not_allowed"
    )
    assert error_code(bazaar.a.post(f"{alpha}/delivery-failed", json={"reason": "Not yet"})) == (
        "order_move_not_allowed"
    )
    assert error_code(bazaar.a.post(f"{alpha}/decline", json={"reason": "Too late"})) == (
        "order_not_awaiting_response"
    )
    assert bazaar.a.post(f"{alpha}/payment", json={"method": "cash"}).status_code == 200
    assert error_code(bazaar.a.post(f"{alpha}/payment", json={"method": "cash"})) == "already_paid"
    # Another seller's part, and another buyer, are not found.
    b_id = _part(order, "beta")["id"]
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{b_id}/ready").status_code == 404
    other, _ = bazaar.buyer()
    assert other.post(f"{me}/confirm-receipt").status_code == 404
    assert db.scalar(select(SellerOrder.status).where(SellerOrder.id == uuid.UUID(a_id))) == "ready"
    assert stock(db, bazaar.a128["id"]) == (5, 2)
