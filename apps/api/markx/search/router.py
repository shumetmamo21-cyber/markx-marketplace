"""Search routes (blueprint D.8, F.7, AD-07).

`/search`              products for a query, with filters and sorting
`/search/suggest`      names as the buyer types
`/product-requests`    "can't find it? ask for it"
`/admin/search/...`    the zero-result report and the synonym tool
                       (`tune_search`)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from markx.accounts.deps import OptionalPrincipal, Principal, require_staff
from markx.accounts.permissions import StaffCapability
from markx.core import ratelimit
from markx.core.http import Db, client_ip
from markx.core.schemas import Ok
from markx.search import selectors, service
from markx.search.models import SearchSynonym
from markx.search.schemas import (
    ProductRequestIn,
    ProductRequestOut,
    SearchOut,
    SuggestionOut,
    SynonymIn,
    SynonymOut,
    ZeroResultOut,
)

router = APIRouter(tags=["search"])
admin_router = APIRouter(prefix="/admin/search", tags=["admin: search"])
SearchTuner = Annotated[Principal, Depends(require_staff(StaffCapability.TUNE_SEARCH))]

LangQuery = Annotated[str, Query(pattern="^(am|en)$")]
Slug = Annotated[str | None, Query(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
PRODUCT_REQUESTS_PER_HOUR = 10


@router.get("/search", response_model=SearchOut)
def search_products(
    principal: OptionalPrincipal,
    db: Db,
    q: Annotated[str, Query(max_length=200)] = "",
    category: Slug = None,
    brand: Slug = None,
    condition: Annotated[str | None, Query(pattern=r"^[a-z_]{2,30}$")] = None,
    min_price: Annotated[int | None, Query(ge=0)] = None,
    max_price: Annotated[int | None, Query(ge=0)] = None,
    min_level: Annotated[int | None, Query(ge=0, le=3)] = None,
    in_stock: bool = False,
    sort: Literal["relevance", "price", "freshness"] = "relevance",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    lang: LangQuery = "am",
) -> SearchOut:
    """Products, never listings (D.8). Prices in santim; the "from" price is
    the lowest in stock. Every first page is logged with its result count."""
    return SearchOut.model_validate(
        selectors.search(
            db, q, language=lang, category=category, brand=brand, condition=condition,
            min_price=min_price, max_price=max_price, min_level=min_level,
            in_stock_only=in_stock, sort=sort, limit=limit, offset=offset,
            user_id=principal.user.id if principal else None,
        )
    )  # fmt: skip


@router.get("/search/suggest", response_model=list[SuggestionOut])
def suggest_products(
    db: Db, q: Annotated[str, Query(max_length=200)] = "", lang: LangQuery = "am"
) -> list[SuggestionOut]:
    return [SuggestionOut.model_validate(row) for row in selectors.suggest(db, q, language=lang)]


@router.post("/product-requests", response_model=ProductRequestOut, status_code=201)
def request_a_product(
    body: ProductRequestIn, principal: OptionalPrincipal, request: Request, db: Db
) -> ProductRequestOut:
    ratelimit.hit(
        f"product_request:ip:{client_ip(request) or 'unknown'}",
        PRODUCT_REQUESTS_PER_HOUR,
        timedelta(hours=1),
    )
    created = service.request_product(
        db, query=body.query, note=body.note, contact_phone=body.contact_phone,
        user_id=principal.user.id if principal else None,
    )  # fmt: skip
    return ProductRequestOut.model_validate(created)


@admin_router.get("/zero-results", response_model=list[ZeroResultOut])
def zero_results(
    staff: SearchTuner,
    db: Db,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ZeroResultOut]:
    """Searches that found nothing, most frequent first (AD-07)."""
    since = datetime.now(UTC) - timedelta(days=days)
    return [
        ZeroResultOut.model_validate(row)
        for row in selectors.zero_result_queries(db, since=since, limit=limit)
    ]


@admin_router.get("/synonyms", response_model=list[SynonymOut])
def list_synonyms(staff: SearchTuner, db: Db) -> list[SynonymOut]:
    return [
        SynonymOut.model_validate(row)
        for row in db.scalars(select(SearchSynonym).order_by(SearchSynonym.term_normalized))
    ]


@admin_router.post("/synonyms", response_model=SynonymOut, status_code=201)
def add_synonym(body: SynonymIn, staff: SearchTuner, request: Request, db: Db) -> SynonymOut:
    return SynonymOut.model_validate(
        service.add_synonym(db, staff.actor(request), term=body.term, expansion=body.expansion)
    )


@admin_router.delete("/synonyms/{synonym_id}", response_model=Ok)
def remove_synonym(synonym_id: uuid.UUID, staff: SearchTuner, request: Request, db: Db) -> Ok:
    service.remove_synonym(db, staff.actor(request), synonym_id)
    return Ok()
