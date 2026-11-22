"""D-106: four Release 1 features through the real API, against PostgreSQL.

- C-19: a past order back in the cart in one tap (`/me/orders/{id}/reorder`);
- C-21: the price-history chart's numbers (`/catalog/products/{slug}/price-history`);
- S-11: a shop's own customers (`/seller/{id}/customers`), only what its order
  pages already show it;
- S-03: a shop's own logo (`/seller/{id}/store/logo`), on its page and in the
  backup's list of files.

The fifth, C-05 (the Ethiopian calendar and clock), is in
tests/unit/test_ethiopian_calendar.py and the web app's unit tests.
Every route under /seller/{seller_id} is also attacked by another shop in
tests/api/test_seller_isolation.py, automatically.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.audit.models import AuditLog
from markx.backup.references import file_references, unclassified_references
from markx.core.storage import get_public_storage
from markx.offers import selectors as offer_selectors
from markx.offers.models import OfferPriceHistory
from markx.sellers.models import SellerMember, Store
from scripts.copy_files_to_object_storage import file_references as copy_tool_references
from tests.bazaar import Bazaar
from tests.conftest import ApiClient
from tests.factories import add_to_cart, address_body, checkout
from tests.unit.test_images import phone_jpeg


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def _order(bazaar: Bazaar, buyer: ApiClient, address_id: str, *lines: tuple[str, int]) -> Any:
    for offer_id, quantity in lines:
        add_to_cart(buyer, offer_id, quantity)
    stores = {"alpha": "seller_rider", "beta": "shop_collection"}
    wanted = {
        "alpha" if offer_id in (bazaar.a128["id"], bazaar.a256["id"]) else "beta"
        for offer_id, _ in lines
    }
    response = checkout(buyer, address_id, {slug: stores[slug] for slug in sorted(wanted)})
    assert response.status_code == 201, response.text
    return response.json()


def _cart_lines(buyer: ApiClient) -> dict[str, tuple[int, int]]:
    cart = buyer.get("/cart").json()
    return {
        line["offer_id"]: (line["quantity"], line["price_santim"])
        for group in cart["groups"]
        for line in group["items"]
    }


# -- C-19: order again in one tap --------------------------------------------------------


def test_a_past_order_goes_back_in_the_cart_at_todays_prices(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    order = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 2), (bazaar.b128["id"], 1))
    assert _cart_lines(buyer) == {}  # checkout emptied the cart
    # Alpha's price went up since.
    changed = bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}", json={"price_santim": 1_900_000}
    )
    assert changed.status_code == 200, changed.text

    response = buyer.post(f"/me/orders/{order['id']}/reorder")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["order_id"], body["order_code"], body["missing"]) == (
        order["id"],
        order["code"],
        [],
    )
    added = {line["offer_id"]: line for line in body["added"]}
    assert added[bazaar.a128["id"]]["quantity"] == 2
    assert added[bazaar.a128["id"]]["unit_price_santim"] == 1_900_000  # today's price
    assert added[bazaar.a128["id"]]["paid_unit_price_santim"] == 1_850_000  # what was paid
    assert added[bazaar.b128["id"]]["quantity"] == 1
    assert added[bazaar.a128["id"]]["title"]
    # The cart holds today's price, never the old one.
    assert _cart_lines(buyer) == {
        bazaar.a128["id"]: (2, 1_900_000),
        bazaar.b128["id"]: (1, 1_790_000),
    }


def test_tapping_twice_never_doubles_and_never_lowers_what_is_in_the_cart(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    order = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 2))
    for _ in range(2):
        assert buyer.post(f"/me/orders/{order['id']}/reorder").status_code == 200
    assert _cart_lines(buyer)[bazaar.a128["id"]][0] == 2
    add_to_cart(buyer, bazaar.a128["id"], 5)
    assert buyer.post(f"/me/orders/{order['id']}/reorder").status_code == 200
    assert _cart_lines(buyer)[bazaar.a128["id"]][0] == 5


def test_an_offer_no_longer_on_sale_is_left_out_and_named(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    order = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 1), (bazaar.b128["id"], 1))
    removed = bazaar.b.delete(f"/seller/{bazaar.b_id}/offers/{bazaar.b128['id']}")
    assert removed.status_code == 200, removed.text

    body = buyer.post(f"/me/orders/{order['id']}/reorder").json()
    assert [line["offer_id"] for line in body["added"]] == [bazaar.a128["id"]]
    (missing,) = body["missing"]
    assert missing["offer_id"] == bazaar.b128["id"]
    assert missing["reason"] == "offer_unavailable"
    assert missing["product_slug"] == bazaar.product["slug"]  # another shop may have it
    assert set(_cart_lines(buyer)) == {bazaar.a128["id"]}


def test_only_the_buyer_can_order_their_order_again(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    order = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 1))
    stranger, _ = bazaar.buyer()
    refused = stranger.post(f"/me/orders/{order['id']}/reorder")
    assert (refused.status_code, refused.json()["error"]["code"]) == (404, "order_not_found")
    assert _cart_lines(stranger) == {}
    assert ApiClient().post(f"/me/orders/{order['id']}/reorder").status_code == 401
    staff = bazaar.staff.post(f"/me/orders/{order['id']}/reorder")
    assert staff.status_code == 403
    missing = buyer.post(f"/me/orders/{uuid.uuid4()}/reorder")
    assert missing.status_code == 404


# -- C-21: the price-history chart -------------------------------------------------------


def _history(bazaar: Bazaar, variant_id: str | None = None) -> Any:
    query = f"?variant_id={variant_id}" if variant_id else ""
    response = ApiClient().get(f"/catalog/products/{bazaar.product['slug']}/price-history{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_chart_shows_the_lowest_price_of_todays_offers_for_the_version(
    bazaar: Bazaar,
) -> None:
    body = _history(bazaar, bazaar.v128)
    assert (body["product_slug"], body["variant_id"], body["days"]) == (
        bazaar.product["slug"], bazaar.v128, offer_selectors.PRICE_HISTORY_DAYS
    )  # fmt: skip
    (new,) = body["series"]
    assert new["condition"] == "new"
    assert new["offers"] == 2  # Alpha's and Beta's 128 GB
    assert new["current_santim"] == new["lowest_santim"] == new["highest_santim"] == 1_790_000
    assert [step["price_santim"] for step in new["steps"]] == [1_790_000]
    # Beta takes its offer down: the line is drawn from the offers on sale today.
    assert bazaar.b.delete(f"/seller/{bazaar.b_id}/offers/{bazaar.b128['id']}").status_code == 200
    (new,) = _history(bazaar, bazaar.v128)["series"]
    assert (new["offers"], new["current_santim"]) == (1, 1_850_000)
    # The other version has its own chart; without a version, the first one.
    (other,) = _history(bazaar, bazaar.v256)["series"]
    assert other["current_santim"] == 2_100_000
    assert _history(bazaar)["variant_id"] == bazaar.v128


def test_the_chart_steps_down_and_up_day_by_day_from_the_recorded_changes(
    bazaar: Bazaar, db: Session
) -> None:
    now = datetime.now(UTC)
    offer_id = uuid.UUID(bazaar.a256["id"])
    # Older changes, as the price history records them (append-only).
    for days_ago, old, new in ((30, 2_100_000, 2_300_000), (20, 2_300_000, 2_000_000),
                               (10, 2_000_000, 2_200_000)):  # fmt: skip
        db.add(
            OfferPriceHistory(
                offer_id=offer_id, old_price_santim=old, new_price_santim=new,
                changed_at=now + timedelta(days=-days_ago),
            )
        )  # fmt: skip
    # And one this morning, back to 2,100,000.
    db.add(
        OfferPriceHistory(
            offer_id=offer_id, old_price_santim=2_200_000, new_price_santim=2_100_000,
            changed_at=now - timedelta(minutes=1),
        )
    )  # fmt: skip
    db.commit()
    history = offer_selectors.price_history(
        db, bazaar.product["slug"], variant_id=uuid.UUID(bazaar.v256), now=now
    )
    (series,) = history["series"]
    prices = [step["price_santim"] for step in series["steps"]]
    # The offer's first price was recorded today (when the test made it), so
    # the older changes come first in time; the line follows them in order.
    assert prices[:3] == [2_300_000, 2_000_000, 2_200_000]
    assert prices[-1] == 2_100_000
    assert series["current_santim"] == 2_100_000
    assert (series["lowest_santim"], series["highest_santim"]) == (2_000_000, 2_300_000)
    days = [step["day"] for step in series["steps"]]
    assert days == sorted(days)
    assert len(set(days)) == len(days)
    assert history["from_day"] == history["to_day"] - timedelta(days=89)


def test_the_chart_refuses_a_version_of_another_product_and_an_unknown_product(
    bazaar: Bazaar,
) -> None:
    client = ApiClient()
    slug = bazaar.product["slug"]
    wrong = client.get(f"/catalog/products/{slug}/price-history?variant_id={uuid.uuid4()}")
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (404, "variant_not_found")
    unknown = client.get("/catalog/products/no-such-product/price-history")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "product_not_found")


# -- S-11: the shop's own customers -------------------------------------------------------


def _customers(client: ApiClient, seller_id: str, query: str = "") -> Any:
    response = client.get(f"/seller/{seller_id}/customers{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _customer(bazaar: Bazaar, name: str, phone: str) -> tuple[ApiClient, str]:
    """A buyer whose order goes to `name` at `phone` (the details a shop sees)."""
    client, _ = bazaar.buyer()
    response = client.post(
        "/me/addresses", json=address_body(bazaar.area_id, recipient_name=name, phone=phone)
    )
    assert response.status_code == 201, response.text
    return client, str(response.json()["id"])


def _confirm(bazaar: Bazaar, order: Any, store: str = "alpha") -> str:
    part = next(p for p in order["seller_orders"] if p["store_slug"] == store)
    client, seller_id = (bazaar.a, bazaar.a_id) if store == "alpha" else (bazaar.b, bazaar.b_id)
    assert client.post(f"/seller/{seller_id}/orders/{part['id']}/confirm").status_code == 200
    return str(part["id"])


def test_a_customer_appears_once_the_shop_confirms_and_only_with_what_it_already_sees(
    bazaar: Bazaar,
) -> None:
    buyer, address_id = _customer(bazaar, "Hanna Tesfaye", "0911777001")
    first = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 1))
    # Placed but not confirmed: the order page shows no buyer, nor does the list.
    assert _customers(bazaar.a, bazaar.a_id) == []
    first_part = _confirm(bazaar, first)
    second = _order(bazaar, buyer, address_id, (bazaar.a256["id"], 1))
    second_part = _confirm(bazaar, second)

    (customer,) = _customers(bazaar.a, bazaar.a_id)
    page = bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{second_part}").json()["buyer"]
    assert (customer["name"], customer["phone"]) == (page["recipient_name"], page["phone"])
    assert (customer["name"], customer["phone"]) == ("Hanna Tesfaye", "+251911777001")
    assert (customer["orders"], customer["completed_orders"]) == (2, 0)
    assert [o["seller_order_id"] for o in customer["recent_orders"]] == [second_part, first_part]
    assert customer["recent_orders"][0]["order_code"] == second["code"]
    assert customer["area_name"]
    # Never the buyer's account, a landmark, a map pin or driver notes.
    assert set(customer) == {
        "phone", "name", "area_name", "orders", "completed_orders", "first_order_at",
        "last_order_at", "recent_orders",
    }  # fmt: skip
    # The other shop never served this person: it sees nobody.
    assert _customers(bazaar.b, bazaar.b_id) == []


def test_an_order_that_ended_without_delivery_shows_nobody(bazaar: Bazaar) -> None:
    buyer, address_id = _customer(bazaar, "Dawit Alemu", "0911777002")
    declined = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 1))
    part = declined["seller_orders"][0]["id"]
    assert (
        bazaar.a.post(
            f"/seller/{bazaar.a_id}/orders/{part}/decline", json={"reason": "Sold out today"}
        ).status_code
        == 200
    )
    cancelled = _order(bazaar, buyer, address_id, (bazaar.a128["id"], 1))
    part = _confirm(bazaar, cancelled)
    assert len(_customers(bazaar.a, bazaar.a_id)) == 1
    gone = buyer.post(f"/me/orders/{cancelled['id']}/seller-orders/{part}/cancel", json={})
    assert gone.status_code == 200, gone.text
    # Cancelled after confirming: the order page hides the buyer again, so does the list.
    assert bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{part}").json()["buyer"] is None
    assert _customers(bazaar.a, bazaar.a_id) == []


def test_customers_are_found_by_name_or_phone_and_kept_apart_by_phone(bazaar: Bazaar) -> None:
    one, one_address = _customer(bazaar, "Meron Girma", "0911777003")
    two, two_address = _customer(bazaar, "Yonas Kebede", "0911777004")
    _confirm(bazaar, _order(bazaar, one, one_address, (bazaar.a128["id"], 1)))
    _confirm(bazaar, _order(bazaar, two, two_address, (bazaar.a128["id"], 1)))
    names = [c["name"] for c in _customers(bazaar.a, bazaar.a_id)]
    assert names == ["Yonas Kebede", "Meron Girma"]  # the latest order first
    assert [c["name"] for c in _customers(bazaar.a, bazaar.a_id, "?q=meron")] == ["Meron Girma"]
    by_phone = _customers(bazaar.a, bazaar.a_id, "?q=0911777004")
    assert [c["name"] for c in by_phone] == ["Yonas Kebede"]
    assert _customers(bazaar.a, bazaar.a_id, "?q=nobody") == []


def test_a_member_who_may_not_see_buyers_contacts_gets_no_customer_list(
    bazaar: Bazaar, db: Session
) -> None:
    client = ApiClient()
    client.sign_in("0911777010")
    user_id = db.scalar(select(User.id).where(User.phone == "+251911777010"))
    db.add(SellerMember(seller_id=uuid.UUID(bazaar.a_id), user_id=user_id, role="catalogue"))
    db.commit()
    refused = client.get(f"/seller/{bazaar.a_id}/customers")
    assert refused.status_code == 403, refused.text


# -- S-03: the shop's own logo --------------------------------------------------------------


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (width, height), (17, 105, 78, 255)).save(out, "PNG")
    return out.getvalue()


def test_a_shop_uploads_its_logo_and_buyers_see_it_on_its_page(bazaar: Bazaar, db: Session) -> None:
    upload = bazaar.a.post(
        f"/seller/{bazaar.a_id}/store/logo",
        files={"file": ("logo.jpg", phone_jpeg(1600, 900), "image/jpeg")},
    )
    assert upload.status_code == 200, upload.text
    logo_url = upload.json()["logo_url"]
    assert logo_url
    assert logo_url.endswith("-256.webp")
    assert bazaar.a.get(f"/seller/{bazaar.a_id}/store").json()["logo_url"] == logo_url
    page = ApiClient().get("/catalog/stores/alpha").json()
    assert page["logo_url"] == logo_url
    # One WebP file, fitted inside 256 pixels, without the camera's data.
    store = db.scalar(select(Store).where(Store.slug == "alpha"))
    assert store is not None
    assert store.logo_key is not None
    data = get_public_storage().get(f"{store.logo_key}-256.webp")
    assert len(data) <= 40_000
    with Image.open(io.BytesIO(data)) as picture:
        assert picture.format == "WEBP"
        assert max(picture.size) == 256
        assert not picture.getexif()
    served = ApiClient().get(logo_url.removeprefix("/api/v1"))
    assert (served.status_code, served.headers["content-type"]) == (200, "image/webp")
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "store.logo_set")).one()
    assert entry.after["logo_key"] == store.logo_key


def test_a_new_logo_replaces_the_old_one_and_a_shop_can_remove_it(bazaar: Bazaar) -> None:
    path = f"/seller/{bazaar.a_id}/store/logo"
    first = bazaar.a.post(path, files={"file": ("a.png", _png(120, 120), "image/png")}).json()
    second = bazaar.a.post(path, files={"file": ("b.png", _png(64, 80), "image/png")}).json()
    assert first["logo_url"] != second["logo_url"]
    assert ApiClient().get("/catalog/stores/alpha").json()["logo_url"] == second["logo_url"]
    removed = bazaar.a.delete(path)
    assert (removed.status_code, removed.json()["logo_url"]) == (200, None)
    assert ApiClient().get("/catalog/stores/alpha").json()["logo_url"] is None


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"", "image_empty"), (b"%PDF-1.4 not a picture", "image_not_a_photo")],
)
def test_a_logo_that_is_not_a_picture_is_refused(bazaar: Bazaar, data: bytes, code: str) -> None:
    refused = bazaar.a.post(
        f"/seller/{bazaar.a_id}/store/logo", files={"file": ("x.jpg", data, "image/jpeg")}
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (422, code)
    assert bazaar.a.get(f"/seller/{bazaar.a_id}/store").json()["logo_url"] is None


def test_the_backup_and_the_copy_tool_know_a_logo_is_a_file_to_keep(
    bazaar: Bazaar, db: Session
) -> None:
    upload = bazaar.a.post(
        f"/seller/{bazaar.a_id}/store/logo", files={"file": ("a.png", _png(90, 90), "image/png")}
    )
    assert upload.status_code == 200, upload.text
    db.rollback()
    store = db.scalar(select(Store).where(Store.slug == "alpha"))
    assert store is not None
    assert store.logo_key is not None
    raw = db.connection().connection.driver_connection
    refs = [r for r in file_references(raw) if r.kind == "store_logo"]
    assert [(r.store, r.key) for r in refs] == [("public", f"{store.logo_key}-256.webp")]
    # Before D-106 a logo counted as a file the backup could not place, which
    # made every set incomplete.
    assert unclassified_references(raw) == 0
    tool = [r for r in copy_tool_references(db) if r.kind == "store_logo"]
    assert [(r.store, r.key, r.content_type) for r in tool] == [
        ("public", f"{store.logo_key}-256.webp", "image/webp")
    ]
