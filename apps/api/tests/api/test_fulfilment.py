"""The second half of the order life cycle (blueprint G.6, G.7, G.9, J.9, J.10,
D.12, P10): ready, dispatch, the handover code, delivered, completed, failed
deliveries and returns, the direct payment record, and the fee.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.delivery.models import MAX_HANDOVER_ATTEMPTS, Shipment, TrackingEvent
from markx.notifications.models import Notification
from markx.offers.models import InventoryReservation
from markx.orders import service
from markx.orders.models import OrderStatusEvent, SellerOrder
from markx.payments.models import (
    CommissionRule,
    FeeCharge,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentIntent,
)
from markx.worker.runner import run_once
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, staff_client


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _two_seller_order(bazaar: Bazaar) -> tuple[ApiClient, str, dict[str, Any]]:
    """Alpha by rider (two units of the 128 GB), Beta collected (one unit)."""
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 2)
    add_to_cart(buyer, bazaar.b128["id"], 1)
    response = checkout(buyer, address_id, {"alpha": "seller_rider", "beta": "shop_collection"})
    assert response.status_code == 201, response.text
    return buyer, address_id, dict(response.json())


def _part(order: dict[str, Any], store: str) -> dict[str, Any]:
    return next(so for so in order["seller_orders"] if so["store_slug"] == store)


def _mine(buyer: ApiClient, order_id: str) -> dict[str, Any]:
    response = buyer.get(f"/me/orders/{order_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def _confirm(bazaar: Bazaar, order: dict[str, Any]) -> tuple[str, str]:
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm").status_code == 200
    assert bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{beta_id}/confirm").status_code == 200
    return alpha_id, beta_id


def _dispatched_alpha(bazaar: Bazaar) -> tuple[ApiClient, dict[str, Any], str, str]:
    """Alpha's part out for delivery; the buyer's code from their order page."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, _ = _confirm(bazaar, order)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{base}/ready").status_code == 200
    assert bazaar.a.post(f"{base}/dispatch", json={"rider_name": "Dawit"}).status_code == 200
    code = _part(_mine(buyer, order["id"]), "alpha")["handover_code"]
    assert code is not None
    return buyer, order, alpha_id, code


# -- P10 criterion 1 ----------------------------------------------------------------------


