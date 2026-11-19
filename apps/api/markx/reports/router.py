"""Report routes (blueprint C-30, AD-16; D-067).

`POST /reports`                         anyone who can see the thing
`/admin/reports`, `.../{id}/resolve`    staff who handle reports (moderate_reviews)
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from markx.accounts.deps import OptionalPrincipal, Principal, require_staff
from markx.accounts.models import SessionKind
from markx.accounts.permissions import StaffCapability
from markx.core import ratelimit
from markx.core.errors import PermissionDenied
from markx.core.http import Db, client_ip
from markx.reports import service
from markx.reports.schemas import ReportIn, ReportOut, ResolveReportIn, StaffReportOut
from markx.trust.models import ReportStatus

router = APIRouter(tags=["reports"])
admin_router = APIRouter(prefix="/admin/reports", tags=["admin: reports"])
ReportHandler = Annotated[Principal, Depends(require_staff(StaffCapability.MODERATE_REVIEWS))]

REPORTS_PER_ADDRESS_PER_HOUR = 10
REPORTS_PER_PERSON_PER_DAY = 20


@router.post("/reports", response_model=ReportOut, status_code=201)
def report(body: ReportIn, principal: OptionalPrincipal, request: Request, db: Db) -> ReportOut:
    """Flag a product, an offer, a store or a review (C-30). Signed in or not;
    limited per network address, and per person when signed in."""
    # Staff act on what they see with their own tools, not through the
    # public form (blueprint C.1: staff and customer powers never mix).
    if principal is not None and principal.session.kind == SessionKind.STAFF:
        raise PermissionDenied("customer_session_required", "Staff use the moderation tools.")
    ratelimit.hit(
        f"report:ip:{client_ip(request) or 'unknown'}",
        REPORTS_PER_ADDRESS_PER_HOUR,
        timedelta(hours=1),
    )
    if principal is not None:
        ratelimit.hit(
            f"report:user:{principal.user.id}", REPORTS_PER_PERSON_PER_DAY, timedelta(days=1)
        )
    filed = service.file_report(
        db, user_id=principal.user.id if principal else None, target_type=body.target_type,
        target_id=body.target_id, store_slug=body.store_slug, reason=body.reason.value,
        note=body.note,
    )  # fmt: skip
    return ReportOut(id=filed.id, status=filed.status, created_at=filed.created_at)


@admin_router.get("", response_model=list[StaffReportOut])
def report_queue(
    staff: ReportHandler,
    db: Db,
    status: Annotated[str, Query(pattern="^(open|actioned|dismissed)$")] = "open",
    target_type: Annotated[str | None, Query(pattern="^(product|offer|store|review)$")] = None,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[StaffReportOut]:
    """Open reports oldest first (page with `before` = the last id: the next
    ones after it); closed ones newest first (AD-16)."""
    return [
        StaffReportOut.model_validate(row)
        for row in service.queue(
            db, status=status, target_type=target_type, before=before, limit=limit
        )
    ]


@admin_router.post("/{report_id}/resolve", response_model=list[StaffReportOut])
def resolve_report(
    report_id: uuid.UUID, body: ResolveReportIn, staff: ReportHandler, request: Request, db: Db
) -> list[StaffReportOut]:
    """`actioned` or `dismissed`, with a note; by default every open report on
    the same target. Returns the reports it closed."""
    closed = service.resolve(
        db, staff.actor(request), report_id, outcome=ReportStatus(body.outcome),
        note=body.note, all_on_target=body.all_on_target,
    )  # fmt: skip
    return [StaffReportOut.model_validate(service.one(db, r.id)) for r in closed]
