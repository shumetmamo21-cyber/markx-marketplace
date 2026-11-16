from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey


class Outbox(UUIDPrimaryKey, CreatedAt, Base):
    """Work to do after a transaction commits (blueprint D.16, F.8).

    A row is written in the same transaction as the change that caused it, so
    work from a rolled-back transaction never exists. The worker claims rows
    with FOR UPDATE SKIP LOCKED; this table is the job queue.
    """

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'done', 'failed')", name="status_allowed"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_outbox_due", "run_after", postgresql_where=text("status = 'pending'")),
    )

    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Notification(UUIDPrimaryKey, CreatedAt, Base):
    """The in-app list and the delivery record for every channel (blueprint G.2)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel in ('in_app', 'telegram', 'sms')", name="channel_allowed"),
        CheckConstraint("status in ('sent', 'failed', 'read')", name="status_allowed"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="sent")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