def test_a_two_seller_order_completes_end_to_end(bazaar: Bazaar, db: DbSession) -> None:
    """Placed to completed for both parts: Alpha by rider with the buyer's
    confirmation, Beta collected at the shop with the worker closing the
    problem window. The stock leaves the shelf only at completion."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _confirm(bazaar, order)
    a, b = f"/seller/{bazaar.a_id}/orders/{alpha_id}", f"/seller/{bazaar.b_id}/orders/{beta_id}"
    mine = _mine(buyer, order["id"])
    assert {so["handover_code"] for so in mine["seller_orders"]} == {None}  # not before ready

    # Alpha packs and sends its rider.
    ready = bazaar.a.post(f"{a}/ready")
    assert ready.status_code == 200, ready.text
    assert (ready.json()["status"], ready.json()["shipment"]["status"]) == ("ready", "ready")
    assert ready.json()["ready_at"] is not None
    assert buyer.post(
        f"/me/orders/{order['id']}/seller-orders/{alpha_id}/cancel", json={}
    ).status_code == 409  # fmt: skip
    sent = bazaar.a.post(f"{a}/dispatch", json={"rider_name": "Dawit", "rider_phone": "0922000111"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "out_for_delivery"
    assert sent.json()["shipment"]["rider_phone"] == "+251922000111"
    assert sent.json()["shipment"]["dispatched_at"] is not None
    assert "handover_code" not in sent.text  # the seller never sees the code
    assert sent.json()["handover_attempts_left"] == MAX_HANDOVER_ATTEMPTS

    mine = _mine(buyer, order["id"])
    alpha = _part(mine, "alpha")
    code = alpha["handover_code"]
    assert code is not None
    assert len(code) == 6
    assert code.isdigit()
    assert alpha["shipment"]["rider_name"] == "Dawit"  # the rider's contact, once on the way
    assert alpha["shipment"]["rider_phone"] == "+251922000111"
    assert [e["status"] for e in alpha["shipment"]["events"]] == ["ready", "out_for_delivery"]
    assert mine["status"] == "in_progress"
    # The code is the same every time the page is opened, and derived: no
    # column anywhere holds it.
    assert _part(_mine(buyer, order["id"]), "alpha")["handover_code"] == code
    shipment = db.scalar(select(Shipment).where(Shipment.seller_order_id == uuid.UUID(alpha_id)))
    assert shipment is not None
    assert code not in str({c.name: getattr(shipment, c.name) for c in Shipment.__table__.columns})

    # At the door: the buyer gives the code; the rider enters it.
    handed = bazaar.a.post(f"{a}/handover", json={"code": code})
    assert handed.status_code == 200, handed.text
    assert handed.json()["status"] == "delivered"
    assert handed.json()["delivered_at"] is not None
    window_end = datetime.fromisoformat(handed.json()["problem_window_ends_at"])
    assert timedelta(hours=71) < window_end - datetime.now(UTC) <= timedelta(hours=72)
    alpha = _part(_mine(buyer, order["id"]), "alpha")
    assert alpha["handover_code"] is None  # spent
    assert alpha["can_confirm_received"] is True
    assert stock(db, bazaar.a128["id"]) == (5, 2)  # still held until completion

    # The buyer paid the rider in cash; the seller records it.
    paid = bazaar.a.post(f"{a}/payment", json={"method": "telebirr"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["paid_method"] == "telebirr"
    assert paid.json()["paid_at"] is not None

    # The buyer confirms the goods: Alpha's part completes at once.
    done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{alpha_id}/confirm-received")
    assert done.status_code == 200, done.text
    alpha = _part(done.json(), "alpha")
    assert alpha["status"] == "completed"
    assert alpha["completed_at"] is not None
    assert alpha["paid_method"] == "telebirr"
    assert stock(db, bazaar.a128["id"]) == (3, 0)  # two units left the shop
    assert bazaar.a.get(a).json()["fee_santim"] == 0

    # Beta: collected at the counter, then the problem window passes.
    assert bazaar.b.post(f"{b}/ready").status_code == 200
    assert error_code(bazaar.b.post(f"{b}/dispatch", json={})) == "collection_order"
    beta_code = _part(_mine(buyer, order["id"]), "beta")["handover_code"]
    assert beta_code is not None
    assert beta_code != code
    collected = bazaar.b.post(f"{b}/handover", json={"code": beta_code})
    assert collected.status_code == 200, collected.text
    assert collected.json()["status"] == "delivered"
    # Both parts handed over, none still moving: the parent reads completed (D-038).
    assert _mine(buyer, order["id"])["status"] == "completed"
    beta_window = datetime.fromisoformat(collected.json()["problem_window_ends_at"])
    jobs = {o.name: o.result for o in run_once(beta_window - timedelta(minutes=1)).jobs}
    assert jobs["orders.complete_after_problem_window"] == 0
    jobs = {o.name: o.result for o in run_once(beta_window + timedelta(minutes=5)).jobs}
    assert jobs["orders.complete_after_problem_window"] == 1

    mine = _mine(buyer, order["id"])
    assert mine["status"] == "completed"
    assert {so["status"] for so in mine["seller_orders"]} == {"completed"}
    assert [(e["to_status"], e["actor_type"]) for e in _part(mine, "alpha")["events"]] == [
        ("placed", "buyer"), ("confirmed", "seller"), ("ready", "seller"),
        ("out_for_delivery", "seller"), ("delivered", "seller"), ("completed", "buyer"),
    ]  # fmt: skip
    assert [(e["to_status"], e["actor_type"]) for e in _part(mine, "beta")["events"]] == [
        ("placed", "buyer"), ("confirmed", "seller"), ("ready", "seller"),
        ("delivered", "seller"), ("completed", "system"),
    ]  # fmt: skip
    assert [e["status"] for e in _part(mine, "beta")["shipment"]["events"]] == [
        "ready", "delivered",
    ]  # fmt: skip
    # The stock: committed through `commit_stock`, the trail replays exactly.
    assert stock(db, bazaar.a128["id"]) == (3, 0)
    assert stock(db, bazaar.b128["id"]) == (4, 0)
    assert Counter(db.scalars(select(InventoryReservation.status))) == {"committed": 2}
    assert_stock_is_consistent(db)
    # One fee charge per part, zero today (D.19), and nothing in the ledger for a zero.
    charges = list(db.scalars(select(FeeCharge)))
    assert {(c.seller_order_id, c.item_value_santim, c.amount_santim) for c in charges} == {
        (uuid.UUID(alpha_id), 3_700_000, 0), (uuid.UUID(beta_id), 1_790_000, 0),
    }  # fmt: skip
    assert db.scalar(select(func.count()).select_from(LedgerTransaction)) == 0
    assert Counter(db.scalars(select(PaymentIntent.status))) == {"succeeded": 1, "pending": 1}
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.ready"] == 1
    assert templates["order.ready_for_collection"] == 1
    assert templates["order.out_for_delivery"] == 1
    assert templates["order.delivered"] == 2
    assert templates["order.payment_recorded"] == 1
    assert templates["order.completed"] == 2
    assert templates["order.completed_for_seller"] == 2
    # Every tracking event names a source, never a person, on the buyer's page.
    assert db.scalar(select(func.count()).select_from(TrackingEvent)) == 5
    assert "actor_user_id" not in str(mine)


# -- the handover code ------------------------------------------------------------------


def test_wrong_codes_lock_the_shipment_until_staff_reissue(bazaar: Bazaar, db: DbSession) -> None:
    """D.13: wrong attempts are limited. After `MAX_HANDOVER_ATTEMPTS` even
    the right code is refused, until staff issue a new one; the old code is
    then dead."""
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for attempt in range(1, MAX_HANDOVER_ATTEMPTS + 1):
        response = bazaar.a.post(f"{base}/handover", json={"code": wrong})
        assert response.status_code == 409, response.text
        left = MAX_HANDOVER_ATTEMPTS - attempt
        assert error_code(response) == (
            "handover_code_locked" if left == 0 else "handover_code_wrong"
        )
        assert response.json()["error"]["details"]["attempts_left"] == left
        # The count survives the failed request (as for login codes).
        assert bazaar.a.get(base).json()["handover_attempts_left"] == left
    assert bazaar.a.get(base).json()["status"] == "out_for_delivery"
    locked = bazaar.a.post(f"{base}/handover", json={"code": code})
    assert error_code(locked) == "handover_code_locked"
    # A code of the wrong shape never reaches the counter.
    assert bazaar.a.post(f"{base}/handover", json={"code": "12345"}).status_code == 422

    # Staff issue a new code, with a reason, in the audit log.
    reissued = bazaar.staff.post(
        f"/admin/orders/seller-orders/{alpha_id}/reissue-code", json={"reason": "Buyer locked out"}
    )
    assert reissued.status_code == 200, reissued.text
    assert _part(reissued.json(), "alpha")["handover_code"] is None  # staff never see it
    new_code = _part(_mine(buyer, order["id"]), "alpha")["handover_code"]
    assert new_code is not None
    assert new_code != code
    assert bazaar.a.get(base).json()["handover_attempts_left"] == MAX_HANDOVER_ATTEMPTS
    assert (
        error_code(bazaar.a.post(f"{base}/handover", json={"code": code})) == "handover_code_wrong"
    )
    assert (
        bazaar.a.post(f"{base}/handover", json={"code": new_code}).json()["status"] == "delivered"
    )
    audit = list(
        db.scalars(select(AuditLog).where(AuditLog.action == "shipment.reissue_handover_code"))
    )
    assert len(audit) == 1
    assert (audit[0].before, audit[0].after) == (
        {"code_version": 1}, {"code_version": 2, "reason": "Buyer locked out"},
    )  # fmt: skip
    # A delivered order has no code to reissue.
    assert (
        error_code(
            bazaar.staff.post(
                f"/admin/orders/seller-orders/{alpha_id}/reissue-code", json={"reason": "Again"}
            )
        )
        == "order_not_awaiting_handover"
    )


def test_the_code_is_shown_only_to_the_signed_in_buyer(bazaar: Bazaar) -> None:
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    assert code not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{alpha_id}").text
    assert code not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders").text
    desk = bazaar.staff.get(f"/admin/orders/{order['code']}")
    assert desk.status_code == 200, desk.text
    assert code not in desk.text
    assert _part(desk.json(), "alpha")["status"] == "out_for_delivery"
    other, _ = bazaar.buyer()
    assert other.get(f"/me/orders/{order['id']}").status_code == 404
    assert ApiClient().get(f"/me/orders/{order['id']}").status_code == 401
    assert bazaar.staff.get("/admin/orders/MX-AAAAAA").status_code == 404
    assert bazaar.staff.get("/admin/orders/not-a-code").status_code == 422
    assert buyer.get(f"/admin/orders/{order['code']}").status_code == 403


# -- failed deliveries, retries, returns --------------------------------------------------


def test_a_failed_delivery_is_retried_and_finally_returned(bazaar: Bazaar, db: DbSession) -> None:
    """G.6: `out_for_delivery -> delivery_failed -> out_for_delivery` and then
    `-> returned`, which gives the stock back and cancels the payment intent."""
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    failed = bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Nobody at the gate"})
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "delivery_failed"
    assert failed.json()["shipment"]["failure_reason"] == "Nobody at the gate"
    # The code still works on the retry; the shipment keeps its first dispatch time.
    first_dispatch = failed.json()["shipment"]["dispatched_at"]
    assert _part(_mine(buyer, order["id"]), "alpha")["handover_code"] == code
    retry = bazaar.a.post(f"{base}/dispatch", json={})
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "out_for_delivery"
    assert retry.json()["shipment"]["failure_reason"] is None
    assert retry.json()["shipment"]["dispatched_at"] == first_dispatch
    assert error_code(bazaar.a.post(f"{base}/return", json={"reason": "x" * 3})) == (
        "order_move_not_allowed"
    )
    assert (
        bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Wrong number"}).status_code == 200
    )
    back = bazaar.a.post(f"{base}/return", json={"reason": "Buyer unreachable twice"})
    assert back.status_code == 200, back.text
    assert back.json()["status"] == "returned"
    assert back.json()["closed_reason"] == "Buyer unreachable twice"
    assert back.json()["shipment"]["status"] == "returned"
    assert [e["status"] for e in back.json()["shipment"]["events"]] == [
        "ready", "out_for_delivery", "delivery_failed", "out_for_delivery", "delivery_failed",
        "returned",
    ]  # fmt: skip
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert_stock_is_consistent(db)
    assert Counter(db.scalars(select(PaymentIntent.status))) == {"cancelled": 1, "pending": 1}
    mine = _mine(buyer, order["id"])
    assert _part(mine, "alpha")["handover_code"] is None
    assert _part(mine, "alpha")["seller_contact"] is not None  # the seller may still be reached
    templates = Counter(db.scalars(select(Notification.template)))
    assert (templates["order.delivery_failed"], templates["order.returned"]) == (2, 1)


# -- what is refused ----------------------------------------------------------------------


def test_moves_out_of_order_are_refused(bazaar: Bazaar) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    a, b = f"/seller/{bazaar.a_id}/orders/{alpha_id}", f"/seller/{bazaar.b_id}/orders/{beta_id}"
    buyer_base = f"/me/orders/{order['id']}/seller-orders/{alpha_id}"
    # Nothing before confirmation.
    assert error_code(bazaar.a.post(f"{a}/ready")) == "order_move_not_allowed"
    assert error_code(bazaar.a.post(f"{a}/dispatch", json={})) == "order_move_not_allowed"
    assert error_code(bazaar.a.post(f"{a}/handover", json={"code": "000000"})) == (
        "order_not_awaiting_handover"
    )
    assert error_code(bazaar.a.post(f"{a}/payment", json={"method": "cash"})) == (
        "payment_not_recordable"
    )
    assert error_code(buyer.post(f"{buyer_base}/confirm-received")) == "order_not_delivered"
    _confirm(bazaar, order)
    # A rider order is not handed over before it leaves; a collection order
    # is never dispatched.
    assert bazaar.a.post(f"{a}/ready").status_code == 200
    assert error_code(bazaar.a.post(f"{a}/handover", json={"code": "000000"})) == (
        "order_not_dispatched"
    )
    assert error_code(bazaar.a.post(f"{a}/delivery-failed", json={"reason": "Gone"})) == (
        "order_move_not_allowed"
    )
    assert bazaar.b.post(f"{b}/ready").status_code == 200
    assert error_code(bazaar.b.post(f"{b}/dispatch", json={})) == "collection_order"
    # A bad rider phone is a validation error, not a stored string.
    assert bazaar.a.post(f"{a}/dispatch", json={"rider_phone": "12"}).status_code == 422
    assert error_code(bazaar.a.post(f"{a}/dispatch", json={"rider_phone": "0400000000"})) == (
        "phone_invalid"
    )
    # Another seller's part, under either seller id, does not exist.
    for path in (
        f"/seller/{bazaar.a_id}/orders/{beta_id}",
        f"/seller/{bazaar.b_id}/orders/{beta_id}",
    ):
        assert bazaar.a.post(f"{path}/ready").status_code == 404
        assert bazaar.a.post(f"{path}/handover", json={"code": "000000"}).status_code == 404


def test_staff_dispatch_and_who_may_intervene(bazaar: Bazaar, db: DbSession) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, _ = _confirm(bazaar, order)
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/ready").status_code == 200
    path = f"/admin/orders/seller-orders/{alpha_id}/dispatch"
    finance = staff_client(db, "0911000299", StaffRole.FINANCE)
    assert finance.get(f"/admin/orders/{order['code']}").status_code == 200  # may find
    assert finance.post(path, json={"rider_name": "Courier"}).status_code == 403  # may not act
    assert buyer.post(path, json={}).status_code == 403
    assert bazaar.a.post(path, json={}).status_code == 403
    sent = bazaar.staff.post(
        path, json={"rider_name": "Partner courier", "rider_phone": "0933000111"}
    )
    assert sent.status_code == 200, sent.text
    alpha = _part(sent.json(), "alpha")
    assert alpha["status"] == "out_for_delivery"
    assert alpha["events"][-1]["actor_type"] == "staff"
    assert alpha["shipment"]["events"][-1]["source"] == "staff"
    assert "actor_user_id" not in sent.text
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "seller_order.dispatch")
        )
        == 1
    )
    assert (
        bazaar.staff.post(
            f"/admin/orders/seller-orders/{uuid.uuid4()}/dispatch", json={}
        ).status_code
        == 404
    )


# -- the direct payment record (D.12) --------------------------------------------------------


def test_a_payment_cannot_be_recorded_before_the_handover(bazaar: Bazaar, db: DbSession) -> None:
    """F-09, option 2 (D-087): the seller records that the buyer paid only
    once the goods are handed over, never in advance. Refused at every step
    before it, leaving the payment intent untouched; accepted at the handover
    and after completion."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    a = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    b = f"/seller/{bazaar.b_id}/orders/{beta_id}"

    def refused_at(client: ApiClient, base: str, state: str) -> None:
        response = client.post(f"{base}/payment", json={"method": "bank_transfer"})
        assert response.status_code == 409, (state, response.text)
        assert error_code(response) == "payment_not_recordable"
        assert "handed over" in response.json()["error"]["message"]

    refused_at(bazaar.a, a, "placed")
    _confirm(bazaar, order)
    refused_at(bazaar.a, a, "confirmed")
    assert bazaar.a.post(f"{a}/ready").status_code == 200
    refused_at(bazaar.a, a, "ready")
    assert bazaar.a.post(f"{a}/dispatch", json={}).status_code == 200
    refused_at(bazaar.a, a, "out_for_delivery")
    assert bazaar.a.post(f"{a}/delivery-failed", json={"reason": "Nobody home"}).status_code == 200
    refused_at(bazaar.a, a, "delivery_failed")
    assert bazaar.b.post(f"{b}/ready").status_code == 200
    refused_at(bazaar.b, b, "ready (shop collection)")

    db.rollback()
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 0
    assert set(db.scalars(select(PaymentIntent.status))) == {"pending"}
    mine = _mine(buyer, order["id"])
    assert [p["paid_at"] for p in mine["seller_orders"]] == [None, None]

    # Handed over: now it may be recorded. Alpha at the door after a retry,
    # Beta after collection and the buyer's confirmation (completed).
    assert bazaar.a.post(f"{a}/dispatch", json={}).status_code == 200
    code = _part(_mine(buyer, order["id"]), "alpha")["handover_code"]
    assert bazaar.a.post(f"{a}/handover", json={"code": code}).status_code == 200
    assert bazaar.a.post(f"{a}/payment", json={"method": "cash"}).status_code == 200
    beta_code = _part(_mine(buyer, order["id"]), "beta")["handover_code"]
    assert bazaar.b.post(f"{b}/handover", json={"code": beta_code}).status_code == 200
    done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{beta_id}/confirm-received")
    assert done.status_code == 200, done.text
    late = bazaar.b.post(f"{b}/payment", json={"method": "telebirr"})
    assert late.status_code == 200, late.text
    assert (late.json()["status"], late.json()["paid_method"]) == ("completed", "telebirr")


