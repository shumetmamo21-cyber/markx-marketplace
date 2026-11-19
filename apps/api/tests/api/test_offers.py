"""Offers and inventory (blueprint D.7, G.4, G.9, P7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core import settings_store
from markx.offers import service
from markx.offers.models import Inventory, InventoryMovement, Offer, OfferPriceHistory
from tests.conftest import ApiClient, error_code
from tests.factories import (
    make_catalog,
    make_offer,
    make_product,
    make_seller,
    make_zone,
    offer_body,
    phone_body,
    staff_client,
)

ADMIN = "0911000200"
A_PHONE = "0911000001"
B_PHONE = "0911000002"


class Market:
    """One approved product with two variants, a delivery zone, two verified sellers."""

    def __init__(self, db: DbSession) -> None:
        self.staff = staff_client(db, ADMIN, StaffRole.SUPER_ADMIN)
        self.catalog = make_catalog(self.staff)
        self.product = make_product(self.staff, self.catalog)
        self.slug = self.product["slug"]
        self.v128, self.v256 = (v["id"] for v in self.product["variants"])
        make_zone(self.staff, "bole", rider_fee=15_000, courier_fee=20_000)
        self.a, self.a_id = make_seller(self.staff, A_PHONE, tin="0000000001", trade_name="Alpha")
        self.b, self.b_id = make_seller(self.staff, B_PHONE, tin="0000000002", trade_name="Beta")

    def public(self, **params: Any) -> dict[str, Any]:
        response = ApiClient().get(f"/catalog/products/{self.slug}/offers", params=params)
        assert response.status_code == 200, response.text
        return dict(response.json())


@pytest.fixture
def market(db: DbSession) -> Market:
    return Market(db)


# -- the P7 completion criteria ----------------------------------------------------


def test_two_sellers_attach_offers_to_one_product_and_both_appear_ranked(market: Market) -> None:
    alpha = make_offer(market.a, market.a_id, market.v128, price_santim=1_850_000)
    beta = make_offer(market.b, market.b_id, market.v128, price_santim=1_790_000)
    assert alpha["product_slug"] == market.slug
    assert alpha["available"] == 5

    listing = market.public(zone="bole")
    assert listing["offer_count"] == 2
    assert listing["lowest_price_santim"] == 1_790_000
    assert [o["store_slug"] for o in listing["offers"]] == ["beta", "alpha"]
    first, second = listing["offers"]
    assert first["id"] == beta["id"]
    assert first["price_santim"] == 1_790_000
    assert first["delivery_fee_santim"] == 15_000
    assert first["delivery_method"] == "seller_rider"
    assert first["total_santim"] == 1_805_000
    assert first["seller_verification_level"] == 2
    assert first["in_stock"] is True
    assert (first["is_default"], first["default_reason"]) == (True, "lowest_total_delivered")
    assert (second["is_default"], second["default_reason"]) == (False, None)
    # The public page is cacheable and shows no exact stock count above the cap.
    assert first["available"] == 5
    assert "on_hand" not in first


def test_the_database_rejects_a_duplicate_offer(market: Market, db: DbSession) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    again = market.a.post(f"/seller/{market.a_id}/offers", json=offer_body(market.v128))
    assert again.status_code == 409
    assert error_code(again) == "offer_exists"
    assert again.json()["error"]["details"]["offer_id"] == offer["id"]

    # Plain SQL, past every line of application code.
    with pytest.raises(IntegrityError, match="uq_offers_seller_id_variant_id_condition"):
        db.execute(
            text(
                "insert into offers (id, seller_id, variant_id, condition, price_santim) "
                "values (gen_random_uuid(), :seller, :variant, 'new', 100)"
            ),
            {"seller": market.a_id, "variant": market.v128},
        )
    db.rollback()
    # A different condition or variant is a different offer.
    make_offer(market.a, market.a_id, market.v128, condition="used")
    make_offer(market.a, market.a_id, market.v256)
    assert len(market.a.get(f"/seller/{market.a_id}/offers").json()) == 3


def _offer_state(db: DbSession, offer_id: str) -> dict[str, Any]:
    db.rollback()
    offer = db.get(Offer, offer_id)
    inventory = db.get(Inventory, offer_id)
    assert offer is not None
    assert inventory is not None
    db.refresh(offer)
    db.refresh(inventory)
    return {
        **{c.name: getattr(offer, c.name) for c in Offer.__table__.columns},
        "on_hand": inventory.on_hand,
        "reserved": inventory.reserved,
        "history": db.scalar(
            select(text("count(*)")).select_from(OfferPriceHistory).where(
                OfferPriceHistory.offer_id == offer.id
            )
        ),
        "movements": db.scalar(
            select(text("count(*)")).select_from(InventoryMovement).where(
                InventoryMovement.offer_id == offer.id
            )
        ),
    }  # fmt: skip


def test_one_seller_cannot_read_or_edit_anothers_offer(market: Market, db: DbSession) -> None:
    theirs = make_offer(market.b, market.b_id, market.v128, price_santim=1_790_000)["id"]
    make_offer(market.a, market.a_id, market.v128)
    before = _offer_state(db, theirs)

    def attempts(seller_id: str) -> list[Any]:
        base = f"/seller/{seller_id}/offers/{theirs}"
        return [
            market.a.get(base),
            market.a.patch(base, json={"price_santim": 100}),
            market.a.put(f"{base}/stock", json={"on_hand": 0}),
            market.a.post(f"{base}/pause"),
            market.a.post(f"{base}/resume"),
            market.a.delete(base),
        ]

    # With B's offer id under A's own seller id: the offer is not A's.
    for response in attempts(market.a_id):
        assert response.status_code == 404, response.text
        assert error_code(response) == "offer_not_found"
    # With B's seller id: A is not a member of B.
    for response in attempts(market.b_id):
        assert response.status_code == 404, response.text
        assert error_code(response) == "seller_not_found"
    assert market.a.get(f"/seller/{market.b_id}/offers").status_code == 404
    assert market.a.get(f"/seller/{market.b_id}/dashboard").status_code == 404
    assert (
        market.a.post(f"/seller/{market.b_id}/offers", json=offer_body(market.v256)).status_code
        == 404
    )

    # A's check-in names B's offer: nothing of B's is touched.
    checked = market.a.post(f"/seller/{market.a_id}/offers/check-in", json={"offer_ids": [theirs]})
    assert checked.json() == {"confirmed": 0}
    assert _offer_state(db, theirs) == before
    # A's own list never contains B's offer.
    assert theirs not in [o["id"] for o in market.a.get(f"/seller/{market.a_id}/offers").json()]


def test_the_check_in_hides_a_stale_offer_and_brings_it_back(market: Market, db: DbSession) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    make_offer(market.b, market.b_id, market.v128)

    assert service.mark_stale_offers(db) == 0
    # Thirteen days: not yet stale, but sunk in the ranking and flagged to the seller.
    old = datetime.now(UTC) - timedelta(days=13)
    db.execute(text("update offers set price_confirmed_at = :t where id = :id"),
               {"t": old, "id": offer["id"]})  # fmt: skip
    db.commit()
    assert service.mark_stale_offers(db) == 0
    listing = market.public()
    assert [(o["store_slug"], o["price_is_fresh"]) for o in listing["offers"]] == [
        ("beta", True), ("alpha", False),
    ]  # fmt: skip
    mine = market.a.get(f"/seller/{market.a_id}/offers").json()[0]
    assert mine["needs_confirmation"] is True
    assert market.a.get(f"/seller/{market.a_id}/dashboard").json()["prices_to_confirm"] == 1

    # Fifteen days: the job hides it.
    assert service.mark_stale_offers(db, now=datetime.now(UTC) + timedelta(days=2)) == 1
    db.commit()
    assert [o["store_slug"] for o in market.public()["offers"]] == ["beta"]
    assert market.a.get(f"/seller/{market.a_id}/offers/{offer['id']}").json()["status"] == "stale"
    assert market.a.get(f"/seller/{market.a_id}/dashboard").json()["stale_offers"] == 1

    # One tap brings it back.
    checked = market.a.post(f"/seller/{market.a_id}/offers/check-in", json={})
    assert checked.json() == {"confirmed": 1}
    listing = market.public()
    assert sorted(o["store_slug"] for o in listing["offers"]) == ["alpha", "beta"]
    assert all(o["price_is_fresh"] for o in listing["offers"])
    assert market.a.get(f"/seller/{market.a_id}/dashboard").json()["prices_to_confirm"] == 0


# -- ranking ---------------------------------------------------------------------


def test_ranking_uses_total_cost_to_the_buyers_zone(market: Market) -> None:
    # Alpha is cheaper on the shelf but only by courier (ETB 200); Beta's own
    # rider costs ETB 150. Totals: Alpha 18,300 + 200 = 18,500; Beta 18,340 + 150 = 18,490.
    make_offer(
        market.a, market.a_id, market.v128, price_santim=1_830_000,
        delivers_by_seller_rider=False, delivers_by_partner_courier=True,
    )  # fmt: skip
    make_offer(market.b, market.b_id, market.v128, price_santim=1_834_000)
    delivered = market.public(zone="bole")["offers"]
    assert [(o["store_slug"], o["total_santim"]) for o in delivered] == [
        ("beta", 1_849_000), ("alpha", 1_850_000),
    ]  # fmt: skip
    # With no zone there is no delivery fee to add, so the shelf price decides.
    plain = market.public()["offers"]
    assert [o["store_slug"] for o in plain] == ["alpha", "beta"]
    assert plain[0]["delivery_fee_santim"] is None
    assert plain[0]["default_reason"] == "lowest_price"
    assert (
        ApiClient()
        .get(f"/catalog/products/{market.slug}/offers", params={"zone": "mars"})
        .status_code
        == 404
    )


def test_in_stock_ranks_first_and_collection_only_ranks_after_delivery(market: Market) -> None:
    cheap_but_empty = make_offer(
        market.a, market.a_id, market.v128, price_santim=1_000_000, quantity=0
    )
    make_offer(
        market.b, market.b_id, market.v128, price_santim=1_700_000,
        delivers_by_seller_rider=False, offers_shop_collection=True,
    )  # fmt: skip
    make_offer(market.a, market.a_id, market.v128, condition="open_box", price_santim=1_800_000)
    offers = market.public(zone="bole")["offers"]
    assert [(o["store_slug"], o["condition"], o["in_stock"]) for o in offers] == [
        ("alpha", "open_box", True),   # delivers to the zone
        ("beta", "new", True),         # cheaper, but the buyer must collect it
        ("alpha", "new", False),       # cheapest, but nothing to sell
    ]  # fmt: skip
    assert offers[1]["delivery_fee_santim"] is None
    assert offers[2]["id"] == cheap_but_empty["id"]
    assert market.public()["lowest_price_santim"] == 1_700_000


def test_only_live_offers_from_trading_level_two_sellers_are_public(
    market: Market, db: DbSession
) -> None:
    a_offer = make_offer(market.a, market.a_id, market.v128)
    make_offer(market.b, market.b_id, market.v128)
    c, c_id = make_seller(market.staff, "0911000003", tin="0000000003", trade_name="Gamma", level=1)
    # A level-1 seller prepares offers, but the launch policy publishes level 2 only.
    make_offer(c, c_id, market.v128, price_santim=1_000_000)
    assert sorted(o["store_slug"] for o in market.public()["offers"]) == ["alpha", "beta"]
    assert ApiClient().get("/catalog/stores/gamma/offers").json() == []

    market.a.post(f"/seller/{market.a_id}/offers/{a_offer['id']}/pause")
    assert [o["store_slug"] for o in market.public()["offers"]] == ["beta"]
    market.a.post(f"/seller/{market.a_id}/offers/{a_offer['id']}/resume")

    market.staff.post(f"/admin/sellers/{market.b_id}/suspend", json={"reason": "Under review"})
    assert [o["store_slug"] for o in market.public()["offers"]] == ["alpha"]
    assert ApiClient().get("/catalog/stores/beta/offers").json() == []

    settings_store.set_setting(db, "sellers.min_level_to_publish", 1)
    db.commit()
    assert sorted(o["store_slug"] for o in market.public()["offers"]) == ["alpha", "gamma"]


def test_a_filter_by_variant_and_an_unknown_product(market: Market) -> None:
    make_offer(market.a, market.a_id, market.v128)
    make_offer(market.a, market.a_id, market.v256, price_santim=2_100_000)
    only = market.public(variant_id=market.v256)["offers"]
    assert [o["price_santim"] for o in only] == [2_100_000]
    assert ApiClient().get("/catalog/products/no-such-phone/offers").status_code == 404


def test_the_store_price_list(market: Market) -> None:
    make_offer(market.a, market.a_id, market.v128)
    make_offer(market.a, market.a_id, market.v256, price_santim=2_100_000)
    make_offer(market.b, market.b_id, market.v128)
    response = ApiClient().get("/catalog/stores/alpha/offers", params={"lang": "en"})
    assert response.status_code == 200
    rows = response.json()
    assert [(r["product_name"], r["price_santim"]) for r in rows] == [
        ("Samsung Galaxy A16", 1_850_000), ("Samsung Galaxy A16", 2_100_000),
    ]  # fmt: skip
    assert rows[0]["variant_attributes"] == {"storage": "128gb", "colour": "black"}
    assert {r["store_slug"] for r in rows} == {"alpha"}


# -- creating and editing ----------------------------------------------------------


def test_creating_an_offer_records_the_price_and_the_opening_stock(
    market: Market, db: DbSession
) -> None:
    offer = make_offer(market.a, market.a_id, market.v128, quantity=7)
    assert offer["status"] == "active"
    assert (offer["on_hand"], offer["reserved"], offer["available"]) == (7, 0, 7)
    assert offer["price_history"] == [
        {"old_price_santim": None, "new_price_santim": 1_850_000,
         "changed_at": offer["price_history"][0]["changed_at"]},
    ]  # fmt: skip
    [movement] = offer["movements"]
    assert (movement["reason"], movement["delta_on_hand"], movement["on_hand_after"]) == (
        "initial", 7, 7,
    )  # fmt: skip
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "offer.create"))
    assert entry is not None
    assert entry.actor_type == "user"
    assert entry.after["seller_id"] == market.a_id


def test_every_price_change_leaves_a_trail(market: Market) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    base = f"/seller/{market.a_id}/offers/{offer['id']}"
    market.a.patch(base, json={"price_santim": 1_800_000})
    market.a.patch(base, json={"price_santim": 1_800_000})  # confirming, not changing
    detail = market.a.patch(base, json={"price_santim": 1_750_000, "warranty_months": 24}).json()
    assert detail["price_santim"] == 1_750_000
    assert detail["warranty_months"] == 24
    assert [(h["old_price_santim"], h["new_price_santim"]) for h in detail["price_history"]] == [
        (1_800_000, 1_750_000), (1_850_000, 1_800_000), (None, 1_850_000),
    ]  # fmt: skip


def test_price_history_and_stock_movements_cannot_be_rewritten(
    market: Market, db: DbSession
) -> None:
    from sqlalchemy.exc import DBAPIError

    make_offer(market.a, market.a_id, market.v128)
    for statement in (
        "update offer_price_history set new_price_santim = 1",
        "delete from offer_price_history",
        "update inventory_movements set on_hand_after = 999",
        "delete from inventory_movements",
    ):
        with pytest.raises(DBAPIError, match=r"permission denied|append-only"):
            db.execute(text(statement))
        db.rollback()


def test_the_seller_counts_the_shelf(market: Market) -> None:
    offer = make_offer(market.a, market.a_id, market.v128, quantity=5)
    base = f"/seller/{market.a_id}/offers/{offer['id']}"
    detail = market.a.put(f"{base}/stock", json={"on_hand": 2, "low_stock_threshold": 3}).json()
    assert (detail["on_hand"], detail["is_low_stock"], detail["low_stock_threshold"]) == (
        2,
        True,
        3,
    )
    assert [(m["reason"], m["delta_on_hand"], m["on_hand_after"]) for m in detail["movements"]] == [
        ("seller_adjust", -3, 2), ("initial", 5, 5),
    ]  # fmt: skip
    # Typing the same number again changes nothing and writes no movement.
    same = market.a.put(f"{base}/stock", json={"on_hand": 2}).json()
    assert len(same["movements"]) == 2
    assert market.a.get(f"/seller/{market.a_id}/dashboard").json()["low_stock_offers"] == 1
    for bad in (-1, 1_000_001, 2.5, "many"):
        assert market.a.put(f"{base}/stock", json={"on_hand": bad}).status_code == 422


def test_stock_cannot_be_set_below_what_is_held_for_orders(market: Market, db: DbSession) -> None:
    offer = make_offer(market.a, market.a_id, market.v128, quantity=5)
    assert service.hold_stock(db, offer["id"], 3) is True
    db.commit()
    base = f"/seller/{market.a_id}/offers/{offer['id']}"
    response = market.a.put(f"{base}/stock", json={"on_hand": 2})
    assert response.status_code == 409
    assert error_code(response) == "stock_below_reserved"
    assert response.json()["error"]["details"] == {"reserved": 3}
    detail = market.a.put(f"{base}/stock", json={"on_hand": 3}).json()
    assert (detail["on_hand"], detail["reserved"], detail["available"]) == (3, 3, 0)
    assert market.public()["offers"][0]["in_stock"] is False


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"price_santim": 0}, 422, "validation_failed"),
        ({"price_santim": -5}, 422, "validation_failed"),
        ({"price_santim": 18500.5}, 422, "validation_failed"),
        ({"price_santim": 10_000_000_001}, 422, "validation_failed"),
        ({"quantity": -1}, 422, "validation_failed"),
        ({"condition": "like_new"}, 422, "validation_failed"),
        ({"warranty_months": 121}, 422, "validation_failed"),
        ({"seller_id": "00000000-0000-0000-0000-000000000000"}, 422, "validation_failed"),
        ({"status": "active", "instant_buy": True}, 422, "validation_failed"),
        (
            {"delivers_by_seller_rider": False, "offers_shop_collection": False},
            422,
            "delivery_option_required",
        ),
        ({"variant_id": "00000000-0000-7000-8000-000000000000"}, 404, "variant_not_found"),
    ],
)
def test_a_bad_offer_is_refused(
    market: Market, overrides: dict[str, Any], status: int, code: str
) -> None:
    body = {**offer_body(market.v128), **overrides}
    response = market.a.post(f"/seller/{market.a_id}/offers", json=body)
    assert response.status_code == status, response.text
    assert error_code(response) == code
    assert market.a.get(f"/seller/{market.a_id}/offers").json() == []


def test_an_offer_attaches_only_to_an_approved_product(market: Market) -> None:
    draft = make_product(
        market.staff, market.catalog, status="draft", name_en="Draft Phone", model="D-1"
    )
    response = market.a.post(
        f"/seller/{market.a_id}/offers", json=offer_body(draft["variants"][0]["id"])
    )
    assert response.status_code == 404
    assert error_code(response) == "variant_not_found"


def test_used_goods_need_level_two(market: Market) -> None:
    c, c_id = make_seller(market.staff, "0911000003", tin="0000000003", trade_name="Gamma", level=1)
    response = c.post(f"/seller/{c_id}/offers", json=offer_body(market.v128, condition="used"))
    assert response.status_code == 403
    assert error_code(response) == "used_goods_need_level_two"
    assert make_offer(market.a, market.a_id, market.v128, condition="used")["condition"] == "used"


def test_a_removed_offer_can_be_listed_again(market: Market) -> None:
    offer = make_offer(market.a, market.a_id, market.v128, quantity=4)
    base = f"/seller/{market.a_id}/offers/{offer['id']}"
    assert market.a.delete(base).json()["status"] == "removed"
    assert market.public()["offers"] == []
    assert market.a.get(f"/seller/{market.a_id}/offers").json() == []
    assert (
        len(market.a.get(f"/seller/{market.a_id}/offers", params={"status": "removed"}).json()) == 1
    )
    for response in (
        market.a.delete(base),
        market.a.patch(base, json={"price_santim": 5}),
        market.a.put(f"{base}/stock", json={"on_hand": 1}),
    ):
        assert error_code(response) == "offer_removed"
    assert error_code(market.a.post(f"{base}/pause")) == "offer_not_live"

    relisted = make_offer(market.a, market.a_id, market.v128, price_santim=1_700_000, quantity=1)
    # The same row comes back, so its history is continuous.
    assert relisted["id"] == offer["id"]
    assert relisted["status"] == "active"
    assert relisted["on_hand"] == 1
    assert [h["new_price_santim"] for h in relisted["price_history"]] == [1_700_000, 1_850_000]


def test_a_suspended_or_unapproved_seller_cannot_change_listings(market: Market) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    market.staff.post(f"/admin/sellers/{market.a_id}/suspend", json={"reason": "Under review"})
    base = f"/seller/{market.a_id}/offers"
    for response in (
        market.a.post(base, json=offer_body(market.v256)),
        market.a.patch(f"{base}/{offer['id']}", json={"price_santim": 1}),
        market.a.put(f"{base}/{offer['id']}/stock", json={"on_hand": 50}),
        market.a.post(f"{base}/check-in", json={}),
        market.a.post(f"/seller/{market.a_id}/product-proposals", json=phone_body(market.catalog)),
    ):
        assert response.status_code == 409, response.text
        assert error_code(response) == "seller_not_active"
    # It can still see its listings and take one down.
    assert len(market.a.get(base).json()) == 1
    assert market.a.delete(f"{base}/{offer['id']}").status_code == 200

    from tests.factories import start_application

    applicant, applicant_id = start_application(market.staff, "0911000004", tin="0000000004")
    response = applicant.post(f"/seller/{applicant_id}/offers", json=offer_body(market.v128))
    assert error_code(response) == "seller_not_active"


def test_a_manager_manages_offers(market: Market) -> None:
    market.a.post(f"/seller/{market.a_id}/members", json={"phone": "0911000050"})
    manager = ApiClient()
    manager.sign_in("0911000050")
    offer = make_offer(manager, market.a_id, market.v128)
    assert manager.patch(
        f"/seller/{market.a_id}/offers/{offer['id']}", json={"price_santim": 1_800_000}
    ).status_code == 200  # fmt: skip


def test_the_quick_edit_list_pages_by_cursor(market: Market) -> None:
    first = make_offer(market.a, market.a_id, market.v128)
    second = make_offer(market.a, market.a_id, market.v256)
    third = make_offer(market.a, market.a_id, market.v128, condition="refurbished")
    market.a.post(f"/seller/{market.a_id}/offers/{second['id']}/pause")
    base = f"/seller/{market.a_id}/offers"
    page = market.a.get(base, params={"limit": 2, "lang": "en"}).json()
    assert [o["id"] for o in page] == [first["id"], second["id"]]
    assert page[0]["product_name"] == "Samsung Galaxy A16"
    rest = market.a.get(base, params={"limit": 2, "after": page[-1]["id"]}).json()
    assert [o["id"] for o in rest] == [third["id"]]
    assert [o["id"] for o in market.a.get(base, params={"status": "paused"}).json()] == [
        second["id"]
    ]
    assert market.a.get(f"/seller/{market.a_id}/dashboard").json() == {
        "active_offers": 2, "paused_offers": 1, "stale_offers": 0, "low_stock_offers": 0,
        "prices_to_confirm": 0,
    }  # fmt: skip


# -- product proposals (S-05) --------------------------------------------------------


def test_a_seller_proposes_a_product_and_staff_approve_it(market: Market) -> None:
    body = phone_body(
        market.catalog, name_en="Tecno Spark 20", name_am="ቴክኖ ስፓርክ 20", model="KJ5",
        slug="chosen-by-seller", status="approved",
    )  # fmt: skip
    response = market.a.post(f"/seller/{market.a_id}/product-proposals", json=body)
    assert response.status_code == 201, response.text
    proposal = response.json()
    # Whatever the seller sent, it is a proposal, not an approved product.
    assert proposal["status"] == "pending_review"
    assert proposal["slug"] == "tecno-spark-20"
    assert ApiClient().get("/catalog/products/tecno-spark-20").status_code == 404

    [row] = market.staff.get("/admin/catalog/products", params={"status": "pending_review"}).json()
    assert row["proposed_by_seller_id"] == market.a_id
    detail = market.staff.get(f"/admin/catalog/products/{proposal['id']}").json()
    variant_id = detail["variants"][0]["id"]
    # Nothing can be sold against a proposal.
    early = market.a.post(f"/seller/{market.a_id}/offers", json=offer_body(variant_id))
    assert error_code(early) == "variant_not_found"

    assert market.staff.post(f"/admin/catalog/products/{proposal['id']}/approve").status_code == 200
    make_offer(market.a, market.a_id, variant_id)
    assert ApiClient().get("/catalog/products/tecno-spark-20/offers").json()["offer_count"] == 1


def test_a_restricted_item_cannot_be_proposed(market: Market) -> None:
    market.staff.post("/admin/catalog/restricted-terms", json={"term": "pistol"})
    response = market.a.post(
        f"/seller/{market.a_id}/product-proposals",
        json=phone_body(market.catalog, name_en="Toy pistol phone"),
    )
    assert response.status_code == 422
    assert error_code(response) == "restricted_goods"


# -- staff moderation (AD-03, C.4) ---------------------------------------------------


@pytest.mark.parametrize("role", list(StaffRole))
def test_who_may_take_a_listing_down(market: Market, db: DbSession, role: StaffRole) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    moderator = staff_client(db, "0911000300", role)
    response = moderator.post(
        f"/admin/offers/{offer['id']}/remove", json={"reason": "Counterfeit item reported"}
    )
    if role in (StaffRole.SUPER_ADMIN, StaffRole.OPERATIONS, StaffRole.CATALOGUE):
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "removed"
        assert market.public()["offers"] == []
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "offer.staff_remove"))
        assert entry is not None
        assert entry.after == {"status": "removed", "reason": "Counterfeit item reported"}
        assert market.a.get("/me").json()["unread_notifications"] >= 1
    else:
        assert response.status_code == 403
        assert error_code(response) == "permission_denied"
        assert market.public()["offer_count"] == 1


def test_sellers_and_visitors_cannot_moderate(market: Market) -> None:
    offer = make_offer(market.b, market.b_id, market.v128)
    path = f"/admin/offers/{offer['id']}/remove"
    assert ApiClient().post(path, json={"reason": "No reason"}).status_code == 401
    response = market.a.post(path, json={"reason": "A competitor"})
    assert response.status_code == 403
    assert error_code(response) == "staff_only"
    assert market.public()["offer_count"] == 1


def test_a_seller_cannot_relist_an_offer_that_staff_took_down(
    market: Market, db: DbSession
) -> None:
    """Moderation must hold. A takedown that the seller can undo with one
    request protects nobody: the offer stays down until staff lift the hold."""
    offer = make_offer(market.a, market.a_id, market.v128)
    removed = market.staff.post(
        f"/admin/offers/{offer['id']}/remove", json={"reason": "Counterfeit item reported"}
    )
    assert removed.status_code == 200, removed.text

    relist = market.a.post(f"/seller/{market.a_id}/offers", json=offer_body(market.v128))
    assert relist.status_code == 403, relist.text
    assert error_code(relist) == "offer_removed_by_staff"
    assert market.public()["offers"] == []
    assert db.scalar(select(Offer.status).where(Offer.id == offer["id"])) == "removed"
    # Its own removal is still relistable: only the staff hold blocks.
    other = make_offer(market.a, market.a_id, market.v256)
    assert market.a.delete(f"/seller/{market.a_id}/offers/{other['id']}").status_code == 200
    assert make_offer(market.a, market.a_id, market.v256)["status"] == "active"
    # Removing it first is no way round a takedown either.
    assert market.a.delete(f"/seller/{market.a_id}/offers/{other['id']}").status_code == 200
    held = market.staff.post(f"/admin/offers/{other['id']}/remove", json={"reason": "Stolen goods"})
    assert held.status_code == 200, held.text
    relist = market.a.post(f"/seller/{market.a_id}/offers", json=offer_body(market.v256))
    assert error_code(relist) == "offer_removed_by_staff"
    again = market.staff.post(f"/admin/offers/{other['id']}/remove", json={"reason": "Twice"})
    assert error_code(again) == "offer_removed"


def test_staff_lift_the_hold_and_the_seller_may_list_again(market: Market, db: DbSession) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    path = f"/admin/offers/{offer['id']}"
    assert error_code(market.staff.post(f"{path}/restore", json={"reason": "x y z"})) == (
        "offer_not_held"
    )
    market.staff.post(f"{path}/remove", json={"reason": "Counterfeit item reported"})

    # Lifting the hold is a staff decision; the seller cannot make it.
    assert market.a.post(f"{path}/restore", json={"reason": "It is genuine"}).status_code == 403
    lifted = market.staff.post(f"{path}/restore", json={"reason": "Invoice checked, genuine"})
    assert lifted.status_code == 200, lifted.text
    # Lifting does not publish anything by itself: the seller lists again.
    assert lifted.json()["status"] == "removed"
    assert market.public()["offers"] == []
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "offer.staff_restore"))
    assert entry is not None
    assert entry.after["reason"] == "Invoice checked, genuine"
    assert make_offer(market.a, market.a_id, market.v128)["id"] == offer["id"]
    assert market.public()["offer_count"] == 1


def test_the_database_keeps_a_held_offer_down(market: Market, db: DbSession) -> None:
    offer = make_offer(market.a, market.a_id, market.v128)
    market.staff.post(f"/admin/offers/{offer['id']}/remove", json={"reason": "Counterfeit item"})
    with pytest.raises(IntegrityError, match="ck_offers_staff_hold_means_removed"):
        db.execute(text("update offers set status = 'active'"))
    db.rollback()
