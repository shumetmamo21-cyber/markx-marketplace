"""A guest cancels from the tracking link, before the shop answers (F-28; D-109).

The founder's decision of 25 November 2026: a guest may cancel their own
order from the tracking link, but only before the shop answers. The stock
held for it goes back at once. After the shop answers, there is no cancel
button. A signed-in buyer's link still never acts (D-048): they cancel from
their own page, as before. Because a guest may now cancel, the cancellation
cool-down (D-099) counts for guests too, per phone number and per network
address, as every other buying limit does (D-108).

Every test here fails on the code before D-109: the cancel route is new,
and the tracking view never offered a guest a cancel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from markx.core import settings_store
from markx.core.db import session_scope
from markx.notifications.models import Notification
from markx.orders import service
from markx.orders.models import OrderStatusEvent
from tests.api.test_d108_guest_checkout import (
    RIDER,
    _alpha_part,
    _guest_order,
    _place,
    _shop_view,
    _split,
    _stored,
    _track,
)
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, address_body, checkout

# These tests run with what MarkX ships: 30 new-account days (F-27).
pytestmark = pytest.mark.founders_new_account_days


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _cancel(path: str, part_id: Any, *, client: ApiClient | None = None, **override: str) -> Any:
    """Cancel one shop's part through the tracking link `path`, as the page does."""
    route, params = _split(path)
    return (client or ApiClient()).post(
        f"{route}/seller-orders/{part_id}/cancel", params={**params, **override, "lang": "en"}
    )


def _handlers(db: DbSession, seller_id: str) -> set[uuid.UUID]:
    db.rollback()
    return {
        uuid.UUID(row)
        for row in db.scalars(
            text("select user_id::text from seller_members where seller_id = :id"),
            {"id": seller_id},
        )
    }


def test_a_guest_cancels_from_the_link_before_the_shop_answers_and_the_stock_is_back_at_once(
    bazaar: Bazaar, db: DbSession
) -> None:
    _, placed = _guest_order(bazaar, quantity=2)
    assert stock(db, bazaar.a128["id"]) == (5, 2)
    part = _alpha_part(db, _stored(db, placed["order_code"]))
    before = _track(placed["tracking_path"])["seller_orders"][0]
    assert (before["status"], before["can_cancel"]) == ("placed", True)
    # The one action a guest has (F-28): no "the goods are right", no problem report.
    assert (before["can_confirm_received"], before["can_report_problem"]) == (False, False)

    cancelled = _cancel(placed["tracking_path"], part.id)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.headers["cache-control"] == "no-store"
    view = cancelled.json()
    assert view["status"] == "cancelled"
    assert view["tracking_path"] is None
    after = view["seller_orders"][0]
    assert (after["status"], after["can_cancel"], after["handover_code"]) == (
        "cancelled",
        False,
        None,
    )
    # The stock held for the guest is back at once, not when a job runs.
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert_stock_is_consistent(db)
    # Recorded as the buyer's own cancellation, by no account.
    db.rollback()
    event = db.scalar(
        select(OrderStatusEvent).where(
            OrderStatusEvent.seller_order_id == part.id, OrderStatusEvent.to_status == "cancelled"
        )
    )
    assert event is not None
    assert (event.actor_type, event.actor_user_id, event.reason) == (
        "buyer",
        None,
        "cancelled_by_buyer",
    )
    # The shop's people are told, as for any buyer's cancellation; nobody else.
    told = db.scalars(
        select(Notification).where(Notification.template == "order.cancelled_by_buyer")
    ).all()
    assert told
    assert {n.user_id for n in told} <= _handlers(db, bazaar.a_id)
    # The link still opens the order, cancelled and with no button.
    again = _track(placed["tracking_path"])["seller_orders"][0]
    assert (again["status"], again["can_cancel"]) == ("cancelled", False)
    # Pressing again is refused in words, and changes nothing.
    assert error_code(_cancel(placed["tracking_path"], part.id)) == "order_cannot_be_cancelled"
    assert stock(db, bazaar.a128["id"]) == (5, 0)


