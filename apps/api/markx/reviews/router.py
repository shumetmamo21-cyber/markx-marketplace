"""Review routes (blueprint D.15, C-18, S-16, AD-12; D-066).

`/catalog/products/{slug}/reviews`, `/catalog/stores/{slug}/reviews`   anyone
`/me/reviews`, `/me/reviews/pending`, `/me/orders/.../review`           the buyer
`/seller/{seller_id}/reviews`                                         the seller
`/admin/reviews`                                                      staff (moderate_reviews)
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from markx.accounts.deps import Principal, SellerContext, require_seller, require_staff
from markx.accounts.permissions import SellerCapability, StaffCapability
from markx.core import ratelimit
from markx.core.http import Db
from markx.orders.router import Buyer
from markx.reviews import selectors, service
from markx.reviews.schemas import (
    ModerateReviewIn,
    MyReviewOut,
    ProductReviewsOut,
    ReviewableItemOut,
    ReviewIn,
    ReviewReplyIn,
    StoreReviewsOut,
)

public_router = APIRouter(prefix="/catalog", tags=["catalog"])
buyer_router = APIRouter(tags=["reviews"])
seller_router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: reviews"])
admin_router = APIRouter(prefix="/admin/reviews", tags=["admin: reviews"])

Replier = Annotated[SellerContext, Depends(require_seller(SellerCapability.REPLY_TO_REVIEWS))]
ReviewModerator = Annotated[Principal, Depends(require_staff(StaffCapability.MODERATE_REVIEWS))]
LangQuery = Annotated[str, Query(pattern="^(am|en)$")]
Slug = Annotated[str, Path(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=120)]
Limit = Annotated[int, Query(ge=1, le=50)]


def _one(db: Db, review_id: uuid.UUID, lang: str, *, for_seller: bool = False) -> MyReviewOut:
    return MyReviewOut.model_validate(
        selectors.one_review(db, review_id, language=lang, for_seller=for_seller)
    )


# -- anyone ------------------------------------------------------------------------------


@public_router.get("/products/{slug}/reviews", response_model=ProductReviewsOut)
def product_reviews(
    slug: Slug,
    response: Response,
    db: Db,
    before: uuid.UUID | None = None,
    limit: Limit = 20,
    lang: LangQuery = "am",
) -> ProductReviewsOut:
    """Published reviews, newest first; page with `before` set to the last id.
    The summary is the product's rating totals."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return ProductReviewsOut.model_validate(
        selectors.product_reviews(db, slug, language=lang, before=before, limit=limit)
    )


@public_router.get("/stores/{slug}/reviews", response_model=StoreReviewsOut)
def store_reviews(
    slug: Slug,
    response: Response,
    db: Db,
    before: uuid.UUID | None = None,
    limit: Limit = 20,
    lang: LangQuery = "am",
) -> StoreReviewsOut:
    response.headers["Cache-Control"] = "public, max-age=60"
    return StoreReviewsOut.model_validate(
        selectors.store_reviews(db, slug, language=lang, before=before, limit=limit)
    )


# -- the buyer ---------------------------------------------------------------------------


@buyer_router.get("/me/reviews/pending", response_model=list[ReviewableItemOut])
def reviewable(buyer: Buyer, db: Db, lang: LangQuery = "am") -> list[ReviewableItemOut]:
    """Items of completed orders waiting for a review, while the window is open."""
    return [
        ReviewableItemOut.model_validate(row)
        for row in selectors.reviewable_items(db, buyer.user, language=lang)
    ]


@buyer_router.get("/me/reviews", response_model=list[MyReviewOut])
def my_reviews(buyer: Buyer, db: Db, lang: LangQuery = "am") -> list[MyReviewOut]:
    return [
        MyReviewOut.model_validate(row)
        for row in selectors.buyer_reviews(db, buyer.user, language=lang)
    ]


@buyer_router.post(
    "/me/orders/{order_id}/items/{item_id}/review", response_model=MyReviewOut, status_code=201
)
def write_review(
    order_id: uuid.UUID, item_id: uuid.UUID, body: ReviewIn, buyer: Buyer, db: Db,
    lang: LangQuery = "am",
) -> MyReviewOut:  # fmt: skip
    """Rate the product and the seller of one item of a completed order (C-18)."""
    ratelimit.hit(f"review-write:{buyer.user.id}", 30, timedelta(hours=1))
    review = service.write_review(
        db, buyer.user, order_id, item_id, product_rating=body.product_rating,
        seller_rating=body.seller_rating, body=body.body,
    )  # fmt: skip
    return _one(db, review.id, lang)


@buyer_router.put("/me/reviews/{review_id}", response_model=MyReviewOut)
def edit_review(
    review_id: uuid.UUID, body: ReviewIn, buyer: Buyer, db: Db, lang: LangQuery = "am"
) -> MyReviewOut:
    """Until the seller replies or the window closes."""
    service.edit_review(
        db, buyer.user, review_id, product_rating=body.product_rating,
        seller_rating=body.seller_rating, body=body.body,
    )  # fmt: skip
    return _one(db, review_id, lang)


# -- the seller --------------------------------------------------------------------------


@seller_router.get("/reviews", response_model=list[MyReviewOut])
def seller_reviews(
    context: Replier, db: Db, before: uuid.UUID | None = None, limit: Limit = 20,
    lang: LangQuery = "am",
) -> list[MyReviewOut]:  # fmt: skip
    """This store's reviews, published or hidden by staff, newest first."""
    return [
        MyReviewOut.model_validate(row)
        for row in selectors.seller_reviews(
            db, context.seller.id, language=lang, before=before, limit=limit
        )
    ]


@seller_router.post("/reviews/{review_id}/reply", response_model=MyReviewOut)
def reply_to_review(
    review_id: uuid.UUID, body: ReviewReplyIn, context: Replier, db: Db, lang: LangQuery = "am"
) -> MyReviewOut:
    """One reply, which the store may reword (S-16). A store cannot remove a review."""
    service.reply(db, context.seller, context.member, review_id, body=body.body)
    return _one(db, review_id, lang, for_seller=True)


# -- staff -------------------------------------------------------------------------------


@admin_router.get("", response_model=list[MyReviewOut])
def review_queue(
    staff: ReviewModerator,
    db: Db,
    status: Annotated[str, Query(pattern="^(held|published|hidden)$")] = "held",
    before: uuid.UUID | None = None,
    limit: Limit = 50,
    lang: LangQuery = "am",
) -> list[MyReviewOut]:
    """Held reviews by default: what a pattern check stopped (AD-12)."""
    return [
        MyReviewOut.model_validate(row)
        for row in selectors.staff_reviews(
            db, status=status, language=lang, before=before, limit=limit
        )
    ]


@admin_router.post("/{review_id}/moderate", response_model=MyReviewOut)
def moderate_review(
    review_id: uuid.UUID, body: ModerateReviewIn, staff: ReviewModerator, request: Request,
    db: Db, lang: LangQuery = "am",
) -> MyReviewOut:  # fmt: skip
    """Publish or hide, with a written reason; audit-logged."""
    service.moderate(db, staff.actor(request), review_id, action=body.action, reason=body.reason)
    return _one(db, review_id, lang)
