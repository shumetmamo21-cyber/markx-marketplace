"""A store's performance in numbers (blueprint D.4, S-17, S-26, K.5; D-069).

"Performance is shown in numbers, not adjectives" (D.4). `figures` counts,
for one store and one period, what the performance page (S-17) and the
weekly message (S-26) show: the orders MarkX brought and what became of
them, how fast the store answered, delivery success, problems, reviews,
and the offers that need attention. Everything is the store's own business;
no buyer is named.

The weekly message: an hourly job finds the last complete week (Monday to
Sunday, Addis Ababa time), and for every trading store without a report for
it, stores the figures (one row per store and week, so a second run sends
nothing twice) and tells the store's members.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from markx.accounts.permissions import SELLER_PERMISSIONS, SellerCapability
from markx.core import settings_store
from markx.notifications import service as notifications
from markx.offers import selectors as offer_selectors
from markx.orders.deadlines import ADDIS_ABABA
from markx.orders.models import ActorType, OrderStatusEvent, SellerOrder, SellerOrderStatus
from markx.performance.models import SellerWeeklyReport
from markx.reviews.selectors import summary as rating_summary
from markx.sellers.models import Seller, SellerMember, SellerStatus
from markx.trust.models import Review, ReviewStatus

WEEKLY_BATCH = 200


logger = logging.getLogger("markx.performance")


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def figures(db: Session, seller_id: uuid.UUID, start: datetime, end: datetime) -> dict[str, Any]:
    """The store's numbers for [start, end)."""
    placed = list(
        db.execute(
            select(SellerOrder.status, SellerOrder.created_at, SellerOrder.confirmed_at).where(
                SellerOrder.seller_id == seller_id,
                SellerOrder.created_at >= start,
                SellerOrder.created_at < end,
            )
        ).all()
    )
    received = len(placed)
    # Who ended each cancelled one (D-086): the buyer, or the system because
    # the store did not fulfil it before its hold ran out (D-043). Counting
    # every cancellation as the buyer's blamed buyers for the store's delays.
    cancelled_by = dict(
        db.execute(
            select(OrderStatusEvent.actor_type, func.count())
            .join(SellerOrder, SellerOrder.id == OrderStatusEvent.seller_order_id)
            .where(
                SellerOrder.seller_id == seller_id,
                SellerOrder.created_at >= start,
                SellerOrder.created_at < end,
                OrderStatusEvent.to_status == SellerOrderStatus.CANCELLED,
            )
            .group_by(OrderStatusEvent.actor_type)
        ).all()
    )
    answered = [(c - p).total_seconds() / 60 for _, p, c in placed if c is not None]
    outcome = {s: sum(1 for status, _, _ in placed if status == s) for s in SellerOrderStatus}
    moves = dict(
        db.execute(
            select(OrderStatusEvent.to_status, func.count())
            .join(SellerOrder, SellerOrder.id == OrderStatusEvent.seller_order_id)
            .where(
                SellerOrder.seller_id == seller_id,
                OrderStatusEvent.occurred_at >= start,
                OrderStatusEvent.occurred_at < end,
            )
            .group_by(OrderStatusEvent.to_status)
        ).all()
    )
    completed_value = db.scalar(
        select(func.coalesce(func.sum(SellerOrder.items_total_santim), 0)).where(
            SellerOrder.seller_id == seller_id,
            SellerOrder.status == SellerOrderStatus.COMPLETED,
            SellerOrder.completed_at >= start,
            SellerOrder.completed_at < end,
        )
    )
    delivered = int(moves.get(SellerOrderStatus.DELIVERED, 0))
    failed = int(moves.get(SellerOrderStatus.DELIVERY_FAILED, 0))
    new_reviews = db.execute(
        select(func.count(), func.avg(Review.seller_rating)).where(
            Review.seller_id == seller_id,
            Review.moderation_status == ReviewStatus.PUBLISHED,
            Review.created_at >= start,
            Review.created_at < end,
        )
    ).one()
    offers = offer_selectors.seller_dashboard(db, seller_id)
    rating = rating_summary(db, "seller", [seller_id])
    return {
        "from_time": start.isoformat(),
        "to_time": end.isoformat(),
        "orders_received": received,
        "orders_confirmed": len(answered),
        "orders_declined": outcome[SellerOrderStatus.DECLINED],
        "orders_unanswered": outcome[SellerOrderStatus.EXPIRED],
        "orders_cancelled_by_buyer": int(cancelled_by.get(ActorType.BUYER, 0)),
        "orders_cancelled_unfulfilled": int(cancelled_by.get(ActorType.SYSTEM, 0)),
        "confirmation_share": _share(len(answered), received),
        "median_minutes_to_confirm": round(statistics.median(answered), 1) if answered else None,
        "delivered": delivered,
        "delivery_failed": failed,
        "delivery_success_share": _share(delivered, delivered + failed),
        "completed": int(moves.get(SellerOrderStatus.COMPLETED, 0)),
        "completed_value_santim": int(completed_value or 0),
        "problems_reported": int(moves.get(SellerOrderStatus.DISPUTED, 0)),
        "refunded": int(moves.get(SellerOrderStatus.REFUNDED, 0)),
        "new_reviews": int(new_reviews[0] or 0),
        "new_reviews_average": round(float(new_reviews[1]), 2) if new_reviews[1] else None,
        "rating_count": rating["count"],
        "rating_average": rating["average"],
        "active_offers": offers["active_offers"],
        "prices_to_confirm": offers["prices_to_confirm"],
        "low_stock_offers": offers["low_stock_offers"],
    }


