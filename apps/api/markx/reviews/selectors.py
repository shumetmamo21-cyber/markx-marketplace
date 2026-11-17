"""Reading reviews and rating totals (blueprint D.15, D.1, AD-12; D-066).

The public sees published reviews only, without the buyer's name or phone:
"a verified buyer", the product's variant, the store and the month. Totals
come from `rating_summaries`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.catalog.models import Product, ProductStatus
from markx.catalog.selectors import resolve_merged
from markx.core import settings_store
from markx.core.errors import NotFound
from markx.orders.models import Order, OrderItem, SellerOrder, SellerOrderStatus
from markx.sellers.models import Store
from markx.sellers.selectors import public_store
from markx.trust.models import RatingSummary, Review, ReviewStatus


def summary(db: Session, subject_type: str, subject_ids: Sequence[uuid.UUID]) -> dict[str, Any]:
    """Count, average to two places, and how many gave each star."""
    rows = list(
        db.scalars(
            select(RatingSummary).where(
                RatingSummary.subject_type == subject_type,
                RatingSummary.subject_id.in_(list(subject_ids)),
            )
        )
    )
    count = sum(r.review_count for r in rows)
    total = sum(r.rating_sum for r in rows)
    stars = {str(star): sum(getattr(r, f"count_{star}") for r in rows) for star in range(1, 6)}
    return {
        "count": count,
        "average": round(total / count, 2) if count else None,
        "stars": stars,
    }


def _rows(db: Session, query: Any, language: str) -> list[dict[str, Any]]:
    out = []
    for review, item, store_slug in db.execute(query).all():
        out.append(
            {
                "id": review.id,
                "product_rating": review.product_rating,
                "seller_rating": review.seller_rating,
                "body": review.body,
                "variant_label": item.variant_label_am
                if language == "am"
                else item.variant_label_en,
                "store_slug": store_slug,
                "created_at": review.created_at,
                "seller_reply": review.seller_reply,
                "seller_replied_at": review.seller_replied_at,
            }
        )
    return out


def _published(subject_condition: Any, before: uuid.UUID | None, limit: int) -> Any:
    query = (
        select(Review, OrderItem, Store.slug)
        .join(OrderItem, OrderItem.id == Review.order_item_id)
        .join(Store, Store.seller_id == Review.seller_id)
        .where(subject_condition, Review.moderation_status == ReviewStatus.PUBLISHED)
        .order_by(Review.id.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(Review.id < before)
    return query


def product_reviews(
    db: Session, slug: str, *, language: str, before: uuid.UUID | None, limit: int
) -> dict[str, Any]:
    """A product page's reviews, newest first. A product merged into another
    shows on the survivor's page, with its reviews and totals."""
    not_found = NotFound("product_not_found", "That product was not found.")
    product = db.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise not_found
    survivor = resolve_merged(db, product)
    if survivor.status != ProductStatus.APPROVED:
        raise not_found
    family = select(Product.id).where(Product.id == survivor.id).cte("family", recursive=True)
    family = family.union_all(select(Product.id).where(Product.merged_into_id == family.c.id))
    ids = list(db.scalars(select(family.c.id)))
    return {
        "product_slug": survivor.slug,
        "summary": summary(db, "product", ids),
        "reviews": _rows(db, _published(Review.product_id.in_(ids), before, limit), language),
    }


def store_reviews(
    db: Session, slug: str, *, language: str, before: uuid.UUID | None, limit: int
) -> dict[str, Any]:
    """A store's reviews (the seller rating), only for a store that trades."""
    found = public_store(db, slug)
    if found is None:
        raise NotFound("store_not_found", "That store was not found.")
    seller, store = found
    return {
        "store_slug": store.slug,
        "summary": summary(db, "seller", [seller.id]),
        "reviews": _rows(db, _published(Review.seller_id == seller.id, before, limit), language),
    }


