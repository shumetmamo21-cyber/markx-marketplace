"""Disputes under contention (blueprint G.6, G.7): a reported problem races
completion, and two staff decisions race each other. Real threads, real
connections; every outcome must be one the state diagram allows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.audit.service import Actor
from markx.core.db import get_engine, session_scope
from markx.core.errors import AppError
from markx.core.phone import normalize_phone
from markx.orders import service
from markx.orders.models import SellerOrder
from markx.payments.models import FeeCharge
from markx.trust.models import CaseDecision, DisputeCase, DisputeMessage
from tests.bazaar import ADMIN, Bazaar, assert_stock_is_consistent, stock
from tests.db.test_fulfilment_contention import Parcel, _assert_every_move_is_an_arrow, _race


def _staff(db: Session) -> Actor:
    """The bazaar's own member of staff. Not the buyer: staff never decide on
    an order they placed (D-098)."""
    user_id = db.scalar(select(User.id).where(User.phone == normalize_phone(ADMIN)))
    assert user_id is not None
    return Actor(type="staff", user_id=user_id)


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
    staff = _staff(db)

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


@pytest.mark.parametrize(
    ("decision", "goods_returned"),
    [(CaseDecision.NO_ACTION, False), (CaseDecision.SELLER_REFUNDED, True)],
)
def test_a_decision_reads_the_clock_only_once_it_holds_the_order(
    bazaar: Bazaar, db: Session, monkeypatch: pytest.MonkeyPatch,
    decision: CaseDecision, goods_returned: bool,
) -> None:  # fmt: skip
    """The race above, made certain. `resolved_at` must be the moment the
    decision took effect, so the clock may only be read while the decision
    holds the seller order's lock. Read before it (as it once was), a reply
    that took the lock in between was stamped after the decision it preceded
    (CI #97). Each clock read is checked from a second connection: if that
    connection can lock the order at once, nobody holds it yet."""
    parcel = Parcel(db, bazaar, state="delivered")
    with session_scope() as session:
        service.open_dispute(
            session, parcel.buyer_user(session), parcel.order_id, parcel.so_id,
            problem_type="wrong_item", description="A different colour.",
        )  # fmt: skip
    db.rollback()
    staff = _staff(db)
    real_now = service._now
    held_when_read: list[bool] = []

    def watched_now() -> datetime:
        with get_engine().connect() as probe:
            try:
                probe.execute(
                    text("select 1 from seller_orders where id = :id for no key update nowait"),
                    {"id": parcel.so_id},
                )
                held = False
            except OperationalError as exc:
                if not isinstance(exc.orig, psycopg.errors.LockNotAvailable):
                    raise  # any other failure is a real error, not "held"
                held = True
            probe.rollback()
        held_when_read.append(held)
        return real_now()

    monkeypatch.setattr(service, "_now", watched_now)
    with session_scope() as session:
        service.resolve_dispute(
            session, staff, parcel.so_id, decision=decision, reason="Decided",
            goods_returned=goods_returned,
        )  # fmt: skip
    assert held_when_read, "the decision never read the clock"
    assert all(held_when_read), held_when_read
