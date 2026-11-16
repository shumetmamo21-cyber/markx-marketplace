"""Fulfilment under contention (blueprint G.7, G.9, P10).

Every operation after confirmation locks the seller order row first, then the
shipment, then the reservations and stock. Threads race through the real
services with their own connections; exactly one of each pair of rivals wins,
stock is committed or released at most once, and nothing deadlocks.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.delivery.models import MAX_HANDOVER_ATTEMPTS, Shipment
from markx.orders import service
from markx.orders.models import ActorType, OrderStatusEvent, SellerOrder
from markx.orders.status import move_allowed
from markx.payments.models import FeeCharge
from markx.sellers.models import Seller, SellerMember
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.factories import add_to_cart, checkout


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        try:
            return task(index)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


class Parcel:
    """One rider order from Alpha for two units, taken to the given state
    through the API, with everything a thread needs to act on it."""

    def __init__(self, db: Session, bazaar: Bazaar, *, state: str) -> None:
        self.buyer, address_id = bazaar.buyer()
        add_to_cart(self.buyer, bazaar.a128["id"], 2)
        order = checkout(self.buyer, address_id, {"alpha": "seller_rider"}).json()
        self.order_id = uuid.UUID(order["id"])
        self.so_id = uuid.UUID(order["seller_orders"][0]["id"])
        self.seller_id = uuid.UUID(bazaar.a_id)
        self.offer_id = bazaar.a128["id"]
        base = f"/seller/{bazaar.a_id}/orders/{self.so_id}"
        steps = {"confirmed": 1, "ready": 2, "out_for_delivery": 3, "delivered": 4}[state]
        for step, path in enumerate(("confirm", "ready", "dispatch", "handover"), start=1):
            if step > steps:
                break
            body: dict[str, Any] = {}
            if path == "handover":
                body = {"code": self.code(db)}
            response = bazaar.a.post(f"{base}/{path}", json=body)
            assert response.status_code == 200, response.text
        db.rollback()
        self.buyer_user_id = uuid.UUID(self.buyer.get("/me").json()["id"])

    def code(self, db: Session) -> str:
        db.rollback()
        shipment = db.scalar(select(Shipment).where(Shipment.seller_order_id == self.so_id))
        assert shipment is not None
        return service.handover_code(shipment)

    def seller(self, session: Session) -> tuple[Seller, SellerMember]:
        seller = session.get(Seller, self.seller_id)
        member = session.scalar(
            select(SellerMember).where(SellerMember.seller_id == self.seller_id)
        )
        assert seller is not None
        assert member is not None
        return seller, member

    def buyer_user(self, session: Session) -> User:
        user = session.get(User, self.buyer_user_id)
        assert user is not None
        return user

    def moves(self, db: Session) -> list[str]:
        db.rollback()
        return list(
            db.scalars(
                select(OrderStatusEvent.to_status)
                .where(OrderStatusEvent.seller_order_id == self.so_id)
                .order_by(OrderStatusEvent.occurred_at, OrderStatusEvent.id)
            )
        )

    def status(self, db: Session) -> str:
        db.rollback()
        return str(db.scalar(select(SellerOrder.status).where(SellerOrder.id == self.so_id)))


def _assert_every_move_is_an_arrow(moves: list[str]) -> None:
    assert moves[0] == "placed"
    for before, after in pairwise(moves):
        assert move_allowed(before, after), moves


def test_delivery_races_a_failed_handover_and_a_return(bazaar: Bazaar, db: Session) -> None:
    """At the door: the right code, "nobody home", "take it back" and the
    worker's hold check all race for one parcel. Every move stays an arrow,
    and the stock is released at most once."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    code = parcel.code(db)
    far_future = datetime.now(UTC) + timedelta(days=30)

    def task(index: int) -> Any:
        with session_scope() as session:
            kind = index % 4
            if kind == 3:
                # Only confirmed and ready parts; this one is on the road.
                return service.cancel_overdue_fulfilment(session, now=far_future)
            seller, member = parcel.seller(session)
            if kind == 0:
                return service.seller_confirm_delivery(
                    session, seller, member, parcel.so_id, code=code
                ).status
            if kind == 1:
                return service.report_delivery_failed(
                    session, seller, member, parcel.so_id, reason="Nobody home"
                ).status
            return service.return_to_seller(
                session, seller, member, parcel.so_id, reason="Back to the shelf"
            ).status

    results = _race(24, task)
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_not_awaiting_handover", "order_move_not_allowed"}, results
    assert results.count(0) == 6  # the hold job never touched a parcel on the road
    moves = parcel.moves(db)
    _assert_every_move_is_an_arrow(moves)
    final = parcel.status(db)
    assert final in {"delivered", "delivery_failed", "returned"}
    assert moves.count("delivered") <= 1
    assert moves.count("returned") <= 1
    assert stock(db, parcel.offer_id) == ((5, 0) if final == "returned" else (5, 2))
    assert_stock_is_consistent(db)


