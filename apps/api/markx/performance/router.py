"""Performance routes (blueprint D.4, S-17, S-26; D-069).

`GET /seller/{seller_id}/performance?days=N`     the performance page (S-17)
`GET /seller/{seller_id}/weekly-reports`         past weekly messages (S-26)

Every member of the store may read them (C.3, "see performance").
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from markx.accounts.deps import SellerContext, require_seller
from markx.accounts.permissions import SellerCapability
from markx.core.http import Db
from markx.performance import service

router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: performance"])
PerformanceReader = Annotated[
    SellerContext, Depends(require_seller(SellerCapability.SEE_PERFORMANCE))
]


class PerformanceOut(BaseModel):
    """Counts and shares (0 to 1, or null with nothing to divide); money in
    santim. "Received" counts the orders placed in the period; the moves
    (delivered, completed, problems) count what happened in it."""

    from_time: datetime
    to_time: datetime
    orders_received: int
    orders_confirmed: int
    orders_declined: int
    orders_unanswered: int
    orders_cancelled_by_buyer: int
    confirmation_share: float | None
    median_minutes_to_confirm: float | None
    delivered: int
    delivery_failed: int
    delivery_success_share: float | None
    completed: int
    completed_value_santim: int
    problems_reported: int
    refunded: int
    new_reviews: int
    new_reviews_average: float | None
    rating_count: int
    rating_average: float | None
    active_offers: int
    prices_to_confirm: int
    low_stock_offers: int


class WeeklyReportOut(BaseModel):
    id: uuid.UUID
    week_start: date
    created_at: datetime
    figures: PerformanceOut


@router.get("/performance", response_model=PerformanceOut)
def performance(
    context: PerformanceReader, db: Db, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> PerformanceOut:
    """The last `days` days, up to now."""
    end = datetime.now(UTC)
    return PerformanceOut.model_validate(
        service.figures(db, context.seller.id, end - timedelta(days=days), end)
    )


@router.get("/weekly-reports", response_model=list[WeeklyReportOut])
def weekly_reports(
    context: PerformanceReader, db: Db, limit: Annotated[int, Query(ge=1, le=52)] = 12
) -> list[WeeklyReportOut]:
    """Newest week first, exactly as each was sent."""
    return [
        WeeklyReportOut(
            id=r.id,
            week_start=r.week_start,
            created_at=r.created_at,
            figures=PerformanceOut.model_validate(r.figures),
        )
        for r in service.weekly_reports(db, context.seller.id, limit=limit)
    ]
