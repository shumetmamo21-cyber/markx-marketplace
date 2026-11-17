"""Reports on listings, stores and reviews (blueprint C-30, AD-16, H.4; D-067).

Anyone may flag a product, an offer, a store or a review they can see,
with a reason from a fixed list and an optional note. A signed-in person
has one open report per target; a visitor is limited by network address.
Staff who handle reports (C.4: "moderate reviews and handle reports") work
the queue, act with the tools they already have (take an offer down, hide
a review, archive a product, suspend a store), and resolve the report as
`actioned` or `dismissed` with a written note, usually for every open
report on the same target at once. Nothing is deleted; every resolution
is audit-logged and the signed-in reporters are told the outcome.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.catalog.models import Product, ProductStatus, ProductVariant
from markx.core.errors import Conflict, NotFound
from markx.notifications import service as notifications
from markx.offers.models import Offer, OfferStatus
from markx.sellers.models import Seller, SellerStatus, Store
from markx.trust.models import Report, ReportStatus, ReportTarget, Review, ReviewStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _visible(db: Session, target_type: ReportTarget, target_id: uuid.UUID) -> bool:
    """Only what a buyer can see can be reported (and nothing else can be
    probed for existence through this form)."""
    if target_type == ReportTarget.PRODUCT:
        status = db.scalar(select(Product.status).where(Product.id == target_id))
        return status == ProductStatus.APPROVED
    if target_type == ReportTarget.OFFER:
        return bool(
            db.scalar(
                select(func.count())
                .select_from(Offer)
                .join(Seller, Seller.id == Offer.seller_id)
                .where(
                    Offer.id == target_id,
                    Offer.status != OfferStatus.REMOVED,
                    Seller.status == SellerStatus.ACTIVE,
                )
            )
        )
    if target_type == ReportTarget.STORE:
        return bool(
            db.scalar(
                select(func.count())
                .select_from(Store)
                .join(Seller, Seller.id == Store.seller_id)
                .where(Store.id == target_id, Seller.status == SellerStatus.ACTIVE)
            )
        )
    status = db.scalar(select(Review.moderation_status).where(Review.id == target_id))
    return status == ReviewStatus.PUBLISHED


def file_report(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    target_type: ReportTarget,
    target_id: uuid.UUID | None,
    store_slug: str | None,
    reason: str,
    note: str | None,
) -> Report:
    if target_type == ReportTarget.STORE and target_id is None and store_slug:
        target_id = db.scalar(select(Store.id).where(Store.slug == store_slug))
    if target_id is None or not _visible(db, target_type, target_id):
        raise NotFound("report_target_not_found", "That item was not found.")
    if user_id is not None and db.scalar(
        select(Report.id).where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.reporter_user_id == user_id,
            Report.status == ReportStatus.OPEN,
        )
    ):
        raise Conflict(
            "already_reported", "You have already reported this. MarkX is looking at it."
        )
    report = Report(
        target_type=target_type.value,
        target_id=target_id,
        reporter_user_id=user_id,
        reason=reason,
        note=(note or "").strip() or None,
    )
    try:
        with db.begin_nested():
            db.add(report)
            db.flush()
    except IntegrityError as exc:  # the same person, twice at once
        raise Conflict(
            "already_reported", "You have already reported this. MarkX is looking at it."
        ) from exc
    return report


def resolve(
    db: Session,
    actor: Actor,
    report_id: uuid.UUID,
    *,
    outcome: ReportStatus,
    note: str,
    all_on_target: bool,
) -> list[Report]:
    """Close one report, or every open report on its target, as `actioned`
    (something was done about it) or `dismissed`. Locked in id order."""
    first = db.scalar(select(Report).where(Report.id == report_id).with_for_update())
    if first is None:
        raise NotFound("report_not_found", "That report was not found.")
    if first.status != ReportStatus.OPEN:
        raise Conflict("report_closed", "This report has already been resolved.")
    if all_on_target:
        closing = list(
            db.scalars(
                select(Report)
                .where(
                    Report.target_type == first.target_type,
                    Report.target_id == first.target_id,
                    Report.status == ReportStatus.OPEN,
                )
                .order_by(Report.id)
                .with_for_update()
            )
        )
    else:
        closing = [first]
    now = _now()
    for report in closing:
        report.status = outcome.value
        report.resolution_note = note
        report.resolved_by_user_id = actor.user_id
        report.resolved_at = now
    db.flush()
    record_by(
        db, actor, f"report.{outcome.value}", "report", first.id,
        before={"status": ReportStatus.OPEN.value},
        after={"status": outcome.value, "note": note, "target_type": first.target_type,
               "target_id": str(first.target_id),
               "reports": [str(r.id) for r in closing]},
    )  # fmt: skip
    for user_id in sorted({r.reporter_user_id for r in closing if r.reporter_user_id}):
        notifications.notify(
            db, user_id, "report.resolved",
            {"target_type": first.target_type, "target_id": str(first.target_id),
             "outcome": outcome.value},
        )  # fmt: skip
    return closing


def _labels(db: Session, reports: list[Report]) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    """What each target is, for the person reading the queue."""
    labels: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}
    for report in reports:
        key = (report.target_type, report.target_id)
        if key in labels:
            continue
        label: dict[str, Any] = {"product_slug": None, "store_slug": None, "excerpt": None}
        if report.target_type == ReportTarget.PRODUCT:
            label["product_slug"] = db.scalar(
                select(Product.slug).where(Product.id == report.target_id)
            )
        elif report.target_type == ReportTarget.OFFER:
            offer_row = db.execute(
                select(Product.slug, Store.slug)
                .select_from(Offer)
                .join(ProductVariant, ProductVariant.id == Offer.variant_id)
                .join(Product, Product.id == ProductVariant.product_id)
                .join(Store, Store.seller_id == Offer.seller_id)
                .where(Offer.id == report.target_id)
            ).first()
            if offer_row is not None:
                label["product_slug"], label["store_slug"] = offer_row
        elif report.target_type == ReportTarget.STORE:
            label["store_slug"] = db.scalar(select(Store.slug).where(Store.id == report.target_id))
        else:
            review_row = db.execute(
                select(Product.slug, Store.slug, Review.body)
                .select_from(Review)
                .join(Product, Product.id == Review.product_id)
                .join(Store, Store.seller_id == Review.seller_id)
                .where(Review.id == report.target_id)
            ).first()
            if review_row is not None:
                label["product_slug"], label["store_slug"] = review_row[0], review_row[1]
                label["excerpt"] = review_row[2][:120]
        labels[key] = label
    return labels


def queue(
    db: Session,
    *,
    status: str,
    target_type: str | None,
    before: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    """The staff queue (AD-16): oldest open reports first, so nothing waits
    for ever; closed ones newest first. Each row says how many open reports
    its target has, so a target many people flag stands out."""
    query = select(Report).where(Report.status == status).limit(limit)
    if target_type:
        query = query.where(Report.target_type == target_type)
    if status == ReportStatus.OPEN:
        query = query.order_by(Report.id)
        if before is not None:
            query = query.where(Report.id > before)
    else:
        query = query.order_by(Report.id.desc())
        if before is not None:
            query = query.where(Report.id < before)
    return _rows(db, list(db.scalars(query)))


def _rows(db: Session, reports: list[Report]) -> list[dict[str, Any]]:
    if not reports:
        return []
    open_counts = {
        (t, i): n
        for t, i, n in db.execute(
            select(Report.target_type, Report.target_id, func.count())
            .where(
                Report.status == ReportStatus.OPEN,
                Report.target_id.in_([r.target_id for r in reports]),
            )
            .group_by(Report.target_type, Report.target_id)
        ).all()
    }
    labels = _labels(db, reports)
    return [
        {
            "id": r.id,
            "target_type": r.target_type,
            "target_id": r.target_id,
            **labels[(r.target_type, r.target_id)],
            "reason": r.reason,
            "note": r.note,
            "from_signed_in_person": r.reporter_user_id is not None,
            "status": r.status,
            "open_reports_on_target": open_counts.get((r.target_type, r.target_id), 0),
            "created_at": r.created_at,
            "resolution_note": r.resolution_note,
            "resolved_at": r.resolved_at,
        }
        for r in reports
    ]


def one(db: Session, report_id: uuid.UUID) -> dict[str, Any]:
    report = db.get(Report, report_id, populate_existing=True)
    if report is None:
        raise NotFound("report_not_found", "That report was not found.")
    return _rows(db, [report])[0]
