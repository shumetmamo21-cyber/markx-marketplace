from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey


class AnalyticsEvent(UUIDPrimaryKey, CreatedAt, Base):
    """First-party funnel events (blueprint D.21). No third-party trackers."""

    __tablename__ = "analytics_events"
    __table_args__ = (Index("ix_analytics_events_name_created", "name", "created_at"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    anon_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
