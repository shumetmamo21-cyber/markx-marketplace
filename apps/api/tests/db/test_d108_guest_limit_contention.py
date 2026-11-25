"""Guest checkouts at the same moment (C-07, AD-13; D-108).

A guest's limits are counted per phone number and per network address, not
per account, so two browsers cannot be serialised by one cart lock as one
buyer's checkouts are (D-099). `place_guest_order` takes an advisory lock on
the number and then on the address, after the browser's cart and before any
seller or offer. Two guest orders at the same moment must never both slip
under a limit that only one of them fits. Each race runs five times.

These tests fail on the code before D-108: `place_guest_order` is new.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.core import settings_store
from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.orders import service
from markx.orders.models import Order
from tests.bazaar import Bazaar, assert_stock_is_consistent
from tests.factories import new_idempotency_key

RIDER = {"alpha": "seller_rider"}
ONE_BY_RIDER = 1_865_000  # one a128 (ETB 18,500) and the rider's fee (ETB 150)


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=20)


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        try:
            return task(index)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(run, range(workers)))


def _browser(bazaar: Bazaar) -> str:
    """A visitor's cart with one a128; returns the cart's secret."""
    with session_scope() as session:
        cart, token = service.create_anonymous_cart(session)
        service.set_cart_item(session, cart, uuid.UUID(bazaar.a128["id"]), 1)
    return token


def _place(bazaar: Bazaar, token: str, *, phone: str, ip: str) -> uuid.UUID:
    with session_scope() as session:
        order, _ = service.place_guest_order(
            session, cart_token=token,
            guest_fields={
                "recipient_name": "Racing Guest", "raw_phone": phone, "raw_phone2": None,
                "delivery_area_id": uuid.UUID(bazaar.area_id),
                "landmark": "Beside the Bole post office", "latitude": None, "longitude": None,
                "driver_notes": None,
            },
            ip=ip, bot_token="solved", deliveries=RIDER, payment_method="cash",
            expected_total_santim=ONE_BY_RIDER, idempotency_key=new_idempotency_key(),
            language="en",
        )  # fmt: skip
        return order.id


def _guest_orders(db: Session) -> int:
    db.rollback()
    return int(
        db.scalar(select(func.count()).select_from(Order).where(Order.guest_phone.is_not(None)))
        or 0
    )


@pytest.mark.parametrize("round_", range(5))
def test_two_guests_with_one_number_at_once_get_one_order(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """A guest may hold one open order per number (P-108-3): two browsers,
    two addresses, one number, at the same moment: one order."""
    tokens = [_browser(bazaar) for _ in range(2)]
    results = _race(
        2, lambda i: _place(bazaar, tokens[i], phone="0911888001", ip=f"198.51.100.{10 + i}")
    )
    placed = [r for r in results if isinstance(r, uuid.UUID)]
    refused = {r.code for r in results if isinstance(r, AppError)}
    assert len(placed) == 1, results
    assert refused == {"new_buyer_too_many_open_orders"}, refused
    assert _guest_orders(db) == 1
    assert_stock_is_consistent(db)


@pytest.mark.parametrize("round_", range(5))
def test_two_guests_behind_one_address_at_once_cannot_pass_its_limit_together(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """Two of the three open guest orders an address may have (P-108-4) are
    taken; two new numbers from that address at the same moment: one order."""
    for n in range(2):
        _place(bazaar, _browser(bazaar), phone=f"091188810{n}", ip="198.51.100.20")
    tokens = [_browser(bazaar) for _ in range(2)]
    results = _race(
        2, lambda i: _place(bazaar, tokens[i], phone=f"091188820{i}", ip="198.51.100.20")
    )
    placed = [r for r in results if isinstance(r, uuid.UUID)]
    refused = {r.code for r in results if isinstance(r, AppError)}
    assert len(placed) == 1, results
    assert refused == {"guest_network_limit"}, refused
    assert _guest_orders(db) == 3
    assert settings_store.get_int(db, "guest_checkout.max_open_orders_per_ip") == 3
    assert_stock_is_consistent(db)


def test_many_guests_at_once_from_many_numbers_and_addresses_all_order(
    bazaar: Bazaar, db: Session
) -> None:
    """Guests who share neither number nor address do not wait for, or
    refuse, each other: ten at once, ten orders, the stock exactly held."""
    tokens = [_browser(bazaar) for _ in range(10)]
    results = _race(
        10, lambda i: _place(bazaar, tokens[i], phone=f"09118883{i:02d}", ip=f"198.51.100.{30 + i}")
    )
    assert all(isinstance(r, uuid.UUID) for r in results), results
    assert _guest_orders(db) == 10
    assert_stock_is_consistent(db)
