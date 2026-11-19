"""Picture routes (blueprint F.6, D.5, S-06, C-16, AD-03; D-062).

`/catalog/products/{slug}/images`                          a product page's pictures
`/admin/catalog/products/{id}/images`                      catalogue pictures (staff)
`/admin/catalog/images/{id}/remove`                        take a picture down (staff)
`/seller/{seller_id}/products/{id}/photos`                 a store's real photos
`/me/orders/.../problem/photos`, `/seller/.../problem/photos`,
`/admin/orders/seller-orders/{id}/problem/photos`          evidence for a problem
`/problem-photos/{id}/content`                             one evidence photo, by signed link
`/media/{key}`                                             public files, laptop and tests only
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile

from markx.accounts.deps import (
    CurrentPrincipal,
    Principal,
    SellerContext,
    require_seller,
    require_staff,
)
from markx.accounts.permissions import SellerCapability, StaffCapability
from markx.core import ratelimit, settings_store
from markx.core.errors import NotFound
from markx.core.http import Db
from markx.core.storage import StoredFileMissing, get_public_storage
from markx.images import selectors, service
from markx.images.schemas import ImageOut, ProblemPhotoOut, ProductImagesOut, RemoveImageIn
from markx.orders.router import Buyer

public_router = APIRouter(tags=["catalog"])
admin_router = APIRouter(prefix="/admin", tags=["admin: pictures"])
seller_router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: pictures"])
buyer_router = APIRouter(tags=["orders"])
media_router = APIRouter(tags=["dev"])

Curator = Annotated[Principal, Depends(require_staff(StaffCapability.CURATE_CATALOGUE))]
ListingModerator = Annotated[Principal, Depends(require_staff(StaffCapability.MODERATE_LISTINGS))]
CaseHandler = Annotated[Principal, Depends(require_staff(StaffCapability.HANDLE_CASES))]
OfferManager = Annotated[SellerContext, Depends(require_seller(SellerCapability.MANAGE_OFFERS))]
OrderHandler = Annotated[SellerContext, Depends(require_seller(SellerCapability.HANDLE_ORDERS))]
Slug = Annotated[str, Path(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=120)]
UPLOADS_PER_HOUR = 60


def _read(db: Db, file: UploadFile) -> bytes:
    # One byte past the limit is enough to know the file is too large,
    # without holding an arbitrarily large upload in memory.
    return file.file.read(settings_store.get_int(db, "images.max_upload_bytes") + 1)


# -- public ------------------------------------------------------------------------------


@public_router.get("/catalog/products/{slug}/images", response_model=ProductImagesOut)
def product_images(slug: Slug, response: Response, db: Db) -> ProductImagesOut:
    """Ready pictures only. Catalogue pictures in their order, then real
    photos from stores that may publish, each with its store."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return ProductImagesOut.model_validate(selectors.public_images(db, slug))


# -- staff ------------------------------------------------------------------------------


@admin_router.get("/catalog/products/{product_id}/images", response_model=list[ImageOut])
def staff_product_images(product_id: uuid.UUID, staff: ListingModerator, db: Db) -> list[ImageOut]:
    """Every picture of a product in every state, for moderation (AD-03)."""
    return [ImageOut.model_validate(row) for row in selectors.staff_images(db, product_id)]


@admin_router.post(
    "/catalog/products/{product_id}/images", response_model=ImageOut, status_code=202
)
def add_catalogue_image(
    product_id: uuid.UUID,
    staff: Curator,
    request: Request,
    db: Db,
    file: Annotated[UploadFile, File()],
    position: Annotated[int, Form(ge=0, le=100)] = 0,
) -> ImageOut:
    """Accepted for processing: the picture is `processing` until the worker
    has rendered it, then `ready`."""
    ratelimit.hit(f"image-upload:staff:{staff.user.id}", UPLOADS_PER_HOUR * 5, timedelta(hours=1))
    image = service.add_catalogue_image(
        db, staff.actor(request), product_id, _read(db, file), position=position
    )
    return ImageOut.model_validate(selectors.one(image))


@admin_router.post("/catalog/images/{image_id}/remove", response_model=ImageOut)
def remove_image(
    image_id: uuid.UUID, body: RemoveImageIn, staff: ListingModerator, request: Request, db: Db
) -> ImageOut:
    """Take a catalogue picture or a seller's photo down, with a reason (AD-03)."""
    image = service.remove_image(db, staff.actor(request), image_id, reason=body.reason)
    return ImageOut.model_validate(selectors.one(image))


@admin_router.get(
    "/orders/seller-orders/{seller_order_id}/problem/photos", response_model=list[ProblemPhotoOut]
)
def staff_problem_photos(
    seller_order_id: uuid.UUID, staff: CaseHandler, request: Request, db: Db
) -> list[ProblemPhotoOut]:
    """The evidence both sides added, each with a link for this member of staff."""
    return [
        ProblemPhotoOut.model_validate(row)
        for row in service.staff_problem_photos(db, staff.actor(request), seller_order_id)
    ]


# -- sellers ----------------------------------------------------------------------------


