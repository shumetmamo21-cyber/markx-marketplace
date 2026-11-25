"""A guest's cancel and the shop's answer at the same moment (F-28; D-109).

A guest may cancel only before the shop answers. `cancel_by_guest` locks the
shop's part of the order, as the shop's answer does, and then gives the
stock back in the lock order of every cancellation (seller orders, then
stock). Whichever comes first wins and the other is refused in words; the
stock is never given back for an order the shop has accepted, never kept for
one the guest cancelled, and never given back twice. Each race runs five
times.

These tests fail on the code before D-109: `cancel_by_guest` is new.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.orders import service
from markx.orders.models import Order, OrderStatusEvent, SellerOrder
from markx.sellers.models import Seller, SellerMember
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.db.test_d108_guest_limit_contention import _browser, _place, _race

# These tests run with what MarkX ships: 30 new-account days (F-27).
pytestmark = pytest.mark.founders_new_account_days


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=20)


def _guest_part(bazaar: Bazaar, db: Session, round_: int) -> tuple[uuid.UUID, uuid.UUID, int, str]:
    """A guest order of one a128; its id, its part's id and its link's query."""
    order_id = _place(
        bazaar, _browser(bazaar), phone=f"09117779{round_:02d}", ip=f"203.0.113.{150 + round_}"
    )
    with session_scope() as session:
        order = session.get(Order, order_id)
        assert order is not None
        link = service.issue_tracking_link(order)
    query = dict(pair.split("=") for pair in link.path.partition("?")[2].split("&"))
    db.rollback()
    part = db.scalar(select(SellerOrder).where(SellerOrder.order_id == order_id))
    assert part is not None
    return order_id, part.id, int(query["expires"]), query["signature"]


def _moves(db: Session, part_id: uuid.UUID) -> list[str]:
    db.rollback()
    return list(
        db.scalars(
            select(OrderStatusEvent.to_status)
            .where(OrderStatusEvent.seller_order_id == part_id)
            .order_by(OrderStatusEvent.occurred_at)
        )
    )


@pytest.mark.parametrize("round_", range(5))
def test_a_guest_cancel_and_the_shops_answer_at_once_one_wins(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    order_id, part_id, expires, signature = _guest_part(bazaar, db, round_)
    seller_id = uuid.UUID(bazaar.a_id)
    accept = round_ % 2 == 0  # the shop accepts in some rounds, declines in the others

    def task(index: int) -> Any:
        with session_scope() as session:
            if index == 0:
                service.cancel_by_guest(
                    session, order_id, part_id, expires=expires, signature=signature
                )
                return "cancelled"
            seller = session.get(Seller, seller_id)
            member = session.scalar(select(SellerMember).where(SellerMember.seller_id == seller_id))
            assert seller is not None
            assert member is not None
            return service.seller_respond(
                session, seller, member, part_id, accept=accept, reason="Gone"
            ).status

    results = _race(2, task)
    won = [r for r in results if not isinstance(r, AppError)]
    lost = {r.code for r in results if isinstance(r, AppError)}
    assert len(won) == 1, results
    assert lost <= {"order_cannot_be_cancelled", "order_not_awaiting_response"}, results
    final = won[0]
    assert _moves(db, part_id) == ["placed", final]
    # The stock follows the winner: held only for an order the shop accepted.
    assert stock(db, bazaar.a128["id"]) == (20, 1 if final == "confirmed" else 0)
    assert_stock_is_consistent(db)


@pytest.mark.parametrize("round_", range(5))
def test_two_cancels_from_two_tabs_at_once_cancel_once(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    order_id, part_id, expires, signature = _guest_part(bazaar, db, round_)

    def task(_: int) -> Any:
        with session_scope() as session:
            service.cancel_by_guest(
                session, order_id, part_id, expires=expires, signature=signature
            )
            return "cancelled"

    results = _race(2, task)
    assert results.count("cancelled") == 1, results
    assert {r.code for r in results if isinstance(r, AppError)} == {"order_cannot_be_cancelled"}
    assert _moves(db, part_id) == ["placed", "cancelled"]
    # Given back once: nothing is reserved, and nothing more is on hand.
    assert stock(db, bazaar.a128["id"]) == (20, 0)
    assert_stock_is_consistent(db)
