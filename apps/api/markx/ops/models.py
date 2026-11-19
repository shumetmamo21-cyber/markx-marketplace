from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, UUIDPrimaryKey, in_check


class OpsAlert(UUIDPrimaryKey, Base):
    """Something wrong with the running marketplace (blueprint F.12; D-064).

    One open alert per key at a time. An alert opens the first time a check
    finds the problem, is touched on every later check that still finds it,
    and resolves on the first check that no longer does. The founder is told
    when it opens and when it resolves. Rows are kept: they are the record
    of what went wrong and for how long.
    """

    __tablename__ = "ops_alerts"
    __table_args__ = (
        in_check("severity", ("warning", "critical")),
        in_check("source", ("watch", "reconcile")),
        CheckConstraint("occurrences >= 1", name="occurrences_positive"),
        CheckConstraint(
            "resolved_at is null or resolved_at >= first_seen_at", name="resolved_after"
        ),
        Index(
            "uq_ops_alerts_open_key",
            "key",
            unique=True,
            postgresql_where=text("resolved_at is null"),
        ),
        Index("ix_ops_alerts_first_seen", "first_seen_at"),
    )

    key: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
