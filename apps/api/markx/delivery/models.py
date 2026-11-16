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

from markx.accounts.models import PHONE_PATTERN
from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check


class DeliveryMode(StrEnum):
    SELLER_RIDER = "seller_rider"
    PARTNER_COURIER = "partner_courier"
    SHOP_COLLECTION = "shop_collection"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    RETURNED = "returned"
    CANCELLED = "cancelled"


MAX_HANDOVER_ATTEMPTS = 5


class DeliveryZone(UUIDPrimaryKey, CreatedAt, Base):
    """An area with one flat delivery fee per method (blueprint D.13, AD-05)."""

    __tablename__ = "delivery_zones"
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_format"),)

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_am: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False, server_default="Addis Ababa")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class DeliveryArea(UUIDPrimaryKey, CreatedAt, Base):
    """A neighbourhood by the name people say aloud, mapped to a zone (I.7)."""

    __tablename__ = "delivery_areas"
    __table_args__ = (
        UniqueConstraint("zone_id", "name_en"),
        Index("ix_delivery_areas_zone_id", "zone_id"),
    )

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_zones.id", ondelete="RESTRICT"), nullable=False
    )
    name_am: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class DeliveryRate(UUIDPrimaryKey, CreatedAt, Base):
    """The flat fee and promised time for one method into one zone.

    Collection at the shop has no rate: it is always free.
    """

    __tablename__ = "delivery_rates"
    __table_args__ = (
        in_check("method", (DeliveryMode.SELLER_RIDER, DeliveryMode.PARTNER_COURIER)),
        CheckConstraint("fee_santim >= 0", name="fee_non_negative"),
        CheckConstraint("promised_hours > 0", name="promised_hours_positive"),
        UniqueConstraint("zone_id", "method"),
    )

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_zones.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    fee_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promised_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Shipment(UUIDPrimaryKey, Timestamps, Base):
    """The delivery of one seller order (blueprint G.2, J.10)."""

    __tablename__ = "shipments"
    __table_args__ = (
        in_check("mode", DeliveryMode),
        in_check("status", ShipmentStatus),
        CheckConstraint("fee_santim >= 0", name="fee_non_negative"),
        CheckConstraint(
            f"handover_attempts between 0 and {MAX_HANDOVER_ATTEMPTS}",
            name="handover_attempts_range",
        ),
        CheckConstraint("code_version > 0", name="code_version_positive"),
        CheckConstraint(
            f"rider_phone is null or rider_phone ~ '{PHONE_PATTERN}'", name="rider_phone_format"
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at is not null)", name="delivered_has_time"
        ),
    )

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_orders.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    fee_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promised_hours: Mapped[int | None] = mapped_column(SmallInteger)
    courier_name: Mapped[str | None] = mapped_column(Text)
    rider_name: Mapped[str | None] = mapped_column(Text)
    rider_phone: Mapped[str | None] = mapped_column(Text)
    # The handover code is derived from the server secret, this row's id and
    # this version; raising the version issues a new code. Nothing here reveals it.
    code_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    handover_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class TrackingEvent(UUIDPrimaryKey, Base):
    """Delivery history. Append-only (blueprint G.2)."""

    __tablename__ = "tracking_events"
    __table_args__ = (
        in_check("status", ShipmentStatus),
        in_check("source", ("buyer", "seller", "rider", "staff", "system")),
        Index("ix_tracking_events_shipment_occurred", "shipment_id", "occurred_at"),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
