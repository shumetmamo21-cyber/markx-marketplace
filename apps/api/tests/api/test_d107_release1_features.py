"""D-107: two Release 1 features through the real API, against PostgreSQL.

- C-03: search filtered by delivery speed and sorted by the total cost to the
  buyer's door (`/search?zone=&max_delivery_hours=&sort=total`);
- C-08: a photo of the buyer's gate on an address, kept privately and seen
  only by the buyer and the shop delivering an order there
  (`/me/addresses/{id}/gate-photo`, `/seller/{id}/orders/{id}/gate-photo`,
  `/gate-photos/{id}/content`).

The other three (C-12 lite mode, S-06 photos shrunk on the phone, S-10 share
cards and QR codes) live in the web app and its unit tests. Every route under
/seller/{seller_id} is also attacked by another shop in
tests/api/test_seller_isolation.py, automatically.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from markx.accounts.models import Address, GatePhoto, StaffRole, User
from markx.audit.models import AuditLog
from markx.backup.references import file_references
from markx.core.storage import get_private_storage
from markx.sellers.models import SellerMember
from markx.worker.runner import run_once
from scripts.copy_files_to_object_storage import file_references as copy_tool_references
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import (
    add_to_cart,
    checkout,
    make_offer,
    make_product,
    make_zone,
    staff_client,
)
from tests.unit.test_images import assert_bare, phone_jpeg


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


# -- C-03: delivery speed and the total to the door ------------------------------------------


class Market:
    """The bazaar's Samsung (Alpha 18,500 by rider; Beta 17,900 collection
    only), a Tecno (Alpha 12,000 by rider) and a Nokia (Beta 11,980 by the
    partner courier only). In Bole the rider costs 150 birr within 24 hours
    and the courier 200 birr within 72 hours."""

    def __init__(self, db: Session, bazaar: Bazaar) -> None:
        self.bazaar = bazaar
        staff = bazaar.staff
        slow = staff.put(
            f"/admin/delivery/zones/{bazaar.zone['id']}/rates",
            json={"method": "partner_courier", "fee_santim": 20_000, "promised_hours": 72},
        )
        assert slow.status_code == 200, slow.text
        self.tecno = make_product(
            staff, bazaar.catalog, model="KJ5", name_am="ቴክኖ ስፓርክ 20", name_en="Tecno Spark 20",
            variants=[{"attribute_values": {"storage": "128gb", "colour": "blue"}}],
        )  # fmt: skip
        make_offer(bazaar.a, bazaar.a_id, self.tecno["variants"][0]["id"], price_santim=1_200_000)
        self.nokia = make_product(
            staff, bazaar.catalog, model="G42", name_am="ኖኪያ ጂ42", name_en="Nokia G42",
            variants=[{"attribute_values": {"storage": "128gb", "colour": "black"}}],
        )  # fmt: skip
        make_offer(
            bazaar.b, bazaar.b_id, self.nokia["variants"][0]["id"], price_santim=1_198_000,
            delivers_by_seller_rider=False, delivers_by_partner_courier=True,
        )  # fmt: skip
        self.visitor = ApiClient()
        run_once(datetime.now(UTC), jobs=())

    def find(self, **params: Any) -> dict[str, Any]:
        response = self.visitor.get("/search", params=params)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def cards(self, **params: Any) -> list[tuple[str, int | None, int | None]]:
        found = self.find(**params)
        return [(card["slug"], *_door(found, card)) for card in found["results"]]


def _door(found: dict[str, Any], card: dict[str, Any]) -> tuple[int | None, int | None]:
    """A card's total to the door and fastest hours in the search's zone."""
    for row in found["delivered"]:
        if row["product_id"] == card["product_id"]:
            return row["total_santim"], row["fastest_hours"]
    return None, None


@pytest.fixture
def market(db: Session, bazaar: Bazaar) -> Market:
    return Market(db, bazaar)


def test_sorting_by_total_to_the_door_puts_the_cheapest_delivered_first(market: Market) -> None:
    samsung, tecno, nokia = (
        market.bazaar.product["slug"], market.tecno["slug"], market.nokia["slug"],
    )  # fmt: skip
    # By price alone the Nokia (11,980) beats the Tecno (12,000)...
    by_price = [slug for slug, _, _ in market.cards(sort="price")]
    assert by_price[:2] == [nokia, tecno]
    # ...but delivered to Bole the Tecno costs 12,150 and the Nokia 12,180.
    found = market.find(zone="bole", sort="total")
    assert found["zone_code"] == "bole"
    assert market.cards(zone="bole", sort="total") == [
        (tecno, 1_215_000, 24),
        (nokia, 1_218_000, 72),
        # Beta's cheaper Samsung is collection only: the door total is Alpha's.
        (samsung, 1_865_000, 24),
    ]


def test_the_total_on_a_card_is_the_product_pages_own_total(market: Market) -> None:
    found = market.find(zone="bole")
    for product in (market.bazaar.product, market.tecno, market.nokia):
        [card] = [c for c in found["results"] if c["slug"] == product["slug"]]
        page = market.visitor.get(
            f"/catalog/products/{product['slug']}/offers", params={"zone": "bole"}
        )
        assert page.status_code == 200, page.text
        delivered = [
            o["total_santim"]
            for o in page.json()["offers"]
            if o["in_stock"] and o["delivery_fee_santim"] is not None
        ]
        assert _door(found, card)[0] == min(delivered)
    # Without a zone, no total is guessed.
    assert market.find()["delivered"] == []
    assert market.find()["zone_code"] is None


def test_the_delivery_speed_filter_keeps_what_arrives_in_time(market: Market) -> None:
    samsung, tecno, nokia = (
        market.bazaar.product["slug"], market.tecno["slug"], market.nokia["slug"],
    )  # fmt: skip
    fast = market.find(zone="bole", max_delivery_hours=24)
    assert fast["total"] == 2
    assert sorted(c["slug"] for c in fast["results"]) == sorted([samsung, tecno])
    assert {_door(fast, c)[1] for c in fast["results"]} == {24}
    within_three_days = market.find(zone="bole", max_delivery_hours=72)
    assert within_three_days["total"] == 3
    assert nokia in [c["slug"] for c in within_three_days["results"]]
    assert market.find(zone="bole", max_delivery_hours=12)["total"] == 0


def test_a_product_nobody_delivers_to_the_zone_sorts_last_and_fails_the_speed_filter(
    market: Market,
) -> None:
    staff = market.bazaar.staff
    lamp = make_product(
        staff, market.bazaar.catalog, model="L1", name_am="መብራት", name_en="Lamp phone",
        variants=[{"attribute_values": {"storage": "128gb", "colour": "blue"}}],
    )  # fmt: skip
    make_offer(
        market.bazaar.b, market.bazaar.b_id, lamp["variants"][0]["id"], price_santim=100_000,
        delivers_by_seller_rider=False,
    )  # fmt: skip
    run_once(datetime.now(UTC), jobs=())
    cards = market.cards(zone="bole", sort="total")
    assert cards[-1] == (lamp["slug"], None, None)
    assert lamp["slug"] not in [
        slug for slug, _, _ in market.cards(zone="bole", max_delivery_hours=720)
    ]
    # It is still the cheapest by price: the other sorts are unchanged.
    assert market.cards(sort="price")[0][0] == lamp["slug"]


def test_a_total_and_a_speed_need_the_buyers_zone(market: Market) -> None:
    for params in ({"sort": "total"}, {"max_delivery_hours": 24}):
        refused = market.visitor.get("/search", params=params)
        assert refused.status_code == 422, refused.text
        assert error_code(refused) == "zone_required"
    unknown = market.visitor.get("/search", params={"zone": "nowhere", "sort": "total"})
    assert unknown.status_code == 404
    assert error_code(unknown) == "zone_not_found"


def test_a_slower_cheaper_method_does_not_count_inside_a_faster_window(
    db: Session, bazaar: Bazaar
) -> None:
    """With a speed asked for, the total is the cheapest way to have it in time."""
    staff = bazaar.staff
    zone = make_zone(staff, "piassa", rider_fee=40_000, courier_fee=10_000)
    for method, fee, hours in (("seller_rider", 40_000, 6), ("partner_courier", 10_000, 48)):
        assert (
            staff.put(
                f"/admin/delivery/zones/{zone['id']}/rates",
                json={"method": method, "fee_santim": fee, "promised_hours": hours},
            ).status_code
            == 200
        )
    gadget = make_product(
        staff, bazaar.catalog, model="X9", name_am="ጋጀት", name_en="Gadget X9",
        variants=[{"attribute_values": {"storage": "128gb", "colour": "black"}}],
    )  # fmt: skip
    make_offer(
        bazaar.a, bazaar.a_id, gadget["variants"][0]["id"], price_santim=500_000,
        delivers_by_seller_rider=True, delivers_by_partner_courier=True,
    )  # fmt: skip
    run_once(datetime.now(UTC), jobs=())
    visitor = ApiClient()

    def total(**params: Any) -> tuple[int | None, int | None]:
        found = visitor.get("/search", params={"q": "gadget", "zone": "piassa", **params}).json()
        [card] = found["results"]
        return _door(found, card)

    assert total() == (510_000, 6)  # the courier is cheapest; the rider is fastest
    assert total(max_delivery_hours=12) == (540_000, 6)


# -- C-08: the gate photo -----------------------------------------------------------------


def _upload(buyer: ApiClient, address_id: str, data: bytes | None = None) -> Any:
    return buyer.post(
        f"/me/addresses/{address_id}/gate-photo",
        files={"file": ("gate.jpg", data or phone_jpeg(), "image/jpeg")},
    )


def _split(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    assert parts.path.startswith("/api/v1/")
    return parts.path.removeprefix("/api/v1"), {k: v[0] for k, v in parse_qs(parts.query).items()}


def _open(client: ApiClient, url: str) -> Any:
    route, params = _split(url)
    return client.get(route, params=params)


def _ordered(bazaar: Bazaar, method: str = "seller_rider") -> tuple[ApiClient, str, str, str]:
    """A buyer with a gate photo on their address orders from Alpha (or Beta
    for collection). Returns the buyer, address id, seller id and seller order id."""
    buyer, address_id = bazaar.buyer()
    assert _upload(buyer, address_id).status_code == 200
    if method == "shop_collection":
        add_to_cart(buyer, bazaar.b128["id"])
        placed = checkout(buyer, address_id, {"beta": "shop_collection"})
        seller_id = bazaar.b_id
    else:
        add_to_cart(buyer, bazaar.a128["id"])
        placed = checkout(buyer, address_id, {"alpha": method})
        seller_id = bazaar.a_id
    assert placed.status_code == 201, placed.text
    [part] = placed.json()["seller_orders"]
    return buyer, address_id, seller_id, part["id"]


def test_a_buyer_adds_a_gate_photo_kept_privately_without_its_location(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address_id = bazaar.buyer()
    added = _upload(buyer, address_id)
    assert added.status_code == 200, added.text
    url = added.json()["gate_photo_url"]
    assert url.startswith("/api/v1/gate-photos/")
    db.rollback()
    photo = db.scalar(select(GatePhoto))
    assert photo is not None
    assert photo.file_key.startswith("gate-photos/")
    stored = get_private_storage().get(photo.file_key)
    assert_bare(stored)  # no EXIF: the phone's location never reaches storage
    shown = _open(buyer, url)
    assert shown.status_code == 200, shown.text
    assert shown.headers["cache-control"] == "private, no-store"
    assert shown.content == stored
    listed = buyer.get("/me/addresses").json()
    assert listed[0]["gate_photo_url"].startswith(f"/api/v1/gate-photos/{photo.id}/content?")
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "address.gate_photo_set"))


def test_nobody_else_opens_a_buyers_gate_photo(bazaar: Bazaar, db: Session) -> None:
    buyer, address_id = bazaar.buyer()
    url = _upload(buyer, address_id).json()["gate_photo_url"]
    other, _ = bazaar.buyer()
    assert error_code(_open(other, url)) == "photo_link_invalid"  # signed for someone else
    assert _open(ApiClient(), url).status_code == 401  # not signed in
    route, params = _split(url)
    forged = {
        **params,
        "signature": params["signature"][:-1] + ("A" if params["signature"][-1] != "A" else "B"),
    }
    assert error_code(buyer.get(route, params=forged)) == "photo_link_invalid"
    # Another buyer cannot put a photo on this address, nor see it in a listing.
    assert _upload(other, address_id).status_code == 404
    assert other.get("/me/addresses").json()[0]["gate_photo_url"] is None


def test_the_delivering_shop_sees_the_gate_photo_only_while_it_delivers(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, _, seller_id, part_id = _ordered(bazaar)
    base = f"/seller/{seller_id}/orders/{part_id}"
    # Before the shop confirms: nothing, like the buyer's phone number.
    assert bazaar.a.get(base).json()["has_gate_photo"] is False
    assert error_code(bazaar.a.get(f"{base}/gate-photo")) == "gate_photo_not_available"

    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    assert bazaar.a.get(base).json()["has_gate_photo"] is True
    link = bazaar.a.get(f"{base}/gate-photo")
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    shown = _open(bazaar.a, url)
    assert shown.status_code == 200, shown.text
    assert_bare(shown.content)
    db.rollback()
    viewed = db.scalar(select(AuditLog).where(AuditLog.action == "gate_photo.viewed"))
    assert viewed is not None
    assert viewed.after == {"seller_order_id": part_id}
    # The buyer's own link does not open the shop's door, nor the shop's the buyer's.
    assert error_code(_open(buyer, url)) == "photo_link_invalid"

    assert bazaar.a.post(f"{base}/ready").status_code == 200
    assert bazaar.a.post(f"{base}/dispatch", json={"rider_name": "Dawit"}).status_code == 200
    assert bazaar.a.get(base).json()["has_gate_photo"] is True
    url = bazaar.a.get(f"{base}/gate-photo").json()["url"]
    order_id = buyer.get("/me/orders").json()[0]["id"]
    code = next(
        so["handover_code"] for so in buyer.get(f"/me/orders/{order_id}").json()["seller_orders"]
    )
    handed = bazaar.a.post(f"{base}/handover", json={"code": code})
    assert handed.status_code == 200, handed.text
    # Handed over: the shop no longer needs the gate, and a link it kept stops.
    assert bazaar.a.get(base).json()["has_gate_photo"] is False
    assert error_code(bazaar.a.get(f"{base}/gate-photo")) == "gate_photo_not_available"
    assert error_code(_open(bazaar.a, url)) == "photo_link_invalid"


def test_collection_at_the_shop_never_shows_the_gate(bazaar: Bazaar) -> None:
    _, _, seller_id, part_id = _ordered(bazaar, "shop_collection")
    base = f"/seller/{seller_id}/orders/{part_id}"
    assert bazaar.b.post(f"{base}/confirm").status_code == 200
    assert bazaar.b.get(base).json()["has_gate_photo"] is False
    assert error_code(bazaar.b.get(f"{base}/gate-photo")) == "gate_photo_not_available"


def _member(db: Session, seller_id: str, phone: str, role: str) -> tuple[ApiClient, uuid.UUID]:
    client = ApiClient()
    client.sign_in(phone)
    user_id = db.scalar(select(User.id).where(User.phone == "+251" + phone[1:]))
    assert user_id is not None
    db.add(SellerMember(seller_id=uuid.UUID(seller_id), user_id=user_id, role=role))
    db.commit()
    return client, user_id


def test_only_the_roles_that_see_buyers_contacts_see_the_gate(bazaar: Bazaar, db: Session) -> None:
    _, _, seller_id, part_id = _ordered(bazaar)
    base = f"/seller/{seller_id}/orders/{part_id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    owners_link = bazaar.a.get(f"{base}/gate-photo").json()["url"]

    catalogue, _ = _member(db, seller_id, "0911777020", "catalogue")
    assert catalogue.get(f"{base}/gate-photo").status_code == 403
    assert error_code(_open(catalogue, owners_link)) == "photo_link_invalid"

    rider_desk, user_id = _member(db, seller_id, "0911777021", "orders")
    assert rider_desk.get(base).json()["has_gate_photo"] is True
    url = rider_desk.get(f"{base}/gate-photo").json()["url"]
    assert _open(rider_desk, url).status_code == 200
    # A member who leaves the shop loses it at once, even with a fresh link.
    db.execute(
        text("update seller_members set is_active = false where user_id = :u"), {"u": user_id}
    )
    db.commit()
    assert error_code(_open(rider_desk, url)) == "photo_link_invalid"


def test_staff_never_open_a_gate_photo(bazaar: Bazaar, db: Session) -> None:
    _, _, seller_id, part_id = _ordered(bazaar)
    base = f"/seller/{seller_id}/orders/{part_id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    url = bazaar.a.get(f"{base}/gate-photo").json()["url"]
    staff = staff_client(db, "0911000299", StaffRole.SUPER_ADMIN)
    assert error_code(_open(staff, url)) == "photo_link_invalid"


def test_an_order_keeps_the_photo_it_was_placed_with(bazaar: Bazaar, db: Session) -> None:
    buyer, address_id, seller_id, part_id = _ordered(bazaar)
    base = f"/seller/{seller_id}/orders/{part_id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    db.rollback()
    first = db.scalar(select(Address.gate_photo_id).where(Address.id == address_id))
    # The buyer replaces, then removes, the address's photo.
    assert _upload(buyer, address_id, phone_jpeg(300, 300)).status_code == 200
    removed = buyer.delete(f"/me/addresses/{address_id}/gate-photo")
    assert removed.status_code == 200, removed.text
    assert removed.json()["gate_photo_url"] is None
    # The shop delivering the order still sees the photo it was placed with.
    url = bazaar.a.get(f"{base}/gate-photo").json()["url"]
    assert f"/gate-photos/{first}/content" in url
    assert _open(bazaar.a, url).status_code == 200
    # Both files are kept: nothing is deleted.
    db.rollback()
    assert len(db.scalars(select(GatePhoto)).all()) == 2


def test_the_database_keeps_a_gate_photo_its_owners_and_unchanged(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address_id = bazaar.buyer()
    _, other_address = bazaar.buyer()
    assert _upload(buyer, address_id).status_code == 200
    db.rollback()
    photo = db.scalar(select(GatePhoto))
    assert photo is not None
    # An address can never point at another buyer's photo.
    with pytest.raises(IntegrityError):
        db.execute(
            text("update addresses set gate_photo_id = :p where id = :a"),
            {"p": photo.id, "a": other_address},
        )
    db.rollback()
    # A photo is never edited or deleted.
    for statement in ("update gate_photos set width = 1", "delete from gate_photos"):
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()


def test_a_gate_photo_that_is_not_a_picture_is_refused(bazaar: Bazaar) -> None:
    buyer, address_id = bazaar.buyer()
    refused = _upload(buyer, address_id, b"%PDF-1.4 not a picture")
    assert refused.status_code == 422
    assert error_code(refused) == "image_not_a_photo"


def test_the_backup_and_the_copy_tool_keep_gate_photos(bazaar: Bazaar, db: Session) -> None:
    buyer, address_id = bazaar.buyer()
    out = io.BytesIO()
    Image.new("RGB", (200, 120), (40, 90, 160)).save(out, "PNG")
    assert _upload(buyer, address_id, out.getvalue()).status_code == 200
    db.rollback()
    photo = db.scalar(select(GatePhoto))
    assert photo is not None
    raw = db.connection().connection.driver_connection
    refs = [r for r in file_references(raw) if r.kind == "gate_photo"]
    assert [(r.store, r.key) for r in refs] == [("private", photo.file_key)]
    tool = [r for r in copy_tool_references(db) if r.kind == "gate_photo"]
    assert [(r.store, r.key, r.content_type) for r in tool] == [
        ("private", photo.file_key, "image/webp")
    ]
