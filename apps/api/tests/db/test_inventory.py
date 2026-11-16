"""Stock integrity under contention (blueprint G.8, G.9).

These tests go around the HTTP layer: many threads, each with its own database
connection, race on the same offer through the service functions that
checkout will use.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.accounts.models import StaffRole
from markx.audit.service import Actor
from markx.core.db import session_scope
from markx.core.errors import AppError, Conflict
from markx.offers import service
from markx.offers.models import Inventory, InventoryMovement, Offer
from markx.sellers.models import Seller
from tests.factories import (
    make_catalog,
    make_offer,
    make_product,
    make_seller,
    staff_client,
)


class Shop:
    def __init__(self, db: Session) -> None:
        staff = staff_client(db, "0911000200", StaffRole.SUPER_ADMIN)
        product = make_product(staff, make_catalog(staff))
        self.variant_id = product["variants"][0]["id"]
        self.other_variant_id = product["variants"][1]["id"]
        self.client, self.seller_id = make_seller(staff, "0911000001")

    def offer(self, quantity: int, **overrides: Any) -> uuid.UUID:
        created = make_offer(
            self.client, self.seller_id, self.variant_id, quantity=quantity, **overrides
        )
        return uuid.UUID(created["id"])


@pytest.fixture
def shop(db: Session) -> Shop:
    return Shop(db)


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    """Start every worker at the same instant; collect results or exceptions."""
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        try:
            return task(index)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


def _stock(db: Session, offer_id: uuid.UUID) -> tuple[int, int]:
    db.rollback()
    row = db.execute(
        select(Inventory.on_hand, Inventory.reserved).where(Inventory.offer_id == offer_id)
    ).one()
    return row.on_hand, row.reserved


def _movements(db: Session, offer_id: uuid.UUID) -> list[InventoryMovement]:
    return list(
        db.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.offer_id == offer_id)
            .order_by(InventoryMovement.created_at, InventoryMovement.id)
        )
    )


# -- the blueprint's test ----------------------------------------------------------


def test_one_hundred_buyers_and_one_unit_exactly_one_wins(shop: Shop, db: Session) -> None:
    """Blueprint G.9: "100 simultaneous purchases of the last unit create
    exactly one order." Each thread is one buyer's checkout transaction."""
    offer_id = shop.offer(1)

    def buy(_: int) -> bool:
        with session_scope() as session:
            return service.hold_stock(session, offer_id, 1, reference_type="test")

    results = _race(100, buy)
    assert results.count(True) == 1
    assert results.count(False) == 99
    assert _stock(db, offer_id) == (1, 1)
    holds = [m for m in _movements(db, offer_id) if m.reason == "reserve"]
    assert len(holds) == 1


def test_mixed_quantities_never_oversell(shop: Shop, db: Session) -> None:
    offer_id = shop.offer(25)
    quantities = [1, 2, 3, 4, 5] * 12  # 60 buyers wanting 180 units of 25

    def buy(index: int) -> int:
        with session_scope() as session:
            return (
                quantities[index] if service.hold_stock(session, offer_id, quantities[index]) else 0
            )

    held = sum(_race(len(quantities), buy))
    on_hand, reserved = _stock(db, offer_id)
    assert on_hand == 25
    assert reserved == held
    assert 20 < held <= 25  # nobody can be refused while 5 or more remain
    # The trail adds up to the stock: every hold is one movement.
    assert sum(m.delta_reserved for m in _movements(db, offer_id)) == held


def test_a_buyers_whole_order_rolls_back_when_one_line_runs_out(shop: Shop, db: Session) -> None:
    """Two lines in one transaction; the second cannot be met. The first hold
    and its movement vanish with the rollback (blueprint G.5 step 3)."""
    plenty = shop.offer(10)
    scarce = uuid.UUID(
        make_offer(shop.client, shop.seller_id, shop.other_variant_id, quantity=1)["id"]
    )

    class OutOfStock(Exception):
        pass

    def checkout() -> None:
        with session_scope() as session:
            assert service.hold_stock(session, plenty, 4) is True
            if not service.hold_stock(session, scarce, 2):
                raise OutOfStock

    with pytest.raises(OutOfStock):
        checkout()
    assert _stock(db, plenty) == (10, 0)
    assert _stock(db, scarce) == (1, 0)
    assert [m.reason for m in _movements(db, plenty)] == ["initial"]


