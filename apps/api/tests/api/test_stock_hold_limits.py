"""Limits against holding a rival shop's stock (H2, D-099).

Every order holds its units at once, until the shop answers or its response
window passes. Before D-099 one buyer could hold up to twenty units of an
offer with a single unanswered order, and order and cancel again and again
without limit, so a cheap account could keep a competitor's stock held.

Now, PROVISIONAL (P-099-3 to P-099-6): one buyer's unanswered orders may hold
at most 5 units of one offer and 10 units of one shop; and a buyer who
cancelled 3 orders within 24 hours may not place another until the oldest of
those is 24 hours old. Ordinary buying is untouched: other buyers are not
limited by one buyer's orders, a confirmed order no longer counts, and a
shop's decline or an expiry is never held against the buyer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.core import settings_store
from markx.core.db import session_scope
from markx.core.errors import Conflict
from markx.orders import service
from markx.orders.models import OrderStatusEvent
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, new_idempotency_key


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=20)


def _order(buyer: ApiClient, address_id: str, *lines: tuple[str, int]) -> Any:
    """Fill the cart with exactly these lines and check out."""
    assert buyer.delete("/cart").status_code == 200
    for offer_id, quantity in lines:
        add_to_cart(buyer, offer_id, quantity)
    stores = {group["store_slug"] for group in buyer.get("/cart").json()["groups"]}
    methods = {"alpha": "seller_rider", "beta": "shop_collection"}
    return checkout(buyer, address_id, {slug: methods[slug] for slug in stores})


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 201, response.text
    return dict(response.json())


def _part(order: dict[str, Any], slug: str) -> str:
    return str(next(p["id"] for p in order["seller_orders"] if p["store_slug"] == slug))


def _cancel(buyer: ApiClient, order: dict[str, Any], slug: str) -> None:
    response = buyer.post(
        f"/me/orders/{order['id']}/seller-orders/{_part(order, slug)}/cancel", json={}
    )
    assert response.status_code == 200, response.text


# -- per offer, per shop --------------------------------------------------------------------


def test_one_buyer_may_hold_at_most_five_units_of_an_offer_before_the_shop_answers(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address = bazaar.buyer()

    refused = _order(buyer, address, (bazaar.a128["id"], 6))
    assert refused.status_code == 409
    assert error_code(refused) == "unconfirmed_offer_limit"
    assert refused.json()["error"]["details"] == {"offer_id": bazaar.a128["id"], "limit": 5}
    assert stock(db, bazaar.a128["id"]) == (20, 0)  # nothing was held

    _ok(_order(buyer, address, (bazaar.a128["id"], 5)))
    # A second order for the same offer counts with the first while it waits.
    assert error_code(_order(buyer, address, (bazaar.a128["id"], 1))) == "unconfirmed_offer_limit"
    assert stock(db, bazaar.a128["id"]) == (20, 5)
    assert_stock_is_consistent(db)
    # The default (PROVISIONAL, D-099).
    assert settings_store.get_int(db, "orders.max_unconfirmed_units_per_offer") == 5


def test_once_the_shop_confirms_or_declines_the_buyer_may_order_again(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address = bazaar.buyer()
    first = _ok(_order(buyer, address, (bazaar.a128["id"], 5)))
    confirmed = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{_part(first, 'alpha')}/confirm", json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    # An answered order no longer counts: an ordinary buyer is never stuck.
    second = _ok(_order(buyer, address, (bazaar.a128["id"], 5)))
    declined = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{_part(second, 'alpha')}/decline",
        json={"reason": "Only the display unit is left"},
    )
    assert declined.status_code == 200, declined.text
    _ok(_order(buyer, address, (bazaar.a128["id"], 5)))
    assert stock(db, bazaar.a128["id"]) == (20, 10)
    assert_stock_is_consistent(db)


def test_one_buyer_may_hold_at_most_ten_units_of_one_shop_before_it_answers(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address = bazaar.buyer()
    _ok(_order(buyer, address, (bazaar.a128["id"], 5), (bazaar.a256["id"], 4)))
    # Alpha's two offers together: 9 waiting, one more is the limit.
    refused = _order(buyer, address, (bazaar.a256["id"], 1), (bazaar.a128["id"], 1))
    assert error_code(refused) == "unconfirmed_offer_limit"  # a128 alone is at 5
    _ok(_order(buyer, address, (bazaar.a256["id"], 1)))
    # The shop's limit is a setting, and another shop is not affected by it.
    settings_store.set_setting(db, "orders.max_unconfirmed_units_per_seller", 6)
    db.commit()
    other, other_address = bazaar.buyer()
    _ok(_order(other, other_address, (bazaar.a128["id"], 4)))
    refused = _order(other, other_address, (bazaar.a256["id"], 3))
    assert refused.status_code == 409
    assert error_code(refused) == "unconfirmed_store_limit"
    assert refused.json()["error"]["details"] == {"store_slug": "alpha", "limit": 6}
    _ok(_order(other, other_address, (bazaar.b128["id"], 3)))
    assert_stock_is_consistent(db)
    # The default (PROVISIONAL, D-099).
    assert settings_store.SETTINGS["orders.max_unconfirmed_units_per_seller"].default == 10


def test_other_buyers_are_not_limited_by_one_buyers_waiting_orders(
    bazaar: Bazaar, db: Session
) -> None:
    """The limits are per buyer, so a rival filling them cannot lock others out."""
    first, first_address = bazaar.buyer()
    second, second_address = bazaar.buyer()
    _ok(_order(first, first_address, (bazaar.a128["id"], 5)))
    _ok(_order(second, second_address, (bazaar.a128["id"], 5)))
    assert stock(db, bazaar.a128["id"]) == (20, 10)


# -- the cool-down after repeated cancellations -----------------------------------------------


def _user(db: Session, buyer: ApiClient) -> User:
    user = db.get(User, uuid.UUID(buyer.get("/me").json()["id"]))
    assert user is not None
    return user


def _place_at(buyer_id: uuid.UUID, address_id: str, offer_id: str, now: datetime) -> None:
    with session_scope() as session:
        user = session.get(User, buyer_id)
        assert user is not None
        cart = service.user_cart(session, user.id, create=True)
        assert cart is not None
        service.clear_cart(session, cart)
        service.set_cart_item(session, cart, uuid.UUID(offer_id), 1)
    with session_scope() as session:
        user = session.get(User, buyer_id)
        assert user is not None
        service.place_order(
            session, user, address_id=uuid.UUID(address_id),
            deliveries={"beta": "shop_collection"}, payment_method="cash",
            expected_total_santim=1_790_000, idempotency_key=new_idempotency_key(), now=now,
        )  # fmt: skip


def test_three_cancellations_in_a_day_pause_new_orders_until_the_first_is_a_day_old(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address = bazaar.buyer()
    for _ in range(3):
        order = _ok(_order(buyer, address, (bazaar.b128["id"], 1)))
        _cancel(buyer, order, "beta")

    refused = _order(buyer, address, (bazaar.b128["id"], 1))
    assert refused.status_code == 409
    assert error_code(refused) == "cancellation_cooldown"
    assert stock(db, bazaar.b128["id"]) == (20, 0)

    db.rollback()
    first_cancel = db.scalar(
        select(func.min(OrderStatusEvent.occurred_at)).where(
            OrderStatusEvent.to_status == "cancelled"
        )
    )
    assert first_cancel is not None
    again_at = datetime.fromisoformat(refused.json()["error"]["details"]["order_again_at"])
    assert again_at == first_cancel + timedelta(hours=24)

    # Another buyer is not affected.
    other, other_address = bazaar.buyer()
    _ok(_order(other, other_address, (bazaar.b128["id"], 1)))

    # Just before that moment still refused; just after it, allowed.
    buyer_id = _user(db, buyer).id
    with pytest.raises(Conflict) as early:
        _place_at(buyer_id, address, bazaar.b128["id"], again_at - timedelta(seconds=1))
    assert early.value.code == "cancellation_cooldown"
    _place_at(buyer_id, address, bazaar.b128["id"], again_at + timedelta(seconds=1))
    assert_stock_is_consistent(db)
    # The default (PROVISIONAL, D-099).
    assert settings_store.get_int(db, "orders.cancellations_before_cooldown") == 3
    assert settings_store.get_int(db, "orders.cancellation_cooldown_hours") == 24


def test_an_ordinary_buyer_who_cancels_now_and_then_is_never_paused(
    bazaar: Bazaar, db: Session
) -> None:
    """Two cancellations in a day are fine; an order of two shops cancelled
    in full counts once; a shop's decline is never held against the buyer."""
    buyer, address = bazaar.buyer()
    both = _ok(_order(buyer, address, (bazaar.a128["id"], 1), (bazaar.b128["id"], 1)))
    _cancel(buyer, both, "alpha")
    _cancel(buyer, both, "beta")
    single = _ok(_order(buyer, address, (bazaar.b128["id"], 1)))
    _cancel(buyer, single, "beta")
    for _ in range(2):
        order = _ok(_order(buyer, address, (bazaar.a128["id"], 1)))
        declined = bazaar.a.post(
            f"/seller/{bazaar.a_id}/orders/{_part(order, 'alpha')}/decline",
            json={"reason": "Sold at the counter"},
        )
        assert declined.status_code == 200, declined.text
    _ok(_order(buyer, address, (bazaar.b128["id"], 1)))


def test_the_new_limits_are_provisional_settings(db: Session) -> None:
    for key in (
        "orders.out_for_delivery_limit_hours",
        "orders.delivery_failed_limit_hours",
        "orders.max_unconfirmed_units_per_offer",
        "orders.max_unconfirmed_units_per_seller",
        "orders.cancellations_before_cooldown",
        "orders.cancellation_cooldown_hours",
    ):
        spec = settings_store.SETTINGS[key]
        assert spec.description.startswith("PROVISIONAL (P-099-"), key