def _private_row(
    review: Review, item: OrderItem, order: Order, store: str, language: str
) -> dict[str, Any]:
    return {
        "id": review.id,
        "order_id": order.id,
        "order_code": order.code,
        "order_item_id": item.id,
        "product_id": review.product_id,
        "title": item.title_am if language == "am" else item.title_en,
        "variant_label": item.variant_label_am if language == "am" else item.variant_label_en,
        "store_slug": store,
        "product_rating": review.product_rating,
        "seller_rating": review.seller_rating,
        "body": review.body,
        "status": review.moderation_status,
        "held_reason": review.held_reason,
        "moderation_reason": review.moderation_reason,
        "seller_reply": review.seller_reply,
        "seller_replied_at": review.seller_replied_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def _private_query(condition: Any, before: uuid.UUID | None, limit: int) -> Any:
    query = (
        select(Review, OrderItem, Order, Store.slug)
        .join(OrderItem, OrderItem.id == Review.order_item_id)
        .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Store, Store.seller_id == Review.seller_id)
        .where(condition)
        .order_by(Review.id.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(Review.id < before)
    return query


def one_review(
    db: Session, review_id: uuid.UUID, *, language: str, for_seller: bool
) -> dict[str, Any]:
    """One review as its buyer or staff see it; with `for_seller`, as its
    store sees it, without the order code."""
    found = db.execute(_private_query(Review.id == review_id, None, 1)).first()
    if found is None:
        raise NotFound("review_not_found", "That review was not found.")
    review, item, order, store = found
    row = _private_row(review, item, order, store, language)
    if for_seller:
        row.update(order_code=None, order_id=None, held_reason=None)
    return row


def buyer_reviews(
    db: Session, user: User, *, language: str, limit: int = 100
) -> list[dict[str, Any]]:
    """The buyer's own reviews in every state, with what staff decided."""
    return [
        _private_row(r, i, o, s, language)
        for r, i, o, s in db.execute(
            _private_query(Review.buyer_user_id == user.id, None, limit)
        ).all()
    ]


def seller_reviews(
    db: Session, seller_id: uuid.UUID, *, language: str, before: uuid.UUID | None, limit: int
) -> list[dict[str, Any]]:
    """Reviews of this store that buyers can see or that staff hid. A held
    review is the staff's to decide first, so the seller does not see it
    yet. The buyer's name and order code are not shown to the seller."""
    rows = []
    for r, i, o, s in db.execute(
        _private_query(
            (Review.seller_id == seller_id) & (Review.moderation_status != ReviewStatus.HELD),
            before,
            limit,
        )
    ).all():
        row = _private_row(r, i, o, s, language)
        row.update(order_code=None, order_id=None, held_reason=None)
        rows.append(row)
    return rows


def staff_reviews(
    db: Session, *, status: str | None, language: str, before: uuid.UUID | None, limit: int
) -> list[dict[str, Any]]:
    """The moderation queue (AD-12): held reviews first by default."""
    condition = Review.moderation_status == (status or ReviewStatus.HELD)
    return [
        _private_row(r, i, o, s, language)
        for r, i, o, s in db.execute(_private_query(condition, before, limit)).all()
    ]


def reviewable_items(db: Session, user: User, *, language: str) -> list[dict[str, Any]]:
    """Items of the buyer's completed orders not reviewed yet, while the
    window is open: what "rate this purchase" offers."""
    window = timedelta(days=settings_store.get_int(db, "reviews.window_days"))
    rows = db.execute(
        select(OrderItem, Order, SellerOrder, Store.slug)
        .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Store, Store.seller_id == SellerOrder.seller_id)
        .outerjoin(Review, Review.order_item_id == OrderItem.id)
        .where(
            Order.buyer_user_id == user.id,
            SellerOrder.status == SellerOrderStatus.COMPLETED,
            SellerOrder.completed_at > func.now() - window,
            Review.id.is_(None),
        )
        .order_by(SellerOrder.completed_at.desc(), OrderItem.id)
    ).all()
    return [
        {
            "order_id": order.id,
            "order_code": order.code,
            "order_item_id": item.id,
            "product_id": item.product_id,
            "title": item.title_am if language == "am" else item.title_en,
            "variant_label": item.variant_label_am if language == "am" else item.variant_label_en,
            "store_slug": store,
            "review_until": seller_order.completed_at + window,
        }
        for item, order, seller_order, store in rows
        if seller_order.completed_at is not None
    ]
