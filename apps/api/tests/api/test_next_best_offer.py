"""The next-best offer when a seller declines or stays silent (blueprint C-26,
D.11): the buyer is pointed at the best offer in stock for the same variant
from another seller, ranked as on the product page.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.notifications.models import Notification
from markx.worker.runner import run_once
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _order(
    bazaar: Bazaar, offer_id: str, store: str, method: str, quantity: int = 1
) -> tuple[ApiClient, dict[str, Any]]:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, offer_id, quantity)
    response = checkout(buyer, address_id, {store: method})
    assert response.status_code == 201, response.text
    return buyer, dict(response.json())


def _suggestions(db: DbSession) -> list[dict[str, Any]]:
    db.rollback()
    return [
        dict(params)
        for params in db.scalars(
            select(Notification.params).where(Notification.template == "order.next_best_offer")
        )
    ]


def _alternatives(buyer: ApiClient, order: dict[str, Any]) -> Any:
    part = order["seller_orders"][0]
    return buyer.get(f"/me/orders/{order['id']}/seller-orders/{part['id']}/alternatives")


def test_beta_declines_and_alpha_is_suggested(bazaar: Bazaar, db: DbSession) -> None:
    buyer, order = _order(bazaar, bazaar.b128["id"], "beta", "shop_collection")
    part = order["seller_orders"][0]
    # While Beta may still answer there is nothing to suggest.
    assert _alternatives(buyer, order).json() == []

    declined = bazaar.b.post(
        f"/seller/{bazaar.b_id}/orders/{part['id']}/decline", json={"reason": "Sold out"}
    )
    assert declined.status_code == 200, declined.text

    (suggestion,) = _suggestions(db)
    assert suggestion == {
        "order_id": order["id"],
        "seller_order_id": part["id"],
        "order_code": order["code"],
        "order_item_id": part["items"][0]["id"],
        "variant_id": bazaar.v128,
        "product_slug": bazaar.product["slug"],
        "offer_id": bazaar.a128["id"],
    }
    (alternative,) = _alternatives(buyer, order).json()
    assert alternative["order_item_id"] == part["items"][0]["id"]
    assert alternative["quantity"] == 1
    assert alternative["offer"]["id"] == bazaar.a128["id"]
    assert alternative["offer"]["store_slug"] == "alpha"
    assert alternative["offer"]["price_santim"] == 1_850_000
    # Beta's own offer is back in stock after the decline, and is still never
    # the suggestion: the seller that failed is left out.
    assert bazaar.b128["id"] not in str(_alternatives(buyer, order).json())


def test_alpha_stays_silent_and_beta_is_suggested(bazaar: Bazaar, db: DbSession) -> None:
    buyer, order = _order(bazaar, bazaar.a128["id"], "alpha", "seller_rider", quantity=2)
    part = order["seller_orders"][0]
    deadline = datetime.fromisoformat(part["response_deadline"])
    report = run_once(deadline + timedelta(minutes=2))
    assert {o.name: o.result for o in report.jobs}["orders.expire_unanswered"] == 1

    (suggestion,) = _suggestions(db)
    assert suggestion["offer_id"] == bazaar.b128["id"]
    assert suggestion["seller_order_id"] == part["id"]
    (alternative,) = _alternatives(buyer, order).json()
    assert (alternative["offer"]["store_slug"], alternative["quantity"]) == ("beta", 2)


def test_nothing_is_suggested_when_no_other_seller_has_it(bazaar: Bazaar, db: DbSession) -> None:
    # Only Alpha sells the 256 GB.
    buyer, order = _order(bazaar, bazaar.a256["id"], "alpha", "seller_rider")
    part = order["seller_orders"][0]
    assert (
        bazaar.a.post(
            f"/seller/{bazaar.a_id}/orders/{part['id']}/decline", json={"reason": "Sold out"}
        ).status_code
        == 200
    )
    assert _suggestions(db) == []
    assert _alternatives(buyer, order).json() == []


def test_an_offer_out_of_stock_is_not_suggested(bazaar: Bazaar, db: DbSession) -> None:
    # Someone else holds all five of Alpha's 128 GB.
    _order(bazaar, bazaar.a128["id"], "alpha", "seller_rider", quantity=5)
    buyer, order = _order(bazaar, bazaar.b128["id"], "beta", "shop_collection")
    part = order["seller_orders"][0]
    assert (
        bazaar.b.post(
            f"/seller/{bazaar.b_id}/orders/{part['id']}/decline", json={"reason": "Sold out"}
        ).status_code
        == 200
    )
    assert _suggestions(db) == []
    assert _alternatives(buyer, order).json() == []


def test_alternatives_belong_to_the_buyer_alone(bazaar: Bazaar) -> None:
    buyer, order = _order(bazaar, bazaar.b128["id"], "beta", "shop_collection")
    part = order["seller_orders"][0]
    bazaar.b.post(f"/seller/{bazaar.b_id}/orders/{part['id']}/decline", json={"reason": "Sold out"})
    stranger, _ = bazaar.buyer()
    response = _alternatives(stranger, order)
    assert response.status_code == 404
    assert error_code(response) == "order_not_found"
    assert _alternatives(ApiClient(), order).status_code == 401
    assert len(_alternatives(buyer, order).json()) == 1
