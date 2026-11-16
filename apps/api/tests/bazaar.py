"""A small marketplace for cart, checkout and order tests.

One approved product with two variants, one delivery zone, two verified
sellers ("alpha" and "beta") each with an offer on both variants, and buyers
made on demand.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts.models import StaffRole
from markx.offers.models import Inventory, InventoryMovement, InventoryReservation
from tests.conftest import ApiClient
from tests.factories import (
    make_buyer,
    make_catalog,
    make_offer,
    make_product,
    make_seller,
    make_zone,
    staff_client,
)

ADMIN = "0911000200"
A_PHONE = "0911000001"
B_PHONE = "0911000002"


class Bazaar:
    def __init__(self, db: Session, *, stock: int = 5) -> None:
        self.staff = staff_client(db, ADMIN, StaffRole.SUPER_ADMIN)
        self.catalog = make_catalog(self.staff)
        self.product = make_product(self.staff, self.catalog)
        self.v128, self.v256 = (v["id"] for v in self.product["variants"])
        self.zone = make_zone(self.staff, "bole", rider_fee=15_000, courier_fee=20_000)
        self.area_id = self.zone["areas"][0]["id"]
        self.a, self.a_id = make_seller(self.staff, A_PHONE, tin="0000000001", trade_name="Alpha")
        self.b, self.b_id = make_seller(
            self.staff, B_PHONE, tin="0000000002", trade_name="Beta", contact_phone="0911000002"
        )
        # Alpha delivers by its own rider; Beta is collection only.
        self.a128 = make_offer(self.a, self.a_id, self.v128, price_santim=1_850_000, quantity=stock)
        self.a256 = make_offer(self.a, self.a_id, self.v256, price_santim=2_100_000, quantity=stock)
        self.b128 = make_offer(
            self.b, self.b_id, self.v128, price_santim=1_790_000, quantity=stock,
            delivers_by_seller_rider=False,
        )  # fmt: skip
        self._buyers = 0

    def buyer(self, phone: str | None = None, **address: Any) -> tuple[ApiClient, str]:
        self._buyers += 1
        return make_buyer(phone or f"09115550{self._buyers:02d}", self.area_id, **address)


def stock(db: Session, offer_id: str | uuid.UUID) -> tuple[int, int]:
    """(on hand, reserved) as the database has it now."""
    db.rollback()
    row = db.execute(
        select(Inventory.on_hand, Inventory.reserved).where(Inventory.offer_id == offer_id)
    ).one()
    return row.on_hand, row.reserved


def assert_stock_is_consistent(db: Session) -> None:
    """Three views of the same truth must agree for every offer: the stock
    row, the held reservations, and the movement trail replayed from zero."""
    db.rollback()
    held = dict(
        db.execute(
            select(InventoryReservation.offer_id, func.sum(InventoryReservation.quantity))
            .where(InventoryReservation.status == "held")
            .group_by(InventoryReservation.offer_id)
        ).all()
    )
    trail = {
        offer_id: (on_hand, reserved)
        for offer_id, on_hand, reserved in db.execute(
            select(
                InventoryMovement.offer_id,
                func.sum(InventoryMovement.delta_on_hand),
                func.sum(InventoryMovement.delta_reserved),
            ).group_by(InventoryMovement.offer_id)
        ).all()
    }
    for inventory in db.scalars(select(Inventory)):
        assert 0 <= inventory.reserved <= inventory.on_hand
        assert inventory.reserved == int(held.get(inventory.offer_id, 0)), inventory.offer_id
        assert trail[inventory.offer_id] == (inventory.on_hand, inventory.reserved)
