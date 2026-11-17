"""Disputes under contention (blueprint G.6, G.7): a reported problem races
completion, and two staff decisions race each other. Real threads, real
connections; every outcome must be one the state diagram allows.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.audit.service import Actor
from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.orders import service
from markx.orders.models import SellerOrder
from markx.payments.models import FeeCharge
from markx.trust.models import CaseDecision, DisputeCase, DisputeMessage
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.db.test_fulfilment_contention import Parcel, _assert_every_move_is_an_arrow, _race


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def test_a_problem_report_races_completion(bazaar: Bazaar, db: Session) -> None:
    """The buyer's report (just inside the window), the buyer's "received"
    and the worker closing the window all hit one delivered part. It ends
    disputed or completed, never both: a disputed part keeps its stock held
    and is charged nothing; a completed one has no case."""
    parcel = Parcel(db, bazaar, state="delivered")
    window_end = db.scalar(
        select(SellerOrder.problem_window_ends_at).where(SellerOrder.id == parcel.so_id)
    )
    assert window_end is not None
    db.rollback()

    def task(index: int) -> Any:
        with session_scope() as session:
            kind = index % 3
            if kind == 0:
                service.open_dispute(
                    session, parcel.buyer_user(session), parcel.order_id, parcel.so_id,
                    problem_type="damaged", description="The screen is cracked.",
                    now=window_end - timedelta(seconds=1),
                )  # fmt: skip
                return "disputed"
            if kind == 1:
                service.confirm_received(
                    session, parcel.buyer_user(session), parcel.order_id, parcel.so_id
                )
                return "completed"
            done = service.complete_after_problem_window(
                session, now=window_end + timedelta(minutes=1)
            )
            return "completed" if done else None

    results = _race(30, task)
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_not_delivered"}, results
    winners = [r for r in results if isinstance(r, str)]
    assert len(winners) == 1, results
    moves = parcel.moves(db)
    _assert_every_move_is_an_arrow(moves)
    assert moves[-1] == winners[0]
    cases = db.scalar(select(func.count()).select_from(DisputeCase))
    charges = db.scalar(select(func.count()).select_from(FeeCharge))
    if winners[0] == "disputed":
        assert (cases, charges) == (1, 0)
        assert stock(db, parcel.offer_id) == (5, 2)
    else:
        assert (cases, charges) == (0, 1)
        assert stock(db, parcel.offer_id) == (3, 0)
    assert_stock_is_consistent(db)


def test_two_decisions_and_a_reply_race_on_one_case(bazaar: Bazaar, db: Session) -> None:
    """Staff decide "no action" and "refunded, goods returned" at the same
    instant while the seller is still answering: exactly one decision lands,
    the stock is settled exactly once, and no message joins a decided case."""
    parcel = Parcel(db, bazaar, state="delivered")
    with session_scope() as session:
        service.open_dispute(
            session, parcel.buyer_user(session), parcel.order_id, parcel.so_id,
            problem_type="wrong_item", description="A different colour.",
        )  # fmt: skip
    staff = Actor(type="staff", user_id=parcel.buyer_user_id)  # any real user id will do here

    def task(index: int) -> Any:
        with session_scope() as session:
            kind = index % 3
            if kind == 0:
                return service.resolve_dispute(
                    session, staff, parcel.so_id, decision=CaseDecision.NO_ACTION, reason="Fine"
                ).status
            if kind == 1:
                return service.resolve_dispute(
                    session, staff, parcel.so_id, decision=CaseDecision.SELLER_REFUNDED,
                    reason="Refunded", goods_returned=True,
                ).status  # fmt: skip
            seller, member = parcel.seller(session)
            service.seller_reply_to_dispute(session, seller, member, parcel.so_id, body="Sorry")
            return None

    results = _race(30, task)
    errors = {r.code for r in results if isinstance(r, AppError)}
    assert errors <= {"order_not_disputed", "problem_already_resolved"}, results
    (outcome,) = [r for r in results if isinstance(r, str)]
    moves = parcel.moves(db)
    _assert_every_move_is_an_arrow(moves)
    assert moves[-2:] == ["disputed", outcome]
    case = db.scalar(select(DisputeCase))
    assert case is not None
    charges = db.scalar(select(func.count()).select_from(FeeCharge))
    if outcome == "completed":
        assert (case.decision, charges) == ("no_action", 1)
        assert stock(db, parcel.offer_id) == (3, 0)
    else:
        assert (case.decision, charges) == ("seller_refunded", 0)
        assert stock(db, parcel.offer_id) == (5, 0)
    assert_stock_is_consistent(db)
    # Every reply that was accepted came before the decision.
    late = db.scalar(
        select(func.count())
        .select_from(DisputeMessage)
        .where(DisputeMessage.created_at > case.resolved_at)
    )
    assert late == 0
