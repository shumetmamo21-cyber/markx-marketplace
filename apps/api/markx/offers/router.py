"""Offer routes (blueprint F.5).

`/seller/{seller_id}/offers...`  the seller's own listings, scoped by `require_seller`
`/catalog/...`                   what buyers see: ranked offers, store price lists
`/admin/offers/...`              listing moderation
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from markx.accounts.deps import Principal, SellerContext, require_seller, require_staff
from markx.accounts.permissions import SellerCapability, StaffCapability
from markx.catalog import service as catalog
from markx.catalog.models import ProductStatus
from markx.catalog.schemas import ProductIn
from markx.core import ratelimit
from markx.core.errors import Conflict
from markx.core.http import Db
from markx.core.schemas import ApiModel
from markx.offers import selectors, service
from markx.offers.schemas import (
    CheckInIn,
    CheckInOut,
    DashboardOut,
    HeldOfferOut,
    ModerationIn,
    OfferIn,
    OfferStatusOut,
    OfferUpdateIn,
    PriceListItemOut,
    ProductOffersOut,
    SellerOfferDetailOut,
    SellerOfferOut,
    StockIn,
)
from markx.sellers.models import SellerStatus

router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: offers"])
public_router = APIRouter(prefix="/catalog", tags=["catalog"])
admin_router = APIRouter(prefix="/admin/offers", tags=["admin: offers"])

AnyMember = Annotated[SellerContext, Depends(require_seller())]
OfferManager = Annotated[SellerContext, Depends(require_seller(SellerCapability.MANAGE_OFFERS))]
Proposer = Annotated[SellerContext, Depends(require_seller(SellerCapability.PROPOSE_PRODUCTS))]
# Takes a listing down and lifts the hold again.
# PROVISIONAL (F-07, D-083): every role that may take a listing down (super
# administrator, operations, catalogue) may also lift the hold, with a reason;
# read the audit log for `offer.staff_restore` now and then.
#   The engineer's guess at the founder's request; THE FOUNDER MUST CONFIRM OR
#   CHANGE IT BEFORE MARKX GOES LIVE.
ListingModerator = Annotated[Principal, Depends(require_staff(StaffCapability.MODERATE_LISTINGS))]

LangQuery = Annotated[str, Query(pattern="^(am|en)$")]
PUBLIC_CACHE = "public, max-age=30"


def _detail(db: Db, context: SellerContext, offer_id: uuid.UUID, lang: str) -> SellerOfferDetailOut:
    return SellerOfferDetailOut.model_validate(
        selectors.seller_offer_detail(db, context.seller.id, offer_id, lang)
    )


# -- seller ----------------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(context: AnyMember, db: Db) -> DashboardOut:
    return DashboardOut(**selectors.seller_dashboard(db, context.seller.id))


@router.get("/offers", response_model=list[SellerOfferOut])
def list_offers(
    context: AnyMember,
    db: Db,
    status: Literal["active", "paused", "stale", "removed"] | None = None,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    lang: LangQuery = "am",
) -> list[SellerOfferOut]:
    rows = selectors.seller_offers(
        db, context.seller.id, lang, status=status, after=after, limit=limit
    )
    return [SellerOfferOut.model_validate(row) for row in rows]


@router.post("/offers", response_model=SellerOfferDetailOut, status_code=201)
def create_offer(
    body: OfferIn, context: OfferManager, request: Request, db: Db, lang: LangQuery = "am"
) -> SellerOfferDetailOut:
    ratelimit.hit(f"offer-create:{context.seller.id}", 300, timedelta(hours=1))
    offer = service.create_offer(
        db, context.principal.actor(request), context.seller,
        service.OfferInput(**body.model_dump()),
    )  # fmt: skip
    return _detail(db, context, offer.id, lang)


# Declared before `/offers/{offer_id}` so "check-in" is not read as an id.
@router.post("/offers/check-in", response_model=CheckInOut)
def check_in(body: CheckInIn, context: OfferManager, request: Request, db: Db) -> CheckInOut:
    """One tap: "my prices and stock are still right" (S-08)."""
    confirmed = service.confirm_offers(
        db, context.principal.actor(request), context.seller, body.offer_ids
    )
    return CheckInOut(confirmed=confirmed)


@router.get("/offers/{offer_id}", response_model=SellerOfferDetailOut)
def read_offer(
    offer_id: uuid.UUID, context: AnyMember, db: Db, lang: LangQuery = "am"
) -> SellerOfferDetailOut:
    return _detail(db, context, offer_id, lang)


@router.patch("/offers/{offer_id}", response_model=SellerOfferDetailOut)
def update_offer(
    offer_id: uuid.UUID,
    body: OfferUpdateIn,
    context: OfferManager,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOfferDetailOut:
    service.update_offer(
        db, context.principal.actor(request), context.seller, offer_id, **body.model_dump()
    )
    return _detail(db, context, offer_id, lang)


@router.put("/offers/{offer_id}/stock", response_model=SellerOfferDetailOut)
def set_stock(
    offer_id: uuid.UUID,
    body: StockIn,
    context: OfferManager,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOfferDetailOut:
    service.set_stock(
        db, context.principal.actor(request), context.seller, offer_id,
        on_hand=body.on_hand, low_stock_threshold=body.low_stock_threshold,
    )  # fmt: skip
    return _detail(db, context, offer_id, lang)


@router.post("/offers/{offer_id}/pause", response_model=SellerOfferDetailOut)
def pause_offer(
    offer_id: uuid.UUID, context: OfferManager, request: Request, db: Db, lang: LangQuery = "am"
) -> SellerOfferDetailOut:
    service.pause_offer(db, context.principal.actor(request), context.seller, offer_id)
    return _detail(db, context, offer_id, lang)


@router.post("/offers/{offer_id}/resume", response_model=SellerOfferDetailOut)
def resume_offer(
    offer_id: uuid.UUID, context: OfferManager, request: Request, db: Db, lang: LangQuery = "am"
) -> SellerOfferDetailOut:
    service.resume_offer(db, context.principal.actor(request), context.seller, offer_id)
    return _detail(db, context, offer_id, lang)


@router.delete("/offers/{offer_id}", response_model=SellerOfferDetailOut)
def remove_offer(
    offer_id: uuid.UUID, context: OfferManager, request: Request, db: Db, lang: LangQuery = "am"
) -> SellerOfferDetailOut:
    service.remove_offer(db, context.principal.actor(request), context.seller, offer_id)
    return _detail(db, context, offer_id, lang)


# -- product proposals (S-05) ------------------------------------------------------


class ProposalOut(ApiModel):
    id: uuid.UUID
    slug: str
    status: str


@router.post("/product-proposals", response_model=ProposalOut, status_code=201)
def propose_product(body: ProductIn, context: Proposer, request: Request, db: Db) -> ProposalOut:
    """A seller proposes a product missing from the catalogue. It is shown to
    nobody until catalogue staff approve it or merge it into an existing one."""
    if context.seller.status != SellerStatus.ACTIVE:
        raise Conflict(
            "seller_not_active", "Your store must be approved and active to propose products."
        )
    ratelimit.hit(f"product-proposal:{context.seller.id}", 30, timedelta(hours=1))
    product = catalog.create_product(
        db, context.principal.actor(request),
        category_id=body.category_id, name_am=body.name_am, name_en=body.name_en,
        description_am=body.description_am, description_en=body.description_en,
        brand_id=body.brand_id, model=body.model, specs=body.specs,
        variants=[
            catalog.VariantInput(attribute_values=v.attribute_values, model_code=v.model_code)
            for v in body.variants
        ],
        # Whatever the body says, a seller's product is a proposal.
        status=ProductStatus.PENDING_REVIEW,
        proposed_by_seller_id=context.seller.id,
    )  # fmt: skip
    return ProposalOut(id=product.id, slug=product.slug, status=product.status)


# -- public ----------------------------------------------------------------------


@public_router.get("/products/{slug}/offers", response_model=ProductOffersOut)
def product_offers(
    slug: str,
    db: Db,
    response: Response,
    zone: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,39}$")] = None,
    variant_id: uuid.UUID | None = None,
) -> ProductOffersOut:
    """Every seller's live offer for a product, ranked for the buyer's zone."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return ProductOffersOut.model_validate(
        selectors.product_offers(db, slug, zone_code=zone, variant_id=variant_id)
    )


