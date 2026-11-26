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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.catalog import selectors as catalog_selectors
from markx.catalog.models import ProductTranslation
from markx.core.errors import NotFound
from markx.core.money import Money
from markx.delivery.models import MAX_HANDOVER_ATTEMPTS, DeliveryZone, Shipment, TrackingEvent
from markx.delivery.selectors import active_rates_for_zone
from markx.images import gate_photos
from markx.orders import notice, service
from markx.orders.models import (
    Cart,
    Order,
    OrderItem,
    OrderStatusEvent,
    SellerOrder,
    SellerOrderStatus,
)
from markx.orders.status import AWAITING_HANDOVER, contact_visible, derive_order_status
from markx.payments.fees import seller_order_fee
from markx.payments.models import PaymentIntent
from markx.sellers.models import Seller, Store
from markx.trust.models import CaseStatus, DisputeCase, DisputeMessage

# As on the product page: in stock or not, never a competitor-readable count.
PUBLIC_STOCK_CAP = 5
_BUYER_MAY_CANCEL = ("placed", "confirmed")
# What the guest's cancel allows (F-28, D-109), from the rule itself.
_GUEST_MAY_CANCEL = frozenset(status.value for status in service.GUEST_MAY_CANCEL_FROM)


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
    labels = catalog_selectors.variant_labels(db, (line.product for line in lines), language)
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
                    "variant_label": labels.get(line.variant.id, ""),
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


def quote_out(db: Session, quote: service.Quote, language: str, *, guest: bool) -> dict[str, Any]:
    """The review step, with the notice the buyer reads before placing the
    order (C-27, D-110): the same figures the order is placed with."""
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
        "notice": notice.order_notice(
            db, [group.seller.legal_name for group in quote.groups], language, guest=guest
        ),
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