def test_holds_race_the_sellers_stock_count_without_breaking_the_rules(
    shop: Shop, db: Session
) -> None:
    """Buyers hold units while the seller keeps retyping the shelf count.
    Whatever order they land in, reserved never exceeds on-hand."""
    offer_id = shop.offer(10)
    seller = db.get(Seller, shop.seller_id)
    assert seller is not None
    actor = Actor(type="user", user_id=None)

    def task(index: int) -> Any:
        with session_scope() as session:
            if index % 4 == 0:
                own = session.get(Seller, seller.id)
                assert own is not None
                service.set_stock(session, actor, own, offer_id, on_hand=index % 7)
                return "counted"
            return service.hold_stock(session, offer_id, 1)

    results = _race(60, task)
    refused = [r for r in results if isinstance(r, Conflict)]
    assert all(r.code == "stock_below_reserved" for r in refused)
    on_hand, reserved = _stock(db, offer_id)
    assert 0 <= reserved <= on_hand
    assert reserved == results.count(True)
    # Replaying the movement trail from zero reproduces the final stock exactly.
    trail = _movements(db, offer_id)
    assert sum(m.delta_on_hand for m in trail) == on_hand
    assert sum(m.delta_reserved for m in trail) == reserved


def test_concurrent_identical_offers_create_exactly_one(shop: Shop, db: Session) -> None:
    def create(_: int) -> uuid.UUID:
        with session_scope() as session:
            seller = session.get(Seller, shop.seller_id)
            assert seller is not None
            offer = service.create_offer(
                session, Actor(type="user", user_id=None), seller,
                service.OfferInput(
                    variant_id=uuid.UUID(shop.variant_id), condition="new",
                    price_santim=1_000_000, quantity=3,
                ),
            )  # fmt: skip
            return offer.id

    results = _race(20, create)
    created = [r for r in results if isinstance(r, uuid.UUID)]
    assert len(created) == 1
    assert all(
        isinstance(r, Conflict) and r.code == "offer_exists" for r in results if r not in created
    )
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Offer)) == 1
    assert _stock(db, created[0]) == (3, 0)


# -- the life of a reservation -------------------------------------------------------


def test_hold_release_and_commit_leave_a_complete_trail(shop: Shop, db: Session) -> None:
    offer_id = shop.offer(5)
    order_item = uuid.uuid4()
    reference = {"reference_type": "order_item", "reference_id": order_item}

    assert service.hold_stock(db, offer_id, 2, **reference) is True
    assert service.hold_stock(db, offer_id, 3, **reference) is True
    assert service.hold_stock(db, offer_id, 1, **reference) is False
    service.release_stock(db, offer_id, 3, **reference)  # one line is declined
    service.commit_stock(db, offer_id, 2, **reference)  # the other is delivered
    db.commit()

    assert _stock(db, offer_id) == (3, 0)
    trail = [
        (m.reason, m.delta_on_hand, m.delta_reserved, m.on_hand_after, m.reserved_after)
        for m in _movements(db, offer_id)
    ]
    assert trail == [
        ("initial", 5, 0, 5, 0),
        ("reserve", 0, 2, 5, 2),
        ("reserve", 0, 3, 5, 5),
        ("release", 0, -3, 5, 2),
        ("commit", -2, -2, 3, 0),
    ]
    assert {m.reference_id for m in _movements(db, offer_id)[1:]} == {order_item}


def test_stock_that_is_not_held_cannot_be_released_or_committed(shop: Shop, db: Session) -> None:
    offer_id = shop.offer(5)
    with pytest.raises(RuntimeError, match="reserved units to release"):
        service.release_stock(db, offer_id, 1)
    with pytest.raises(RuntimeError, match="reserved units to commit"):
        service.commit_stock(db, offer_id, 1)
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="whole number above zero"):
            service.hold_stock(db, offer_id, bad)  # type: ignore[arg-type]
    assert service.hold_stock(db, uuid.uuid4(), 1) is False
    assert _stock(db, offer_id) == (5, 0)


# -- what the database refuses by itself ---------------------------------------------


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("update inventory set reserved = on_hand + 1", "ck_inventory_reserved_within_on_hand"),
        ("update inventory set on_hand = -1", "ck_inventory_on_hand_non_negative"),
        ("update inventory set reserved = -1", "ck_inventory_reserved_non_negative"),
        ("update offers set price_santim = 0", "ck_offers_price_positive"),
        ("update offers set status = 'sold_out'", "ck_offers_status_allowed"),
        (
            "update offers set delivers_by_seller_rider = false, offers_shop_collection = false",
            "ck_offers_at_least_one_delivery_option",
        ),
    ],
)
def test_the_database_refuses_impossible_stock_and_offers(
    shop: Shop, db: Session, statement: str, constraint: str
) -> None:
    shop.offer(5)
    with pytest.raises(IntegrityError, match=constraint):
        db.execute(text(statement))
    db.rollback()
