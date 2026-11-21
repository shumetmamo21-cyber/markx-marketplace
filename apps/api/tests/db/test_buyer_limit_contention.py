"""One buyer's buying limits under simultaneous orders, and expired orders
never counting against the buyer (pull request #7 review; D-099, D-101
task item 7).

The limits (D-099) are checked under the buyer's cart lock in `place_order`:
at most `orders.max_open_direct_orders` open orders, at most
`orders.max_unconfirmed_units_per_offer` and `..._per_seller` units held by
orders the shop has not answered, and the cancellation cool-down. Two
orders of one buyer at the same moment must not both slip under a limit
that only one of them fits, whichever reaches the lock first.
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

from markx.accounts.models import User
from markx.core import settings_store
from markx.core.db import session_scope
from markx.core.errors import AppError
from markx.orders import service
from markx.orders.models import Order, OrderItem, SellerOrder
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient
from tests.factories import add_to_cart, new_idempotency_key

ALPHA = {"alpha": "seller_rider"}
BETA = {"beta": "shop_collection"}


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=20)


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    """Run `task(i)` in `workers` threads released together; an AppError is
    returned, not raised. A refusal is any of the limit's own, or one that
    says the cart changed under the order (`cart_empty`: the other order
    spent it; `total_changed`: the other browser changed it after the
    quote; `delivery_choice_missing`: it added a shop), all of which leave
    nothing held."""
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        try:
            return task(index)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(run, range(workers)))


def _buyer(db: Session, bazaar: Bazaar) -> tuple[ApiClient, uuid.UUID, uuid.UUID]:
    client, address = bazaar.buyer()
    user_id = uuid.UUID(client.get("/me").json()["id"])
    return client, user_id, uuid.UUID(address)


def _fill(user_id: uuid.UUID, lines: list[tuple[str, int]]) -> None:
    with session_scope() as session:
        cart = service.user_cart(session, user_id, create=True)
        assert cart is not None
        for offer_id, quantity in lines:
            service.set_cart_item(session, cart, uuid.UUID(offer_id), quantity)


def _place(
    user_id: uuid.UUID,
    address_id: uuid.UUID,
    deliveries: dict[str, str],
    *,
    add: list[tuple[str, int]] | None = None,
    now: datetime | None = None,
) -> uuid.UUID:
    """One checkout, in its own transaction, as the checkout request makes
    it. With `add`, another browser of the same buyer first puts lines in
    the cart, in a request (a transaction) of its own."""
    if add:
        _fill(user_id, add)
    with session_scope() as session:
        user = session.get(User, user_id)
        assert user is not None
        cart = service.user_cart(session, user_id, create=True)
        assert cart is not None
        quote = service.build_quote(
            session, user, cart, address_id=address_id, deliveries=deliveries
        )
        order, _ = service.place_order(
            session, user, address_id=address_id, deliveries=deliveries, payment_method="cash",
            expected_total_santim=quote.grand_total.amount,
            idempotency_key=new_idempotency_key(), now=now,
        )  # fmt: skip
        return order.id


def _units_waiting(db: Session, user_id: uuid.UUID) -> int:
    db.rollback()
    return int(
        db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
            .join(Order, Order.id == SellerOrder.order_id)
            .where(Order.buyer_user_id == user_id, SellerOrder.status == "placed")
        )
        or 0
    )


def _orders(db: Session, user_id: uuid.UUID) -> int:
    db.rollback()
    return int(db.scalar(select(func.count()).where(Order.buyer_user_id == user_id)) or 0)


# -- simultaneous orders of one buyer -----------------------------------------------------------


@pytest.mark.parametrize("round_", range(5))
def test_two_simultaneous_checkouts_of_one_cart_make_one_order(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """Two browsers of one buyer press "Place order" at once, each with its
    own key: one order, the other finds the cart already spent."""
    client, user_id, address = _buyer(db, bazaar)
    second = ApiClient()
    for name in ("markx_session", "markx_csrf"):
        second.http.cookies.set(name, client.http.cookies.get(name))
    add_to_cart(client, bazaar.b128["id"], 5)
    choice = [{"store_slug": "beta", "method": "shop_collection"}]
    quote = client.post("/checkout/quote", json={"address_id": str(address), "deliveries": choice})
    body = {"address_id": str(address), "deliveries": choice, "payment_method": "cash",
            "expected_total_santim": quote.json()["grand_total_santim"]}  # fmt: skip
    results = _race(
        2,
        lambda i: (client, second)[i].post(
            "/checkout", json={**body, "idempotency_key": new_idempotency_key()}
        ),
    )
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 201, [r.text for r in results]
    assert codes[1] in (400, 409, 422), [r.text for r in results]
    assert _orders(db, user_id) == 1
    assert _units_waiting(db, user_id) == 5
    assert stock(db, bazaar.b128["id"]) == (20, 5)
    assert_stock_is_consistent(db)


@pytest.mark.parametrize("round_", range(5))
def test_two_simultaneous_orders_cannot_pass_the_per_offer_limit_together(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """4 units waiting already, of the 5 allowed. One browser orders the 1
    unit in the cart while another raises it to 2: whichever comes first,
    never more than 5 units are held."""
    _, user_id, address = _buyer(db, bazaar)
    _fill(user_id, [(bazaar.a128["id"], 4)])
    _place(user_id, address, ALPHA)
    _fill(user_id, [(bazaar.a128["id"], 1)])
    results = _race(
        2,
        lambda i: _place(user_id, address, ALPHA, add=None if i == 0 else [(bazaar.a128["id"], 2)]),
    )
    refused = {r.code for r in results if isinstance(r, AppError)}
    assert sum(isinstance(r, uuid.UUID) for r in results) <= 1, results
    assert refused <= {"unconfirmed_offer_limit", "cart_empty", "total_changed"}, refused
    assert _units_waiting(db, user_id) <= 5
    assert_stock_is_consistent(db)


@pytest.mark.parametrize("round_", range(5))
def test_two_simultaneous_orders_cannot_pass_the_per_shop_limit_together(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """A shop limit of 6: one order of 4 units of one offer and one of 4
    units of the other each fit alone; together they would hold 8."""
    settings_store.set_setting(db, "orders.max_unconfirmed_units_per_seller", 6)
    db.commit()
    _, user_id, address = _buyer(db, bazaar)
    _fill(user_id, [(bazaar.a128["id"], 4)])
    results = _race(
        2,
        lambda i: _place(user_id, address, ALPHA, add=None if i == 0 else [(bazaar.a256["id"], 4)]),
    )
    placed = [r for r in results if isinstance(r, uuid.UUID)]
    refused = {r.code for r in results if isinstance(r, AppError)}
    assert len(placed) <= 1, results
    assert refused <= {"unconfirmed_store_limit", "cart_empty", "total_changed"}, refused
    assert _units_waiting(db, user_id) <= 6
    assert_stock_is_consistent(db)


@pytest.mark.parametrize("round_", range(5))
def test_two_simultaneous_orders_cannot_pass_the_open_order_limit_together(
    bazaar: Bazaar, db: Session, round_: int
) -> None:
    """Two orders open of the three allowed: two more at once give one."""
    _, user_id, address = _buyer(db, bazaar)
    for _ in range(2):
        _fill(user_id, [(bazaar.b128["id"], 1)])
        _place(user_id, address, BETA)
    _fill(user_id, [(bazaar.b128["id"], 1)])
    results = _race(
        2,
        lambda i: _place(
            user_id, address, BETA if i == 0 else {**BETA, **ALPHA},
            add=None if i == 0 else [(bazaar.a128["id"], 1)],
        ),
    )  # fmt: skip
    refused = {r.code for r in results if isinstance(r, AppError)}
    assert sum(isinstance(r, uuid.UUID) for r in results) == 1, results
    assert refused <= {
        "too_many_open_orders",
        "cart_empty",
        "total_changed",
        "delivery_choice_missing",
    }, refused
    db.rollback()
    assert service.open_order_count(db, user_id) == 3
    assert settings_store.get_int(db, "orders.max_open_direct_orders") == 3
    assert_stock_is_consistent(db)


# -- expired orders never count against the buyer -----------------------------------------------


def _expire_everything_unanswered(db: Session) -> int:
    with session_scope() as session:
        return service.expire_unanswered_orders(session, now=datetime.now(UTC) + timedelta(days=7))


def test_expired_orders_do_not_hold_the_per_offer_or_per_shop_limit(
    bazaar: Bazaar, db: Session
) -> None:
    _, user_id, address = _buyer(db, bazaar)
    _fill(user_id, [(bazaar.a128["id"], 5), (bazaar.a256["id"], 5)])
    _place(user_id, address, ALPHA)
    assert _expire_everything_unanswered(db) == 1
    assert stock(db, bazaar.a128["id"]) == (20, 0), "an expired order's stock came back"
    # The same 5 + 5 again: an expired order counts for neither limit.
    _fill(user_id, [(bazaar.a128["id"], 5), (bazaar.a256["id"], 5)])
    _place(user_id, address, ALPHA)
    assert _units_waiting(db, user_id) == 10
    assert_stock_is_consistent(db)


def test_expired_orders_do_not_take_an_open_order_place(bazaar: Bazaar, db: Session) -> None:
    _, user_id, address = _buyer(db, bazaar)
    for _ in range(3):
        _fill(user_id, [(bazaar.b128["id"], 1)])
        _place(user_id, address, BETA)
    _fill(user_id, [(bazaar.b128["id"], 1)])
    with pytest.raises(AppError) as full:
        _place(user_id, address, BETA)
    assert full.value.code == "too_many_open_orders"
    assert _expire_everything_unanswered(db) == 3
    db.rollback()
    assert service.open_order_count(db, user_id) == 0
    _place(user_id, address, BETA)


def test_expired_orders_never_start_the_cancellation_cool_down(bazaar: Bazaar, db: Session) -> None:
    """Three orders the shop let expire in one day: the buyer did nothing
    wrong and may order again at once (unlike three cancellations)."""
    _, user_id, address = _buyer(db, bazaar)
    for _ in range(3):
        _fill(user_id, [(bazaar.b128["id"], 1)])
        _place(user_id, address, BETA)
        _expire_everything_unanswered(db)
    _fill(user_id, [(bazaar.b128["id"], 1)])
    _place(user_id, address, BETA)
    assert _orders(db, user_id) == 4