def test_the_seller_records_a_direct_payment_once(bazaar: Bazaar, db: DbSession) -> None:
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{base}/handover", json={"code": code}).status_code == 200
    before = datetime.now(UTC)
    paid = bazaar.a.post(f"{base}/payment", json={"method": "bank_transfer"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "delivered"  # the status does not move (D.12)
    assert paid.json()["paid_method"] == "bank_transfer"
    assert datetime.fromisoformat(paid.json()["paid_at"]) >= before  # the server's clock
    assert error_code(bazaar.a.post(f"{base}/payment", json={"method": "cash"})) == "already_paid"
    assert bazaar.a.post(f"{base}/payment", json={"method": "card"}).status_code == 422
    intent = db.scalar(
        select(PaymentIntent).where(PaymentIntent.seller_order_id == uuid.UUID(alpha_id))
    )
    assert intent is not None
    assert (intent.status, intent.method, intent.settled_at is not None) == (
        "succeeded",
        "bank_transfer",
        True,
    )
    (attempt,) = db.scalars(select(PaymentAttempt).where(PaymentAttempt.intent_id == intent.id))
    assert attempt.status == "succeeded"
    assert attempt.raw_result == {"recorded_by": "seller", "method": "bank_transfer"}
    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "seller_order.record_payment"))
    assert entry.after == {"method": "bank_transfer", "amount_santim": 3_715_000}
    assert _part(_mine(buyer, order["id"]), "alpha")["paid_method"] == "bank_transfer"
    # A cancelled part cannot be paid for; nothing of the intent changes.
    beta_id = _part(order, "beta")["id"]
    buyer.post(f"/me/orders/{order['id']}/seller-orders/{beta_id}/cancel", json={})
    assert (
        error_code(
            bazaar.b.post(
                f"/seller/{bazaar.b_id}/orders/{beta_id}/payment", json={"method": "cash"}
            )
        )
        == "payment_not_recordable"
    )


