"""Checkout and multi-seller orders (blueprint D.10, D.11, G.5 to G.7, P9, P10).

The buyer's cart becomes one parent order and one seller order per seller.
Every price comes from the server; the browser is never trusted.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import User
from markx.core import settings_store
from markx.delivery.models import Shipment
from markx.notifications.models import Notification, Outbox
from markx.offers.models import InventoryReservation
from markx.orders import service
from markx.orders.models import Order, OrderItem, OrderStatusEvent, SellerOrder
from markx.orders.status import ALLOWED_MOVES
from markx.payments.models import CommissionRule, PaymentIntent
from markx.sellers.models import Seller, SellerMember
from markx.worker.runner import run_once
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, make_offer, new_idempotency_key

NO_JOBS: tuple[Any, ...] = ()


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


# -- the P9 and P10 completion criteria ------------------------------------------------


def test_one_checkout_becomes_one_order_with_a_seller_order_per_seller(
    bazaar: Bazaar, db: DbSession
) -> None:
    """Blueprint G.5, step by step, read back from the database."""
    buyer, _, order = _two_seller_order(bazaar)
    assert re.fullmatch(r"MX-[34679ACDEFGHJKMNPQRTUVWXY]{6}", order["code"])
    assert order["status"] == "placed"
    assert order["payment_mode"] == "direct"
    # Totals: 2 x 18,500 + 17,900 in goods, plus Alpha's rider fee.
    assert (order["items_total_santim"], order["delivery_total_santim"]) == (5_490_000, 15_000)
    assert order["grand_total_santim"] == 5_505_000
    assert order["address"]["recipient_name"] == "Sara Bekele"
    assert order["address"]["zone_code"] == "bole"

    alpha, beta = _part(order, "alpha"), _part(order, "beta")
    assert (alpha["items_total_santim"], alpha["delivery_fee_santim"]) == (3_700_000, 15_000)
    assert alpha["total_santim"] == 3_715_000
    assert (beta["items_total_santim"], beta["delivery_fee_santim"]) == (1_790_000, 0)
    assert (alpha["delivery_method"], beta["delivery_method"]) == (
        "seller_rider",
        "shop_collection",
    )
    assert alpha["promised_hours"] == 24
    assert alpha["response_deadline"] == beta["response_deadline"]
    assert datetime.fromisoformat(alpha["response_deadline"]) > datetime.now(UTC)
    assert {so["payment_reference"] for so in order["seller_orders"]} == {
        f"{order['code']}-1",
        f"{order['code']}-2",
    }
    # Each line keeps its own copy of what was bought (G.8 rule 4).
    (line,) = alpha["items"]
    assert line["title"] == "ሳምሰንግ ጋላክሲ A16"
    assert line["variant_label"] == "ጥቁር · 128 ጊባ"
    assert (line["unit_price_santim"], line["quantity"], line["line_total_santim"]) == (
        1_850_000, 2, 3_700_000,
    )  # fmt: skip
    assert (line["condition"], line["warranty_months"]) == ("new", 12)
    english = buyer.get(f"/me/orders/{order['id']}", params={"lang": "en"}).json()
    assert _part(english, "alpha")["items"][0]["title"] == "Samsung Galaxy A16"
    assert _part(english, "alpha")["items"][0]["variant_label"] == "Black · 128 GB"

    # The stock is held, one reservation beside each hold, until the deadline.
    assert stock(db, bazaar.a128["id"]) == (5, 2)
    assert stock(db, bazaar.b128["id"]) == (5, 1)
    reservations = list(db.scalars(select(InventoryReservation)))
    assert {(str(r.offer_id), r.quantity, r.status) for r in reservations} == {
        (bazaar.a128["id"], 2, "held"), (bazaar.b128["id"], 1, "held"),
    }  # fmt: skip
    assert {r.expires_at.isoformat() for r in reservations} == {
        datetime.fromisoformat(alpha["response_deadline"]).isoformat()
    }
    assert_stock_is_consistent(db)
    # One shipment and one payment intent per seller order (G.5 step 6).
    assert db.scalar(select(func.count()).select_from(Shipment)) == 2
    assert {(i.reference, i.amount_santim, i.status, i.method) for i in db.scalars(select(PaymentIntent))} == {
        (f"{order['code']}-1", 3_715_000, "pending", "cash"),
        (f"{order['code']}-2", 1_790_000, "pending", "cash"),
    }  # fmt: skip
    # A status event per seller order, and a message to every party (step 7).
    events = list(db.scalars(select(OrderStatusEvent)))
    assert [(e.from_status, e.to_status, e.actor_type) for e in events] == [
        (None, "placed", "buyer"), (None, "placed", "buyer"),
    ]  # fmt: skip
    templates = Counter(
        db.scalars(select(Notification.template).where(Notification.template.like("order.%")))
    )
    assert templates == {"order.placed_for_seller": 2, "order.placed": 1}
    # Every notification has its outbox row, written in the same transaction.
    # (Search rebuilds share the outbox under their own topic, D-051.)
    assert db.scalar(
        select(func.count()).select_from(Outbox).where(Outbox.topic == "notify.push")
    ) == db.scalar(select(func.count()).select_from(Notification))
    assert buyer.get("/cart").json()["line_count"] == 0  # the cart is spent
    assert buyer.get("/me").json()["unread_notifications"] == 1


def test_a_request_with_a_lowered_price_is_refused(bazaar: Bazaar, db: DbSession) -> None:
    """P9 criterion 1. There is no price field to lower, so the two things a
    browser can try are a lower total and an old cart price."""
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    response = buyer.post(
        "/checkout",
        json={
            "address_id": address_id,
            "deliveries": [{"store_slug": "alpha", "method": "seller_rider"}],
            "payment_method": "cash",
            "expected_total_santim": 1_865_000,
            "idempotency_key": new_idempotency_key(),
            "items_total_santim": 1,  # a price field is simply not accepted
        },
    )
    assert response.status_code == 422

    lowered = checkout(buyer, address_id, {"alpha": "seller_rider"}, expected_total=1_000)
    assert lowered.status_code == 409
    assert error_code(lowered) == "total_changed"
    assert lowered.json()["error"]["details"] == {"total_santim": 1_865_000}

    # The seller raised the price after the buyer last looked at the cart.
    bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}", json={"price_santim": 1_900_000}
    )
    stale = checkout(buyer, address_id, {"alpha": "seller_rider"}, expected_total=1_865_000)
    assert stale.status_code == 409
    assert error_code(stale) == "price_changed"
    assert stale.json()["error"]["details"]["items"] == [
        {"offer_id": bazaar.a128["id"], "price_seen_santim": 1_850_000, "price_santim": 1_900_000}
    ]
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    # Once the buyer accepts the new price, the order goes through at that price.
    buyer.post("/cart/accept-changes")
    placed = checkout(buyer, address_id, {"alpha": "seller_rider"})
    assert placed.status_code == 201, placed.text
    assert placed.json()["grand_total_santim"] == 1_915_000


def test_the_same_submission_sent_twice_creates_one_order(bazaar: Bazaar, db: DbSession) -> None:
    """P9 criterion 4, and D-010: the key is unique per buyer."""
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    key = new_idempotency_key()
    first = checkout(buyer, address_id, {"alpha": "seller_rider"}, key=key)
    assert first.status_code == 201
    again = checkout(buyer, address_id, {"alpha": "seller_rider"}, key=key, expected_total=1)
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert stock(db, bazaar.a128["id"]) == (5, 1)

    # Another buyer with the same key gets their own order, never this one.
    other, other_address = bazaar.buyer()
    add_to_cart(other, bazaar.a128["id"], 1)
    theirs = checkout(other, other_address, {"alpha": "seller_rider"}, key=key)
    assert theirs.status_code == 201
    assert theirs.json()["id"] != first.json()["id"]
    assert db.scalar(select(func.count()).select_from(Order)) == 2


def test_an_item_that_sold_out_ends_the_whole_order(bazaar: Bazaar, db: DbSession) -> None:
    """G.5 step 3: one line short and nothing is written; the buyer is told
    which item. The hold already taken for the other line vanishes too."""
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    add_to_cart(buyer, bazaar.a256["id"], 4)
    rival, rival_address = bazaar.buyer()
    add_to_cart(rival, bazaar.a256["id"], 2)
    assert checkout(rival, rival_address, {"alpha": "seller_rider"}).status_code == 201

    response = checkout(buyer, address_id, {"alpha": "seller_rider"})
    assert response.status_code == 409
    assert error_code(response) == "out_of_stock"
    assert response.json()["error"]["details"] == {"offer_id": bazaar.a256["id"], "requested": 4}
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert stock(db, bazaar.a256["id"]) == (5, 2)
    assert_stock_is_consistent(db)
    # The cart is kept, and now says why.
    cart = buyer.get("/cart").json()
    assert cart["line_count"] == 2
    problems = {i["offer_id"]: i["problem"] for g in cart["groups"] for i in g["items"]}
    assert problems == {bazaar.a128["id"]: None, bazaar.a256["id"]: "not_enough_stock"}


def test_an_expired_reservation_returns_the_stock(bazaar: Bazaar, db: DbSession) -> None:
    """P9 criterion 5 and P10 criterion 4: a silent seller's order expires and
    releases its stock, through the worker's job."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id = _part(order, "alpha")["id"]
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm").status_code == 200
    deadline = datetime.fromisoformat(_part(order, "beta")["response_deadline"])

    assert {o.name: o.result for o in run_once(deadline - timedelta(seconds=1)).jobs}[
        "orders.expire_unanswered"
    ] == 0
    # The job runs every minute; the next pass after the deadline picks it up.
    report = run_once(deadline + timedelta(minutes=2))
    assert {o.name: o.result for o in report.jobs}["orders.expire_unanswered"] == 1

    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert (_part(mine, "alpha")["status"], _part(mine, "beta")["status"]) == (
        "confirmed", "expired",
    )  # fmt: skip
    assert mine["status"] == "in_progress"  # a late seller never blocks the others (D.11)
    assert _part(mine, "beta")["closed_reason"] == "no_answer_in_time"
    assert _part(mine, "beta")["events"][-1]["actor_type"] == "system"
    assert stock(db, bazaar.b128["id"]) == (5, 0)
    assert stock(db, bazaar.a128["id"]) == (5, 2)  # Alpha's confirmed hold stays
    assert_stock_is_consistent(db)
    assert (
        db.scalar(
            select(InventoryReservation.status).where(
                InventoryReservation.offer_id == uuid.UUID(bazaar.b128["id"])
            )
        )
        == "released"
    )
    assert (
        db.scalar(
            select(Shipment.status)
            .join(SellerOrder, SellerOrder.id == Shipment.seller_order_id)
            .where(SellerOrder.seller_id == uuid.UUID(bazaar.b_id))
        )
        == "cancelled"
    )
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.seller_did_not_answer"] == 1
    assert templates["order.expired_unanswered"] == 1
    # Running it again changes nothing.
    assert {o.name: o.result for o in run_once(deadline + timedelta(days=1)).jobs}[
        "orders.expire_unanswered"
    ] == 0


