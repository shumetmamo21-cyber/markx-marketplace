"""Reviews and ratings (blueprint D.15, C-18, S-16, AD-12, H.4; D-066).

* **Only real orders.** A buyer reviews an order item of their own once its
  seller order is `completed`, within `reviews.window_days`, once per item
  (a unique constraint). Nobody reviews a store they belong to.
* **Fake-review guards** (D.15, H.4): a daily limit per buyer; a review
  whose text carries a phone number or a link, or a buyer's fourth review
  of one seller in 30 days, is `held` until staff look at it. Held and
  hidden reviews are never shown or counted.
* **The seller replies** (S-16) and cannot remove a review. The buyer may
  edit theirs until the seller replies or the window closes.
* **Staff moderate** (AD-12): publish a held review, hide any, show a hidden
  one again, each with a written reason, audit-logged.
* **Rating totals** are derived (`rating_summaries`): every change queues
  `reviews.recount` through the outbox, and a daily job recounts all.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.accounts.permissions import SELLER_PERMISSIONS, SellerCapability, seller_can
from markx.audit.service import Actor, record_by
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, PermissionDenied, RateLimited
from markx.notifications import service as notifications
from markx.notifications.models import Outbox
from markx.orders.models import Order, OrderItem, SellerOrder, SellerOrderStatus
from markx.sellers.models import Seller, SellerMember
from markx.trust import conflict
from markx.trust.models import RatingSummary, Review, ReviewStatus

TOPIC_RECOUNT = "reviews.recount"
SAME_SELLER_DAYS = 30
# A phone number (Ethiopian mobile, local or international form) or a link:
# contact details that move a buyer off MarkX, or spam (H.4).
_CONTACT = re.compile(
    r"(?:\+?251|\b0)[\s.-]?[79](?:[\s.-]?\d){8}"
    r"|https?://|\bwww\.|\bt\.me/|\btelegram\.me\b|(?<![\w.])@[A-Za-z][A-Za-z0-9_]{4,}",
    re.IGNORECASE,
)
_RECOUNT_LOCK_SPACE = 0x4D585256  # "MXRV"


def _now() -> datetime:
    return datetime.now(UTC)


# -- writing ---------------------------------------------------------------------------


def _own_item(
    db: Session, user: User, order_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[OrderItem, SellerOrder]:
    row = db.execute(
        select(OrderItem, SellerOrder)
        .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .where(OrderItem.id == item_id, Order.id == order_id, Order.buyer_user_id == user.id)
    ).first()
    if row is None:
        raise NotFound("order_not_found", "That order was not found.")
    return row[0], row[1]


def _window_end(db: Session, seller_order: SellerOrder) -> datetime | None:
    if seller_order.status != SellerOrderStatus.COMPLETED or seller_order.completed_at is None:
        return None
    return seller_order.completed_at + timedelta(
        days=settings_store.get_int(db, "reviews.window_days")
    )


def _pattern_hold(db: Session, user_id: uuid.UUID, seller_id: uuid.UUID, body: str,
                  *, now: datetime, excluding: uuid.UUID | None = None) -> str | None:  # fmt: skip
    """Why this review should wait for staff, or None (D.15 "pattern checks")."""
    if _CONTACT.search(body):
        return "contact_details"
    earlier = (
        select(func.count())
        .select_from(Review)
        .where(
            Review.buyer_user_id == user_id,
            Review.seller_id == seller_id,
            Review.created_at >= now - timedelta(days=SAME_SELLER_DAYS),
        )
    )
    if excluding is not None:
        earlier = earlier.where(Review.id != excluding)
    if int(db.scalar(earlier) or 0) >= settings_store.get_int(db, "reviews.hold_after_same_seller"):
        return "many_reviews_of_one_seller"
    return None


def write_review(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    product_rating: int,
    seller_rating: int,
    body: str,
    now: datetime | None = None,
) -> Review:
    now = now or _now()
    item, seller_order = _own_item(db, user, order_id, item_id)
    window_end = _window_end(db, seller_order)
    if window_end is None:
        raise Conflict("review_not_open", "A review can be written once the order is completed.")
    if now >= window_end:
        raise Conflict("review_window_closed", "The time to review this order has passed.")
    if db.scalar(
        select(SellerMember.id).where(
            SellerMember.seller_id == seller_order.seller_id, SellerMember.user_id == user.id
        )
    ):
        raise PermissionDenied("own_store_review", "You cannot review a store you belong to.")
    if db.scalar(select(Review.id).where(Review.order_item_id == item.id)):
        raise Conflict("review_exists", "You have already reviewed this item.")
    today = db.scalar(
        select(func.count())
        .select_from(Review)
        .where(Review.buyer_user_id == user.id, Review.created_at >= now - timedelta(days=1))
    )
    if int(today or 0) >= settings_store.get_int(db, "reviews.per_buyer_per_day"):
        raise RateLimited(
            "review_limit", "You have written many reviews today. Please try again tomorrow."
        )
    text = body.strip()
    held = _pattern_hold(db, user.id, seller_order.seller_id, text, now=now)
    review = Review(
        order_item_id=item.id,
        buyer_user_id=user.id,
        product_id=item.product_id,
        seller_id=seller_order.seller_id,
        product_rating=product_rating,
        seller_rating=seller_rating,
        body=text,
        moderation_status=(ReviewStatus.HELD if held else ReviewStatus.PUBLISHED).value,
        held_reason=held,
    )
    try:
        with db.begin_nested():
            db.add(review)
            db.flush()
    except IntegrityError as exc:  # the same item reviewed twice at once
        raise Conflict("review_exists", "You have already reviewed this item.") from exc
    _queue_recount(db, review)
    if review.moderation_status == ReviewStatus.PUBLISHED:
        _notify_seller(db, review)
    return review


def edit_review(
    db: Session,
    user: User,
    review_id: uuid.UUID,
    *,
    product_rating: int,
    seller_rating: int,
    body: str,
    now: datetime | None = None,
) -> Review:
    """The buyer corrects their review, until the seller has replied or the
    window has closed. A review staff hid stays as it is."""
    now = now or _now()
    review = db.scalar(
        select(Review)
        .where(Review.id == review_id, Review.buyer_user_id == user.id)
        .with_for_update()
    )
    if review is None:
        raise NotFound("review_not_found", "That review was not found.")
    if review.moderation_status == ReviewStatus.HIDDEN:
        raise Conflict("review_hidden", "This review was hidden by MarkX and cannot be changed.")
    if review.seller_reply is not None:
        raise Conflict(
            "review_answered", "The seller has replied; the review can no longer change."
        )
    seller_order = db.scalar(
        select(SellerOrder)
        .join(OrderItem, OrderItem.seller_order_id == SellerOrder.id)
        .where(OrderItem.id == review.order_item_id)
    )
    assert seller_order is not None
    window_end = _window_end(db, seller_order)
    if window_end is None or now >= window_end:
        raise Conflict("review_window_closed", "The time to change this review has passed.")
    text = body.strip()
    held = _pattern_hold(db, user.id, review.seller_id, text, now=now, excluding=review.id)
    was_published = review.moderation_status == ReviewStatus.PUBLISHED
    review.product_rating, review.seller_rating, review.body = product_rating, seller_rating, text
    if held:
        review.moderation_status, review.held_reason = ReviewStatus.HELD.value, held
    elif review.moderation_status == ReviewStatus.HELD and review.held_reason in (
        "contact_details", "many_reviews_of_one_seller",
    ):  # fmt: skip
        # The text no longer trips a check: shown again, as a new review would be.
        review.moderation_status = ReviewStatus.PUBLISHED.value
    db.flush()
    _queue_recount(db, review)
    if not was_published and review.moderation_status == ReviewStatus.PUBLISHED:
        _notify_seller(db, review)
    return review


# -- the seller's reply (S-16) -----------------------------------------------------------


def reply(
    db: Session, seller: Seller, member: SellerMember, review_id: uuid.UUID, *, body: str
) -> Review:
    """One reply per review, which the seller may reword. Only on a review
    buyers can see. Another seller's review looks like no review."""
    if not seller_can(member.role, SellerCapability.REPLY_TO_REVIEWS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    review = db.scalar(
        select(Review)
        .where(Review.id == review_id, Review.seller_id == seller.id)
        .with_for_update()
    )
    if review is None:
        raise NotFound("review_not_found", "That review was not found.")
    if review.moderation_status != ReviewStatus.PUBLISHED:
        raise Conflict("review_not_published", "Only a published review can be answered.")
    first = review.seller_reply is None
    review.seller_reply = body.strip()
    review.seller_replied_at = _now()
    db.flush()
    if first:
        notifications.notify(
            db, review.buyer_user_id, "review.seller_replied",
            {"review_id": str(review.id), "product_id": str(review.product_id)},
        )  # fmt: skip
    return review


# -- moderation (AD-12) --------------------------------------------------------------------


def moderate(
    db: Session, actor: Actor, review_id: uuid.UUID, *, action: str, reason: str
) -> Review:
    """`publish` (a held or hidden review is shown) or `hide`, with a reason."""
    review = db.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if review is None:
        raise NotFound("review_not_found", "That review was not found.")
    conflict.refuse_conflict(
        db, actor, action=f"review.{action}", target_type="review", target_id=review.id,
        seller_ids=[review.seller_id], author_user_ids=[review.buyer_user_id],
    )  # fmt: skip
    target = ReviewStatus.PUBLISHED if action == "publish" else ReviewStatus.HIDDEN
    if review.moderation_status == target:
        raise Conflict("review_unchanged", f"This review is already {target.value}.")
    before = review.moderation_status
    review.moderation_status = target.value
    review.moderation_reason = reason
    review.moderated_by_user_id = actor.user_id
    review.moderated_at = _now()
    db.flush()
    record_by(
        db, actor, f"review.{action}", "review", review.id,
        before={"status": before}, after={"status": target.value, "reason": reason},
    )  # fmt: skip
    _queue_recount(db, review)
    if target == ReviewStatus.PUBLISHED and before == ReviewStatus.HELD:
        _notify_seller(db, review)
    return review


# -- rating totals (D.15: "updated in the background") -----------------------------------


def _queue_recount(db: Session, review: Review) -> None:
    db.add(
        Outbox(
            topic=TOPIC_RECOUNT,
            payload={"product_id": str(review.product_id), "seller_id": str(review.seller_id)},
        )
    )


def recount(db: Session, subject_type: str, subject_id: uuid.UUID) -> RatingSummary | None:
    """Rebuild one subject's totals from its published reviews. One recount of
    a subject at a time (an advisory lock until commit), so an older count
    can never be written after a newer one, as for search (D-057)."""
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                _RECOUNT_LOCK_SPACE,
                func.hashtext(literal(f"{subject_type}:{subject_id}", type_=Text)),
            )
        )
    )
    column = Review.product_id if subject_type == "product" else Review.seller_id
    rating = Review.product_rating if subject_type == "product" else Review.seller_rating
    rows = dict(
        db.execute(
            select(rating, func.count())
            .where(column == subject_id, Review.moderation_status == ReviewStatus.PUBLISHED)
            .group_by(rating)
        ).all()
    )
    counts = {f"count_{star}": int(rows.get(star, 0)) for star in range(1, 6)}
    values: dict[str, Any] = {
        **counts,
        "review_count": sum(counts.values()),
        "rating_sum": sum(star * int(rows.get(star, 0)) for star in range(1, 6)),
        "updated_at": func.now(),
    }
    db.execute(
        insert(RatingSummary)
        .values(subject_type=subject_type, subject_id=subject_id, **values)
        .on_conflict_do_update(
            index_elements=[RatingSummary.subject_type, RatingSummary.subject_id], set_=values
        )
    )
    return db.get(RatingSummary, (subject_type, subject_id), populate_existing=True)


