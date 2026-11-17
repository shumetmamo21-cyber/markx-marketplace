from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check


class ReportTarget(StrEnum):
    PRODUCT = "product"
    OFFER = "offer"
    STORE = "store"
    REVIEW = "review"


class ProblemType(StrEnum):
    NOT_RECEIVED = "not_received"
    WRONG_ITEM = "wrong_item"
    NOT_AS_DESCRIBED = "not_as_described"
    DAMAGED = "damaged"
    SUSPECTED_FAKE = "suspected_fake"
    OTHER = "other"


class CaseStatus(StrEnum):
    OPEN = "open"
    SELLER_RESPONDED = "seller_responded"
    RESOLVED = "resolved"


class CaseDecision(StrEnum):
    NO_ACTION = "no_action"
    SELLER_REFUNDED = "seller_refunded"


class ReviewStatus(StrEnum):
    """Only `published` reviews are shown and counted (D-066)."""

    PUBLISHED = "published"
    # Waiting for staff: a pattern check flagged it (contact details in the
    # text, many reviews of one seller by one buyer).
    HELD = "held"
    HIDDEN = "hidden"


class Review(UUIDPrimaryKey, Timestamps, Base):
    """A rating that only a real completed order can create (blueprint D.15,
    C-18; D-066). The buyer rates the product and the seller; the seller may
    reply once (S-16); staff moderate (AD-12). A seller cannot remove one."""

    __tablename__ = "reviews"
    __table_args__ = (
        in_check("moderation_status", ReviewStatus),
        CheckConstraint("product_rating between 1 and 5", name="product_rating_range"),
        CheckConstraint("seller_rating between 1 and 5", name="seller_rating_range"),
        CheckConstraint(
            "(seller_reply is null) = (seller_replied_at is null)", name="reply_fields_together"
        ),
        CheckConstraint("length(body) <= 2000", name="body_length"),
        CheckConstraint(
            "seller_reply is null or length(btrim(seller_reply)) between 1 and 1000",
            name="reply_length",
        ),
        CheckConstraint(
            "moderation_status <> 'held' or held_reason is not null", name="held_has_reason"
        ),
        CheckConstraint(
            "moderation_status <> 'hidden' or moderation_reason is not null",
            name="hidden_has_reason",
        ),
        Index("ix_reviews_product_id", "product_id"),
        Index("ix_reviews_seller_id", "seller_id"),
        Index("ix_reviews_status_created", "moderation_status", "created_at"),
        Index("ix_reviews_buyer_created", "buyer_user_id", "created_at"),
    )

    # One review per order item (G.8 rule 2).
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    product_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seller_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    moderation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="published")
    held_reason: Mapped[str | None] = mapped_column(Text)
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    moderated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seller_reply: Mapped[str | None] = mapped_column(Text)
    seller_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RatingSummary(Base):
    """Rating totals for one product or one seller, from its published reviews
    (D.15: "rating totals are updated in the background"; D-066). Derived:
    the worker rebuilds a row from the reviews whenever one changes, and a
    daily job rebuilds them all."""

    __tablename__ = "rating_summaries"
    __table_args__ = (
        in_check("subject_type", ("product", "seller")),
        CheckConstraint("review_count >= 0", name="review_count_non_negative"),
        CheckConstraint(
            "rating_sum between review_count and 5 * review_count", name="rating_sum_range"
        ),
        CheckConstraint(
            "count_1 >= 0 and count_2 >= 0 and count_3 >= 0 and count_4 >= 0 and count_5 >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "count_1 + count_2 + count_3 + count_4 + count_5 = review_count",
            name="counts_add_up",
        ),
    )

    subject_type: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    count_1: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    count_2: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    count_3: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    count_4: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    count_5: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Report(UUIDPrimaryKey, CreatedAt, Base):
    """A flag on a listing, store or review, feeding the staff queue (C-30, AD-16)."""

    __tablename__ = "reports"
    __table_args__ = (
        in_check("target_type", ReportTarget),
        in_check("status", ("open", "actioned", "dismissed")),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_present"),
        Index("ix_reports_status_created", "status", "created_at"),
    )

    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisputeCase(UUIDPrimaryKey, Timestamps, Base):
    """A problem a buyer raised on a delivered order (blueprint D.17).

    In Release 1 MarkX records the outcome and moves no money.
    """

    __tablename__ = "dispute_cases"
    __table_args__ = (
        in_check("problem_type", ProblemType),
        in_check("status", CaseStatus),
        in_check("decision", CaseDecision),
        CheckConstraint(
            "(status = 'resolved') = (decision is not null)", name="resolved_has_decision"
        ),
        # A written reason on every decision (blueprint I.5).
        CheckConstraint(
            "decision is null or length(btrim(decision_reason)) > 0", name="decision_has_reason"
        ),
        Index("ix_dispute_cases_status_due", "status", "decision_due_at"),
    )

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_orders.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    problem_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    decision: Mapped[str | None] = mapped_column(Text)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decision_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisputeMessage(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "dispute_messages"
    __table_args__ = (
        in_check("author_type", ("buyer", "seller", "staff")),
        CheckConstraint("length(btrim(body)) > 0", name="body_present"),
        Index("ix_dispute_messages_case_created", "case_id", "created_at"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dispute_cases.id", ondelete="RESTRICT"), nullable=False
    )
    author_type: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ProblemPhoto(UUIDPrimaryKey, CreatedAt, Base):
    """A photo added to a reported problem as evidence (blueprint C-16, D.17,
    I.5; D-062). Private: re-encoded to WebP without metadata, kept in
    private storage and opened only through a short-lived link issued to the
    buyer, a member of the seller who handles orders, or staff."""

    __tablename__ = "problem_photos"
    __table_args__ = (
        in_check("author_type", ("buyer", "seller")),
        CheckConstraint("width > 0 and height > 0", name="dimensions_positive"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_problem_photos_case_created", "case_id", "created_at"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dispute_cases.id", ondelete="RESTRICT"), nullable=False
    )
    author_type: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    file_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
