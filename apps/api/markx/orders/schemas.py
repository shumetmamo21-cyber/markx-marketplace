from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel, PhoneText, ShortText
from markx.offers.schemas import RankedOfferOut
from markx.orders.models import MAX_QUANTITY_PER_LINE

DeliveryMethod = Literal["seller_rider", "partner_courier", "shop_collection"]
PaymentMethod = Literal["cash", "telebirr", "bank_transfer", "ethqr"]
StoreSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class CartItemIn(ApiModel):
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY_PER_LINE)]


class ReorderLineOut(ApiModel):
    """An item of the order now in the cart, at today's price."""

    offer_id: uuid.UUID
    title: str
    variant_label: str
    quantity: int
    unit_price_santim: int
    # What the order paid for one; shown beside today's price, never charged.
    paid_unit_price_santim: int


class ReorderMissingOut(ApiModel):
    """An item of the order that could not go back in the cart."""

    offer_id: uuid.UUID
    title: str
    variant_label: str
    # The product's page, for another shop's offer; null when it is not shown.
    product_slug: str | None
    reason: Literal["offer_unavailable", "cart_full"]


class ReorderOut(ApiModel):
    """Order again (C-19): what went back in the cart, and what did not."""

    order_id: uuid.UUID
    order_code: str
    added: list[ReorderLineOut]
    missing: list[ReorderMissingOut]


class CustomerOrderOut(ApiModel):
    seller_order_id: uuid.UUID
    order_code: str
    status: str
    placed_at: datetime
    total_santim: int


class SellerCustomerOut(ApiModel):
    """One person the shop has served (S-11): only what its own order pages
    already show it, from the orders whose buyer details it can see now."""

    phone: str
    name: str
    # The delivery area of their latest order.
    area_name: str
    orders: int
    completed_orders: int
    first_order_at: datetime
    last_order_at: datetime
    # Their latest orders with this shop, newest first.
    recent_orders: list[CustomerOrderOut]


class CartItemOut(ApiModel):
    offer_id: uuid.UUID
    product_slug: str
    product_name: str
    variant_attributes: dict[str, Any]
    # "Black · 128 GB", as the product page shows it.
    variant_label: str
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


class TrackingEventOut(ApiModel):
    status: str
    note: str | None
    source: str
    occurred_at: datetime


class ShipmentOut(ApiModel):
    """The delivery of one seller order (J.10). The handover code is never here."""

    status: str
    method: str
    promised_hours: int | None
    rider_name: str | None
    # Shown to the buyer only once the parcel is on its way.
    rider_phone: str | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    failure_reason: str | None
    events: list[TrackingEventOut]


class ProblemMessageOut(ApiModel):
    author_type: str
    body: str
    created_at: datetime


class ProblemOut(ApiModel):
    """A problem the buyer reported on a delivered part (D.17)."""

    problem_type: str
    description: str
    status: str
    opened_at: datetime
    decision_due_at: datetime
    decision: str | None
    decision_reason: str | None
    resolved_at: datetime | None
    messages: list[ProblemMessageOut]


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
    ready_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None
    problem_window_ends_at: datetime | None
    paid_method: str | None
    paid_at: datetime | None
    can_cancel: bool
    can_confirm_received: bool
    # "Report a problem" is open: delivered, and inside the problem window.
    can_report_problem: bool
    problem: ProblemOut | None
    # The one-time code (C-15), shown only while a handover is awaited and
    # only to the signed-in buyer. Give it only after seeing the goods.
    handover_code: str | None
    shipment: ShipmentOut
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
    # The secure link to this page without sign-in (D.14); only on the buyer's own view.
    tracking_path: str | None
    payment_mode: str
    currency: str
    items_total_santim: int
    delivery_total_santim: int
    grand_total_santim: int
    address: dict[str, Any]
    seller_orders: list[BuyerSellerOrderOut]


class AlternativeOfferOut(RankedOfferOut):
    product_slug: str


class AlternativeOut(ApiModel):
    """The next-best offer for one line of a part that fell through (C-26)."""

    order_item_id: uuid.UUID
    quantity: int
    offer: AlternativeOfferOut


LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class ProblemIn(ApiModel):
    problem_type: Literal[
        "not_received", "wrong_item", "not_as_described", "damaged", "suspected_fake", "other"
    ]
    description: LongText


class ProblemMessageIn(ApiModel):
    body: LongText


class ResolveProblemIn(ApiModel):
    decision: Literal["no_action", "seller_refunded"]
    reason: Reason
    # With a refund: did the goods go back to the shop? Then the stock returns to sale.
    goods_returned: bool = False


class OpenProblemOut(ApiModel):
    seller_order_id: uuid.UUID
    order_code: str
    store_slug: str
    problem_type: str
    status: str
    opened_at: datetime
    decision_due_at: datetime


class CancelIn(ApiModel):
    reason: Reason | None = None


class DeclineIn(ApiModel):
    reason: Reason


class DispatchIn(ApiModel):
    rider_name: ShortText | None = None
    rider_phone: PhoneText | None = None


class HandoverIn(ApiModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]


class PaymentRecordIn(ApiModel):
    method: PaymentMethod


class ReasonIn(ApiModel):
    reason: Reason


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
    # The fee actually charged, once the order completed (D.19).
    fee_santim: int | None
    delivery_method: str
    promised_hours: int | None
    payment_method: str | None
    payment_reference: str
    ready_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None
    problem_window_ends_at: datetime | None
    paid_method: str | None
    paid_at: datetime | None
    handover_attempts_left: int
    problem: ProblemOut | None
    shipment: ShipmentOut
    delivery_area: DeliveryAreaOut
    # Null until this seller confirms (blueprint C.5).
    buyer: BuyerContactOut | None
    items: list[OrderItemOut]
    events: list[StatusEventOut]
