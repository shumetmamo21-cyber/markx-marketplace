"""What the marketplace checks about itself (blueprint F.8, F.12; D-064).

Each check reads the database and returns findings: a stable key, a
severity, one line a person can act on, and details. Findings carry counts,
order codes and ids, never a name, phone number or address (F.12: alerts
leave the server).

`watch` checks run every few minutes; `reconcile` checks run once a day and
prove that order totals add up and that fees match the ledger (F.12, "a
daily reconciliation report").
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from markx.catalog.models import ImageStatus, ProductImage
from markx.core import ratelimit, settings_store
from markx.notifications.models import Outbox
from markx.offers.models import Inventory, InventoryReservation, ReservationStatus
from markx.orders.models import Order, OrderItem, SellerOrder, SellerOrderStatus
from markx.payments.models import FeeCharge, LedgerEntry
from markx.trust.models import (
    CaseStatus,
    DisputeCase,
    Review,
    ReviewStatus,
)
from markx.worker.models import ScheduledJob

logger = logging.getLogger("markx.ops.checks")

SAMPLE = 10  # ids or codes named in one finding

# How long past its moment a thing may be before it is called stuck. The
# jobs run every one to ten minutes, so these leave room for a slow run.
STUCK_DELIVERED = timedelta(minutes=30)
STUCK_PLACED = timedelta(minutes=15)
STUCK_HOLD = timedelta(minutes=30)
OUTBOX_BACKLOG = timedelta(minutes=15)
IMAGE_STUCK = timedelta(minutes=30)
JOB_FAILURES_ALERT = 3
SMS_WARNING_SHARE = 0.8


@dataclass(frozen=True, slots=True)
class Finding:
    key: str
    severity: str  # "warning" or "critical"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


Check = Callable[[Session, datetime], list[Finding]]


# -- watch -----------------------------------------------------------------------------


def failing_jobs(db: Session, now: datetime) -> list[Finding]:
    """A scheduled job that failed three times in a row (F.8)."""
    return [
        Finding(
            key=f"job.failing:{job.name}",
            severity="critical",
            summary=f"The scheduled job {job.name} has failed {job.consecutive_failures} times "
            "in a row.",
            details={
                "job": job.name,
                "failures": job.consecutive_failures,
                "last_error": (job.last_error or "")[:300],
            },
        )
        for job in db.scalars(
            select(ScheduledJob)
            .where(ScheduledJob.consecutive_failures >= JOB_FAILURES_ALERT)
            .order_by(ScheduledJob.name)
        )
    ]


def overdue_jobs(db: Session, now: datetime) -> list[Finding]:
    """A job that was due long ago and has not run: a worker is stuck, or the
    job's own lock is held by a run that never ends."""
    late = list(
        db.scalars(
            select(ScheduledJob.name)
            .where(
                ScheduledJob.next_run_at < now - timedelta(minutes=30),
                # The watch itself is running right now; its row is updated
                # only when it returns.
                ScheduledJob.name != "ops.watch",
            )
            .order_by(ScheduledJob.name)
        )
    )
    if not late:
        return []
    return [
        Finding(
            key="jobs.overdue",
            severity="critical",
            summary=f"{len(late)} scheduled job(s) are more than 30 minutes overdue: "
            f"{', '.join(late[:SAMPLE])}.",
            details={"jobs": late},
        )
    ]


def outbox_problems(db: Session, now: datetime) -> list[Finding]:
    """Messages that gave up, and a queue that is not draining."""
    findings = []
    failed = db.execute(
        select(Outbox.topic, func.count())
        .where(Outbox.status == "failed", Outbox.finished_at >= now - timedelta(days=7))
        .group_by(Outbox.topic)
        .order_by(Outbox.topic)
    ).all()
    if failed:
        total = sum(count for _, count in failed)
        findings.append(
            Finding(
                key="outbox.failed",
                severity="critical",
                summary=f"{total} outbox message(s) gave up in the last 7 days "
                f"({', '.join(f'{topic}: {count}' for topic, count in failed)}).",
                details={"by_topic": dict(failed)},
            )
        )
    backlog = db.execute(
        # By the database's clock, which stamped `run_after` itself.
        select(func.count(), func.min(Outbox.run_after)).where(
            Outbox.status == "pending", Outbox.run_after < func.now() - OUTBOX_BACKLOG
        )
    ).one()
    if backlog[0]:
        findings.append(
            Finding(
                key="outbox.backlog",
                severity="warning",
                summary=f"{backlog[0]} outbox message(s) have waited more than 15 minutes.",
                details={"count": backlog[0], "oldest_due": backlog[1].isoformat()},
            )
        )
    return findings


