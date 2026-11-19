from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    source: str
    severity: str
    summary: str
    details: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    resolved_at: datetime | None


class JobOut(BaseModel):
    name: str
    next_run_at: datetime
    last_started_at: datetime | None
    last_succeeded_at: datetime | None
    last_result: int | None
    consecutive_failures: int
    last_error: str | None


class OutboxCountOut(BaseModel):
    topic: str
    status: str
    count: int


class OpsStatusOut(BaseModel):
    """Open alerts (critical first), every scheduled job, and the outbox
    messages that are not done, by topic and status."""

    open_alerts: list[AlertOut]
    jobs: list[JobOut]
    outbox: list[OutboxCountOut]
