from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, Base):
    """Who did what (blueprint G.2). Insert-only.

    The application role holds no UPDATE or DELETE right on this table, and a
    trigger refuses both for every role, so history cannot be rewritten.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("actor_type in ('user', 'staff', 'system')", name="actor_type_allowed"),
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Deliberately not a foreign key: the trail must outlive any row it mentions.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[Any | None] = mapped_column(JSONB)
    after: Mapped[Any | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(Text)
