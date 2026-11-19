"""Platform tables that belong to no single business module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base


class Setting(Base):
    """Feature switches and limits (blueprint F.2). Changed by staff, audit-logged."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RateLimitCounter(Base):
    """Fixed-window counters kept in PostgreSQL (blueprint F.3): no Redis at launch."""

    __tablename__ = "rate_limit_counters"
    __table_args__ = (CheckConstraint("count >= 0", name="count_non_negative"),)

    bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
