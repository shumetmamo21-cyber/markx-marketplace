"""Checkout under contention (blueprint G.9, P9).

Many threads, each with its own database connection, race through the real
`place_order` and the operations that share its locks. These go around the
HTTP layer so that a hundred buyers can really submit at the same instant.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import User
from markx.audit.service import Actor
from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.offers import service as offers
from markx.offers.models import Offer
from markx.orders import service
from markx.orders.models import Order, OrderStatusEvent, SellerOrder
from markx.sellers.models import Seller, SellerMember
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.factories import new_idempotency_key

ACTOR = Actor(type="user", user_id=None)


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    """Start every worker at the same instant; collect results or app errors."""
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        try:
            return task(index)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


class Crowd:
    """Buyers made straight through the services: a hundred sign-ins through
    the API would take minutes and trip the rate limits meant for attackers."""

    def __init__(self, db: Session, bazaar: Bazaar, count: int) -> None:
        self.user_ids: list[uuid.UUID] = []
        self.address_ids: list[uuid.UUID] = []
        for n in range(count):
            user = accounts.get_or_create_user_by_phone(db, f"+2519{20_000_000 + n:08d}")
            address = accounts.create_address(
                db, user, recipient_name=f"Buyer {n}", raw_phone=user.phone, raw_phone2=None,
                delivery_area_id=uuid.UUID(bazaar.area_id), landmark="By the big tree",
                latitude=None, longitude=None, driver_notes=None,
            )  # fmt: skip
            self.user_ids.append(user.id)
            self.address_ids.append(address.id)
        db.commit()

    def fill(self, db: Session, index: int, offer_id: str, quantity: int) -> None:
        cart = service.user_cart(db, self.user_ids[index], create=True)
        assert cart is not None
        service.set_cart_item(db, cart, uuid.UUID(offer_id), quantity)
        db.commit()

    def order(
        self, index: int, deliveries: dict[str, str], total: int, now: datetime | None = None
    ) -> uuid.UUID:
        with session_scope() as session:
            user = session.get(User, self.user_ids[index])
            assert user is not None
            order, _ = service.place_order(
                session, user, address_id=self.address_ids[index], deliveries=deliveries,
                payment_method="cash", expected_total_santim=total,
                idempotency_key=new_idempotency_key(), now=now,
            )  # fmt: skip
            return order.id


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=1)


# -- the blueprint's own tests (G.9, P9) -----------------------------------------------


def test_one_hundred_simultaneous_checkouts_of_the_last_unit_create_exactly_one_order(
    bazaar: Bazaar, db: Session
) -> None:
    crowd = Crowd(db, bazaar, 100)
    for index in range(100):
        crowd.fill(db, index, bazaar.b128["id"], 1)

    results = _race(100, lambda i: crowd.order(i, {"beta": "shop_collection"}, 1_790_000))
    won = [r for r in results if isinstance(r, uuid.UUID)]
    lost = [r for r in results if isinstance(r, AppError)]
    assert len(won) == 1
    assert len(lost) == 99
    assert {exc.code for exc in lost} == {"out_of_stock"}
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert db.scalar(select(func.count()).select_from(SellerOrder)) == 1
    assert stock(db, bazaar.b128["id"]) == (1, 1)
    assert_stock_is_consistent(db)
    # Ninety-nine carts are untouched; one was spent.
    carts_with_lines = db.scalar(
        select(func.count(func.distinct(service.CartItem.cart_id))).select_from(service.CartItem)
    )
    assert carts_with_lines == 99


def test_fifty_buyers_competing_for_ten_units_get_exactly_ten(bazaar: Bazaar, db: Session) -> None:
    bazaar.b.put(f"/seller/{bazaar.b_id}/offers/{bazaar.b128['id']}/stock", json={"on_hand": 10})
    crowd = Crowd(db, bazaar, 50)
    for index in range(50):
        crowd.fill(db, index, bazaar.b128["id"], 1)

    results = _race(50, lambda i: crowd.order(i, {"beta": "shop_collection"}, 1_790_000))
    assert sum(isinstance(r, uuid.UUID) for r in results) == 10
    assert {r.code for r in results if isinstance(r, AppError)} == {"out_of_stock"}
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Order)) == 10
    assert stock(db, bazaar.b128["id"]) == (10, 10)
    assert_stock_is_consistent(db)


def test_mixed_quantities_never_oversell_at_checkout(bazaar: Bazaar, db: Session) -> None:
    bazaar.a.put(f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}/stock", json={"on_hand": 7})
    crowd = Crowd(db, bazaar, 30)
    wanted = [1, 2, 3] * 10
    for index in range(30):
        crowd.fill(db, index, bazaar.a128["id"], wanted[index])

    results = _race(
        30, lambda i: crowd.order(i, {"alpha": "shop_collection"}, wanted[i] * 1_850_000)
    )
    db.rollback()
    on_hand, reserved = stock(db, bazaar.a128["id"])
    assert on_hand == 7
    sold = sum(wanted[i] for i, r in enumerate(results) if isinstance(r, uuid.UUID))
    assert reserved == sold
    assert 5 <= sold <= 7  # nobody who wanted one unit can be refused while one is free
    assert_stock_is_consistent(db)


# -- every operation that takes two locks, raced against the others ----------------------


def test_checkouts_race_the_seller_editing_the_offer_without_deadlock(
    bazaar: Bazaar, db: Session
) -> None:
    """Checkout locks the seller, the offer and then the stock row; the
    seller's price edit and stock count lock the offer and then the stock
    row (D-027). Same order, so nobody waits in a circle."""
    bazaar.a.put(f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}/stock", json={"on_hand": 20})
    crowd = Crowd(db, bazaar, 40)
    for index in range(40):
        crowd.fill(db, index, bazaar.a128["id"], 1)
    offer_id = uuid.UUID(bazaar.a128["id"])
    seller_id = uuid.UUID(bazaar.a_id)

    price = {"seen": 1_850_000}

    def task(index: int) -> Any:
        if index % 4 == 1:
            with session_scope() as session:
                seller = session.get(Seller, seller_id)
                assert seller is not None
                offers.update_offer(
                    session, ACTOR, seller, offer_id, price_santim=1_850_000 + (index % 2)
                )
                return "repriced"
        if index % 4 == 3:
            with session_scope() as session:
                seller = session.get(Seller, seller_id)
                assert seller is not None
                offers.set_stock(session, ACTOR, seller, offer_id, on_hand=20 - index % 5)
                return "counted"
        return crowd.order(index, {"alpha": "shop_collection"}, price["seen"])

    for _ in range(3):
        # Every buyer starts each round with the item in the cart at today's
        # price: a buyer whose order won the round before has an empty cart,
        # and would otherwise be refused for that alone ("cart_empty"), which
        # is no part of the race this test is about.
        for index in range(40):
            if index % 4 in (0, 2):
                crowd.fill(db, index, bazaar.a128["id"], 1)
        price["seen"] = int(db.scalar(select(Offer.price_santim).where(Offer.id == offer_id)) or 0)
        db.rollback()
        results = _race(40, task)
        codes = {r.code for r in results if isinstance(r, AppError)}
        # Only the refusals the rules call for: never a deadlock or a timeout.
        assert codes <= {"out_of_stock", "price_changed", "stock_below_reserved"}, results
        assert_stock_is_consistent(db)


def test_the_seller_the_buyer_and_the_clock_race_for_one_order(bazaar: Bazaar, db: Session) -> None:
    """Confirm, decline, cancel and expiry all lock the seller order row and
    then the reservations and stock. Exactly one of them wins; the stock is
    released at most once; every move has exactly one event."""
    bazaar.b.put(f"/seller/{bazaar.b_id}/offers/{bazaar.b128['id']}/stock", json={"on_hand": 3})
    crowd = Crowd(db, bazaar, 1)
    crowd.fill(db, 0, bazaar.b128["id"], 2)
    placed_at = datetime.now(UTC)
    order_id = crowd.order(0, {"beta": "shop_collection"}, 3_580_000, now=placed_at)
    db.rollback()
    seller_order = db.scalar(select(SellerOrder).where(SellerOrder.order_id == order_id))
    assert seller_order is not None
    deadline = seller_order.response_deadline
    seller_id, so_id = uuid.UUID(bazaar.b_id), seller_order.id

    def task(index: int) -> Any:
        with session_scope() as session:
            kind = index % 4
            if kind == 0:
                return service.expire_unanswered_orders(session, now=deadline + timedelta(hours=1))
            if kind == 3:
                user = session.get(User, crowd.user_ids[0])
                assert user is not None
                return service.cancel_by_buyer(session, user, order_id, so_id).status
            seller = session.get(Seller, seller_id)
            member = session.scalar(select(SellerMember).where(SellerMember.seller_id == seller_id))
            assert seller is not None
            assert member is not None
            return service.seller_respond(
                session, seller, member, so_id, accept=kind == 1, reason="Gone",
                now=deadline - timedelta(seconds=1),
            ).status  # fmt: skip

    results = _race(32, task)
    outcomes = [r for r in results if not isinstance(r, AppError)]
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_not_awaiting_response", "order_cannot_be_cancelled"}, results
    db.rollback()
    db.refresh(seller_order)
    final = seller_order.status
    moves = list(
        db.scalars(
            select(OrderStatusEvent.to_status)
            .where(OrderStatusEvent.seller_order_id == so_id)
            .order_by(OrderStatusEvent.occurred_at)
        )
    )
    if final == "cancelled" and "confirmed" in moves:
        # The seller confirmed first and the buyer cancelled after: two moves.
        assert moves == ["placed", "confirmed", "cancelled"]
    else:
        assert moves == ["placed", final]
    assert final in {"confirmed", "declined", "cancelled", "expired"}
    assert stock(db, bazaar.b128["id"]) == ((3, 2) if final == "confirmed" else (3, 0))
    assert_stock_is_consistent(db)
    assert outcomes.count(0) + outcomes.count(1) == results.count(0) + results.count(1)