# -- the fee (D.19, J.8, G.10) ------------------------------------------------------------------


def test_the_fee_is_charged_at_completion_and_posted_to_the_ledger(
    bazaar: Bazaar, db: DbSession
) -> None:
    """A 3% category rule: the fee is on item value only, rounded to a santim,
    charged when the part completes, and balanced in the ledger."""
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(bazaar.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.get(base).json()["fee_santim"] is None  # not charged yet
    assert bazaar.a.post(f"{base}/handover", json={"code": code}).status_code == 200
    done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{alpha_id}/confirm-received")
    assert done.status_code == 200, done.text

    # 3% of 37,000.00 birr in goods: 1,110.00 birr. The 150 birr rider fee is not in it.
    assert bazaar.a.get(base).json()["fee_santim"] == 111_000
    (charge,) = db.scalars(select(FeeCharge))
    assert (charge.item_value_santim, charge.amount_santim, charge.cap_applied) == (
        3_700_000,
        111_000,
        False,
    )
    txn = db.get(LedgerTransaction, charge.ledger_transaction_id)
    assert txn is not None
    assert (txn.kind, txn.reference_type, txn.reference_id) == (
        "fee_charge",
        "seller_order",
        uuid.UUID(alpha_id),
    )
    entries = {
        (account.code, entry.direction, entry.amount_santim)
        for entry, account in db.execute(
            select(LedgerEntry, LedgerAccount)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerEntry.transaction_id == txn.id)
        ).all()
    }
    assert entries == {
        (f"seller_receivable:{bazaar.a_id}", "debit", 111_000),
        ("commission_income", "credit", 111_000),
    }
    assert (
        db.scalar(
            select(SellerOrder.commission_santim).where(SellerOrder.id == uuid.UUID(alpha_id))
        )
        == 111_000
    )
    # The buyer's total is untouched by the fee.
    assert _part(_mine(buyer, order["id"]), "alpha")["total_santim"] == 3_715_000


