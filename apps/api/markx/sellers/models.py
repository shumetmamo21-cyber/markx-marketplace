from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.accounts.models import PHONE_PATTERN
from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check


class SellerKind(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class SellerStatus(StrEnum):
    APPLIED = "applied"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class ReviewState(StrEnum):
    PENDING = "pending"
    NEEDS_DOCUMENTS = "needs_documents"
    APPROVED = "approved"
    REJECTED = "rejected"


class SellerRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    CATALOGUE = "catalogue"
    ORDERS = "orders"
    FINANCE = "finance"


class SellerPlan(StrEnum):
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class DocumentType(StrEnum):
    OWNER_ID = "owner_id"
    BUSINESS_LICENCE = "business_licence"
    TIN_CERTIFICATE = "tin_certificate"
    SHOP_PHOTO = "shop_photo"
    OTHER = "other"


SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class Seller(UUIDPrimaryKey, Timestamps, Base):
    """A seller's legal identity (blueprint G.2). The public face is its store."""

    __tablename__ = "sellers"
    __table_args__ = (
        in_check("kind", SellerKind),
        in_check("status", SellerStatus),
        in_check("review_state", ReviewState),
        in_check("plan", SellerPlan),
        CheckConstraint("verification_level between 0 and 3", name="verification_level_range"),
        CheckConstraint(f"contact_phone ~ '{PHONE_PATTERN}'", name="contact_phone_format"),
        # A business has a TIN; that is what makes it a business seller.
        CheckConstraint("kind <> 'business' or tin is not null", name="business_has_tin"),
        CheckConstraint(
            "(shop_latitude is null) = (shop_longitude is null)", name="shop_pin_complete"
        ),
        # One live seller per TIN. A closed or rejected seller frees the number.
        Index(
            "uq_sellers_tin_live",
            "tin",
            unique=True,
            postgresql_where=text("tin is not null and status <> 'closed'"),
        ),
        Index("ix_sellers_status_review_state", "status", "review_state"),
    )

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    trade_name: Mapped[str] = mapped_column(Text, nullable=False)
    tin: Mapped[str | None] = mapped_column(Text)
    licence_number: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str] = mapped_column(Text, nullable=False)
    shop_address: Mapped[str] = mapped_column(Text, nullable=False)
    shop_latitude: Mapped[float | None] = mapped_column(Float)
    shop_longitude: Mapped[float | None] = mapped_column(Float)
    verification_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="applied")
    review_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Verification is re-checked every year (blueprint D.3).
    recheck_due_on: Mapped[date | None] = mapped_column(Date)
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="starter")
    is_founding: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class SellerMember(UUIDPrimaryKey, CreatedAt, Base):
    """Who may act for a seller. A person can belong to several sellers."""

    __tablename__ = "seller_members"
    __table_args__ = (
        in_check("role", SellerRole),
        Index("uq_seller_members_seller_user", "seller_id", "user_id", unique=True),
        # Exactly one owner per seller (blueprint C.5): at most one by this index,
        # at least one because the owner is created with the seller.
        Index(
            "uq_seller_members_one_owner",
            "seller_id",
            unique=True,
            postgresql_where=text("role = 'owner' and is_active"),
        ),
        Index("ix_seller_members_user_id", "user_id"),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class SellerDocument(UUIDPrimaryKey, CreatedAt, Base):
    """An identity or licence document, held in private storage. Every view is logged."""

    __tablename__ = "seller_documents"
    __table_args__ = (
        in_check("doc_type", DocumentType),
        in_check("review_status", ("pending", "accepted", "rejected")),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_seller_documents_seller_id", "seller_id"),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_on: Mapped[date | None] = mapped_column(Date)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class SellerPayoutAccount(UUIDPrimaryKey, CreatedAt, Base):
    """Where a seller is paid. Collected in Release 1, used from Release 2 (S-13).

    The number is encrypted; only its last four digits are readable. A new
    account becomes effective only after a cooling-off period.
    """

    __tablename__ = "seller_payout_accounts"
    __table_args__ = (
        in_check("kind", ("bank", "wallet")),
        in_check("status", ("pending", "active", "replaced")),
        Index(
            "uq_seller_payout_accounts_one_active",
            "seller_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_seller_payout_accounts_one_pending",
            "seller_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_number_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_last4: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class Store(UUIDPrimaryKey, Timestamps, Base):
    """The public shop front. One per seller at launch (blueprint D.4)."""

    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint("length(slug) between 3 and 60", name="slug_length"),
        CheckConstraint("length(btrim(name)) > 0", name="name_present"),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    return_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    working_hours: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    areas_served: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    telegram_channel: Mapped[str | None] = mapped_column(Text)
    logo_key: Mapped[str | None] = mapped_column(Text)