def _codes(db: Session, condition: Any) -> tuple[int, list[str]]:
    count = int(db.scalar(select(func.count()).select_from(SellerOrder).where(condition)) or 0)
    codes = list(
        db.scalars(
            select(Order.code)
            .join(SellerOrder, SellerOrder.order_id == Order.id)
            .where(condition)
            .order_by(SellerOrder.id)
            .limit(SAMPLE)
        )
    )
    return count, codes


def stuck_orders(db: Session, now: datetime) -> list[Finding]:
    """Orders a job should already have moved on: the job is failing for
    them (D-060), or not running at all (F.12, "stuck orders")."""
    findings = []
    rules: Sequence[tuple[str, str, Any, str]] = (
        (
            "orders.stuck_delivered",
            "critical",
            and_(
                SellerOrder.status == SellerOrderStatus.DELIVERED,
                SellerOrder.problem_window_ends_at < now - STUCK_DELIVERED,
            ),
            "delivered part(s) are still not completed 30 minutes after their problem window",
        ),
        (
            "orders.stuck_placed",
            "critical",
            and_(
                SellerOrder.status == SellerOrderStatus.PLACED,
                SellerOrder.response_deadline < now - STUCK_PLACED,
            ),
            "unanswered part(s) have not expired 15 minutes after their deadline",
        ),
    )
    for key, severity, condition, words in rules:
        count, codes = _codes(db, condition)
        if count:
            findings.append(
                Finding(
                    key=key,
                    severity=severity,
                    summary=f"{count} {words} ({', '.join(codes)}).",
                    details={"count": count, "order_codes": codes},
                )
            )
    held = db.scalar(
        select(func.count(func.distinct(OrderItem.seller_order_id)))
        .join(InventoryReservation, InventoryReservation.order_item_id == OrderItem.id)
        .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        .where(
            InventoryReservation.status == ReservationStatus.HELD,
            InventoryReservation.expires_at < now - STUCK_HOLD,
            SellerOrder.status.in_((SellerOrderStatus.CONFIRMED, SellerOrderStatus.READY)),
        )
    )
    if held:
        findings.append(
            Finding(
                key="orders.stuck_hold",
                severity="warning",
                summary=f"{held} part(s) kept stock past their fulfilment hold without being "
                "cancelled.",
                details={"count": held},
            )
        )
    return findings


def overdue_problems(db: Session, now: datetime) -> list[Finding]:
    """Reported problems past the time staff promised a decision (D.17, AD-09)."""
    count, codes = (
        int(
            db.scalar(
                select(func.count())
                .select_from(DisputeCase)
                .where(DisputeCase.status != CaseStatus.RESOLVED, DisputeCase.decision_due_at < now)
            )
            or 0
        ),
        list(
            db.scalars(
                select(Order.code)
                .join(SellerOrder, SellerOrder.order_id == Order.id)
                .join(DisputeCase, DisputeCase.seller_order_id == SellerOrder.id)
                .where(DisputeCase.status != CaseStatus.RESOLVED, DisputeCase.decision_due_at < now)
                .order_by(DisputeCase.decision_due_at)
                .limit(SAMPLE)
            )
        ),
    )
    if not count:
        return []
    return [
        Finding(
            key="problems.overdue",
            severity="warning",
            summary=f"{count} reported problem(s) are past their decision time "
            f"({', '.join(codes)}).",
            details={"count": count, "order_codes": codes},
        )
    ]


