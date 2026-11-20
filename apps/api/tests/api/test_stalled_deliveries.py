"""Parts on the road, or after a failed handover, that nobody moves on (M6, D-099).

Before D-099 such a part waited for ever: no job looked at `out_for_delivery`
or `delivery_failed`, so it held its stock and one of the buyer's open-order
places with nobody told. Now each state has a time limit (PROVISIONAL,
P-099-1 and P-099-2). Once it passes, staff are told by order code, and the
part stops taking one of the buyer's places. The part is never ended and its
stock never released by the system: the goods are not on the shelf, and a
paid part must never end undelivered without staff (D-086).

Status events are append-only, so the tests move the clock forward (`now`)
instead of moving the events back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from markx.core import settings_store
from markx.core.db import session_scope
from markx.core.errors import Conflict
from markx.delivery.models import Shipment
from markx.offers.models import InventoryReservation
from markx.ops import checks
from markx.orders import service
from markx.orders.models import Order
from markx.orders.status import move_allowed
from tests.api.test_paid_orders import _pay
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import error_code
from tests.db.test_fulfilment_contention import Parcel
from tests.factories import add_to_cart, checkout, new_idempotency_key

ROAD = "orders.stalled_on_the_road"
FAILED = "orders.stalled_after_failed_handover"


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db, stock=10)


def _later(hours: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _findings(db: Session, now: datetime) -> dict[str, checks.Finding]:
    db.rollback()
    return {finding.key: finding for finding in checks.stalled_deliveries(db, now)}


def _code(db: Session, parcel: Parcel) -> str:
    db.rollback()
    return str(db.scalar(select(Order.code).where(Order.id == parcel.order_id)))


def _held(db: Session, parcel: Parcel) -> list[str]:
    db.rollback()
    return list(
        db.scalars(
            select(InventoryReservation.status).where(
                InventoryReservation.offer_id == parcel.offer_id
            )
        )
    )


def _fail_handover(bazaar: Bazaar, parcel: Parcel) -> None:
    response = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/delivery-failed",
        json={"reason": "Nobody at the gate"},
    )
    assert response.status_code == 200, response.text


def _assert_every_move_is_an_arrow(moves: list[str]) -> None:
    for before, after in pairwise(moves):
        assert move_allowed(before, after), moves


# -- on the road ----------------------------------------------------------------------------


def test_a_part_left_on_the_road_past_its_limit_goes_to_staff_and_keeps_its_stock(
    bazaar: Bazaar, db: Session
) -> None:
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    assert stock(db, parcel.offer_id) == (10, 2)

    assert ROAD not in _findings(db, _later(47))
    finding = _findings(db, _later(49))[ROAD]
    assert finding.severity == "warning"
    assert finding.details == {"count": 1, "order_codes": [_code(db, parcel)]}
    assert "follow them up with the shop" in finding.summary

    # Nothing else happened: the part, its stock and its hold are as they were,
    # and the scheduled jobs leave it alone however late it is.
    far = _later(24 * 60)
    with session_scope() as session:
        service.cancel_overdue_fulfilment(session, now=far)
        service.expire_unanswered_orders(session, now=far)
        service.complete_after_problem_window(session, now=far)
    assert parcel.status(db) == "out_for_delivery"
    assert stock(db, parcel.offer_id) == (10, 2)
    assert _held(db, parcel) == ["held"]

    # The shop can still finish it: the buyer's code still works.
    handed = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/handover", json={"code": parcel.code(db)}
    )
    assert handed.status_code == 200, handed.text
    assert ROAD not in _findings(db, _later(49))
    _assert_every_move_is_an_arrow(parcel.moves(db))
    assert_stock_is_consistent(db)
    # The default (PROVISIONAL, D-099).
    assert settings_store.get_int(db, "orders.out_for_delivery_limit_hours") == 48


def test_a_part_on_the_road_is_never_called_stalled_before_its_promised_time(
    bazaar: Bazaar, db: Session
) -> None:
    """A slow courier zone may promise more than the limit (rates allow up to
    720 hours): the part is followed up only once both have passed."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    db.execute(
        update(Shipment).where(Shipment.seller_order_id == parcel.so_id).values(promised_hours=100)
    )
    db.commit()
    assert ROAD not in _findings(db, _later(49))
    assert ROAD not in _findings(db, _later(99))
    assert _findings(db, _later(101))[ROAD].details["count"] == 1


