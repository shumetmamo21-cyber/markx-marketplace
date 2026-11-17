from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel
from markx.orders.models import MAX_QUANTITY_PER_LINE

DeliveryMethod = Literal["seller_rider", "partner_courier", "shop_collection"]
PaymentMethod = Literal["cash", "telebirr", "bank_transfer", "ethqr"]
StoreSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class CartItemIn(ApiModel):
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY_PER_LINE)]


class CartItemOut(ApiModel):
    offer_id: uuid.UUID
    product_slug: str
    product_name: str
    variant_attributes: dict[str, Any]
    condition: str
    warranty_months: int
    quantity: int
    price_santim: int
    # What the buyer saw when the line was added or last accepted.
    price_seen_santim: int
    price_changed: bool
    line_total_santim: int
    available: int
    # Why the line cannot be ordered right now, or null.
    problem: str | None


class DeliveryOptionOut(ApiModel):
    method: str
    fee_santim: int
    promised_hours: int | None


class CartGroupOut(ApiModel):
    store_slug: str
    store_name: str
    seller_verification_level: int
    items_total_santim: int
    # Null until a delivery zone is given.
    delivery_options: list[DeliveryOptionOut] | None
    items: list[CartItemOut]


class CartOut(ApiModel):
    line_count: int
    items_total_santim: int
    currency: str
    has_price_changes: bool
    can_check_out: bool
    zone_code: str | None
    groups: list[CartGroupOut]


class DeliveryChoiceIn(ApiModel):
    store_slug: StoreSlug
    method: DeliveryMethod


class QuoteIn(ApiModel):
    address_id: uuid.UUID
    deliveries: Annotated[list[DeliveryChoiceIn], Field(max_length=30)]


class CheckoutIn(QuoteIn):
    """There is no price in this request. The browser says what and where;
    the server decides what it costs."""

    payment_method: PaymentMethod
    # The grand total the buyer saw on the review step. Compared, never used.
    expected_total_santim: Annotated[int, Field(gt=0)]
    # Made up by the client once per submission; a repeat returns the same order.
    idempotency_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,64}$")]


class QuoteGroupOut(ApiModel):
    store_slug: str
    store_name: str
    seller_legal_name: str
    shop_address: str
    return_policy: str
    delivery_method: str
    delivery_fee_santim: int
    promised_hours: int | None
    items_total_santim: int
    total_santim: int


class QuoteOut(ApiModel):
    items_total_santim: int
    delivery_total_santim: int
    grand_total_santim: int
    currency: str
    zone_code: str
    price_changes: list[dict[str, Any]]
    groups: list[QuoteGroupOut]


class OrderItemOut(ApiModel):
    id: uuid.UUID
    offer_id: uuid.UUID
    title: str
    variant_label: str
    condition: str
    warranty_months: int
    unit_price_santim: int
    quantity: int
    line_total_santim: int


class StatusEventOut(ApiModel):
    from_status: str | None
    to_status: str
    actor_type: str
    reason: str | None
    occurred_at: datetime


class SellerContactOut(ApiModel):
    phone: str
    shop_address: str


class BuyerSellerOrderOut(ApiModel):
    id: uuid.UUID
    store_slug: str
    store_name: str
    status: str
    items_total_santim: int
    delivery_fee_santim: int
    total_santim: int
    response_deadline: datetime
    confirmed_at: datetime | None
    closed_reason: str | None
    delivery_method: str
    promised_hours: int | None
    payment_method: str | None
    payment_reference: str
    can_cancel: bool
    can_confirm_receipt: bool
    delivery_status: str
    # The one-time handover code (C-15): shown only while the goods are on
    # their way, and only to the buyer. Share it at handover and never before.
    handover_code: str | None
    rider_name: str | None
    rider_phone: str | None
    delivered_at: datetime | None
    problem_window_ends_at: datetime | None
    completed_at: datetime | None
    paid_method: str | None
    paid_at: datetime | None
    # Null until the seller confirms (blueprint C.5).
    seller_contact: SellerContactOut | None
    items: list[OrderItemOut]
    events: list[StatusEventOut]


class OrderOut(ApiModel):
    id: uuid.UUID
    code: str
    # Derived from the seller orders on every read; never stored.
    status: str
    created_at: datetime
    payment_mode: str
    currency: str
    items_total_santim: int
    delivery_total_santim: int
    grand_total_santim: int
    address: dict[str, Any]
    seller_orders: list[BuyerSellerOrderOut]


class CancelIn(ApiModel):
    reason: Reason | None = None


class DeclineIn(ApiModel):
    reason: Reason


class DispatchIn(ApiModel):
    rider_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)] | None = None  # fmt: skip
    rider_phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=9, max_length=24)] | None = None  # fmt: skip


class HandoverIn(ApiModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]


class PaymentIn(ApiModel):
    method: PaymentMethod


class DeliveryAreaOut(ApiModel):
    zone_code: str | None
    zone_name_am: str | None
    zone_name_en: str | None
    area_name_am: str | None
    area_name_en: str | None


class BuyerContactOut(ApiModel):
    recipient_name: str | None
    phone: str | None
    phone2: str | None
    landmark: str | None
    latitude: float | None
    longitude: float | None
    driver_notes: str | None


class SellerOrderOut(ApiModel):
    """One seller's part of an order. Nothing here belongs to another seller."""

    id: uuid.UUID
    order_code: str
    status: str
    placed_at: datetime
    response_deadline: datetime
    confirmed_at: datetime | None
    closed_reason: str | None
    items_total_santim: int
    delivery_fee_santim: int
    total_santim: int
    estimated_fee_santim: int
    delivery_method: str
    promised_hours: int | None
    payment_method: str | None
    payment_reference: str
    delivery_area: DeliveryAreaOut
    delivery_status: str
    handover_attempts: int
    rider_name: str | None
    rider_phone: str | None
    delivered_at: datetime | None
    completed_at: datetime | None
    paid_method: str | None
    paid_at: datetime | None
    # The fee actually charged, once the order completed (D.19).
    fee_charged_santim: int | None
    # Null until this seller confirms (blueprint C.5).
    buyer: BuyerContactOut | None
    items: list[OrderItemOut]
    events: list[StatusEventOut]
