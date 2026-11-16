from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.accounts.models import LANGUAGES
from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check
from markx.offers.models import Condition

MAX_QUANTITY_PER_LINE = 20


class PaymentMode(StrEnum):
    DIRECT = "direct"
    PROTECTED_PREPAY = "protected_prepay"
    PROTECTED_AT_DOOR = "protected_at_door"


class SellerOrderStatus(StrEnum):
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PAID = "paid"
    READY = "ready"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DELIVERY_FAILED = "delivery_failed"
    RETURNED = "returned"
    DISPUTED = "disputed"
    REFUNDED = "refunded"


class DirectPaymentMethod(StrEnum):
    CASH = "cash"
    TELEBIRR = "telebirr"
    BANK_TRANSFER = "bank_transfer"
    ETHQR = "ethqr"


class ActorType(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"
    RIDER = "rider"
    STAFF = "staff"
    SYSTEM = "system"


class Cart(UUIDPrimaryKey, Timestamps, Base):
    """The server copy of a cart: a signed-in user's, or an anonymous visitor's."""

    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(
            "(user_id is not null) <> (anon_token_hash is not null)", name="exactly_one_owner"
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    anon_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)


class CartItem(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint(f"quantity between 1 and {MAX_QUANTITY_PER_LINE}", name="quantity_range"),
        CheckConstraint("price_seen_santim > 0", name="price_seen_positive"),
        UniqueConstraint("cart_id", "offer_id"),
    )

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the buyer last saw, so the cart can say when a price changed (C-06).
    price_seen_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Order(UUIDPrimaryKey, CreatedAt, Base):
    """The buyer's whole checkout: the parent order (blueprint D.11, G.5).

    It has no status column. Its status is always derived from its seller orders.
    """

    __tablename__ = "orders"
    __table_args__ = (
        in_check("payment_mode", PaymentMode),
        in_check("currency", ("ETB",)),
        in_check("channel", ("web", "telegram")),
        in_check("language", LANGUAGES),
        CheckConstraint("code ~ '^MX-[34679ACDEFGHJKMNPQRTUVWXY]{6}$'", name="code_format"),
        CheckConstraint("items_total_santim > 0", name="items_total_positive"),
        CheckConstraint("delivery_total_santim >= 0", name="delivery_total_non_negative"),
        CheckConstraint(
            "grand_total_santim = items_total_santim + delivery_total_santim",
            name="grand_total_adds_up",
        ),
        # The same submission sent twice creates one order (D.10). Scoped to the
        # buyer, so one person's key can never return another person's order.
        UniqueConstraint("buyer_user_id", "idempotency_key"),
        Index("ix_orders_buyer_created", "buyer_user_id", "created_at"),
    )

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    payment_mode: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="ETB")
    items_total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivery_total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grand_total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # A copy of the address as it was when the order was placed.
    address_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delivery_zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_zones.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="web")
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="am")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)


class SellerOrder(UUIDPrimaryKey, Timestamps, Base):
    """One seller's part of an order, with its own status and money trail."""

    __tablename__ = "seller_orders"
    __table_args__ = (
        in_check("status", SellerOrderStatus),
        in_check("paid_method", DirectPaymentMethod),
        CheckConstraint("items_total_santim > 0", name="items_total_positive"),
        CheckConstraint("delivery_fee_santim >= 0", name="delivery_fee_non_negative"),
        CheckConstraint("commission_santim >= 0", name="commission_non_negative"),
        CheckConstraint(
            "total_santim = items_total_santim + delivery_fee_santim", name="total_adds_up"
        ),
        CheckConstraint("(paid_at is null) = (paid_method is null)", name="paid_fields_together"),
        # One seller order per order and seller (G.8 rule 2).
        UniqueConstraint("order_id", "seller_id"),
        Index("ix_seller_orders_seller_status", "seller_id", "status"),
        Index("ix_seller_orders_status_deadline", "status", "response_deadline"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="placed")
    items_total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivery_fee_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_santim: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    response_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    problem_window_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Direct orders: the seller records how and when the buyer paid them (D.12).
    paid_method: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(Text)


class OrderItem(UUIDPrimaryKey, Base):
    """A purchased line. It keeps its own copy of everything it shows.

    Order lines never read live catalogue data (G.8 rule 4): a seller may edit
    or remove a product tomorrow, and this line must still say what was bought.
    """

    __tablename__ = "order_items"
    __table_args__ = (
        in_check("condition", Condition),
        CheckConstraint(f"quantity between 1 and {MAX_QUANTITY_PER_LINE}", name="quantity_range"),
        CheckConstraint("unit_price_santim > 0", name="unit_price_positive"),
        CheckConstraint(
            "line_total_santim = unit_price_santim * quantity", name="line_total_adds_up"
        ),
        CheckConstraint("commission_bps between 0 and 10000", name="commission_bps_range"),
        Index("ix_order_items_seller_order_id", "seller_order_id"),
        Index("ix_order_items_offer_id", "offer_id"),
    )

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_orders.id", ondelete="RESTRICT"), nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    title_am: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=False)
    variant_label_am: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    variant_label_en: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    image_key: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    warranty_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    unit_price_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # The fee rate in force when the order was placed; never recalculated (D.19).
    commission_bps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Serial number or IMEI, recorded at dispatch for phones (D.6, D.22).
    serial_number: Mapped[str | None] = mapped_column(Text)


class OrderStatusEvent(UUIDPrimaryKey, Base):
    """Every status change, with who, when and why. Append-only (D.23 rule 5)."""

    __tablename__ = "order_status_events"
    __table_args__ = (
        in_check("to_status", SellerOrderStatus),
        in_check("actor_type", ActorType),
        Index("ix_order_status_events_seller_order_occurred", "seller_order_id", "occurred_at"),
    )

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_orders.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