# -- the fulfilment hold (D-043) ---------------------------------------------------------------


def test_an_overdue_fulfilment_hold_cancels_the_order_and_frees_the_stock(
    bazaar: Bazaar, db: DbSession
) -> None:
    """A confirmed part nobody packed for fourteen days is cancelled by the
    worker. A parcel already on the road is left alone."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _confirm(bazaar, order)
    a = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{a}/ready").status_code == 200
    assert bazaar.a.post(f"{a}/dispatch", json={}).status_code == 200
    held = db.scalar(
        select(InventoryReservation).where(
            InventoryReservation.offer_id == uuid.UUID(bazaar.b128["id"])
        )
    )
    assert held is not None
    jobs = {o.name: o.result for o in run_once(held.expires_at - timedelta(hours=1)).jobs}
    assert jobs["orders.cancel_overdue_fulfilment"] == 0
    jobs = {o.name: o.result for o in run_once(held.expires_at + timedelta(minutes=1)).jobs}
    assert jobs["orders.cancel_overdue_fulfilment"] == 1

    mine = _mine(buyer, order["id"])
    assert (_part(mine, "alpha")["status"], _part(mine, "beta")["status"]) == (
        "out_for_delivery", "cancelled",
    )  # fmt: skip
    assert _part(mine, "beta")["closed_reason"] == "fulfilment_hold_expired"
    assert _part(mine, "beta")["events"][-1]["actor_type"] == "system"
    assert stock(db, bazaar.b128["id"]) == (5, 0)
    assert stock(db, bazaar.a128["id"]) == (5, 2)
    assert_stock_is_consistent(db)
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.cancelled_not_fulfilled"] == 1
    assert templates["order.cancelled_not_fulfilled_for_seller"] == 1
    assert (
        bazaar.b.get(f"/seller/{bazaar.b_id}/orders/{beta_id}").json()["shipment"]["status"]
        == "cancelled"
    )
    assert db.scalar(select(func.count()).select_from(OrderStatusEvent)) == 2 + 2 + 2 + 1


def test_a_cancelled_or_returned_part_never_completes(bazaar: Bazaar, db: DbSession) -> None:
    """The completion job touches only delivered parts, and `commit_stock`
    is never asked for stock that is not held."""
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Gone"})
    bazaar.a.post(f"{base}/return", json={"reason": "Gone twice"})
    jobs = {o.name: o.result for o in run_once(datetime.now(UTC) + timedelta(days=30)).jobs}
    assert jobs["orders.complete_after_problem_window"] == 0
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 0
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert_stock_is_consistent(db)
    assert (
        error_code(
            buyer.post(f"/me/orders/{order['id']}/seller-orders/{alpha_id}/confirm-received")
        )
        == "order_not_delivered"
    )
    # `handover_code` is derived from the shipment and its version: the
    # service computes the same value the page showed.
    shipment = db.scalar(select(Shipment).where(Shipment.seller_order_id == uuid.UUID(alpha_id)))
    assert shipment is not None
    assert service.handover_code(shipment) == code


def test_every_cancelled_shipment_has_its_tracking_event(bazaar: Bazaar, db: DbSession) -> None:
    """A shipment changes only with its tracking event (J.10), also when the
    order around it is declined, cancelled by the buyer, expired unanswered
    or cancelled by the overdue-hold job. Found in the fifth session's review:
    those four paths changed the shipment with a bulk update and no event."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    declined = bazaar.b.post(
        f"/seller/{bazaar.b_id}/orders/{beta_id}/decline", json={"reason": "Sold out"}
    )
    assert declined.status_code == 200, declined.text
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm").status_code == 200
    cancelled = buyer.post(f"/me/orders/{order['id']}/seller-orders/{alpha_id}/cancel", json={})
    assert cancelled.status_code == 200, cancelled.text

    silent_buyer, address_id = bazaar.buyer()
    add_to_cart(silent_buyer, bazaar.a256["id"], 1)
    silent = checkout(silent_buyer, address_id, {"alpha": "seller_rider"}).json()
    deadline = datetime.fromisoformat(silent["seller_orders"][0]["response_deadline"])
    assert {o.name: o.result for o in run_once(deadline + timedelta(minutes=2)).jobs}[
        "orders.expire_unanswered"
    ] == 1

    late_buyer, address_id = bazaar.buyer()
    add_to_cart(late_buyer, bazaar.b128["id"], 1)
    late = checkout(late_buyer, address_id, {"beta": "shop_collection"}).json()
    late_id = late["seller_orders"][0]["id"]
    for step in ("confirm", "ready"):
        assert bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{late_id}/{step}").status_code == 200
    jobs = {o.name: o.result for o in run_once(datetime.now(UTC) + timedelta(days=15)).jobs}
    assert jobs["orders.cancel_overdue_fulfilment"] == 1

    db.rollback()
    shipments = list(db.scalars(select(Shipment)))
    assert len(shipments) == 4
    for shipment in shipments:
        trail = list(
            db.scalars(
                select(TrackingEvent.status)
                .where(TrackingEvent.shipment_id == shipment.id)
                .order_by(TrackingEvent.occurred_at, TrackingEvent.id)
            )
        )
        assert shipment.status == "cancelled"
        assert trail, shipment.id
        assert trail[-1] == "cancelled", (shipment.id, trail)
    sources = Counter(
        db.scalars(select(TrackingEvent.source).where(TrackingEvent.status == "cancelled"))
    )
    assert sources == {"seller": 1, "buyer": 1, "system": 2}
    # The buyer's timeline shows it.
    events = _part(_mine(buyer, order["id"]), "beta")["shipment"]["events"]
    assert [e["status"] for e in events] == ["cancelled"]