# -- the weekly message (S-26) ------------------------------------------------------------


def last_complete_week(now: datetime) -> date:
    """The Monday that starts the last whole week before `now`, Addis time."""
    today = now.astimezone(ADDIS_ABABA).date()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, ADDIS_ABABA)
    return start, start + timedelta(days=7)


def send_weekly_reports(db: Session, now: datetime) -> int:
    """The scheduled `sellers.weekly_report` job. Returns how many it sent."""
    if not settings_store.get_bool(db, "sellers.weekly_report_enabled"):
        return 0
    week_start = last_complete_week(now)
    start, end = week_bounds(week_start)
    sent_already = select(SellerWeeklyReport.seller_id).where(
        SellerWeeklyReport.week_start == week_start
    )
    sellers = list(
        db.scalars(
            select(Seller.id)
            .where(
                Seller.status == SellerStatus.ACTIVE,
                Seller.created_at < end,
                Seller.id.not_in(sent_already),
            )
            .order_by(Seller.id)
            .limit(WEEKLY_BATCH)
        )
    )
    roles = [role.value for role in SELLER_PERMISSIONS[SellerCapability.SEE_PERFORMANCE]]
    sent = 0
    for seller_id in sellers:
        # Each store in its own savepoint (D-086, as D-060 does for orders):
        # one that fails is undone alone, logged and tried on the next run,
        # while every other store still gets its report.
        try:
            with db.begin_nested():
                _send_one(db, seller_id, week_start, start, end, roles)
                db.execute(text("set constraints all immediate"))
        except Exception:
            logger.exception(
                "a store's weekly report could not be made; it is tried again next run",
                extra={"seller_id": str(seller_id), "job": "sellers.weekly_report"},
            )
        else:
            sent += 1
        finally:
            db.execute(text("set constraints all deferred"))
    return sent


def _send_one(
    db: Session,
    seller_id: uuid.UUID,
    week_start: date,
    start: datetime,
    end: datetime,
    roles: list[str],
) -> None:
    numbers = figures(db, seller_id, start, end)
    report = SellerWeeklyReport(seller_id=seller_id, week_start=week_start, figures=numbers)
    db.add(report)
    db.flush()
    for user_id in db.scalars(
        select(SellerMember.user_id)
        .where(
            SellerMember.seller_id == seller_id,
            SellerMember.is_active,
            SellerMember.role.in_(roles),
        )
        .order_by(SellerMember.created_at)
    ):
        notifications.notify(
            db, user_id, "seller.weekly_report",
            {
                "seller_id": str(seller_id), "report_id": str(report.id),
                "week_start": week_start.isoformat(),
                "orders_received": numbers["orders_received"],
                # D-102: the Telegram text (S-26) also says these two.
                "orders_confirmed": numbers["orders_confirmed"],
                "prices_to_confirm": numbers["prices_to_confirm"],
                "completed": numbers["completed"],
                "completed_value_santim": numbers["completed_value_santim"],
            },
        )  # fmt: skip


def weekly_reports(db: Session, seller_id: uuid.UUID, *, limit: int) -> list[SellerWeeklyReport]:
    return list(
        db.scalars(
            select(SellerWeeklyReport)
            .where(SellerWeeklyReport.seller_id == seller_id)
            .order_by(SellerWeeklyReport.week_start.desc())
            .limit(limit)
        )
    )
