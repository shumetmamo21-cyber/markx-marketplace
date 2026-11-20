"""Parts on the road, or after a failed handover, that nobody moves on (M6, D-099).

Only the shop moves a part out of `out_for_delivery` (the buyer's code, or
"the handover failed") and out of `delivery_failed` (a retry, or "returned").
A shop that does neither left such a part, its held stock and one of the
buyer's open-order places waiting for ever: the overdue-fulfilment job covers
only `confirmed` and `ready` (D-043), and rightly, because goods on the road
are no longer on the shelf.

So each of the two states has a time limit (PROVISIONAL, P-099-1 and P-099-2,
in `core/settings_store.py`), counted from the moment the part last entered
it, so a retry starts the clock again. A part on the road is never called
stalled before its own promised delivery time. Once its limit passes:

- the operations watch reports it to staff by order code, for follow-up with
  the shop (`ops.checks.stalled_deliveries`); the part keeps its status, and
  the buyer and the shop still see it and can still act on it;
- it stops counting against the buyer's open orders (`open_order_count`),
  which is safe: the buyer cannot move it on, and no goods or money move;
- its stock is NOT released, and the part is never ended by the system. The
  goods are with a rider, the buyer or somewhere unknown, so releasing the
  hold could sell a unit the shop no longer has; and a part with a recorded
  payment must never end undelivered without staff (D-086). The stock comes
  back when the shop records the return (`return_to_seller`) once the goods
  are back, or the part completes when they were in fact delivered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from markx.core import settings_store
from markx.delivery.models import Shipment
from markx.orders.models import OrderStatusEvent, SellerOrder, SellerOrderStatus

ON_THE_ROAD = SellerOrderStatus.OUT_FOR_DELIVERY
AFTER_FAILED_HANDOVER = SellerOrderStatus.DELIVERY_FAILED


def entered_current_status() -> Any:
    """When the part last entered the status it has now, from its events
    (every move writes one, and the database refuses a move without it)."""
    return (
        select(func.max(OrderStatusEvent.occurred_at))
        .where(
            OrderStatusEvent.seller_order_id == SellerOrder.id,
            OrderStatusEvent.to_status == SellerOrder.status,
        )
        .scalar_subquery()
    )


def _hours(hours: Any) -> Any:
    return func.make_interval(0, 0, 0, 0, hours)


def stalled_on_the_road(db: Session, now: datetime) -> Any:
    """Out for delivery for longer than the limit and than its own promised
    delivery time."""
    limit = settings_store.get_int(db, "orders.out_for_delivery_limit_hours")
    promised = (
        select(Shipment.promised_hours)
        .where(Shipment.seller_order_id == SellerOrder.id)
        .scalar_subquery()
    )
    return and_(
        SellerOrder.status == ON_THE_ROAD,
        entered_current_status() + _hours(func.greatest(limit, func.coalesce(promised, 0))) <= now,
    )


def stalled_after_failed_handover(db: Session, now: datetime) -> Any:
    """Waiting after a failed handover, neither retried nor returned, for
    longer than the limit."""
    limit = settings_store.get_int(db, "orders.delivery_failed_limit_hours")
    return and_(
        SellerOrder.status == AFTER_FAILED_HANDOVER,
        entered_current_status() + _hours(limit) <= now,
    )


def stalled(db: Session, now: datetime) -> Any:
    """Either of the two: a condition on `SellerOrder` for a query."""
    return or_(stalled_on_the_road(db, now), stalled_after_failed_handover(db, now))