def test_no_payment_is_recorded_before_confirmation_or_after_a_return(
    bazaar: Bazaar, db: DbSession
) -> None:
    """Ported from the alternative branch (session three, `03a879b`), which the
    official tests did not cover. A buyer owes a seller only between
    confirmation and the end of the part: neither a part still waiting for the
    seller nor goods that went back to the shop can be marked paid, and the
    payment intent is left exactly as it was."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id = _part(order, "alpha")["id"]
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"

    def intent() -> tuple[str, str | None, datetime | None]:
        db.rollback()
        row = db.scalar(
            select(PaymentIntent).where(PaymentIntent.seller_order_id == uuid.UUID(alpha_id))
        )
        assert row is not None
        return row.status, row.method, row.settled_at

    waiting = intent()
    assert waiting[0] == "pending"
    refused = bazaar.a.post(f"{base}/payment", json={"method": "cash"})
    assert refused.status_code == 409
    assert error_code(refused) == "payment_not_recordable"
    assert intent() == waiting

    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    assert bazaar.a.post(f"{base}/ready").status_code == 200
    assert bazaar.a.post(f"{base}/dispatch", json={}).status_code == 200
    failed = bazaar.a.post(f"{base}/delivery-failed", json={"reason": "Nobody at the gate"})
    assert failed.status_code == 200, failed.text
    back = bazaar.a.post(f"{base}/return", json={"reason": "Buyer unreachable twice"})
    assert back.status_code == 200, back.text
    returned = intent()
    assert returned[0] == "cancelled"
    refused = bazaar.a.post(f"{base}/payment", json={"method": "cash"})
    assert refused.status_code == 409
    assert error_code(refused) == "payment_not_recordable"
    assert intent() == returned
    assert _part(_mine(buyer, order["id"]), "alpha")["paid_method"] is None
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 0


# -- one failing order never holds back the others (D-060) ---------------------------------


def _both_parts_delivered(bazaar: Bazaar) -> tuple[ApiClient, dict[str, Any], str, str, datetime]:
    """Alpha handed over by its rider, Beta collected at the counter; returns
    the moment both problem windows have passed."""
    buyer, order, alpha_id, code = _dispatched_alpha(bazaar)
    beta_id = _part(order, "beta")["id"]
    a = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    b = f"/seller/{bazaar.b_id}/orders/{beta_id}"
    alpha = bazaar.a.post(f"{a}/handover", json={"code": code})
    assert alpha.status_code == 200, alpha.text
    assert bazaar.b.post(f"{b}/ready").status_code == 200
    beta_code = _part(_mine(buyer, order["id"]), "beta")["handover_code"]
    beta = bazaar.b.post(f"{b}/handover", json={"code": beta_code})
    assert beta.status_code == 200, beta.text
    after = max(
        datetime.fromisoformat(alpha.json()["problem_window_ends_at"]),
        datetime.fromisoformat(beta.json()["problem_window_ends_at"]),
    ) + timedelta(minutes=5)
    return buyer, order, alpha_id, beta_id, after


@pytest.mark.parametrize("failure", ["raises", "unbalanced_ledger"])
def test_one_order_that_cannot_complete_never_blocks_the_others(
    bazaar: Bazaar, db: DbSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """D-060. Alpha's completion fails, either at once or only in a check the
    database defers to commit (an unbalanced ledger posting). Beta still
    completes in the same run; Alpha is undone alone, stays delivered with
    its stock held, and completes on a later run once the fault is gone."""
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(bazaar.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    _, _, alpha_id, beta_id, after = _both_parts_delivered(bazaar)
    real_charge_fee = service.ledger.charge_fee

    def faulty_charge_fee(session: DbSession, **kwargs: Any) -> LedgerTransaction:
        if kwargs["seller_order_id"] != uuid.UUID(alpha_id):
            return real_charge_fee(session, **kwargs)
        if failure == "raises":
            raise RuntimeError("the fee could not be posted")
        txn = LedgerTransaction(
            idempotency_key=f"broken:{alpha_id}", kind="fee_charge",
            reference_type="seller_order", reference_id=kwargs["seller_order_id"],
            description="debit without its credit",
        )  # fmt: skip
        session.add(txn)
        session.flush()
        receivable = service.ledger.seller_receivable(session, kwargs["seller_id"])
        session.add(
            LedgerEntry(
                transaction_id=txn.id, account_id=receivable.id, direction="debit",
                amount_santim=kwargs["fee"].amount, currency="ETB",
            )
        )  # fmt: skip
        session.flush()
        return txn

    monkeypatch.setattr(service.ledger, "charge_fee", faulty_charge_fee)
    outcome = next(
        o for o in run_once(after).jobs if o.name == "orders.complete_after_problem_window"
    )
    assert (outcome.ok, outcome.result) == (True, 1)

    db.rollback()
    statuses = dict(
        db.execute(
            select(SellerOrder.id, SellerOrder.status).where(
                SellerOrder.id.in_([uuid.UUID(alpha_id), uuid.UUID(beta_id)])
            )
        ).all()
    )
    assert statuses == {uuid.UUID(alpha_id): "delivered", uuid.UUID(beta_id): "completed"}
    charged = set(db.scalars(select(FeeCharge.seller_order_id)))
    assert charged == {uuid.UUID(beta_id)}
    assert db.scalar(select(func.count()).select_from(LedgerTransaction)) == 1
    assert stock(db, bazaar.a128["id"]) == (5, 2)  # Alpha's two units still held
    assert_stock_is_consistent(db)

    monkeypatch.setattr(service.ledger, "charge_fee", real_charge_fee)
    outcome = next(
        o
        for o in run_once(after + timedelta(minutes=10)).jobs
        if o.name == "orders.complete_after_problem_window"
    )
    assert (outcome.ok, outcome.result) == (True, 1)
    db.rollback()
    assert db.scalar(select(SellerOrder.status).where(SellerOrder.id == uuid.UUID(alpha_id))) == (
        "completed"
    )
    assert stock(db, bazaar.a128["id"]) == (3, 0)
    assert_stock_is_consistent(db)
