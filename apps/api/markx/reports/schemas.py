from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from markx.trust.models import ReportReason, ReportTarget


class ReportIn(BaseModel):
    """What is reported, and why. A store is named by its id or its link
    name (`store_slug`, as on its page); everything else by its id."""

    target_type: ReportTarget
    target_id: uuid.UUID | None = None
    store_slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)
    reason: ReportReason
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_target(self) -> ReportIn:
        if self.store_slug is not None and self.target_type != ReportTarget.STORE:
            raise ValueError("store_slug names a store only")
        if self.target_id is None and self.store_slug is None:
            raise ValueError("say what is reported: target_id, or store_slug for a store")
        return self


class ReportOut(BaseModel):
    """The reporter learns only that the report was received."""

    id: uuid.UUID
    status: str
    created_at: datetime


class ResolveReportIn(BaseModel):
    outcome: Literal["actioned", "dismissed"]
    note: str = Field(min_length=3, max_length=500)
    # Close every open report on the same target, not just this one.
    all_on_target: bool = True


class StaffReportOut(BaseModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    product_slug: str | None
    store_slug: str | None
    excerpt: str | None
    reason: str
    note: str | None
    from_signed_in_person: bool
    status: str
    open_reports_on_target: int
    created_at: datetime
    resolution_note: str | None
    resolved_at: datetime | None