def test_a_two_seller_order_moves_each_part_on_its_own(bazaar: Bazaar, db: DbSession) -> None:
    """P10 criterion 1 as far as Release 1's API goes today: placed, then
    each seller answers, and the parent's status follows (D.11)."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]

    confirmed = bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmed_at"] is not None
    assert buyer.get(f"/me/orders/{order['id']}").json()["status"] == "awaiting_seller"

    declined = bazaar.b.post(
        f"/seller/{bazaar.b_id}/orders/{beta_id}/decline", json={"reason": "Sold over the counter"}
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert mine["status"] == "in_progress"
    assert _part(mine, "beta")["closed_reason"] == "Sold over the counter"
    assert _part(mine, "beta")["can_cancel"] is False
    assert [(e["to_status"], e["actor_type"]) for e in _part(mine, "beta")["events"]] == [
        ("placed", "buyer"), ("declined", "seller"),
    ]  # fmt: skip
    # The decline released Beta's stock; Alpha's stays held for fulfilment.
    assert stock(db, bazaar.b128["id"]) == (5, 0)
    assert stock(db, bazaar.a128["id"]) == (5, 2)
    assert_stock_is_consistent(db)
    held = db.scalar(
        select(InventoryReservation).where(
            InventoryReservation.offer_id == uuid.UUID(bazaar.a128["id"])
        )
    )
    assert held is not None
    assert held.status == "held"
    assert held.expires_at > datetime.now(UTC) + timedelta(days=13)
    assert Counter(db.scalars(select(PaymentIntent.status))) == {"pending": 1, "cancelled": 1}
    templates = Counter(db.scalars(select(Notification.template)))
    assert templates["order.seller_confirmed"] == 1
    assert templates["order.seller_declined"] == 1


def test_every_status_change_is_in_the_log_and_other_moves_are_refused(
    bazaar: Bazaar, db: DbSession
) -> None:
    """P10 criterion 2, at both layers: the service and the database."""
    _, _, order = _two_seller_order(bazaar)
    alpha_id = _part(order, "alpha")["id"]
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    # Confirmed cannot become declined, nor confirmed again.
    again = bazaar.a.post(f"{base}/confirm")
    assert error_code(again) == "order_not_awaiting_response"
    assert error_code(bazaar.a.post(f"{base}/decline", json={"reason": "Too late"})) == (
        "order_not_awaiting_response"
    )
    events = db.scalars(
        select(OrderStatusEvent.to_status)
        .where(OrderStatusEvent.seller_order_id == uuid.UUID(alpha_id))
        .order_by(OrderStatusEvent.occurred_at)
    )
    assert list(events) == ["placed", "confirmed"]

    # Plain SQL, as the application role: the trigger refuses an arrow that
    # is not in the diagram ...
    with pytest.raises(IntegrityError, match="cannot move from confirmed to placed"):
        db.execute(text("update seller_orders set status = 'placed'"))
    db.rollback()
    # ... a seller order that does not start as placed ...
    with pytest.raises(IntegrityError, match="starts as placed"):
        db.execute(
            text(
                """
                insert into seller_orders
                  (id, order_id, seller_id, status, items_total_santim, delivery_fee_santim,
                   total_santim, response_deadline)
                select gen_random_uuid(), order_id, seller_id, 'confirmed', 1, 0, 1, now()
                  from seller_orders limit 1
                """
            )
        )
    db.rollback()
    # ... and, at commit, a legal move that wrote no status event.
    db.execute(text("update seller_orders set status = 'ready' where status = 'confirmed'"))
    with pytest.raises(IntegrityError, match="has no status event"):
        db.commit()
    db.rollback()
    assert db.scalar(select(SellerOrder.status).where(SellerOrder.id == uuid.UUID(alpha_id))) == (
        "confirmed"
    )


def test_the_database_and_the_code_agree_on_every_move(bazaar: Bazaar, db: DbSession) -> None:
    states = sorted(ALLOWED_MOVES)
    allowed_by_database = {
        (a, b): db.scalar(
            text("select markx_seller_order_move_allowed(:a, :b)"), {"a": a.value, "b": b.value}
        )
        for a in states
        for b in states
    }
    assert len(allowed_by_database) == 196
    for (a, b), allowed in allowed_by_database.items():
        assert allowed is (b in ALLOWED_MOVES[a]), (a, b)


# -- what the server decides, and the browser cannot ---------------------------------------


def test_the_order_keeps_its_own_copy_of_the_catalogue(bazaar: Bazaar, db: DbSession) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    db.execute(text("update product_translations set name = 'Renamed' where language = 'am'"))
    db.commit()
    bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}", json={"price_santim": 9_999_999}
    )
    bazaar.b.delete(f"/seller/{bazaar.b_id}/offers/{bazaar.b128['id']}")
    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert _part(mine, "alpha")["items"][0]["title"] == "ሳምሰንግ ጋላክሲ A16"
    assert _part(mine, "alpha")["items"][0]["unit_price_santim"] == 1_850_000
    assert mine["grand_total_santim"] == 5_505_000
    assert _part(mine, "beta")["items"][0]["title"] == "ሳምሰንግ ጋላክሲ A16"


def test_the_commission_rate_in_force_is_copied_onto_the_line(
    bazaar: Bazaar, db: DbSession
) -> None:
    """Blueprint D.19 and J.8: the most specific rule wins, the rate is
    stored with the line, and no rule means no fee. Direct orders carry a
    zero rate in year one because no direct rule exists."""
    _before_rules, _, early = _two_seller_order(bazaar)
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(bazaar.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.add(
        CommissionRule(
            scope="seller", payment_kind="direct", seller_id=uuid.UUID(bazaar.b_id), rate_bps=150
        )
    )
    db.commit()
    _, _, later = _two_seller_order(bazaar)

    rates = {
        (str(so.seller_id), so.order_id): item.commission_bps
        for item, so in db.execute(
            select(OrderItem, SellerOrder).join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        ).all()
    }  # fmt: skip
    assert rates == {
        (bazaar.a_id, uuid.UUID(early["id"])): 0,
        (bazaar.b_id, uuid.UUID(early["id"])): 0,
        (bazaar.a_id, uuid.UUID(later["id"])): 300,  # the category rule
        (bazaar.b_id, uuid.UUID(later["id"])): 150,  # Beta's own rule wins over it
    }
    # The seller sees the fee in birr before confirming (D.19): 3% of 37,000.
    alpha_orders = bazaar.a.get(f"/seller/{bazaar.a_id}/orders").json()
    assert [o["estimated_fee_santim"] for o in alpha_orders] == [111_000, 0]


def test_delivery_choices_are_checked_against_what_the_store_offers(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    add_to_cart(buyer, bazaar.b128["id"], 1)
    missing = checkout(buyer, address_id, {"alpha": "seller_rider"}, expected_total=1)
    assert missing.status_code == 422
    assert error_code(missing) == "delivery_choice_missing"
    assert missing.json()["error"]["details"] == {
        "store_slug": "beta", "methods": ["shop_collection"],
    }  # fmt: skip
    # Beta has no rider; Alpha does not use the partner courier.
    for choices in (
        {"alpha": "seller_rider", "beta": "seller_rider"},
        {"alpha": "partner_courier", "beta": "shop_collection"},
    ):
        response = checkout(buyer, address_id, choices, expected_total=1)
        assert response.status_code == 409
        assert error_code(response) == "delivery_method_unavailable"
    unknown = checkout(
        buyer, address_id,
        {"alpha": "seller_rider", "beta": "shop_collection", "gamma": "shop_collection"},
        expected_total=1,
    )  # fmt: skip
    assert error_code(unknown) == "delivery_choice_unknown"
    quote = buyer.post(
        "/checkout/quote",
        json={
            "address_id": address_id,
            "deliveries": [
                {"store_slug": "alpha", "method": "shop_collection"},
                {"store_slug": "beta", "method": "shop_collection"},
            ],
        },
    ).json()
    assert (quote["delivery_total_santim"], quote["grand_total_santim"]) == (
        0,
        5_490_000 - 1_850_000,
    )
    assert {g["store_slug"]: g["seller_legal_name"] for g in quote["groups"]} == {
        "alpha": "Abebe Electronics PLC", "beta": "Abebe Electronics PLC",
    }  # fmt: skip


def test_an_empty_cart_or_someone_elses_address_cannot_be_ordered(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    assert error_code(checkout(buyer, address_id, {}, expected_total=1)) == "cart_empty"
    _other, other_address = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    response = checkout(buyer, other_address, {"alpha": "seller_rider"}, expected_total=1)
    assert response.status_code == 404
    assert error_code(response) == "address_not_found"
    nobody = checkout(buyer, str(uuid.uuid4()), {"alpha": "seller_rider"}, expected_total=1)
    strip = re.compile(r'"request_id":"[^"]+"')
    assert strip.sub("", nobody.text) == strip.sub("", response.text)


def test_a_seller_cannot_order_from_its_own_store(bazaar: Bazaar) -> None:
    address = bazaar.a.post(
        "/me/addresses",
        json={
            "recipient_name": "Abebe", "phone": "0911000001", "delivery_area_id": bazaar.area_id,
            "landmark": "The shop itself",
        },
    ).json()  # fmt: skip
    add_to_cart(bazaar.a, bazaar.a128["id"], 1)
    add_to_cart(bazaar.a, bazaar.b128["id"], 1)
    response = checkout(
        bazaar.a, address["id"], {"alpha": "shop_collection", "beta": "shop_collection"}
    )
    assert response.status_code == 403
    assert error_code(response) == "own_store"
    assert response.json()["error"]["details"] == {"store_slugs": ["alpha"]}


def test_limits_on_open_orders_and_order_value(bazaar: Bazaar, db: DbSession) -> None:
    settings_store.set_setting(db, "orders.max_open_direct_orders", 1)
    db.commit()
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    first = checkout(buyer, address_id, {"alpha": "seller_rider"})
    assert first.status_code == 201
    add_to_cart(buyer, bazaar.b128["id"], 1)
    second = checkout(buyer, address_id, {"beta": "shop_collection"})
    assert error_code(second) == "too_many_open_orders"
    # Cancelling the open one makes room.
    so_id = first.json()["seller_orders"][0]["id"]
    cancelled = buyer.post(f"/me/orders/{first.json()['id']}/seller-orders/{so_id}/cancel", json={})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert checkout(buyer, address_id, {"beta": "shop_collection"}).status_code == 201

    settings_store.set_setting(db, "orders.max_order_value_santim", 100)
    db.commit()
    other, other_address = bazaar.buyer()
    add_to_cart(other, bazaar.a128["id"], 1)
    assert error_code(checkout(other, other_address, {"alpha": "seller_rider"})) == (
        "order_too_large"
    )


# -- the seller's side ----------------------------------------------------------------


def test_the_seller_sees_only_its_own_part_and_the_buyers_phone_only_after_confirming(
    bazaar: Bazaar,
) -> None:
    """Blueprint C.5 and G.11."""
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]

    listed = bazaar.a.get(f"/seller/{bazaar.a_id}/orders").json()
    assert [o["id"] for o in listed] == [alpha_id]
    (alpha,) = listed
    assert alpha["order_code"] == order["code"]
    assert alpha["total_santim"] == 3_715_000  # Alpha's part, never the buyer's grand total
    assert [i["offer_id"] for i in alpha["items"]] == [bazaar.a128["id"]]
    assert alpha["buyer"] is None
    assert alpha["delivery_area"]["zone_code"] == "bole"
    assert "+251911555001" not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{alpha_id}").text
    assert "beta" not in str(alpha).lower()
    # Nor does the buyer see the seller's phone yet.
    assert _part(buyer.get(f"/me/orders/{order['id']}").json(), "alpha")["seller_contact"] is None

    bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm")
    alpha = bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{alpha_id}").json()
    assert alpha["buyer"] == {
        "recipient_name": "Sara Bekele", "phone": "+251911555001", "phone2": None,
        "landmark": "Behind Edna Mall, the blue gate", "latitude": None, "longitude": None,
        "driver_notes": "Call when you reach the gate",
    }  # fmt: skip
    mine = buyer.get(f"/me/orders/{order['id']}").json()
    assert _part(mine, "alpha")["seller_contact"] == {
        "phone": "+251911000001", "shop_address": "Bole Medhanialem, Alem Building, shop 12",
    }  # fmt: skip
    assert _part(mine, "beta")["seller_contact"] is None

    # Beta's part is not reachable through Alpha, under either seller id.
    assert bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{beta_id}").status_code == 404
    assert error_code(bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{beta_id}")) == "order_not_found"
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{beta_id}/confirm").status_code == 404
    assert bazaar.a.post(f"/seller/{bazaar.b_id}/orders/{beta_id}/confirm").status_code == 404
    # A declined order hides the phone again.
    bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{beta_id}/decline", json={"reason": "No stock"})
    assert bazaar.b.get(f"/seller/{bazaar.b_id}/orders/{beta_id}").json()["buyer"] is None


def test_one_buyer_never_sees_anothers_order(bazaar: Bazaar) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    other, _ = bazaar.buyer()
    assert [o["id"] for o in buyer.get("/me/orders").json()] == [order["id"]]
    assert other.get("/me/orders").json() == []
    theirs = other.get(f"/me/orders/{order['id']}")
    nobody = other.get(f"/me/orders/{uuid.uuid4()}")
    assert theirs.status_code == nobody.status_code == 404
    strip = re.compile(r'"request_id":"[^"]+"')
    assert strip.sub("", theirs.text) == strip.sub("", nobody.text)
    so_id = _part(order, "alpha")["id"]
    cancel = other.post(f"/me/orders/{order['id']}/seller-orders/{so_id}/cancel", json={})
    assert cancel.status_code == 404
    assert ApiClient().get(f"/me/orders/{order['id']}").status_code == 401
    assert buyer.get(f"/me/orders/{order['id']}").json()["status"] == "placed"


def test_who_may_answer_an_order(bazaar: Bazaar, db: DbSession) -> None:
    _, _, order = _two_seller_order(bazaar)
    alpha_id = _part(order, "alpha")["id"]
    bazaar.a.post(f"/seller/{bazaar.a_id}/members", json={"phone": "0911000050"})
    manager = ApiClient()
    manager.sign_in("0911000050")
    assert manager.get(f"/seller/{bazaar.a_id}/orders").status_code == 200
    # A member whose role does not handle orders is refused (blueprint C.3).
    db.execute(
        text("update seller_members set role = 'finance' where user_id = :user_id"),
        {"user_id": db.scalar(select(User.id).where(User.phone == "+251911000050"))},
    )
    db.commit()
    for response in (
        manager.get(f"/seller/{bazaar.a_id}/orders"),
        manager.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm"),
    ):
        assert response.status_code == 403
        assert error_code(response) == "permission_denied"
    # Nor can the service layer be talked into it.
    seller = db.get(Seller, uuid.UUID(bazaar.a_id))
    member = db.scalar(select(SellerMember).where(SellerMember.role == "finance"))
    assert seller is not None
    assert member is not None
    with pytest.raises(Exception, match="does not allow"):
        service.seller_respond(db, seller, member, uuid.UUID(alpha_id), accept=True)
    db.rollback()

    assert (
        error_code(
            bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/decline", json={"reason": "x"})
        )
        == "validation_failed"
    )
    bazaar.staff.post(f"/admin/sellers/{bazaar.a_id}/suspend", json={"reason": "Under review"})
    assert error_code(bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm")) == (
        "seller_not_active"
    )
    assert db.scalar(select(SellerOrder.status).where(SellerOrder.id == uuid.UUID(alpha_id))) == (
        "placed"
    )


def test_an_answer_after_the_deadline_is_refused(bazaar: Bazaar, db: DbSession) -> None:
    _, _, order = _two_seller_order(bazaar)
    alpha_id = _part(order, "alpha")["id"]
    deadline = datetime.fromisoformat(_part(order, "alpha")["response_deadline"])
    seller = db.get(Seller, uuid.UUID(bazaar.a_id))
    owner = db.scalar(select(SellerMember).where(SellerMember.seller_id == seller.id))  # type: ignore[union-attr]
    assert seller is not None
    assert owner is not None
    with pytest.raises(Exception, match="time to answer"):
        service.seller_respond(
            db, seller, owner, uuid.UUID(alpha_id), accept=True, now=deadline + timedelta(seconds=1)
        )
    db.rollback()
    confirmed = service.seller_respond(
        db, seller, owner, uuid.UUID(alpha_id), accept=True, now=deadline - timedelta(seconds=1)
    )
    assert confirmed.status == "confirmed"
    db.rollback()


def test_the_buyer_cancels_before_dispatch_and_the_stock_returns(
    bazaar: Bazaar, db: DbSession
) -> None:
    buyer, _, order = _two_seller_order(bazaar)
    alpha_id, beta_id = _part(order, "alpha")["id"], _part(order, "beta")["id"]
    bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{alpha_id}/confirm")
    base = f"/me/orders/{order['id']}/seller-orders"
    cancelled = buyer.post(f"{base}/{alpha_id}/cancel", json={"reason": "Found it cheaper"})
    assert cancelled.status_code == 200, cancelled.text
    assert _part(cancelled.json(), "alpha")["status"] == "cancelled"
    assert _part(cancelled.json(), "alpha")["closed_reason"] == "Found it cheaper"
    assert _part(cancelled.json(), "alpha")["seller_contact"] is None
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert stock(db, bazaar.b128["id"]) == (5, 1)
    assert_stock_is_consistent(db)
    assert error_code(buyer.post(f"{base}/{alpha_id}/cancel", json={})) == (
        "order_cannot_be_cancelled"
    )
    assert Counter(db.scalars(select(Notification.template)))["order.cancelled_by_buyer"] == 1
    # The other seller's part is untouched.
    assert bazaar.b.get(f"/seller/{bazaar.b_id}/orders/{beta_id}").json()["status"] == "placed"


def test_orders_are_listed_newest_first_with_a_cursor(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    codes = []
    for _ in range(3):
        add_to_cart(buyer, bazaar.b128["id"], 1)
        codes.append(checkout(buyer, address_id, {"beta": "shop_collection"}).json()["code"])
    page = buyer.get("/me/orders", params={"limit": 2}).json()
    assert [o["code"] for o in page] == codes[::-1][:2]
    rest = buyer.get("/me/orders", params={"limit": 2, "before": page[-1]["id"]}).json()
    assert [o["code"] for o in rest] == [codes[0]]
    sellers_view = bazaar.b.get(f"/seller/{bazaar.b_id}/orders", params={"status": "placed"}).json()
    assert [o["order_code"] for o in sellers_view] == codes[::-1]
    assert (
        bazaar.b.get(f"/seller/{bazaar.b_id}/orders", params={"status": "confirmed"}).json() == []
    )


def test_a_used_item_from_a_level_one_seller_is_never_in_an_order(bazaar: Bazaar) -> None:
    """The publishing rule holds at checkout, not only on the product page:
    an offer that buyers should not see is refused even if its id is known."""
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    bazaar.staff.post(
        f"/admin/sellers/{bazaar.a_id}/verification-level",
        json={"level": 1, "reason": "Licence expired"},
    )
    response = checkout(buyer, address_id, {"alpha": "seller_rider"}, expected_total=1)
    assert error_code(response) == "cart_item_unavailable"
    assert response.json()["error"]["details"]["items"] == [
        {"offer_id": bazaar.a128["id"], "reason": "seller_not_available"}
    ]
    offer = make_offer(bazaar.b, bazaar.b_id, bazaar.v256, quantity=1)
    bazaar.b.post(f"/seller/{bazaar.b_id}/offers/{offer['id']}/pause")
    assert error_code(buyer.put(f"/cart/items/{offer['id']}", json={"quantity": 1})) == (
        "offer_not_found"
    )
