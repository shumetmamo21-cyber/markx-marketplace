"""Order actions that a person starts read the clock only once they hold the
seller order (D-086), as `resolve_dispute` does (see test_dispute_contention).

Read before the lock, an action that waited behind another was stamped before
the action that came first: a buyer's cancel that waited for the seller's
confirmation was recorded as "cancelled" before "confirmed", an order history
the life cycle does not allow. At every clock read, a second connection tries
to lock the order without waiting; it must be refused.

The scheduled jobs (expiry, completion after the window, overdue fulfilment)
and the two deadline checks a person is entitled to (`seller_respond`,
`open_dispute`: the button was pressed in time) keep reading the clock first,
on purpose; see docs/DEVELOPMENT_STATUS.md.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from markx.audit.service import Actor
from markx.core.db import get_engine, session_scope
from markx.orders import service
from tests.bazaar import Bazaar
from tests.db.test_fulfilment_contention import Parcel


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def _watch_the_clock(monkeypatch: pytest.MonkeyPatch, so_id: Any) -> list[bool]:
    """Record, at each clock read, whether someone already holds the order."""
    real_now = service._now
    held_when_read: list[bool] = []

    def watched_now() -> datetime:
        with get_engine().connect() as probe:
            try:
                probe.execute(
                    text("select 1 from seller_orders where id = :id for no key update nowait"),
                    {"id": so_id},
                )
                held = False
            except OperationalError as exc:
                if not isinstance(exc.orig, psycopg.errors.LockNotAvailable):
                    raise
                held = True
            probe.rollback()
        held_when_read.append(held)
        return real_now()

    monkeypatch.setattr(service, "_now", watched_now)
    return held_when_read


def _cancel(parcel: Parcel, session: Session) -> None:
    service.cancel_by_buyer(session, parcel.buyer_user(session), parcel.order_id, parcel.so_id)


def _confirm_received(parcel: Parcel, session: Session) -> None:
    service.confirm_received(session, parcel.buyer_user(session), parcel.order_id, parcel.so_id)


def _record_payment(parcel: Parcel, session: Session) -> None:
    seller, member = parcel.seller(session)
    actor = Actor(type="user", user_id=member.user_id)
    service.record_direct_payment(session, seller, member, actor, parcel.so_id, method="cash")


@pytest.mark.parametrize(
    ("state", "action", "after"),
    [
        ("confirmed", _cancel, "cancelled"),
        ("delivered", _confirm_received, "completed"),
        ("ready", _record_payment, "ready"),
    ],
    ids=["cancel_by_buyer", "confirm_received", "record_direct_payment"],
)
def test_the_clock_is_read_only_once_the_order_is_held(
    bazaar: Bazaar,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    action: Callable[[Parcel, Session], None],
    after: str,
) -> None:
    parcel = Parcel(db, bazaar, state=state)
    held_when_read = _watch_the_clock(monkeypatch, parcel.so_id)
    with session_scope() as session:
        action(parcel, session)
    assert parcel.status(db) == after
    assert held_when_read, "the action never read the clock"
    assert all(held_when_read), held_when_read
