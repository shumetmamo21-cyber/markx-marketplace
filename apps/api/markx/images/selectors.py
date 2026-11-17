"""Reading product pictures (blueprint D.5, F.6; D-062)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from markx.catalog.models import ImageKind, ImageStatus, Product, ProductImage, ProductStatus
from markx.catalog.selectors import resolve_merged
from markx.core import settings_store
from markx.core.errors import NotFound
from markx.core.storage import public_url
from markx.images.service import main_key, thumb_key
from markx.sellers.models import Seller, SellerStatus, Store


def _urls(image: ProductImage) -> dict[str, str | None]:
    if image.status != ImageStatus.READY:
        return {"thumb_url": None, "main_url": None}
    return {"thumb_url": public_url(thumb_key(image)), "main_url": public_url(main_key(image))}


def public_images(db: Session, slug: str) -> dict[str, Any]:
    """The pictures a buyer sees on a product page: ready catalogue pictures
    in their order, then ready real photos of stores that are trading and
    may publish (the same rule as offers). A merged product shows its
    survivor's pictures; anything not approved is "not found"."""
    not_found = NotFound("product_not_found", "That product was not found.")
    product = db.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise not_found
    product = resolve_merged(db, product)
    if product.status != ProductStatus.APPROVED:
        raise not_found
    catalogue = list(
        db.scalars(
            select(ProductImage)
            .where(
                ProductImage.product_id == product.id,
                ProductImage.kind == ImageKind.CATALOGUE,
                ProductImage.status == ImageStatus.READY,
            )
            .order_by(ProductImage.position, ProductImage.created_at, ProductImage.id)
        )
    )
    min_level = settings_store.get_int(db, "sellers.min_level_to_publish")
    real = db.execute(
        select(ProductImage, Store.slug)
        .join(Seller, Seller.id == ProductImage.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .where(
            ProductImage.product_id == product.id,
            ProductImage.kind == ImageKind.SELLER_REAL_PHOTO,
            ProductImage.status == ImageStatus.READY,
            Seller.status == SellerStatus.ACTIVE,
            Seller.verification_level >= min_level,
        )
        .order_by(ProductImage.created_at, ProductImage.id)
    ).all()
    return {
        "product_slug": product.slug,
        "catalogue": [
            {"id": i.id, "width": i.width, "height": i.height, **_urls(i)} for i in catalogue
        ],
        "real_photos": [
            {"id": i.id, "store_slug": store, "width": i.width, "height": i.height, **_urls(i)}
            for i, store in real
        ],
    }


def first_thumbnails(db: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each product's first ready catalogue picture as a thumbnail link, for
    the product card (D.9). Products without one are left out."""
    if not product_ids:
        return {}
    first = (
        select(ProductImage)
        .where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.kind == ImageKind.CATALOGUE,
            ProductImage.status == ImageStatus.READY,
        )
        .order_by(
            ProductImage.product_id,
            ProductImage.position,
            ProductImage.created_at,
            ProductImage.id,
        )
        .ext(distinct_on(ProductImage.product_id))
    )
    return {image.product_id: public_url(thumb_key(image)) for image in db.scalars(first)}


def _row(image: ProductImage) -> dict[str, Any]:
    return {
        "id": image.id,
        "product_id": image.product_id,
        "kind": image.kind,
        "seller_id": image.seller_id,
        "status": image.status,
        "position": image.position,
        "width": image.width,
        "height": image.height,
        "thumb_bytes": image.thumb_bytes,
        "main_bytes": image.main_bytes,
        "failure_reason": image.failure_reason,
        "removed_reason": image.removed_reason,
        "created_at": image.created_at,
        **_urls(image),
    }


def staff_images(db: Session, product_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every picture of a product, in every state, for moderation (AD-03)."""
    if db.get(Product, product_id) is None:
        raise NotFound("product_not_found", "That product was not found.")
    return [
        _row(image)
        for image in db.scalars(
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.kind, ProductImage.position, ProductImage.created_at)
        )
    ]


def seller_images(db: Session, seller_id: uuid.UUID, product_id: uuid.UUID) -> list[dict[str, Any]]:
    """A seller's own photos of one product, in every state. Never another
    seller's photos, and never the catalogue's."""
    return [
        _row(image)
        for image in db.scalars(
            select(ProductImage)
            .where(ProductImage.product_id == product_id, ProductImage.seller_id == seller_id)
            .order_by(ProductImage.created_at, ProductImage.id)
        )
    ]


def one(image: ProductImage) -> dict[str, Any]:
    return _row(image)