def handle_recount(db: Session, row: Outbox) -> None:
    """The outbox handler for `reviews.recount`."""
    recount(db, "product", uuid.UUID(str(row.payload["product_id"])))
    recount(db, "seller", uuid.UUID(str(row.payload["seller_id"])))


def recount_all(db: Session) -> int:
    """The daily safety net: every subject with a review or a summary."""
    subjects = set(db.execute(select(literal("product"), Review.product_id).distinct()).all())
    subjects |= set(db.execute(select(literal("seller"), Review.seller_id).distinct()).all())
    subjects |= set(db.execute(select(RatingSummary.subject_type, RatingSummary.subject_id)).all())
    for subject_type, subject_id in sorted(subjects, key=lambda s: (s[0], str(s[1]))):
        recount(db, subject_type, subject_id)
    return len(subjects)


def _notify_seller(db: Session, review: Review) -> None:
    """Told to the members whose role may answer it (C.3)."""
    roles = [role.value for role in SELLER_PERMISSIONS[SellerCapability.REPLY_TO_REVIEWS]]
    for user_id in db.scalars(
        select(SellerMember.user_id)
        .where(
            SellerMember.seller_id == review.seller_id,
            SellerMember.is_active,
            SellerMember.role.in_(roles),
        )
        .order_by(SellerMember.created_at)
    ):
        notifications.notify(
            db, user_id, "review.received_for_seller",
            {"seller_id": str(review.seller_id), "review_id": str(review.id)},
        )  # fmt: skip
