"""Export routes (blueprint C.4 "export data": super administrator and finance;
D-068).

`GET /admin/exports/{kind}?first_day=YYYY-MM-DD&last_day=YYYY-MM-DD`
    kind: fees, ledger, seller-orders, seller-balances. A CSV file.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response

from markx.accounts.deps import Principal, require_staff
from markx.accounts.permissions import StaffCapability
from markx.core.http import Db
from markx.exports import service

router = APIRouter(prefix="/admin/exports", tags=["admin: exports"])
Exporter = Annotated[Principal, Depends(require_staff(StaffCapability.EXPORT_DATA))]


@router.get(
    "/{kind}",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The CSV file."}},
)
def export(
    kind: Literal["fees", "ledger", "seller-orders", "seller-balances"],
    first_day: date,
    last_day: date,
    staff: Exporter,
    request: Request,
    db: Db,
) -> Response:
    """Whole days in Addis Ababa time, at most 366. UTF-8 with a byte-order
    mark; amounts in exact birr and in santim. Every export is audit-logged."""
    made = service.export(db, staff.actor(request), kind, service.period(first_day, last_day))
    return Response(
        content=made.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{made.filename}"',
            "Cache-Control": "private, no-store",
            "X-Export-Rows": str(made.rows),
        },
    )