def test_completion_races_the_buyer_the_worker_and_the_payment_record(
    bazaar: Bazaar, db: Session
) -> None:
    """The buyer's "received", the worker closing the window and the seller
    recording the payment, all at once: one completion, one fee charge, the
    stock committed exactly once."""
    parcel = Parcel(db, bazaar, state="delivered")
    db.rollback()
    window_end = db.scalar(
        select(SellerOrder.problem_window_ends_at).where(SellerOrder.id == parcel.so_id)
    )
    assert window_end is not None
    after = window_end + timedelta(minutes=1)

    def task(index: int) -> Any:
        with session_scope() as session:
            kind = index % 3
            if kind == 0:
                return service.complete_after_problem_window(session, now=after)
            if kind == 1:
                service.confirm_received(
                    session, parcel.buyer_user(session), parcel.order_id, parcel.so_id, now=after
                )
                return "buyer_completed"
            seller, member = parcel.seller(session)
            return service.record_direct_payment(
                session, seller, member, service.Actor(type="user", user_id=member.user_id),
                parcel.so_id, method="cash", now=after,
            ).status  # fmt: skip

    results = _race(30, task)
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_not_delivered", "already_paid"}, results
    # The worker's passes: one of them completed it, or the buyer did.
    worker_completions = sum(r for r in results if isinstance(r, int))
    buyer_completions = results.count("buyer_completed")
    assert worker_completions + buyer_completions == 1
    assert parcel.moves(db) == [
        "placed",
        "confirmed",
        "ready",
        "out_for_delivery",
        "delivered",
        "completed",
    ]
    assert stock(db, parcel.offer_id) == (3, 0)
    assert_stock_is_consistent(db)
    assert db.scalar(select(func.count()).select_from(FeeCharge)) == 1
    paid = db.execute(
        select(SellerOrder.paid_method, SellerOrder.commission_santim).where(
            SellerOrder.id == parcel.so_id
        )
    ).one()
    assert paid == ("cash", 0)


def test_wrong_codes_at_once_never_exceed_the_limit(bazaar: Bazaar, db: Session) -> None:
    """Twenty wrong codes in the same instant: exactly `MAX_HANDOVER_ATTEMPTS`
    count, the rest are refused as locked, and the right code is then dead."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    code = parcel.code(db)
    wrong = f"{(int(code) + 7) % 1_000_000:06d}"

    def task(index: int) -> Any:
        with session_scope() as session:
            seller, member = parcel.seller(session)
            return service.seller_confirm_delivery(
                session, seller, member, parcel.so_id, code=wrong
            ).status

    results = _race(20, task)
    codes = [r.code for r in results if isinstance(r, AppError)]
    assert len(codes) == 20
    assert codes.count("handover_code_wrong") == MAX_HANDOVER_ATTEMPTS - 1
    assert codes.count("handover_code_locked") == 20 - (MAX_HANDOVER_ATTEMPTS - 1)
    db.rollback()
    attempts = db.scalar(
        select(Shipment.handover_attempts).where(Shipment.seller_order_id == parcel.so_id)
    )
    assert attempts == MAX_HANDOVER_ATTEMPTS
    with session_scope() as session:
        seller, member = parcel.seller(session)
        with pytest.raises(AppError) as refused:
            service.seller_confirm_delivery(session, seller, member, parcel.so_id, code=code)
        assert refused.value.code == "handover_code_locked"
    assert parcel.status(db) == "out_for_delivery"


def test_the_worker_and_the_seller_race_for_an_overdue_hold(bazaar: Bazaar, db: Session) -> None:
    """The hold expires the moment the seller marks the part ready and
    dispatches: either the order was cancelled first (stock back), or it got
    on the road first (stock still held). Never both, never a deadlock."""
    parcel = Parcel(db, bazaar, state="confirmed")
    far_future = datetime.now(UTC) + timedelta(days=30)

    def task(index: int) -> Any:
        with session_scope() as session:
            if index % 2 == 0:
                return service.cancel_overdue_fulfilment(session, now=far_future)
            seller, member = parcel.seller(session)
            service.mark_ready(session, seller, member, parcel.so_id)
            return service.seller_dispatch(session, seller, member, parcel.so_id).status

    results = _race(16, task)
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_move_not_allowed"}, results
    final = parcel.status(db)
    moves = parcel.moves(db)
    _assert_every_move_is_an_arrow(moves)
    if final == "cancelled":
        assert sum(r for r in results if isinstance(r, int)) == 1
        assert stock(db, parcel.offer_id) == (5, 0)
    else:
        assert final == "out_for_delivery"
        assert moves == ["placed", "confirmed", "ready", "out_for_delivery"]
        assert stock(db, parcel.offer_id) == (5, 2)
    assert_stock_is_consistent(db)
    if final == "cancelled":
        (event,) = db.scalars(
            select(OrderStatusEvent).where(
                OrderStatusEvent.seller_order_id == parcel.so_id,
                OrderStatusEvent.to_status == "cancelled",
            )
        )
        assert (event.actor_type, event.reason) == (
            ActorType.SYSTEM.value,
            "fulfilment_hold_expired",
        )
