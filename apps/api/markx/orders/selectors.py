"""Read queries for carts and orders. Nothing here changes data.

Who may see what (blueprint C.5, G.11):

* A buyer's order is found only together with the buyer's own id.
* A seller order is found only together with the seller's id, and shows only
  that seller's lines: never the other sellers in the same checkout.
* Buyer and seller see each other's phone number only after the seller
  confirms, and not once the order ended undelivered.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.catalog.models import ProductTranslation
from markx.core.errors import NotFound
from markx.core.money import Money
from markx.delivery.models import DeliveryZone, Shipment
from markx.delivery.selectors import active_rates_for_zone
from markx.orders import service
from markx.orders.models import Cart, Order, OrderItem, OrderStatusEvent, SellerOrder
from markx.orders.status import contact_visible, derive_order_status
from markx.payments.models import PaymentIntent
from markx.sellers.models import Seller, Store

# As on the product page: in stock or not, never a competitor-readable count.
PUBLIC_STOCK_CAP = 5
_BUYER_MAY_CANCEL = ("placed", "confirmed")


def _names(db: Session, product_ids: set[uuid.UUID], language: str) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, dict[str, str]] = {}
    if product_ids:
        for t in db.scalars(
            select(ProductTranslation).where(ProductTranslation.product_id.in_(product_ids))
        ):
            names.setdefault(t.product_id, {})[t.language] = t.name
    other = "en" if language == "am" else "am"
    return {pid: by.get(language) or by.get(other) or "" for pid, by in names.items()}


# -- the cart ------------------------------------------------------------------------


def cart_view(
    db: Session, cart: Cart | None, language: str, *, zone_code: str | None
) -> dict[str, Any]:
    """The cart, re-checked against live prices and stock (blueprint D.10).

    Each line says what changed since the buyer last looked: a new price, or a
    reason it cannot be ordered. With a zone, each store's group lists the
    delivery methods and fees to that zone.
    """
    zone = None
    if zone_code is not None:
        zone = db.scalar(
            select(DeliveryZone).where(DeliveryZone.code == zone_code, DeliveryZone.is_active)
        )
        if zone is None:
            raise NotFound("zone_not_found", "That delivery zone was not found.")
    lines = service.load_lines(db, cart.id) if cart is not None else []
    names = _names(db, {line.product.id for line in lines}, language)
    min_level = service._min_level(db)
    rates = active_rates_for_zone(db, zone.id) if zone is not None else {}

    groups, items_total, has_changes, orderable = [], Money.zero(), False, bool(lines)
    for group in service.group_by_seller(lines):
        group_total, items = Money.zero(), []
        for line in group:
            problem = service.line_problem(line, min_level)
            if problem is None and line.available == 0:
                problem = "out_of_stock"
            elif problem is None and line.available < line.item.quantity:
                problem = "not_enough_stock"
            price_changed = line.item.price_seen_santim != line.offer.price_santim
            has_changes = has_changes or price_changed
            orderable = orderable and problem is None
            group_total += line.total
            items.append(
                {
                    "offer_id": line.offer.id,
                    "product_slug": line.product.slug,
                    "product_name": names.get(line.product.id, ""),
                    "variant_attributes": line.variant.attribute_values,
                    "condition": line.offer.condition,
                    "warranty_months": line.offer.warranty_months,
                    "quantity": line.item.quantity,
                    "price_santim": line.offer.price_santim,
                    "price_seen_santim": line.item.price_seen_santim,
                    "price_changed": price_changed,
                    "line_total_santim": line.total.amount,
                    "available": min(line.available, PUBLIC_STOCK_CAP),
                    "problem": problem,
                }
            )
        items_total += group_total
        store, seller = group[0].store, group[0].seller
        groups.append(
            {
                "store_slug": store.slug,
                "store_name": store.name,
                "seller_verification_level": seller.verification_level,
                "items_total_santim": group_total.amount,
                "delivery_options": [
                    {
                        "method": option.method.value,
                        "fee_santim": option.fee.amount,
                        "promised_hours": option.promised_hours,
                    }
                    for option in service.delivery_options(group, rates)
                ]
                if zone is not None
                else None,
                "items": items,
            }
        )
    return {
        "line_count": len(lines),
        "items_total_santim": items_total.amount,
        "currency": "ETB",
        "has_price_changes": has_changes,
        "can_check_out": orderable and not has_changes,
        "zone_code": zone.code if zone is not None else None,
        "groups": groups,
    }


def quote_out(quote: service.Quote) -> dict[str, Any]:
    return {
        "items_total_santim": quote.items_total.amount,
        "delivery_total_santim": quote.delivery_total.amount,
        "grand_total_santim": quote.grand_total.amount,
        "currency": "ETB",
        "zone_code": quote.zone.code,
        "price_changes": quote.price_changes,
        "groups": [
            {
                "store_slug": group.store.slug,
                "store_name": group.store.name,
                # The review step shows who the buyer is buying from (C-27).
                "seller_legal_name": group.seller.legal_name,
                "shop_address": group.seller.shop_address,
                "return_policy": group.store.return_policy,
                "delivery_method": group.delivery.method.value,
                "delivery_fee_santim": group.delivery.fee.amount,
                "promised_hours": group.delivery.promised_hours,
                "items_total_santim": group.items_total.amount,
                "total_santim": group.total.amount,
            }
            for group in quote.groups
        ],
    }


# -- orders: shared pieces -------------------------------------------------------------


def _items(db: Session, seller_order_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[OrderItem]]:
    by_order: dict[uuid.UUID, list[OrderItem]] = {}
    if seller_order_ids:
        for item in db.scalars(
            select(OrderItem)
            .where(OrderItem.seller_order_id.in_(seller_order_ids))
            .order_by(OrderItem.id)
        ):
            by_order.setdefault(item.seller_order_id, []).append(item)
    return by_order


def _events(
    db: Session, seller_order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    by_order: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if seller_order_ids:
        for event in db.scalars(
            select(OrderStatusEvent)
            .where(OrderStatusEvent.seller_order_id.in_(seller_order_ids))
            .order_by(OrderStatusEvent.occurred_at, OrderStatusEvent.id)
        ):
            # Who did it by role, never which person: the other side of an
            # order does not learn a staff or team member's identity.
            by_order.setdefault(event.seller_order_id, []).append(
                {
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "actor_type": event.actor_type,
                    "reason": event.reason,
                    "occurred_at": event.occurred_at,
                }
            )
    return by_order


def _item_out(item: OrderItem, language: str) -> dict[str, Any]:
    other = "en" if language == "am" else "am"
    return {
        "id": item.id,
        "offer_id": item.offer_id,
        "title": getattr(item, f"title_{language}") or getattr(item, f"title_{other}"),
        "variant_label": getattr(item, f"variant_label_{language}")
        or getattr(item, f"variant_label_{other}"),
        "condition": item.condition,
        "warranty_months": item.warranty_months,
        "unit_price_santim": item.unit_price_santim,
        "quantity": item.quantity,
        "line_total_santim": item.line_total_santim,
    }


def _shipments(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Shipment]:
    if not ids:
        return {}
    return {
        s.seller_order_id: s
        for s in db.scalars(select(Shipment).where(Shipment.seller_order_id.in_(ids)))
    }


def _intents(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, PaymentIntent]:
    if not ids:
        return {}
    intents: dict[uuid.UUID, PaymentIntent] = {}
    for intent in db.scalars(
        select(PaymentIntent)
        .where(PaymentIntent.seller_order_id.in_(ids))
        .order_by(PaymentIntent.created_at)
    ):
        intents[intent.seller_order_id] = intent
    return intents


# -- orders: the buyer -----------------------------------------------------------------


def _buyer_order_out(db: Session, order: Order, language: str) -> dict[str, Any]:
    rows = db.execute(
        select(SellerOrder, Seller, Store)
        .join(Seller, Seller.id == SellerOrder.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .where(SellerOrder.order_id == order.id)
        .order_by(SellerOrder.id)
    ).all()
    ids = [seller_order.id for seller_order, _, _ in rows]
    items, events = _items(db, ids), _events(db, ids)
    shipments, intents = _shipments(db, ids), _intents(db, ids)
    seller_orders = []
    for seller_order, seller, store in rows:
        shipment, intent = shipments[seller_order.id], intents[seller_order.id]
        shows_contact = contact_visible(seller_order.status, seller_order.confirmed_at is not None)
        seller_orders.append(
            {
                "id": seller_order.id,
                "store_slug": store.slug,
                "store_name": store.name,
                "status": seller_order.status,
                "items_total_santim": seller_order.items_total_santim,
                "delivery_fee_santim": seller_order.delivery_fee_santim,
                "total_santim": seller_order.total_santim,
                "response_deadline": seller_order.response_deadline,
                "confirmed_at": seller_order.confirmed_at,
                "closed_reason": seller_order.closed_reason,
                "delivery_method": shipment.mode,
                "promised_hours": shipment.promised_hours,
                "payment_method": intent.method,
                "payment_reference": intent.reference,
                "can_cancel": seller_order.status in _BUYER_MAY_CANCEL,
                "can_confirm_receipt": seller_order.status == "delivered",
                "delivery_status": shipment.status,
                "handover_code": service.handover_code(shipment)
                if service.shows_handover_code(seller_order.status)
                else None,
                "rider_name": shipment.rider_name if shows_contact else None,
                "rider_phone": shipment.rider_phone if shows_contact else None,
                "delivered_at": seller_order.delivered_at,
                "problem_window_ends_at": seller_order.problem_window_ends_at,
                "completed_at": seller_order.completed_at,
                "paid_method": seller_order.paid_method,
                "paid_at": seller_order.paid_at,
                "seller_contact": {
                    "phone": seller.contact_phone,
                    "shop_address": seller.shop_address,
                }
                if shows_contact
                else None,
                "items": [_item_out(item, language) for item in items.get(seller_order.id, [])],
                "events": events.get(seller_order.id, []),
            }
        )
    return {
        "id": order.id,
        "code": order.code,
        "status": derive_order_status(str(so["status"]) for so in seller_orders),
        "created_at": order.created_at,
        "payment_mode": order.payment_mode,
        "currency": order.currency,
        "items_total_santim": order.items_total_santim,
        "delivery_total_santim": order.delivery_total_santim,
        "grand_total_santim": order.grand_total_santim,
        "address": order.address_snapshot,
        "seller_orders": seller_orders,
    }


def buyer_order(db: Session, user_id: uuid.UUID, order_id: uuid.UUID, language: str) -> Any:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user_id))
    if order is None:
        # The same answer for another buyer's order and one that does not exist.
        raise NotFound("order_not_found", "That order was not found.")
    return _buyer_order_out(db, order, language)


def buyer_orders(
    db: Session, user_id: uuid.UUID, language: str, *, before: uuid.UUID | None, limit: int
) -> list[dict[str, Any]]:
    """Newest first. Keys are time-ordered, so the last id of a page is the
    cursor for the next (blueprint F.5)."""
    query = (
        select(Order).where(Order.buyer_user_id == user_id).order_by(Order.id.desc()).limit(limit)
    )
    if before is not None:
        query = query.where(Order.id < before)
    return [_buyer_order_out(db, order, language) for order in db.scalars(query)]


# -- orders: the seller ----------------------------------------------------------------


def _seller_order_out(
    order: Order,
    seller_order: SellerOrder,
    items: list[OrderItem],
    events: list[dict[str, Any]],
    shipment: Shipment,
    intent: PaymentIntent,
    language: str,
    *,
    may_see_contact: bool,
) -> dict[str, Any]:
    address: dict[str, Any] = order.address_snapshot
    fee = Money.zero()
    for item in items:
        fee += Money(item.line_total_santim).portion_bps(item.commission_bps)
    shows_contact = may_see_contact and contact_visible(
        seller_order.status, seller_order.confirmed_at is not None
    )
    return {
        "id": seller_order.id,
        "order_code": order.code,
        "status": seller_order.status,
        "placed_at": seller_order.created_at,
        "response_deadline": seller_order.response_deadline,
        "confirmed_at": seller_order.confirmed_at,
        "closed_reason": seller_order.closed_reason,
        "items_total_santim": seller_order.items_total_santim,
        "delivery_fee_santim": seller_order.delivery_fee_santim,
        "total_santim": seller_order.total_santim,
        # Shown in birr before the seller confirms (blueprint D.19).
        "estimated_fee_santim": fee.amount,
        "delivery_method": shipment.mode,
        "promised_hours": shipment.promised_hours,
        "payment_method": intent.method,
        "payment_reference": intent.reference,
        "delivery_status": shipment.status,
        "handover_attempts": shipment.handover_attempts,
        "rider_name": shipment.rider_name,
        "rider_phone": shipment.rider_phone,
        "delivered_at": seller_order.delivered_at,
        "completed_at": seller_order.completed_at,
        "paid_method": seller_order.paid_method,
        "paid_at": seller_order.paid_at,
        "fee_charged_santim": seller_order.commission_santim
        if seller_order.status == "completed"
        else None,
        # Enough to decide whether the order can be delivered, and no more.
        "delivery_area": {
            key: address.get(key)
            for key in ("zone_code", "zone_name_am", "zone_name_en", "area_name_am", "area_name_en")
        },
        "buyer": {
            key: address.get(key)
            for key in (
                "recipient_name", "phone", "phone2", "landmark", "latitude", "longitude",
                "driver_notes",
            )
        }
        if shows_contact
        else None,
        "items": [_item_out(item, language) for item in items],
        "events": events,
    }  # fmt: skip


def seller_orders(
    db: Session,
    seller_id: uuid.UUID,
    language: str,
    *,
    status: str | None,
    before: uuid.UUID | None,
    limit: int,
    may_see_contact: bool,
) -> list[dict[str, Any]]:
    query = (
        select(SellerOrder, Order)
        .join(Order, Order.id == SellerOrder.order_id)
        .where(SellerOrder.seller_id == seller_id)
        .order_by(SellerOrder.id.desc())
        .limit(limit)
    )
    if status is not None:
        query = query.where(SellerOrder.status == status)
    if before is not None:
        query = query.where(SellerOrder.id < before)
    rows = db.execute(query).all()
    ids = [seller_order.id for seller_order, _ in rows]
    items, events = _items(db, ids), _events(db, ids)
    shipments, intents = _shipments(db, ids), _intents(db, ids)
    return [
        _seller_order_out(
            order, seller_order, items.get(seller_order.id, []), events.get(seller_order.id, []),
            shipments[seller_order.id], intents[seller_order.id], language,
            may_see_contact=may_see_contact,
        )
        for seller_order, order in rows
    ]  # fmt: skip


def seller_order(
    db: Session,
    seller_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    language: str,
    *,
    may_see_contact: bool,
) -> dict[str, Any]:
    row = db.execute(
        select(SellerOrder, Order)
        .join(Order, Order.id == SellerOrder.order_id)
        .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller_id)
    ).first()
    if row is None:
        raise NotFound("order_not_found", "That order was not found.")
    found, order = row
    ids = [found.id]
    return _seller_order_out(
        order, found, _items(db, ids).get(found.id, []), _events(db, ids).get(found.id, []),
        _shipments(db, ids)[found.id], _intents(db, ids)[found.id], language,
        may_see_contact=may_see_contact,
    )  # fmt: skip
