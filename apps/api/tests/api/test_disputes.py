"""Problems on a delivered order (blueprint D.17, G.6, G.7, C-16, S-16, AD-09):
the buyer reports inside the problem window, completion waits, each side adds
its account, and staff decide. Release 1 records the outcome; MarkX moves no
money.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.notifications.models import Notification
from markx.offers.models import InventoryReservation
from markx.orders.models import SellerOrder
from markx.payments.models import CommissionRule, FeeCharge, LedgerTransaction, PaymentIntent
from markx.trust.models import DisputeCase, DisputeMessage
from markx.worker.runner import run_once
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, staff_client

PROBLEM = {"problem_type": "not_as_described", "description": "The box says 128 GB, the phone 64."}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    # A 3% rule, so that a completion charges a fee and a refund visibly does not.
    market = Bazaar(db)
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(market.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    return market


class Delivered:
    """Two units from Alpha by rider, handed over with the buyer's code."""

    def __init__(self, bazaar: Bazaar) -> None:
        self.buyer, address_id = bazaar.buyer()
        add_to_cart(self.buyer, bazaar.a128["id"], 2)
        response = checkout(self.buyer, address_id, {"alpha": "seller_rider"})
        assert response.status_code == 201, response.text
        self.order_id = response.json()["id"]
        self.so_id = response.json()["seller_orders"][0]["id"]
        self.seller = f"/seller/{bazaar.a_id}/orders/{self.so_id}"
        self.mine = f"/me/orders/{self.order_id}/seller-orders/{self.so_id}"
        self.admin = f"/admin/orders/seller-orders/{self.so_id}"
        for step in ("confirm", "ready", "dispatch"):
            assert bazaar.a.post(f"{self.seller}/{step}", json={}).status_code == 200
        code = self.part()["handover_code"]
        assert bazaar.a.post(f"{self.seller}/handover", json={"code": code}).status_code == 200

    def part(self) -> dict[str, Any]:
        response = self.buyer.get(f"/me/orders/{self.order_id}")
        assert response.status_code == 200, response.text
        return dict(response.json()["seller_orders"][0])

    def report(self) -> Any:
        return self.buyer.post(f"{self.mine}/problem", json=PROBLEM)


def test_a_reported_problem_stops_completion_until_staff_decide(
    bazaar: Bazaar, db: DbSession
) -> None:
    d = Delivered(bazaar)
    assert d.part()["can_report_problem"] is True
    assert d.part()["problem"] is None

    reported = d.report()
    assert reported.status_code == 200, reported.text
    part = reported.json()["seller_orders"][0]
    assert (part["status"], reported.json()["status"]) == ("disputed", "disputed")
    assert (part["can_report_problem"], part["can_confirm_received"]) == (False, False)
    assert part["events"][-1]["to_status"] == "disputed"
    assert (part["events"][-1]["actor_type"], part["events"][-1]["reason"]) == (
        "buyer",
        "not_as_described",
    )
    problem = part["problem"]
    assert (problem["problem_type"], problem["status"], problem["decision"]) == (
        "not_as_described",
        "open",
        None,
    )
    assert problem["description"] == PROBLEM["description"]
    due = datetime.fromisoformat(problem["decision_due_at"]) - datetime.now(UTC)
    assert timedelta(hours=47) < due <= timedelta(hours=48)
    # Once only: the part is no longer "delivered".
    assert error_code(d.report()) == "order_not_delivered"
    assert error_code(d.buyer.post(f"{d.mine}/confirm-received")) == "order_not_delivered"

    # The window passes: the worker leaves a disputed part alone. Nothing is
    # charged and the stock is still held.
    jobs = {o.name: o.result for o in run_once(datetime.now(UTC) + timedelta(days=30)).jobs}
    assert jobs["orders.complete_after_problem_window"] == 0
    assert d.part()["status"] == "disputed"
    assert stock(db, bazaar.a128["id"]) == (5, 2)
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 0

    # Both sides add their account; each sees the whole exchange by role.
    seen_by_seller = bazaar.a.get(d.seller).json()
    assert seen_by_seller["status"] == "disputed"
    assert seen_by_seller["problem"]["description"] == PROBLEM["description"]
    replied = bazaar.a.post(f"{d.seller}/problem/reply", json={"body": "It was sealed, 128 GB."})
    assert replied.status_code == 200, replied.text
    assert replied.json()["problem"]["status"] == "seller_responded"
    added = d.buyer.post(f"{d.mine}/problem/messages", json={"body": "Settings shows 64 GB."})
    assert added.status_code == 200, added.text
    messages = added.json()["seller_orders"][0]["problem"]["messages"]
    assert [(m["author_type"], m["body"]) for m in messages] == [
        ("seller", "It was sealed, 128 GB."),
        ("buyer", "Settings shows 64 GB."),
    ]
    assert "user_id" not in str(messages)

    # The staff queue shows it; support may decide, with a written reason.
    support = staff_client(db, "0911000300", StaffRole.SUPPORT)
    (waiting,) = support.get("/admin/orders/problems").json()
    assert (waiting["seller_order_id"], waiting["store_slug"], waiting["status"]) == (
        d.so_id,
        "alpha",
        "seller_responded",
    )
    assert support.post(f"{d.admin}/resolve-problem", json={"decision": "no_action"}).status_code == 422  # fmt: skip
    resolved = support.post(
        f"{d.admin}/resolve-problem",
        json={"decision": "no_action", "reason": "Photos show the 128 GB model."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["seller_orders"][0]["status"] == "completed"
    assert resolved.json()["seller_orders"][0]["handover_code"] is None

    # Completed as any other: stock committed, the fee charged on the goods.
    part = d.part()
    assert (part["status"], part["problem"]["status"], part["problem"]["decision"]) == (
        "completed",
        "resolved",
        "no_action",
    )
    assert part["problem"]["decision_reason"] == "Photos show the 128 GB model."
    assert part["events"][-1]["actor_type"] == "staff"
    assert stock(db, bazaar.a128["id"]) == (3, 0)
    assert_stock_is_consistent(db)
    (charge,) = db.scalars(select(FeeCharge))
    assert charge.amount_santim == 111_000
    assert support.get("/admin/orders/problems").json() == []
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "dispute.resolve"))
    assert audit is not None
    assert audit.after["decision"] == "no_action"
    # A decided case is closed to everyone.
    assert error_code(d.buyer.post(f"{d.mine}/problem/messages", json={"body": "But still"})) == (
        "problem_already_resolved"
    )
    assert error_code(bazaar.a.post(f"{d.seller}/problem/reply", json={"body": "Thanks"})) == (
        "problem_already_resolved"
    )
    assert error_code(
        support.post(f"{d.admin}/resolve-problem", json={"decision": "no_action", "reason": "Again"})
    ) == "order_not_disputed"  # fmt: skip
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.problem_reported"] == 1
    assert templates["order.problem_reported_for_seller"] == 1
    assert templates["order.problem_seller_replied"] == 1
    assert templates["order.problem_buyer_added"] == 1
    # The decision itself, to the buyer and the store's order handler (D-092).
    assert templates["dispute.decided"] == 1
    assert templates["dispute.decided_for_seller"] == 1


