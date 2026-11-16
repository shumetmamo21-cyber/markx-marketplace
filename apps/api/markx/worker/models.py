from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base


class ScheduledJob(Base):
    """When each scheduled job runs next (blueprint F.8).

    One row per job. A worker runs a job only while it holds this row's lock,
    so two workers never run the same job at once, and a worker that dies
    mid-run leaves the row exactly as it was: the job is simply due again.
    """

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_non_negative"),
    )

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