@public_router.get("/stores/{slug}/offers", response_model=list[PriceListItemOut])
def store_price_list(
    slug: str,
    db: Db,
    response: Response,
    lang: LangQuery = "am",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[PriceListItemOut]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return [
        PriceListItemOut.model_validate(row)
        for row in selectors.store_price_list(db, slug, lang, limit=limit)
    ]


# -- staff -----------------------------------------------------------------------


@admin_router.get("/held", response_model=list[HeldOfferOut])
def list_held_offers(
    _: ListingModerator,
    db: Db,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    lang: LangQuery = "am",
) -> list[HeldOfferOut]:
    """Listings under a staff takedown, newest first, with the reason given."""
    rows = selectors.held_offers(db, lang, before=before, limit=limit)
    return [HeldOfferOut.model_validate(row) for row in rows]


@admin_router.post("/{offer_id}/remove", response_model=OfferStatusOut)
def staff_remove_offer(
    offer_id: uuid.UUID, body: ModerationIn, staff: ListingModerator, request: Request, db: Db
) -> OfferStatusOut:
    offer = service.staff_remove_offer(db, staff.actor(request), offer_id, reason=body.reason)
    return OfferStatusOut.model_validate(offer)


@admin_router.post("/{offer_id}/restore", response_model=OfferStatusOut)
def staff_restore_offer(
    offer_id: uuid.UUID, body: ModerationIn, staff: ListingModerator, request: Request, db: Db
) -> OfferStatusOut:
    """Lift a takedown, so the seller may list the item again."""
    offer = service.staff_restore_offer(db, staff.actor(request), offer_id, reason=body.reason)
    return OfferStatusOut.model_validate(offer)