def sms_budget(db: Session, now: datetime) -> list[Finding]:
    """Unusual SMS spending (F.12): most of today's budget is gone."""
    budget = settings_store.get_int(db, "auth.sms_daily_budget")
    if budget <= 0:
        return []
    sent = ratelimit.current("sms:daily", timedelta(days=1), now=now)
    if sent >= budget:
        severity, words = "critical", "spent: no more login codes go out today"
    elif sent >= budget * SMS_WARNING_SHARE:
        severity, words = "warning", "nearly spent"
    else:
        return []
    return [
        Finding(
            key="sms.budget",
            severity=severity,
            summary=f"The daily SMS budget is {words} ({sent} of {budget}).",
            details={"sent": sent, "budget": budget},
        )
    ]


def stuck_images(db: Session, now: datetime) -> list[Finding]:
    count = db.scalar(
        select(func.count())
        .select_from(ProductImage)
        .where(
            ProductImage.status == ImageStatus.PROCESSING,
            ProductImage.created_at < now - IMAGE_STUCK,
        )
    )
    if not count:
        return []
    return [
        Finding(
            key="images.stuck",
            severity="warning",
            summary=f"{count} picture(s) have been processing for more than 30 minutes.",
            details={"count": count},
        )
    ]


def held_reviews(db: Session, now: datetime) -> list[Finding]:
    """Reviews a pattern check held, waiting more than two days for staff
    (AD-12): a buyer is waiting to see their review appear (D-066)."""
    count = db.scalar(
        select(func.count())
        .select_from(Review)
        .where(
            Review.moderation_status == ReviewStatus.HELD,
            Review.created_at < now - timedelta(days=2),
        )
    )
    if not count:
        return []
    return [
        Finding(
            key="reviews.held",
            severity="warning",
            summary=f"{count} held review(s) have waited more than two days for staff.",
            details={"count": count},
        )
    ]


WATCH: tuple[Check, ...] = (
    failing_jobs,
    overdue_jobs,
    outbox_problems,
    stuck_orders,
    overdue_problems,
    sms_budget,
    stuck_images,
    held_reviews,
)


# -- reconcile (once a day) -------------------------------------------------------------


def order_totals(db: Session, now: datetime) -> list[Finding]:
    """Every order equals the sum of its parts, and every part the sum of its
    lines (F.12)."""
    parts = (
        select(
            SellerOrder.order_id,
            func.sum(SellerOrder.items_total_santim).label("items_sum"),
            func.sum(SellerOrder.delivery_fee_santim).label("delivery"),
        )
        .group_by(SellerOrder.order_id)
        .subquery()
    )
    orders_off = list(
        db.scalars(
            select(Order.code)
            .outerjoin(parts, parts.c.order_id == Order.id)
            .where(
                or_(
                    parts.c.items_sum.is_(None),
                    parts.c.items_sum != Order.items_total_santim,
                    parts.c.delivery != Order.delivery_total_santim,
                )
            )
            .order_by(Order.code)
        )
    )
    lines = (
        select(OrderItem.seller_order_id, func.sum(OrderItem.line_total_santim).label("line_sum"))
        .group_by(OrderItem.seller_order_id)
        .subquery()
    )
    parts_off = list(
        db.scalars(
            select(SellerOrder.id)
            .outerjoin(lines, lines.c.seller_order_id == SellerOrder.id)
            .where(
                or_(lines.c.line_sum.is_(None), lines.c.line_sum != SellerOrder.items_total_santim)
            )
            .order_by(SellerOrder.id)
        )
    )
    if not orders_off and not parts_off:
        return []
    return [
        Finding(
            key="reconcile.order_totals",
            severity="critical",
            summary=f"Order totals do not add up: {len(orders_off)} order(s) against their "
            f"parts, {len(parts_off)} part(s) against their lines.",
            details={
                "order_codes": orders_off[:SAMPLE],
                "seller_order_ids": [str(i) for i in parts_off[:SAMPLE]],
            },
        )
    ]