def test_a_refund_with_the_goods_returned_puts_the_stock_back_and_charges_no_fee(
    bazaar: Bazaar, db: DbSession
) -> None:
    d = Delivered(bazaar)
    assert d.report().status_code == 200
    resolved = bazaar.staff.post(
        f"{d.admin}/resolve-problem",
        json={
            "decision": "seller_refunded",
            "reason": "Wrong model. The shop took it back and returned the cash.",
            "goods_returned": True,
        },
    )
    assert resolved.status_code == 200, resolved.text
    part = d.part()
    assert (part["status"], part["problem"]["decision"]) == ("refunded", "seller_refunded")
    assert (part["events"][-1]["to_status"], part["events"][-1]["actor_type"]) == (
        "refunded",
        "staff",
    )
    assert d.buyer.get(f"/me/orders/{d.order_id}").json()["status"] == "refunded"
    # Back on sale, nothing charged, nothing in the ledger, nothing owed.
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert_stock_is_consistent(db)
    assert db.scalar(select(InventoryReservation.status)) == "released"
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 0
    assert db.scalar(select(func.count()).select_from(LedgerTransaction)) == 0
    assert db.scalar(select(PaymentIntent.status)) == "cancelled"
    assert bazaar.a.get(d.seller).json()["fee_santim"] is None
    # It never completes afterwards.
    jobs = {o.name: o.result for o in run_once(datetime.now(UTC) + timedelta(days=30)).jobs}
    assert jobs["orders.complete_after_problem_window"] == 0
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "dispute.resolve"))
    assert audit is not None
    assert (audit.after["decision"], audit.after["goods_returned"]) == ("seller_refunded", True)
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.refunded"] == 1
    assert templates["order.refunded_for_seller"] == 1
    assert templates["order.completed"] == 0


