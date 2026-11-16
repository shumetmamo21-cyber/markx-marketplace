from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check


class Condition(StrEnum):
    NEW = "new"
    OPEN_BOX = "open_box"
    REFURBISHED = "refurbished"
    USED = "used"


class OfferStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    STALE = "stale"
    REMOVED = "removed"


class ReservationStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"


class MovementReason(StrEnum):
    INITIAL = "initial"
    SELLER_ADJUST = "seller_adjust"
    STAFF_ADJUST = "staff_adjust"
    RESERVE = "reserve"
    RELEASE = "release"
    COMMIT = "commit"


class Offer(UUIDPrimaryKey, Timestamps, Base):
    """One seller's terms for one variant: where sellers meet a product (G.4)."""

    __tablename__ = "offers"
    __table_args__ = (
        in_check("condition", Condition),
        in_check("status", OfferStatus),
        in_check("currency", ("ETB",)),
        CheckConstraint("price_santim > 0", name="price_positive"),
        CheckConstraint("warranty_months between 0 and 120", name="warranty_months_range"),
        CheckConstraint(
            "delivers_by_seller_rider or delivers_by_partner_courier or offers_shop_collection",
            name="at_least_one_delivery_option",
        ),
        # One offer per seller, variant and condition (blueprint D.7, G.8 rule 2).
        UniqueConstraint("seller_id", "variant_id", "condition"),
        Index("ix_offers_variant_live", "variant_id", postgresql_where=text("status = 'active'")),
        Index("ix_offers_seller_status", "seller_id", "status"),
        Index(
            "ix_offers_price_confirmed_live",
            "price_confirmed_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    price_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="ETB")
    warranty_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    warranty_note: Mapped[str | None] = mapped_column(Text)
    delivers_by_seller_rider: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    delivers_by_partner_courier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    offers_shop_collection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    price_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stock_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Earned from proven stock accuracy; skips seller confirmation. Later stage.
    instant_buy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class OfferPriceHistory(UUIDPrimaryKey, Base):
    """Every price change. Append-only; feeds the price chart (C-21)."""

    __tablename__ = "offer_price_history"
    __table_args__ = (
        CheckConstraint("new_price_santim > 0", name="new_price_positive"),
        CheckConstraint(
            "old_price_santim is null or old_price_santim > 0", name="old_price_positive"
        ),
        Index("ix_offer_price_history_offer_changed", "offer_id", "changed_at"),
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    old_price_santim: Mapped[int | None] = mapped_column(BigInteger)
    new_price_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Inventory(Base):
    """Stock per offer. The database guarantees it never oversells (G.8, G.9)."""

    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved <= on_hand", name="reserved_within_on_hand"),
        CheckConstraint("low_stock_threshold >= 0", name="low_stock_threshold_non_negative"),
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), primary_key=True
    )
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InventoryReservation(UUIDPrimaryKey, CreatedAt, Base):
    """Stock held for one order line. Always carries an expiry (G.8 rule 8)."""

    __tablename__ = "inventory_reservations"
    __table_args__ = (
        in_check("status", ReservationStatus),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index(
            "ix_inventory_reservations_held_expiry",
            "expires_at",
            postgresql_where=text("status = 'held'"),
        ),
        Index("ix_inventory_reservations_offer_id", "offer_id"),
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="held")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryMovement(UUIDPrimaryKey, CreatedAt, Base):
    """Stock history. Append-only, and the only way stock changes (G.2)."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        in_check("reason", MovementReason),
        CheckConstraint("delta_on_hand <> 0 or delta_reserved <> 0", name="changes_something"),
        CheckConstraint("on_hand_after >= 0 and reserved_after >= 0", name="after_non_negative"),
        Index("ix_inventory_movements_offer_created", "offer_id", "created_at"),
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    delta_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delta_reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    on_hand_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
