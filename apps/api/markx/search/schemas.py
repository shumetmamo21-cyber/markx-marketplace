from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints

from markx.core.schemas import ApiModel, PhoneText

Words = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ProductCardOut(ApiModel):
    """The product card used everywhere (blueprint D.9)."""

    product_id: uuid.UUID
    slug: str
    name: str
    brand: str | None
    category_path: str
    # The lowest price in stock ("from ETB"); null when nothing is in stock.
    min_price_santim: int | None
    offer_count: int
    seller_count: int
    best_seller_level: int
    in_stock: bool
    price_is_fresh: bool


class SearchOut(ApiModel):
    query: str
    total: int
    results: list[ProductCardOut]
    # Offered when nothing matched (D.8): the nearest products by spelling.
    did_you_mean: list[ProductCardOut]


class SuggestionOut(ApiModel):
    slug: str
    name: str


class ProductRequestIn(ApiModel):
    query: Words
    note: Note | None = None
    contact_phone: PhoneText | None = None


class ProductRequestOut(ApiModel):
    id: uuid.UUID
    status: str


class SynonymIn(ApiModel):
    term: Words
    expansion: Words


class SynonymOut(ApiModel):
    id: uuid.UUID
    term: str
    expansion: str
    term_normalized: str
    expansion_normalized: str
    created_at: datetime


class ZeroResultOut(ApiModel):
    normalized: str
    searches: int
    last_searched_at: datetime
    example: str