def fees_and_ledger(db: Session, now: datetime) -> list[Finding]:
    """Every completed part has one fee charge equal to its commission, and
    every charged fee is in the ledger for exactly that amount (G.10)."""
    problems: list[str] = []
    missing = db.scalar(
        select(func.count())
        .select_from(SellerOrder)
        .outerjoin(FeeCharge, FeeCharge.seller_order_id == SellerOrder.id)
        .where(SellerOrder.status == SellerOrderStatus.COMPLETED, FeeCharge.id.is_(None))
    )
    if missing:
        problems.append(f"{missing} completed part(s) have no fee charge")
    unequal = db.scalar(
        select(func.count())
        .select_from(FeeCharge)
        .join(SellerOrder, SellerOrder.id == FeeCharge.seller_order_id)
        .where(FeeCharge.amount_santim != SellerOrder.commission_santim)
    )
    if unequal:
        problems.append(f"{unequal} fee charge(s) differ from their part's commission")
    debits = (
        select(LedgerEntry.transaction_id, func.sum(LedgerEntry.amount_santim).label("debit"))
        .where(LedgerEntry.direction == "debit")
        .group_by(LedgerEntry.transaction_id)
        .subquery()
    )
    unposted = db.scalar(
        select(func.count())
        .select_from(FeeCharge)
        .outerjoin(debits, debits.c.transaction_id == FeeCharge.ledger_transaction_id)
        .where(
            FeeCharge.amount_santim > 0,
            or_(debits.c.debit.is_(None), debits.c.debit != FeeCharge.amount_santim),
        )
    )
    if unposted:
        problems.append(
            f"{unposted} fee(s) are missing from the ledger or posted for another amount"
        )
    totals = db.execute(
        select(
            LedgerEntry.direction, func.coalesce(func.sum(LedgerEntry.amount_santim), 0)
        ).group_by(LedgerEntry.direction)
    ).all()
    balance = dict(totals)
    if balance.get("debit", 0) != balance.get("credit", 0):
        problems.append("the ledger's debits and credits differ")
    if not problems:
        return []
    return [
        Finding(
            key="reconcile.fees",
            severity="critical",
            summary="Fees and the ledger disagree: " + "; ".join(problems) + ".",
            details={"problems": problems},
        )
    ]


def stock_counts(db: Session, now: datetime) -> list[Finding]:
    """The stock reserved on every offer equals the units its held
    reservations account for (G.9)."""
    held = (
        select(
            InventoryReservation.offer_id,
            func.sum(InventoryReservation.quantity).label("held"),
        )
        .where(InventoryReservation.status == ReservationStatus.HELD)
        .group_by(InventoryReservation.offer_id)
        .subquery()
    )
    off = db.scalar(
        select(func.count())
        .select_from(Inventory)
        .outerjoin(held, held.c.offer_id == Inventory.offer_id)
        .where(Inventory.reserved != func.coalesce(held.c.held, 0))
    )
    if not off:
        return []
    return [
        Finding(
            key="reconcile.stock",
            severity="critical",
            summary=f"{off} offer(s) show reserved stock that their held reservations do not "
            "account for.",
            details={"count": off},
        )
    ]


RECONCILE: tuple[Check, ...] = (order_totals, fees_and_ledger, stock_counts)


def run(db: Session, now: datetime, checks: Sequence[Check]) -> list[Finding]:
    """Every check, each in its own savepoint. A check that breaks becomes a
    critical finding of its own instead of stopping the others: the watch
    is what reports a failing job, so it must not fail with one bad check."""
    findings: list[Finding] = []
    for check in checks:
        try:
            with db.begin_nested():
                findings += check(db, now)
        except Exception as exc:
            logger.exception("an operations check failed", extra={"check": check.__name__})
            findings.append(
                Finding(
                    key=f"ops.check_failed:{check.__name__}",
                    severity="critical",
                    summary=f"The operations check {check.__name__} could not run: "
                    f"{type(exc).__name__}.",
                    details={"check": check.__name__, "error": str(exc)[:300]},
                )
            )
    return findings
