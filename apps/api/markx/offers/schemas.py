from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel
from markx.offers.service import MAX_PRICE_SANTIM, MAX_STOCK

PriceSantim = Annotated[int, Field(gt=0, le=MAX_PRICE_SANTIM)]
Quantity = Annotated[int, Field(ge=0, le=MAX_STOCK)]
WarrantyMonths = Annotated[int, Field(ge=0, le=120)]
WarrantyNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
ConditionText = Literal["new", "open_box", "refurbished", "used"]
Threshold = Annotated[int, Field(ge=0, le=10_000)]


class OfferIn(ApiModel):
    variant_id: uuid.UUID
    condition: ConditionText = "new"
    price_santim: PriceSantim
    quantity: Quantity
    warranty_months: WarrantyMonths = 0
    warranty_note: WarrantyNote | None = None
    delivers_by_seller_rider: bool = False
    delivers_by_partner_courier: bool = False
    offers_shop_collection: bool = True
    low_stock_threshold: Threshold = 2


class OfferUpdateIn(ApiModel):
    price_santim: PriceSantim | None = None
    warranty_months: WarrantyMonths | None = None
    warranty_note: WarrantyNote | None = None
    delivers_by_seller_rider: bool | None = None
    delivers_by_partner_courier: bool | None = None
    offers_shop_collection: bool | None = None


class StockIn(ApiModel):
    on_hand: Quantity
    low_stock_threshold: Threshold | None = None


class CheckInIn(ApiModel):
    # Omit to confirm every live offer.
    offer_ids: Annotated[list[uuid.UUID], Field(max_length=500)] | None = None


class CheckInOut(ApiModel):
    confirmed: int


class SellerOfferOut(ApiModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID
    product_slug: str
    product_name: str
    variant_attributes: dict[str, Any]
    variant_label: str
    model_code: str | None
    condition: str
    price_santim: int
    currency: str
    warranty_months: int
    warranty_note: str | None
    delivers_by_seller_rider: bool
    delivers_by_partner_courier: bool
    offers_shop_collection: bool
    status: str
    on_hand: int
    reserved: int
    available: int
    low_stock_threshold: int
    is_low_stock: bool
    needs_confirmation: bool
    price_confirmed_at: datetime
    stock_confirmed_at: datetime
    created_at: datetime


class PriceChangeOut(ApiModel):
    old_price_santim: int | None
    new_price_santim: int
    changed_at: datetime


class MovementOut(ApiModel):
    delta_on_hand: int
    delta_reserved: int
    on_hand_after: int
    reserved_after: int
    reason: str
    created_at: datetime


class SellerOfferDetailOut(SellerOfferOut):
    price_history: list[PriceChangeOut]
    movements: list[MovementOut]


class DashboardOut(ApiModel):
    active_offers: int
    paused_offers: int
    stale_offers: int
    low_stock_offers: int
    prices_to_confirm: int


class PublicOfferOut(ApiModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    condition: str
    price_santim: int
    currency: str
    warranty_months: int
    warranty_note: str | None
    in_stock: bool
    # Capped: buyers learn "5 or more", not the seller's exact count.
    available: int
    store_slug: str
    store_name: str
    seller_verification_level: int
    delivers_by_seller_rider: bool
    delivers_by_partner_courier: bool
    offers_shop_collection: bool
    price_confirmed_at: datetime


class RankedOfferOut(PublicOfferOut):
    delivery_fee_santim: int | None
    delivery_method: str | None
    delivery_promised_hours: int | None
    total_santim: int
    price_is_fresh: bool
    is_default: bool
    default_reason: str | None


class ProductOffersOut(ApiModel):
    product_slug: str
    zone_code: str | None
    offer_count: int
    lowest_price_santim: int | None
    offers: list[RankedOfferOut]


class PriceListItemOut(PublicOfferOut):
    product_slug: str
    product_name: str
    variant_attributes: dict[str, Any]
    variant_label: str


class ModerationIn(ApiModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class OfferStatusOut(ApiModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    status: str