def test_after_the_shop_answers_there_is_no_cancel(bazaar: Bazaar, db: DbSession) -> None:
    _, accepted = _guest_order(bazaar)
    _, declined = _guest_order(bazaar, phone="0911777611", ip="203.0.113.111")
    _, expiring = _guest_order(bazaar, phone="0911777612", ip="203.0.113.112")
    accepted_part = _alpha_part(db, _stored(db, accepted["order_code"]))
    declined_part = _alpha_part(db, _stored(db, declined["order_code"]))
    expiring_part = _alpha_part(db, _stored(db, expiring["order_code"]))
    shop = f"/seller/{bazaar.a_id}/orders"
    assert bazaar.a.post(f"{shop}/{accepted_part.id}/confirm").status_code == 200
    assert (
        bazaar.a.post(
            f"{shop}/{declined_part.id}/decline", json={"reason": "Out of stock today"}
        ).status_code
        == 200
    )
    # The third the shop never answers: it expires, and the guest cannot cancel it either.
    with session_scope() as session:
        later = datetime.now(UTC) + timedelta(days=7)
        assert service.expire_unanswered_orders(session, now=later) == 1
    for placed, part, status in (
        (accepted, accepted_part, "confirmed"),
        (declined, declined_part, "declined"),
        (expiring, expiring_part, "expired"),
    ):
        view = _track(placed["tracking_path"])["seller_orders"][0]
        assert (view["status"], view["can_cancel"]) == (status, False), status
        refused = _cancel(placed["tracking_path"], part.id)
        assert refused.status_code == 409, refused.text
        assert error_code(refused) == "order_cannot_be_cancelled"
        assert _track(placed["tracking_path"])["seller_orders"][0]["status"] == status
    # The accepted order's stock stays held for the guest; the others' went back.
    assert stock(db, bazaar.a128["id"]) == (5, 1)
    assert_stock_is_consistent(db)


def test_a_signed_in_buyers_link_still_never_cancels(bazaar: Bazaar, db: DbSession) -> None:
    buyer, address = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    placed = checkout(buyer, address, RIDER)
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    mine = buyer.get(f"/me/orders/{order_id}").json()
    part_id = mine["seller_orders"][0]["id"]
    # On their own page, as before (D-048).
    assert mine["seller_orders"][0]["can_cancel"] is True
    link = mine["tracking_path"]
    assert _track(link)["seller_orders"][0]["can_cancel"] is False
    refused = _cancel(link, part_id)
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "order_cannot_be_cancelled"
    # Even from the buyer's own signed-in browser: the link never acts.
    assert error_code(_cancel(link, part_id, client=buyer)) == "order_cannot_be_cancelled"
    assert buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["status"] == "placed"
    assert stock(db, bazaar.a128["id"]) == (5, 1)


def test_a_forged_expired_or_borrowed_link_cancels_nothing(bazaar: Bazaar, db: DbSession) -> None:
    _, placed = _guest_order(bazaar)
    _, other = _guest_order(bazaar, phone="0911777613", ip="203.0.113.113")
    part = _alpha_part(db, _stored(db, placed["order_code"]))
    other_part = _alpha_part(db, _stored(db, other["order_code"]))
    _, params = _split(placed["tracking_path"])
    an_hour_ago = str(int((datetime.now(UTC) - timedelta(hours=1)).timestamp()))
    for response, code in (
        (_cancel(placed["tracking_path"], part.id, signature="A" * 43), "tracking_link_invalid"),
        (_cancel(placed["tracking_path"], part.id, expires=an_hour_ago), "tracking_link_invalid"),
        # Another order's part through this order's link.
        (_cancel(placed["tracking_path"], other_part.id), "order_not_found"),
        # This link's signature on another order.
        (
            ApiClient().post(
                f"/track/{other_part.order_id}/seller-orders/{other_part.id}/cancel",
                params={**params, "lang": "en"},
            ),
            "tracking_link_invalid",
        ),
    ):
        assert response.status_code == 404, response.text
        assert error_code(response) == code
    # Like every request that changes something, it needs the MarkX app (H.2).
    forged = _cancel(placed["tracking_path"], part.id, client=ApiClient(send_client_header=False))
    assert error_code(forged) == "csrf_header_missing"
    for order in (placed, other):
        assert _track(order["tracking_path"])["seller_orders"][0]["status"] == "placed"
    assert stock(db, bazaar.a128["id"]) == (5, 2)


