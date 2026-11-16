"""The server-side cart (blueprint D.10, C-06, P9)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.core.security import hash_token
from markx.orders import service
from markx.orders.models import Cart, CartItem
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, make_offer, make_seller, make_zone, staff_client


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _lines(cart: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {item["offer_id"]: item for group in cart["groups"] for item in group["items"]}


# -- visitors --------------------------------------------------------------------


def test_a_visitor_builds_a_cart_without_an_account(bazaar: Bazaar, db: DbSession) -> None:
    visitor = ApiClient()
    assert visitor.get("/cart").json()["line_count"] == 0
    assert db.scalar(select(func.count()).select_from(Cart)) == 0  # reading creates nothing

    cart = add_to_cart(visitor, bazaar.a128["id"], 2)
    assert cart["line_count"] == 1
    assert cart["items_total_santim"] == 3_700_000
    assert visitor.get("/cart").json() == cart

    token = visitor.http.cookies.get("markx_cart")
    assert token is not None
    stored = db.scalar(select(Cart))
    assert stored is not None
    # Only the hash of the secret is stored, as for sessions.
    assert stored.anon_token_hash == hash_token(token)
    assert stored.user_id is None


def test_the_cart_cookie_cannot_be_read_by_scripts(bazaar: Bazaar) -> None:
    visitor = ApiClient()
    response = visitor.put(f"/cart/items/{bazaar.a128['id']}", json={"quantity": 1})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("markx_cart=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_one_visitor_cannot_see_anothers_cart(bazaar: Bazaar) -> None:
    first, second = ApiClient(), ApiClient()
    add_to_cart(first, bazaar.a128["id"], 3)
    assert second.get("/cart").json()["line_count"] == 0
    # A made-up cookie finds nothing, and cannot be used to plant a cart.
    second.http.cookies.set("markx_cart", "x" * 43)
    assert second.get("/cart").json()["line_count"] == 0
    assert first.get("/cart").json()["line_count"] == 1


def test_a_cart_cannot_be_changed_from_another_site(bazaar: Bazaar) -> None:
    forged = ApiClient(send_client_header=False)
    response = forged.put(f"/cart/items/{bazaar.a128['id']}", json={"quantity": 1})
    assert response.status_code == 403
    assert error_code(response) == "csrf_header_missing"


def test_the_cart_follows_the_visitor_through_sign_in(bazaar: Bazaar, db: DbSession) -> None:
    """Blueprint D.10: no account wall. The cart built as a visitor is the
    cart after signing in."""
    visitor = ApiClient()
    add_to_cart(visitor, bazaar.a128["id"], 2)
    add_to_cart(visitor, bazaar.b128["id"], 1)
    visitor.sign_in("0911555001")

    cart = visitor.get("/cart")
    assert cart.json()["line_count"] == 2
    assert 'markx_cart=""' in cart.headers["set-cookie"]  # the anonymous cookie is retired
    carts = list(db.scalars(select(Cart)))
    assert len(carts) == 1
    assert carts[0].user_id is not None
    assert carts[0].anon_token_hash is None
    # The same account on another device sees the same cart.
    elsewhere = ApiClient()
    elsewhere.sign_in("0911555001")
    assert _lines(elsewhere.get("/cart").json())[bazaar.a128["id"]]["quantity"] == 2


def test_merging_keeps_the_larger_quantity_and_both_carts_lines(bazaar: Bazaar) -> None:
    signed_in = ApiClient()
    signed_in.sign_in("0911555001")
    add_to_cart(signed_in, bazaar.a128["id"], 1)
    add_to_cart(signed_in, bazaar.a256["id"], 4)

    visitor = ApiClient()
    add_to_cart(visitor, bazaar.a128["id"], 3)
    add_to_cart(visitor, bazaar.b128["id"], 2)
    visitor.sign_in("0911555001")
    lines = _lines(visitor.get("/cart").json())
    assert {offer_id: line["quantity"] for offer_id, line in lines.items()} == {
        bazaar.a128["id"]: 3, bazaar.a256["id"]: 4, bazaar.b128["id"]: 2,
    }  # fmt: skip


# -- lines -----------------------------------------------------------------------


def test_add_change_remove_and_clear(bazaar: Bazaar, db: DbSession) -> None:
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    add_to_cart(buyer, bazaar.b128["id"], 2)
    cart = add_to_cart(buyer, bazaar.a128["id"], 4)  # the same offer again changes the quantity
    assert cart["line_count"] == 2
    assert _lines(cart)[bazaar.a128["id"]]["quantity"] == 4
    assert cart["items_total_santim"] == 4 * 1_850_000 + 2 * 1_790_000
    # Grouped by store, each with its own subtotal (blueprint D.10).
    assert {g["store_slug"]: g["items_total_santim"] for g in cart["groups"]} == {
        "alpha": 7_400_000, "beta": 3_580_000,
    }  # fmt: skip

    cart = buyer.delete(f"/cart/items/{bazaar.b128['id']}").json()
    assert [g["store_slug"] for g in cart["groups"]] == ["alpha"]
    assert buyer.delete("/cart").json()["line_count"] == 0
    assert db.scalar(select(func.count()).select_from(CartItem)) == 0


def test_a_line_shows_what_the_buyer_needs_and_no_exact_stock(bazaar: Bazaar) -> None:
    big = make_offer(bazaar.b, bazaar.b_id, bazaar.v256, quantity=400)
    buyer, _ = bazaar.buyer()
    line = _lines(add_to_cart(buyer, big["id"], 1))[big["id"]]
    assert line["product_slug"] == "samsung-galaxy-a16"
    assert line["product_name"] == "ሳምሰንግ ጋላክሲ A16"
    assert line["variant_attributes"] == {"storage": "256gb", "colour": "black"}
    assert (line["condition"], line["warranty_months"]) == ("new", 12)
    assert line["available"] == 5  # capped, as on the product page (D-029)
    assert (
        buyer.get("/cart", params={"lang": "en"}).json()["groups"][0]["items"][0]["product_name"]
        == "Samsung Galaxy A16"
    )


@pytest.mark.parametrize("quantity", [0, -1, 21, 1.5, "two"])
def test_a_quantity_outside_one_to_twenty_is_refused(bazaar: Bazaar, quantity: object) -> None:
    buyer, _ = bazaar.buyer()
    response = buyer.put(f"/cart/items/{bazaar.a128['id']}", json={"quantity": quantity})
    assert response.status_code == 422


def test_the_browser_cannot_put_a_price_in_the_cart(bazaar: Bazaar, db: DbSession) -> None:
    buyer, _ = bazaar.buyer()
    response = buyer.put(
        f"/cart/items/{bazaar.a128['id']}", json={"quantity": 1, "price_seen_santim": 100}
    )
    assert response.status_code == 422
    add_to_cart(buyer, bazaar.a128["id"], 1)
    assert db.scalar(select(CartItem.price_seen_santim)) == 1_850_000


def test_a_cart_holds_a_limited_number_of_lines(
    bazaar: Bazaar, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_CART_LINES", 2)
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"])
    add_to_cart(buyer, bazaar.a256["id"])
    response = buyer.put(f"/cart/items/{bazaar.b128['id']}", json={"quantity": 1})
    assert error_code(response) == "cart_full"
    add_to_cart(buyer, bazaar.a128["id"], 5)  # changing a line already there is fine


def test_an_offer_buyers_cannot_see_cannot_be_added(bazaar: Bazaar, db: DbSession) -> None:
    """A paused offer, a seller below the publishing level and an id that does
    not exist all give the same answer."""
    paused = bazaar.a256["id"]
    bazaar.a.post(f"/seller/{bazaar.a_id}/offers/{paused}/pause")
    level_one, level_one_id = make_seller(bazaar.staff, "0911000003", tin="0000000003", level=1)
    hidden = make_offer(level_one, level_one_id, bazaar.v128)["id"]
    buyer, _ = bazaar.buyer()
    replies = [
        buyer.put(f"/cart/items/{offer_id}", json={"quantity": 1})
        for offer_id in (paused, hidden, "01900000-0000-7000-8000-000000000000")
    ]
    assert {r.status_code for r in replies} == {404}
    assert {error_code(r) for r in replies} == {"offer_not_found"}
    assert db.scalar(select(func.count()).select_from(CartItem)) == 0


# -- what changed since the buyer last looked (C-06) ------------------------------------


def test_the_cart_says_when_a_price_changed(bazaar: Bazaar) -> None:
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 2)
    bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}", json={"price_santim": 1_900_000}
    )
    cart = buyer.get("/cart").json()
    line = _lines(cart)[bazaar.a128["id"]]
    assert (line["price_seen_santim"], line["price_santim"]) == (1_850_000, 1_900_000)
    assert line["price_changed"] is True
    assert line["line_total_santim"] == 3_800_000  # always today's price
    assert (cart["has_price_changes"], cart["can_check_out"]) == (True, False)

    cart = buyer.post("/cart/accept-changes").json()
    line = _lines(cart)[bazaar.a128["id"]]
    assert (line["price_seen_santim"], line["price_changed"]) == (1_900_000, False)
    assert (cart["has_price_changes"], cart["can_check_out"]) == (False, True)


def test_the_cart_says_why_a_line_cannot_be_ordered(bazaar: Bazaar) -> None:
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 3)
    add_to_cart(buyer, bazaar.a256["id"], 1)
    add_to_cart(buyer, bazaar.b128["id"], 1)

    bazaar.a.put(f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}/stock", json={"on_hand": 2})
    bazaar.a.post(f"/seller/{bazaar.a_id}/offers/{bazaar.a256['id']}/pause")
    cart = buyer.get("/cart").json()
    lines = _lines(cart)
    assert lines[bazaar.a128["id"]]["problem"] == "not_enough_stock"
    assert lines[bazaar.a128["id"]]["available"] == 2
    assert lines[bazaar.a256["id"]]["problem"] == "offer_not_available"
    assert lines[bazaar.b128["id"]]["problem"] is None
    assert cart["can_check_out"] is False

    bazaar.a.put(f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}/stock", json={"on_hand": 0})
    bazaar.staff.post(f"/admin/sellers/{bazaar.b_id}/suspend", json={"reason": "Under review"})
    lines = _lines(buyer.get("/cart").json())
    assert lines[bazaar.a128["id"]]["problem"] == "out_of_stock"
    assert lines[bazaar.b128["id"]]["problem"] == "seller_not_available"


# -- delivery choices (D.10, J.9) -----------------------------------------------------


def test_each_store_lists_its_delivery_choices_for_the_buyers_zone(bazaar: Bazaar) -> None:
    make_zone(bazaar.staff, "yeka", areas=("Megenagna",), rider_fee=None, courier_fee=25_000)
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"])
    add_to_cart(buyer, bazaar.b128["id"])
    assert all(g["delivery_options"] is None for g in buyer.get("/cart").json()["groups"])

    def options(zone: str) -> dict[str, list[tuple[str, int]]]:
        cart = buyer.get("/cart", params={"zone": zone}).json()
        assert cart["zone_code"] == zone
        return {
            g["store_slug"]: [(o["method"], o["fee_santim"]) for o in g["delivery_options"]]
            for g in cart["groups"]
        }

    assert options("bole") == {
        "alpha": [("seller_rider", 15_000), ("shop_collection", 0)],
        "beta": [("shop_collection", 0)],
    }
    # Yeka has no rider fee, and Alpha does not use the partner courier.
    assert options("yeka") == {
        "alpha": [("shop_collection", 0)], "beta": [("shop_collection", 0)],
    }  # fmt: skip
    assert error_code(buyer.get("/cart", params={"zone": "nowhere"})) == "zone_not_found"


def test_a_method_counts_only_if_every_line_from_that_store_offers_it(bazaar: Bazaar) -> None:
    """A seller order travels as one shipment."""
    bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a256['id']}",
        json={"delivers_by_seller_rider": False},
    )
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"])
    cart = buyer.get("/cart", params={"zone": "bole"}).json()
    assert [o["method"] for o in cart["groups"][0]["delivery_options"]] == [
        "seller_rider", "shop_collection",
    ]  # fmt: skip
    add_to_cart(buyer, bazaar.a256["id"])
    cart = buyer.get("/cart", params={"zone": "bole"}).json()
    assert [o["method"] for o in cart["groups"][0]["delivery_options"]] == ["shop_collection"]


# -- who may shop ----------------------------------------------------------------------


def test_one_buyer_never_sees_anothers_cart(bazaar: Bazaar) -> None:
    first, _ = bazaar.buyer()
    second, _ = bazaar.buyer()
    add_to_cart(first, bazaar.a128["id"], 2)
    assert second.get("/cart").json()["line_count"] == 0
    second.delete("/cart")
    second.delete(f"/cart/items/{bazaar.a128['id']}")
    assert first.get("/cart").json()["line_count"] == 1


def test_a_staff_session_cannot_shop(bazaar: Bazaar, db: DbSession) -> None:
    """Staff powers and shopping never mix in one session (blueprint C.1)."""
    support = staff_client(db, "0911000300", StaffRole.SUPPORT)
    for response in (
        support.get("/cart"),
        support.put(f"/cart/items/{bazaar.a128['id']}", json={"quantity": 1}),
        support.get("/me/orders"),
    ):
        assert response.status_code == 403
        assert error_code(response) == "customer_session_required"