def _problems(db: Session, seller_order_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The problem reported on each seller order, if any, with what each side
    wrote (D.17). Authors by role, never by person."""
    by_order: dict[uuid.UUID, dict[str, Any]] = {}
    if not seller_order_ids:
        return by_order
    by_case: dict[uuid.UUID, dict[str, Any]] = {}
    for case in db.scalars(
        select(DisputeCase).where(DisputeCase.seller_order_id.in_(seller_order_ids))
    ):
        out = {
            "problem_type": case.problem_type,
            "description": case.description,
            "status": case.status,
            "opened_at": case.created_at,
            "decision_due_at": case.decision_due_at,
            "decision": case.decision,
            "decision_reason": case.decision_reason,
            "resolved_at": case.resolved_at,
            "messages": [],
        }
        by_order[case.seller_order_id] = by_case[case.id] = out
    if by_case:
        for message in db.scalars(
            select(DisputeMessage)
            .where(DisputeMessage.case_id.in_(list(by_case)))
            .order_by(DisputeMessage.created_at, DisputeMessage.id)
        ):
            by_case[message.case_id]["messages"].append(
                {
                    "author_type": message.author_type,
                    "body": message.body,
                    "created_at": message.created_at,
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


def _tracking(
    db: Session, shipments: dict[uuid.UUID, Shipment]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    by_shipment: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if shipments:
        for event in db.scalars(
            select(TrackingEvent)
            .where(TrackingEvent.shipment_id.in_([s.id for s in shipments.values()]))
            .order_by(TrackingEvent.occurred_at, TrackingEvent.id)
        ):
            by_shipment.setdefault(event.shipment_id, []).append(
                {
                    "status": event.status,
                    "note": event.note,
                    "source": event.source,
                    "occurred_at": event.occurred_at,
                }
            )
    return by_shipment


def _shipment_out(
    shipment: Shipment, events: list[dict[str, Any]], *, show_rider: bool
) -> dict[str, Any]:
    return {
        "status": shipment.status,
        "method": shipment.mode,
        "promised_hours": shipment.promised_hours,
        "rider_name": shipment.rider_name if show_rider else None,
        "rider_phone": shipment.rider_phone if show_rider else None,
        "dispatched_at": shipment.dispatched_at,
        "delivered_at": shipment.delivered_at,
        "failure_reason": shipment.failure_reason,
        "events": events,
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
    tracking = _tracking(db, shipments)
    problems = _problems(db, ids)
    now = datetime.now(UTC)
    seller_orders = []
    for seller_order, seller, store in rows:
        shipment, intent = shipments[seller_order.id], intents[seller_order.id]
        shows_contact = contact_visible(seller_order.status, seller_order.confirmed_at is not None)
        awaiting_handover = seller_order.status in AWAITING_HANDOVER
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
                "ready_at": seller_order.ready_at,
                "delivered_at": seller_order.delivered_at,
                "completed_at": seller_order.completed_at,
                "problem_window_ends_at": seller_order.problem_window_ends_at,
                "paid_method": seller_order.paid_method,
                "paid_at": seller_order.paid_at,
                # Not once a payment is recorded: staff settle that (D-086).
                "can_cancel": seller_order.status in _BUYER_MAY_CANCEL
                and seller_order.paid_at is None,
                "can_confirm_received": seller_order.status == "delivered",
                "can_report_problem": seller_order.status == "delivered"
                and seller_order.problem_window_ends_at is not None
                and now < seller_order.problem_window_ends_at,
                "problem": problems.get(seller_order.id),
                # Only while a handover is awaited, and only to the signed-in
                # buyer or by a guest order's own link (D-108).
                "handover_code": service.handover_code(shipment) if awaiting_handover else None,
                "shipment": _shipment_out(
                    shipment,
                    tracking.get(shipment.id, []),
                    show_rider=shows_contact and shipment.dispatched_at is not None,
                ),
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
        "tracking_path": service.issue_tracking_link(order).path,
        "is_guest": order.buyer_user_id is None,
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


def buyer_alternatives(
    db: Session, user_id: uuid.UUID, order_id: uuid.UUID, seller_order_id: uuid.UUID
) -> list[dict[str, Any]]:
    """The next-best offer for each line of a part its seller declined or let
    expire (C-26), read live. Nothing for a part in any other state."""
    row = db.execute(
        select(SellerOrder, Order)
        .join(Order, Order.id == SellerOrder.order_id)
        .where(
            SellerOrder.id == seller_order_id,
            Order.id == order_id,
            Order.buyer_user_id == user_id,
        )
    ).first()
    if row is None:
        raise NotFound("order_not_found", "That order was not found.")
    seller_order, order = row
    if seller_order.status not in ("declined", "expired"):
        return []
    return service.next_best_offers(db, seller_order, order)


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
    tracking: list[dict[str, Any]],
    intent: PaymentIntent,
    language: str,
    *,
    may_see_contact: bool,
    problem: dict[str, Any] | None,
) -> dict[str, Any]:
    address: dict[str, Any] = order.address_snapshot
    # The same calculation as at completion, each rule's cap included (D-099).
    fee = seller_order_fee(service.fee_lines(items)).amount
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
        "fee_santim": seller_order.commission_santim if seller_order.completed_at else None,
        "delivery_method": shipment.mode,
        "promised_hours": shipment.promised_hours,
        "payment_method": intent.method,
        "payment_reference": intent.reference,
        "ready_at": seller_order.ready_at,
        "delivered_at": seller_order.delivered_at,
        "completed_at": seller_order.completed_at,
        "problem_window_ends_at": seller_order.problem_window_ends_at,
        "paid_method": seller_order.paid_method,
        "paid_at": seller_order.paid_at,
        "handover_attempts_left": MAX_HANDOVER_ATTEMPTS - shipment.handover_attempts,
        # The buyer's gate photo, only while this shop delivers it to the door
        # (C-08; D-107); the link comes from `.../orders/{id}/gate-photo`.
        "has_gate_photo": shows_contact and gate_photos.visible_to_shop(seller_order, order, shipment),
        "problem": problem,
        # The seller's own rider: always shown to the seller.
        "shipment": _shipment_out(shipment, tracking, show_rider=True),
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
    tracking = _tracking(db, shipments)
    problems = _problems(db, ids)
    return [
        _seller_order_out(
            order, seller_order, items.get(seller_order.id, []), events.get(seller_order.id, []),
            shipments[seller_order.id], tracking.get(shipments[seller_order.id].id, []),
            intents[seller_order.id], language, may_see_contact=may_see_contact,
            problem=problems.get(seller_order.id),
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
    shipments = _shipments(db, ids)
    return _seller_order_out(
        order, found, _items(db, ids).get(found.id, []), _events(db, ids).get(found.id, []),
        shipments[found.id], _tracking(db, shipments).get(shipments[found.id].id, []),
        _intents(db, ids)[found.id], language, may_see_contact=may_see_contact,
        problem=_problems(db, ids).get(found.id),
    )  # fmt: skip


# -- the seller's customers (blueprint S-11, D.4; D-106) -------------------------------------

# PROVISIONAL (P-106-4): how many of each customer's orders the list names.
CUSTOMER_RECENT_ORDERS = 5


def seller_customers(
    db: Session, seller_id: uuid.UUID, language: str, *, query: str | None, limit: int
) -> list[dict[str, Any]]:
    """The people this shop has served (S-11), built only from what its own
    order pages already show it: the seller orders whose buyer details are
    visible now (confirmed by the shop, and not ended without delivery, as
    `contact_visible` says), grouped by the phone number those pages show.
    A buyer's account is never named or linked; an order the shop cannot see
    the contact of, or one that ended undelivered, adds nothing. The route
    asks for the capability to see buyers' contacts (blueprint C.3).
    Newest customer first, by their latest order."""
    rows = db.execute(
        select(
            SellerOrder.id,
            SellerOrder.status,
            SellerOrder.confirmed_at,
            SellerOrder.created_at,
            SellerOrder.total_santim,
            Order.code,
            Order.address_snapshot,
        )
        .join(Order, Order.id == SellerOrder.order_id)
        .where(SellerOrder.seller_id == seller_id, SellerOrder.confirmed_at.is_not(None))
        .order_by(SellerOrder.created_at.desc(), SellerOrder.id.desc())
    ).all()
    other = "en" if language == "am" else "am"
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not contact_visible(row.status, row.confirmed_at is not None):
            continue
        address: dict[str, Any] = row.address_snapshot or {}
        phone = address.get("phone")
        if not isinstance(phone, str) or not phone:
            continue
        customer = found.get(phone)
        if customer is None:  # their latest order: its name and area are shown
            customer = found[phone] = {
                "phone": phone,
                "name": address.get("recipient_name") or "",
                "area_name": address.get(f"area_name_{language}")
                or address.get(f"area_name_{other}")
                or "",
                "orders": 0,
                "completed_orders": 0,
                "first_order_at": row.created_at,
                "last_order_at": row.created_at,
                "recent_orders": [],
            }
        customer["orders"] += 1
        if row.status == SellerOrderStatus.COMPLETED:
            customer["completed_orders"] += 1
        customer["first_order_at"] = row.created_at
        if len(customer["recent_orders"]) < CUSTOMER_RECENT_ORDERS:
            customer["recent_orders"].append({
                "seller_order_id": row.id, "order_code": row.code, "status": row.status,
                "placed_at": row.created_at, "total_santim": row.total_santim,
            })  # fmt: skip
    customers = list(found.values())
    wanted = (query or "").strip().casefold()
    if wanted:
        digits = "".join(ch for ch in wanted if ch.isdigit())
        customers = [
            c
            for c in customers
            if wanted in c["name"].casefold()
            or (len(digits) >= 3 and (digits in c["phone"] or _local(digits) in c["phone"]))
        ]
    return customers[:limit]


def _local(digits: str) -> str:
    """A number typed the local way, 09..., as the shown form has it: +2519..."""
    return "251" + digits[1:] if digits.startswith("0") else digits


# -- orders: staff ---------------------------------------------------------------------


def _staff_order_out(db: Session, order: Order | None, language: str) -> dict[str, Any]:
    if order is None:
        raise NotFound("order_not_found", "That order was not found.")
    out = _buyer_order_out(db, order, language)
    out["tracking_path"] = None
    for seller_order in out["seller_orders"]:
        seller_order["handover_code"] = None
        seller_order["can_report_problem"] = False
    return out


# -- orders: the tracking page -------------------------------------------------------------

_TRACKING_ADDRESS_KEYS = ("zone_code", "zone_name_am", "zone_name_en", "area_name_am", "area_name_en", "city")  # fmt: skip


def tracking_view(db: Session, order: Order, language: str) -> dict[str, Any]:
    """The order as the secure link shows it (D.14): the timeline of every
    part, the expected time, the seller's and rider's contact once allowed,
    the items and totals. Not the recipient's name, phones or pin, and no
    action: those need the signed-in page.

    The handover code only on a guest's order (C-07, D-108; PROVISIONAL
    P-108-7, to be confirmed before going live): the link is a guest's only
    page, so it shows the code as the signed-in page does, from `ready`
    until the handover, or the guest could never receive the goods.
    A guest's link is never sent anywhere (no Telegram, no SMS, no in-app
    message); it is handed only to the browser that placed the order. A
    signed-in buyer's link never shows it (D-048).

    One action, on a guest's order only: cancelling a shop's part before the
    shop answers (F-28, D-109; `service.cancel_by_guest` checks again). A
    signed-in buyer's link still offers none."""
    out = _buyer_order_out(db, order, language)
    guest = order.buyer_user_id is None
    out["tracking_path"] = None
    out["address"] = {key: out["address"].get(key) for key in _TRACKING_ADDRESS_KEYS}
    for seller_order in out["seller_orders"]:
        if not guest:
            seller_order["handover_code"] = None
        seller_order["can_cancel"] = (
            guest
            and seller_order["status"] in _GUEST_MAY_CANCEL
            and seller_order["paid_at"] is None
        )
        seller_order["can_confirm_received"] = False
        seller_order["can_report_problem"] = False
        # What the buyer wrote about a problem is for the signed-in page.
        seller_order["problem"] = None
    return out


