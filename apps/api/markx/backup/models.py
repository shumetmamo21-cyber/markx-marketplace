from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, UUIDPrimaryKey, in_check

RUN_KINDS = ("backup", "drill", "verify")
RUN_STATUSES = ("running", "succeeded", "incomplete", "failed", "skipped", "abandoned")


class BackupRun(UUIDPrimaryKey, Base):
    """One attempt of the backup service, a restore drill or a verification
    (D-094). Written by the backup service (as the schema owner); the API's
    role may only read it, and the worker's watch turns it into alerts.

    `verified` means the set's every piece was read back from the destination
    and matched; `offsite` means that destination is away from this server.
    Only a run that is both, and `succeeded`, is a fresh off-server recovery
    point. Nothing here is a secret: the destination is named by provider,
    host, bucket and prefix only.
    """

    __tablename__ = "backup_runs"
    __table_args__ = (
        in_check("kind", RUN_KINDS),
        in_check("status", RUN_STATUSES),
        CheckConstraint(
            "(status = 'running') = (finished_at is null)", name="finished_unless_running"
        ),
        CheckConstraint(
            "status not in ('failed', 'abandoned') or error_code is not null",
            name="failure_has_a_code",
        ),
        CheckConstraint("not verified or status = 'succeeded'", name="verified_only_if_succeeded"),
        CheckConstraint(
            "finished_at is null or finished_at >= started_at", name="finished_after_start"
        ),
        Index("ix_backup_runs_kind_started", "kind", "started_at"),
    )

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    backup_id: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    offsite: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    database_bytes: Mapped[int | None] = mapped_column(BigInteger)
    object_count: Mapped[int | None] = mapped_column(Integer)
    object_bytes: Mapped[int | None] = mapped_column(BigInteger)
    new_objects: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
