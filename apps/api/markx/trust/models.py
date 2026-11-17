from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, Text
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


class Review(UUIDPrimaryKey, Timestamps, Base):
    """A rating that only a real delivered order can create (blueprint D.15)."""

    __tablename__ = "reviews"
    __table_args__ = (
        in_check("moderation_status", ("published", "hidden")),
        CheckConstraint("product_rating between 1 and 5", name="product_rating_range"),
        CheckConstraint("seller_rating between 1 and 5", name="seller_rating_range"),
        CheckConstraint(
            "(seller_reply is null) = (seller_replied_at is null)", name="reply_fields_together"
        ),
        Index("ix_reviews_product_id", "product_id"),
        Index("ix_reviews_seller_id", "seller_id"),
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
    seller_reply: Mapped[str | None] = mapped_column(Text)
    seller_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