def staff_order(db: Session, code: str, language: str) -> dict[str, Any]:
    """The whole order by its code, for the orders desk (P11): every part,
    with the handover code left out. Staff never need it."""
    return _staff_order_out(db, db.scalar(select(Order).where(Order.code == code)), language)


def staff_order_by_id(db: Session, order_id: uuid.UUID, language: str) -> dict[str, Any]:
    return _staff_order_out(db, db.get(Order, order_id), language)


def staff_open_problems(db: Session, *, limit: int) -> list[dict[str, Any]]:
    """The cases waiting for a decision, the most urgent first (AD-09)."""
    rows = db.execute(
        select(DisputeCase, SellerOrder, Order, Store)
        .join(SellerOrder, SellerOrder.id == DisputeCase.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Store, Store.seller_id == SellerOrder.seller_id)
        .where(DisputeCase.status != CaseStatus.RESOLVED)
        .order_by(DisputeCase.decision_due_at, DisputeCase.id)
        .limit(limit)
    ).all()
    return [
        {
            "seller_order_id": seller_order.id,
            "order_code": order.code,
            "store_slug": store.slug,
            "problem_type": case.problem_type,
            "status": case.status,
            "opened_at": case.created_at,
            "decision_due_at": case.decision_due_at,
        }
        for case, seller_order, order, store in rows
    ]
