from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    product_rating: int = Field(ge=1, le=5)
    seller_rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=2000)


class ReviewReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class ModerateReviewIn(BaseModel):
    action: Literal["publish", "hide"]
    reason: str = Field(min_length=3, max_length=500)


class RatingSummaryOut(BaseModel):
    """`average` has two decimals, or is null with no review; `stars` counts
    the reviews that gave each number of stars, "1" to "5"."""

    count: int
    average: float | None
    stars: dict[str, int]


class PublicReviewOut(BaseModel):
    """A published review as anyone sees it: from a verified buyer, never
    with their name or phone number."""

    id: uuid.UUID
    product_rating: int
    seller_rating: int
    body: str
    variant_label: str
    store_slug: str
    created_at: datetime
    seller_reply: str | None
    seller_replied_at: datetime | None


class ProductReviewsOut(BaseModel):
    product_slug: str
    summary: RatingSummaryOut
    reviews: list[PublicReviewOut]


class StoreReviewsOut(BaseModel):
    store_slug: str
    summary: RatingSummaryOut
    reviews: list[PublicReviewOut]


class MyReviewOut(BaseModel):
    """A review with its state, for its buyer, its seller and staff. The
    seller never sees the order code."""

    id: uuid.UUID
    order_id: uuid.UUID | None
    order_code: str | None
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    title: str
    variant_label: str
    store_slug: str
    product_rating: int
    seller_rating: int
    body: str
    status: str
    held_reason: str | None
    moderation_reason: str | None
    seller_reply: str | None
    seller_replied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewableItemOut(BaseModel):
    order_id: uuid.UUID
    order_code: str
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    title: str
    variant_label: str
    store_slug: str
    review_until: datetime
