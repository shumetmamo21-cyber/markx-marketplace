from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey


class SellerWeeklyReport(UUIDPrimaryKey, CreatedAt, Base):
    """One store's weekly performance message (blueprint S-26, K.5; D-069):
    the figures of one week, Monday to Sunday in Addis Ababa time, kept as
    they were sent so the store can read past weeks again. One per store and
    week, which is also what makes sending them safe to run twice."""

    __tablename__ = "seller_weekly_reports"
    __table_args__ = (
        UniqueConstraint("seller_id", "week_start"),
        CheckConstraint("extract(isodow from week_start) = 1", name="week_starts_on_monday"),
    )

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    figures: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