def test_the_shop_sees_a_guest_cancel_exactly_as_a_signed_in_buyers(
    bazaar: Bazaar, db: DbSession
) -> None:
    details = {
        "recipient_name": "Hana Tesfaye", "phone": "0911777711", "landmark": "Behind Edna Mall",
        "driver_notes": "The blue gate",
    }  # fmt: skip
    buyer = ApiClient()
    buyer.sign_in("0911777710")
    saved = buyer.post("/me/addresses", json=address_body(bazaar.area_id, **details))
    assert saved.status_code == 201, saved.text
    add_to_cart(buyer, bazaar.a128["id"], 1)
    own = checkout(buyer, saved.json()["id"], RIDER)
    assert own.status_code == 201, own.text
    _, placed = _guest_order(bazaar, **details)
    rows = bazaar.a.get(f"/seller/{bazaar.a_id}/orders").json()
    guest_part, account_part = rows  # newest first
    cancelled = buyer.post(
        f"/me/orders/{own.json()['id']}/seller-orders/{account_part['id']}/cancel", json={}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert _cancel(placed["tracking_path"], guest_part["id"]).status_code == 200
    seen = [
        bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{row['id']}").json()
        for row in (guest_part, account_part)
    ]
    assert seen[0]["status"] == "cancelled"
    assert _shop_view(seen[0]) == _shop_view(seen[1])
    listed = bazaar.a.get(f"/seller/{bazaar.a_id}/orders").json()
    assert _shop_view(listed[0]) == _shop_view(listed[1])
    assert "is_guest" not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders").text
    # The shop's people were told of both in the same words.
    db.rollback()
    alerts = db.scalars(
        select(Notification).where(Notification.template == "order.cancelled_by_buyer")
    ).all()
    assert len(alerts) == 2
    assert {tuple(sorted(n.params)) for n in alerts} == {
        ("order_code", "seller_id", "seller_order_id")
    }
    assert {n.user_id for n in alerts} == {alerts[0].user_id}


def test_the_cancellation_cool_down_counts_for_guests_per_number_and_per_address(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "orders.cancellations_before_cooldown", 2)
    db.commit()

    def place_and_cancel(phone: str, ip: str) -> None:
        _, placed = _guest_order(bazaar, phone=phone, ip=ip)
        part = _alpha_part(db, _stored(db, placed["order_code"]))
        assert _cancel(placed["tracking_path"], part.id).status_code == 200

    # One number, cancelling twice from two addresses: its third order waits.
    place_and_cancel("0911777621", "203.0.113.121")
    place_and_cancel("0911777621", "203.0.113.122")
    visitor = ApiClient(ip="203.0.113.123")
    add_to_cart(visitor, bazaar.a128["id"], 1)
    refused = _place(visitor, bazaar, phone="0911777621")
    assert error_code(refused) == "cancellation_cooldown", refused.text
    again_at = datetime.fromisoformat(refused.json()["error"]["details"]["order_again_at"])
    assert timedelta(hours=23) < again_at - datetime.now(UTC) <= timedelta(hours=24)
    # One address, two numbers cancelling once each: a third number from it waits.
    place_and_cancel("0911777631", "203.0.113.131")
    place_and_cancel("0911777632", "203.0.113.131")
    crowd = ApiClient(ip="203.0.113.131")
    add_to_cart(crowd, bazaar.a128["id"], 1)
    paused = _place(crowd, bazaar, phone="0911777633")
    assert error_code(paused) == "guest_network_cooldown", paused.text
    assert "order_again_at" in paused.json()["error"]["details"]
    # A guest's cancellations never count against an account with that number,
    # which would reveal the account (D-108).
    holder, address = bazaar.buyer("0911777621")
    add_to_cart(holder, bazaar.a128["id"], 1)
    assert checkout(holder, address, RIDER).status_code == 201
    # Nothing was held for the refused orders.
    assert stock(db, bazaar.a128["id"]) == (5, 1)
    assert_stock_is_consistent(db)


def test_the_guest_cool_down_is_marked_provisional_where_it_lives() -> None:
    service_py = Path(service.__file__).read_text(encoding="utf-8")
    assert "PROVISIONAL P-109-1" in service_py
    assert "_refuse_during_guest_cancellation_cooldown(db, by_phone, by_network, now)" in service_py
