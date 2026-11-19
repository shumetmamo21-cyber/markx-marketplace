from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PublicImageOut(BaseModel):
    id: uuid.UUID
    width: int
    height: int
    thumb_url: str | None
    main_url: str | None


class RealPhotoOut(PublicImageOut):
    store_slug: str


class ProductImagesOut(BaseModel):
    """A product page's pictures: catalogue pictures first, then each store's
    real photos, tagged with the store (D.5)."""

    product_slug: str
    catalogue: list[PublicImageOut]
    real_photos: list[RealPhotoOut]


class ImageOut(BaseModel):
    """A picture with its pipeline state, for staff and for the seller who
    uploaded it. `thumb_url` and `main_url` are set once it is `ready`."""

    id: uuid.UUID
    product_id: uuid.UUID
    kind: str
    seller_id: uuid.UUID | None
    status: str
    position: int
    width: int
    height: int
    thumb_bytes: int | None
    main_bytes: int | None
    failure_reason: str | None
    removed_reason: str | None
    created_at: datetime
    thumb_url: str | None
    main_url: str | None


class RemoveImageIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProblemPhotoOut(BaseModel):
    """An evidence photo, with a link that works for five minutes and only
    for the person it was issued to."""

    id: uuid.UUID
    author_type: str
    width: int
    height: int
    created_at: datetime
    url: str
    url_expires_at: datetime