def test_the_limit_is_a_setting(bazaar: Bazaar, db: Session) -> None:
    """Six hours, set by staff: the part's promised 24 hours still come first."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    settings_store.set_setting(db, "orders.out_for_delivery_limit_hours", 6)
    db.commit()
    assert ROAD not in _findings(db, _later(23))
    assert _findings(db, _later(25))[ROAD].details["order_codes"] == [_code(db, parcel)]


# -- after a failed handover -----------------------------------------------------------------


def test_a_part_waiting_after_a_failed_handover_goes_to_staff_and_keeps_its_stock(
    bazaar: Bazaar, db: Session
) -> None:
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    _fail_handover(bazaar, parcel)

    assert _findings(db, _later(71)) == {}
    found = _findings(db, _later(73))
    assert set(found) == {FAILED}
    assert found[FAILED].details == {"count": 1, "order_codes": [_code(db, parcel)]}

    with session_scope() as session:
        service.cancel_overdue_fulfilment(session, now=_later(24 * 60))
    assert parcel.status(db) == "delivery_failed"
    assert stock(db, parcel.offer_id) == (10, 2)
    assert _held(db, parcel) == ["held"]

    # Once the shop says the goods are back on the shelf, the stock returns
    # and staff are no longer asked.
    returned = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/return", json={"reason": "Back on shelf"}
    )
    assert returned.status_code == 200, returned.text
    assert stock(db, parcel.offer_id) == (10, 0)
    assert _findings(db, _later(73)) == {}
    _assert_every_move_is_an_arrow(parcel.moves(db))
    assert_stock_is_consistent(db)
    # The default (PROVISIONAL, D-099).
    assert settings_store.get_int(db, "orders.delivery_failed_limit_hours") == 72


def test_a_retry_after_a_failed_handover_is_on_the_road_again(bazaar: Bazaar, db: Session) -> None:
    """The clock counts from when the part last entered its status: a part
    sent out again is judged by the limit for the road."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    _fail_handover(bazaar, parcel)
    again = bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/dispatch", json={})
    assert again.status_code == 200, again.text
    assert set(_findings(db, _later(49))) == {ROAD}


def test_a_paid_part_after_a_failed_handover_is_left_to_the_paid_check(
    bazaar: Bazaar, db: Session
) -> None:
    """A part paid in advance (before D-087) is already reported a day after
    the failure by `orders.paid_delivery_failed` (D-086); it is not reported
    twice, and it still cannot go back to the shop without staff."""
    parcel = Parcel(db, bazaar, state="out_for_delivery")
    _fail_handover(bazaar, parcel)
    _pay(db, parcel)
    assert _findings(db, _later(73)) == {}
    db.rollback()
    assert "orders.paid_delivery_failed" in {
        finding.key for finding in checks.paid_orders_waiting(db, _later(73))
    }
    refused = bazaar.a.post(
        f"/seller/{bazaar.a_id}/orders/{parcel.so_id}/return", json={"reason": "Back on shelf"}
    )
    assert error_code(refused) == "paid_order_needs_staff"
    assert parcel.status(db) == "delivery_failed"
    assert stock(db, parcel.offer_id) == (10, 2)


def test_the_check_is_part_of_the_watch() -> None:
    assert checks.stalled_deliveries in checks.WATCH


# -- the buyer's open-order places ------------------------------------------------------------


def _place(parcel: Parcel, offer_id: str, address_id: str, *, now: datetime) -> None:
    """The same buyer orders one unit of a Beta offer at the given moment."""
    with session_scope() as session:
        user = parcel.buyer_user(session)
        cart = service.user_cart(session, user.id, create=True)
        assert cart is not None
        service.clear_cart(session, cart)
        service.set_cart_item(session, cart, uuid.UUID(offer_id), 1)
    with session_scope() as session:
        service.place_order(
            session, parcel.buyer_user(session), address_id=uuid.UUID(address_id),
            deliveries={"beta": "shop_collection"}, payment_method="cash",
            expected_total_santim=1_790_000, idempotency_key=new_idempotency_key(), now=now,
        )  # fmt: skip


def test_a_stalled_part_stops_taking_one_of_the_buyers_places_and_nothing_else(
    bazaar: Bazaar, db: Session
) -> None:
    """The buyer cannot move a part on the road on; after its limit it no
    longer counts against their open orders. It still holds its stock."""
    settings_store.set_setting(db, "orders.max_open_direct_orders", 1)
    db.commit()
    parcel = Parcel(db, bazaar, state="out_for_delivery")

    # Now, and just before the limit, the part counts: a second order is refused.
    add_to_cart(parcel.buyer, bazaar.b128["id"])
    address_id = parcel.buyer.get("/me/addresses").json()[0]["id"]
    assert error_code(checkout(parcel.buyer, address_id, {"beta": "shop_collection"})) == (
        "too_many_open_orders"
    )
    with pytest.raises(Conflict) as before:
        _place(parcel, bazaar.b128["id"], address_id, now=_later(47))
    assert before.value.code == "too_many_open_orders"

    # After the limit it no longer counts, and nothing else about it changed.
    _place(parcel, bazaar.b128["id"], address_id, now=_later(49))
    assert parcel.status(db) == "out_for_delivery"
    assert stock(db, parcel.offer_id) == (10, 2)
    with session_scope() as session:
        user = parcel.buyer_user(session)
        assert service.open_order_count(session, user.id, now=_later(49)) == 1
        assert service.open_order_count(session, user.id) == 2
    assert_stock_is_consistent(db)
