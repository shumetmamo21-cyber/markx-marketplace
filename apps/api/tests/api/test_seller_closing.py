"""Closing a store (blueprint G.1, C.3; D-076): final, by the owner only, and
never while the store still has orders in progress, since a closed store can
no longer act on them.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def test_a_store_with_an_order_in_progress_cannot_close_until_it_is_finished(
    bazaar: Bazaar,
) -> None:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    placed = checkout(buyer, address_id, {"alpha": "shop_collection"})
    assert placed.status_code == 201, placed.text
    (part,) = placed.json()["seller_orders"]

    refused = bazaar.a.post(f"/seller/{bazaar.a_id}/close")
    assert refused.status_code == 409
    assert error_code(refused) == "open_orders_remain"
    assert refused.json()["error"]["details"] == {"open_orders": 1}
    assert ApiClient().get("/catalog/stores/alpha").status_code == 200  # still trading

    # Accepted, the order is still in progress; declined, it is finished.
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{part['id']}/confirm").status_code == 200
    assert error_code(bazaar.a.post(f"/seller/{bazaar.a_id}/close")) == "open_orders_remain"
    cancelled = buyer.post(
        f"/me/orders/{placed.json()['id']}/seller-orders/{part['id']}/cancel", json={}
    )
    assert cancelled.status_code == 200, cancelled.text

    closed = bazaar.a.post(f"/seller/{bazaar.a_id}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert ApiClient().get("/catalog/stores/alpha").status_code == 404


def test_another_stores_orders_do_not_hold_this_one_open(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.b128["id"], 1)
    assert checkout(buyer, address_id, {"beta": "shop_collection"}).status_code == 201
    assert bazaar.a.post(f"/seller/{bazaar.a_id}/close").status_code == 200
    assert error_code(bazaar.b.post(f"/seller/{bazaar.b_id}/close")) == "open_orders_remain"