def test_a_refund_without_the_goods_takes_them_off_the_shelf_count(
    bazaar: Bazaar, db: DbSession
) -> None:
    """The buyer keeps (or never got) the goods and the seller gives the money
    back: the units are gone from the shop, and the payment the seller
    recorded stays on record as the seller's word."""
    d = Delivered(bazaar)
    assert bazaar.a.post(f"{d.seller}/payment", json={"method": "cash"}).status_code == 200
    assert d.report().status_code == 200
    bad = bazaar.staff.post(
        f"{d.admin}/resolve-problem",
        json={"decision": "no_action", "reason": "Mixed up", "goods_returned": True},
    )
    assert error_code(bad) == "goods_returned_without_refund"
    resolved = bazaar.staff.post(
        f"{d.admin}/resolve-problem",
        json={"decision": "seller_refunded", "reason": "Damaged in transit; cash returned."},
    )
    assert resolved.status_code == 200, resolved.text
    assert d.part()["status"] == "refunded"
    assert stock(db, bazaar.a128["id"]) == (3, 0)
    assert_stock_is_consistent(db)
    assert db.scalar(select(InventoryReservation.status)) == "committed"
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 0
    assert db.scalar(select(PaymentIntent.status)) == "succeeded"


def test_who_may_report_reply_and_decide(bazaar: Bazaar, db: DbSession) -> None:
    # Not before the goods changed hands.
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.b128["id"], 1)
    early = checkout(buyer, address_id, {"beta": "shop_collection"}).json()
    early_part = early["seller_orders"][0]["id"]
    assert (
        error_code(
            buyer.post(f"/me/orders/{early['id']}/seller-orders/{early_part}/problem", json=PROBLEM)
        )
        == "order_not_delivered"
    )
    assert error_code(
        bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{early_part}/problem/reply", json={"body": "Hm?"})
    ) == "problem_not_found"  # fmt: skip

    d = Delivered(bazaar)
    stranger, _ = bazaar.buyer()
    assert stranger.post(f"{d.mine}/problem", json=PROBLEM).status_code == 404
    assert ApiClient().post(f"{d.mine}/problem", json=PROBLEM).status_code == 401
    assert d.buyer.post(f"{d.mine}/problem", json={"problem_type": "bored", "description": "No"}).status_code == 422  # fmt: skip
    # A part of someone else's order under the buyer's own order id.
    assert buyer.post(f"/me/orders/{early['id']}/seller-orders/{d.so_id}/problem", json=PROBLEM).status_code == 404  # fmt: skip
    assert d.report().status_code == 200
    assert stranger.post(f"{d.mine}/problem/messages", json={"body": "Me too"}).status_code == 404
    assert buyer.post(
        f"/me/orders/{early['id']}/seller-orders/{d.so_id}/problem/messages", json={"body": "Hi!"}
    ).status_code == 404  # fmt: skip
    # Beta cannot answer for Alpha, under either seller id.
    for path in (
        f"/seller/{bazaar.b_id}/orders/{d.so_id}/problem/reply",
        f"/seller/{bazaar.a_id}/orders/{d.so_id}/problem/reply",
    ):
        assert bazaar.b.post(path, json={"body": "Not ours"}).status_code in (403, 404)
    assert db.scalar(select(func.count()).select_from(DisputeMessage)) == 0

    # Finance and catalogue staff do not handle cases; buyers and sellers never.
    body = {"decision": "seller_refunded", "reason": "Because"}
    for role, phone in ((StaffRole.FINANCE, "0911000301"), (StaffRole.CATALOGUE, "0911000302")):
        outsider = staff_client(db, phone, role)
        assert outsider.post(f"{d.admin}/resolve-problem", json=body).status_code == 403
        assert outsider.get("/admin/orders/problems").status_code == 403
    assert d.buyer.post(f"{d.admin}/resolve-problem", json=body).status_code == 403
    assert bazaar.a.get("/admin/orders/problems").status_code == 403
    assert d.part()["status"] == "disputed"

    # The tracking link shows the status, never what the buyer wrote.
    order = d.buyer.get(f"/me/orders/{d.order_id}").json()
    tracked = ApiClient().get(order["tracking_path"].removeprefix("/api/v1"))
    assert tracked.status_code == 200, tracked.text
    assert tracked.json()["seller_orders"][0]["status"] == "disputed"
    assert tracked.json()["seller_orders"][0]["problem"] is None
    assert PROBLEM["description"] not in tracked.text
    # Staff reading the order see the case.
    seen = bazaar.staff.get(f"/admin/orders/{order['code']}").json()["seller_orders"][0]
    assert seen["problem"]["description"] == PROBLEM["description"]


def test_a_problem_cannot_be_reported_after_the_window(bazaar: Bazaar, db: DbSession) -> None:
    d = Delivered(bazaar)
    db.execute(
        update(SellerOrder)
        .where(SellerOrder.id == uuid.UUID(d.so_id))
        .values(problem_window_ends_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert d.part()["can_report_problem"] is False
    assert error_code(d.report()) == "problem_window_closed"
    assert db.scalar(select(func.count()).select_from(DisputeCase)) == 0
    assert d.part()["status"] == "delivered"