@seller_router.get("/products/{product_id}/photos", response_model=list[ImageOut])
def seller_photos(product_id: uuid.UUID, context: OfferManager, db: Db) -> list[ImageOut]:
    """This store's own photos of one product, in every state."""
    return [
        ImageOut.model_validate(row)
        for row in selectors.seller_images(db, context.seller.id, product_id)
    ]


@seller_router.post("/products/{product_id}/photos", response_model=ImageOut, status_code=202)
def add_seller_photo(
    product_id: uuid.UUID,
    context: OfferManager,
    request: Request,
    db: Db,
    file: Annotated[UploadFile, File()],
) -> ImageOut:
    """A real photo of a product this store has an offer for (D.5, S-06)."""
    ratelimit.hit(f"image-upload:seller:{context.seller.id}", UPLOADS_PER_HOUR, timedelta(hours=1))
    image = service.add_real_photo(
        db, context.principal.actor(request), context.seller, context.member, product_id,
        _read(db, file),
    )  # fmt: skip
    return ImageOut.model_validate(selectors.one(image))


@seller_router.post("/photos/{image_id}/withdraw", response_model=ImageOut)
def withdraw_seller_photo(
    image_id: uuid.UUID, context: OfferManager, request: Request, db: Db
) -> ImageOut:
    image = service.withdraw_real_photo(
        db, context.principal.actor(request), context.seller, context.member, image_id
    )
    return ImageOut.model_validate(selectors.one(image))


@seller_router.get("/orders/{seller_order_id}/problem/photos", response_model=list[ProblemPhotoOut])
def seller_problem_photos(
    seller_order_id: uuid.UUID, context: OrderHandler, db: Db
) -> list[ProblemPhotoOut]:
    return [
        ProblemPhotoOut.model_validate(row)
        for row in service.seller_problem_photos(
            db, context.seller, context.member, seller_order_id
        )
    ]


@seller_router.post(
    "/orders/{seller_order_id}/problem/photos", response_model=ProblemPhotoOut, status_code=201
)
def add_seller_problem_photo(
    seller_order_id: uuid.UUID,
    context: OrderHandler,
    request: Request,
    db: Db,
    file: Annotated[UploadFile, File()],
) -> ProblemPhotoOut:
    """The seller's evidence on a reported problem, while it is open."""
    ratelimit.hit(f"image-upload:seller:{context.seller.id}", UPLOADS_PER_HOUR, timedelta(hours=1))
    photo = service.seller_add_problem_photo(
        db, context.principal.actor(request), context.seller, context.member, seller_order_id,
        _read(db, file),
    )  # fmt: skip
    (row,) = [
        r
        for r in service.seller_problem_photos(db, context.seller, context.member, seller_order_id)
        if r["id"] == photo.id
    ]
    return ProblemPhotoOut.model_validate(row)


# -- buyers -----------------------------------------------------------------------------


@buyer_router.get(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/photos",
    response_model=list[ProblemPhotoOut],
)
def my_problem_photos(
    order_id: uuid.UUID, seller_order_id: uuid.UUID, buyer: Buyer, db: Db
) -> list[ProblemPhotoOut]:
    return [
        ProblemPhotoOut.model_validate(row)
        for row in service.buyer_problem_photos(db, buyer.user, order_id, seller_order_id)
    ]


@buyer_router.post(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/photos",
    response_model=ProblemPhotoOut,
    status_code=201,
)
def add_my_problem_photo(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    buyer: Buyer,
    request: Request,
    db: Db,
    file: Annotated[UploadFile, File()],
) -> ProblemPhotoOut:
    """The buyer's photo evidence on their own open problem (C-16)."""
    ratelimit.hit(f"image-upload:buyer:{buyer.user.id}", 20, timedelta(hours=1))
    photo = service.buyer_add_problem_photo(
        db, buyer.actor(request), buyer.user, order_id, seller_order_id, _read(db, file)
    )
    (row,) = [
        r
        for r in service.buyer_problem_photos(db, buyer.user, order_id, seller_order_id)
        if r["id"] == photo.id
    ]
    return ProblemPhotoOut.model_validate(row)


@buyer_router.get("/problem-photos/{photo_id}/content")
def read_problem_photo(
    photo_id: uuid.UUID,
    principal: CurrentPrincipal,
    request: Request,
    db: Db,
    expires: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=20, max_length=64)],
) -> Response:
    """The photo behind a signed link. The link alone is not enough: the same
    person it was issued to must be signed in, and still be allowed."""
    data = service.open_problem_photo(
        db, principal.actor(request), photo_id, expires=expires, signature=signature,
        staff_role=principal.staff.role if principal.is_staff_session and principal.staff else None,
    )  # fmt: skip
    return Response(
        content=data,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# -- public files on a laptop -------------------------------------------------------------


@media_router.get("/media/{key:path}")
def media(key: str) -> Response:
    """Rendered product pictures, served by the API on a laptop and in tests
    only. A real server serves them from the CDN's cookieless domain (F.6)."""
    if not key.endswith(".webp"):
        raise NotFound("media_not_found", "That file was not found.")
    try:
        data = get_public_storage().get(key)
    except (StoredFileMissing, ValueError) as exc:
        raise NotFound("media_not_found", "That file was not found.") from exc
    return Response(
        content=data,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
