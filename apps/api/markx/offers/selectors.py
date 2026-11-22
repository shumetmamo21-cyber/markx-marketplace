"""Read queries for offers. Nothing here changes data.

The ranking of offers on a product page is computed on every read and never
stored (blueprint D.7, G.4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.audit.models import AuditLog
from markx.catalog.models import Product, ProductStatus, ProductTranslation, ProductVariant
from markx.catalog.selectors import resolve_merged, variant_labels
from markx.core import settings_store
from markx.core.errors import NotFound
from markx.delivery.models import DeliveryMode, DeliveryRate, DeliveryZone
from markx.offers.models import (
    Condition,
    Inventory,
    InventoryMovement,
    Offer,
    OfferPriceHistory,
    OfferStatus,
)
from markx.sellers.models import Seller, SellerStatus, Store

# Buyers see whether an offer is in stock, not a competitor-readable count.
PUBLIC_STOCK_CAP = 5


def _product_names(db: Session, product_ids: set[uuid.UUID], language: str) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, dict[str, str]] = {}
    if product_ids:
        for t in db.scalars(
            select(ProductTranslation).where(ProductTranslation.product_id.in_(product_ids))
        ):
            names.setdefault(t.product_id, {})[t.language] = t.name
    other = "en" if language == "am" else "am"
    return {pid: by.get(language) or by.get(other) or "" for pid, by in names.items()}


def _seller_row(
    offer: Offer, inventory: Inventory, variant: ProductVariant, product: Product, name: str,
    sink_before: datetime, label: str,
) -> dict[str, Any]:  # fmt: skip
    available = inventory.on_hand - inventory.reserved
    return {
        "id": offer.id,
        "variant_id": offer.variant_id,
        "product_id": product.id,
        "product_slug": product.slug,
        "product_name": name,
        "variant_attributes": variant.attribute_values,
        "variant_label": label,
        "model_code": variant.model_code,
        "condition": offer.condition,
        "price_santim": offer.price_santim,
        "currency": offer.currency,
        "warranty_months": offer.warranty_months,
        "warranty_note": offer.warranty_note,
        "delivers_by_seller_rider": offer.delivers_by_seller_rider,
        "delivers_by_partner_courier": offer.delivers_by_partner_courier,
        "offers_shop_collection": offer.offers_shop_collection,
        "status": offer.status,
        "on_hand": inventory.on_hand,
        "reserved": inventory.reserved,
        "available": available,
        "low_stock_threshold": inventory.low_stock_threshold,
        "is_low_stock": available <= inventory.low_stock_threshold,
        "needs_confirmation": offer.status == OfferStatus.STALE
        or (offer.status == OfferStatus.ACTIVE and offer.price_confirmed_at < sink_before),
        "price_confirmed_at": offer.price_confirmed_at,
        "stock_confirmed_at": offer.stock_confirmed_at,
        "created_at": offer.created_at,
    }


def _seller_query(seller_id: uuid.UUID) -> Any:
    return (
        select(Offer, Inventory, ProductVariant, Product)
        .join(Inventory, Inventory.offer_id == Offer.id)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(Offer.seller_id == seller_id)
    )


def _sink_before(db: Session) -> datetime:
    return datetime.now(UTC) - timedelta(days=settings_store.get_int(db, "offers.sink_after_days"))


def seller_offers(
    db: Session,
    seller_id: uuid.UUID,
    language: str,
    *,
    status: str | None,
    after: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    """The seller's quick-edit list, oldest first, paged by cursor.
    Removed offers are listed only when asked for."""
    query = _seller_query(seller_id).order_by(Offer.id).limit(limit)
    if status is not None:
        query = query.where(Offer.status == status)
    else:
        query = query.where(Offer.status != OfferStatus.REMOVED)
    if after is not None:
        query = query.where(Offer.id > after)
    rows = db.execute(query).all()
    names = _product_names(db, {product.id for _, _, _, product in rows}, language)
    labels = variant_labels(db, (product for *_, product in rows), language)
    sink_before = _sink_before(db)
    return [
        _seller_row(
            offer, inventory, variant, product, names.get(product.id, ""), sink_before,
            labels.get(variant.id, ""),
        )
        for offer, inventory, variant, product in rows
    ]  # fmt: skip


def seller_offer_detail(
    db: Session, seller_id: uuid.UUID, offer_id: uuid.UUID, language: str
) -> dict[str, Any]:
    row = db.execute(_seller_query(seller_id).where(Offer.id == offer_id)).first()
    if row is None:
        raise NotFound("offer_not_found", "That offer was not found.")
    offer, inventory, variant, product = row
    names = _product_names(db, {product.id}, language)
    out = _seller_row(
        offer, inventory, variant, product, names.get(product.id, ""), _sink_before(db),
        variant_labels(db, [product], language).get(variant.id, ""),
    )  # fmt: skip
    out["price_history"] = [
        {
            "old_price_santim": h.old_price_santim,
            "new_price_santim": h.new_price_santim,
            "changed_at": h.changed_at,
        }
        for h in db.scalars(
            select(OfferPriceHistory)
            .where(OfferPriceHistory.offer_id == offer.id)
            .order_by(OfferPriceHistory.changed_at.desc(), OfferPriceHistory.id.desc())
            .limit(50)
        )
    ]
    out["movements"] = [
        {
            "delta_on_hand": m.delta_on_hand,
            "delta_reserved": m.delta_reserved,
            "on_hand_after": m.on_hand_after,
            "reserved_after": m.reserved_after,
            "reason": m.reason,
            "created_at": m.created_at,
        }
        for m in db.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.offer_id == offer.id)
            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .limit(50)
        )
    ]
    return out


def seller_dashboard(db: Session, seller_id: uuid.UUID) -> dict[str, int]:
    """Counts for the dashboard shell (blueprint D.4): what needs attention."""
    by_status = dict(
        db.execute(
            select(Offer.status, func.count()).where(Offer.seller_id == seller_id).group_by(
                Offer.status
            )
        ).all()
    )  # fmt: skip
    live = (Offer.seller_id == seller_id, Offer.status == OfferStatus.ACTIVE)
    low_stock = db.scalar(
        select(func.count())
        .select_from(Offer)
        .join(Inventory, Inventory.offer_id == Offer.id)
        .where(*live, Inventory.on_hand - Inventory.reserved <= Inventory.low_stock_threshold)
    )
    unconfirmed = db.scalar(
        select(func.count())
        .select_from(Offer)
        .where(*live, Offer.price_confirmed_at < _sink_before(db))
    )
    return {
        "active_offers": int(by_status.get(OfferStatus.ACTIVE, 0)),
        "paused_offers": int(by_status.get(OfferStatus.PAUSED, 0)),
        "stale_offers": int(by_status.get(OfferStatus.STALE, 0)),
        "low_stock_offers": int(low_stock or 0),
        "prices_to_confirm": int(unconfirmed or 0) + int(by_status.get(OfferStatus.STALE, 0)),
    }


# -- public ----------------------------------------------------------------------


def _live_offers() -> Any:
    """Offers a buyer may see: active, from a trading seller verified to the
    level the launch policy requires (blueprint D.1, D.3)."""
    return (
        select(Offer, Inventory, Seller, Store)
        .join(Inventory, Inventory.offer_id == Offer.id)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .where(Offer.status == OfferStatus.ACTIVE, Seller.status == SellerStatus.ACTIVE)
    )


def _public_row(offer: Offer, inventory: Inventory, seller: Seller, store: Store) -> dict[str, Any]:
    available = max(inventory.on_hand - inventory.reserved, 0)
    return {
        "id": offer.id,
        "variant_id": offer.variant_id,
        "condition": offer.condition,
        "price_santim": offer.price_santim,
        "currency": offer.currency,
        "warranty_months": offer.warranty_months,
        "warranty_note": offer.warranty_note,
        "in_stock": available > 0,
        "available": min(available, PUBLIC_STOCK_CAP),
        "store_slug": store.slug,
        "store_name": store.name,
        "seller_verification_level": seller.verification_level,
        "delivers_by_seller_rider": offer.delivers_by_seller_rider,
        "delivers_by_partner_courier": offer.delivers_by_partner_courier,
        "offers_shop_collection": offer.offers_shop_collection,
        "price_confirmed_at": offer.price_confirmed_at,
    }


def product_offers(
    db: Session, slug: str, *, zone_code: str | None, variant_id: uuid.UUID | None
) -> dict[str, Any]:
    """Every live offer for a product, ranked (blueprint D.7, C-04).

    Order: in stock before out of stock; a recently confirmed price before one
    that has sunk; when the buyer's zone is known, offers that deliver there
    before collection-only ones; then the lowest total cost (price plus the
    cheapest delivery to the zone); then the higher seller level; then the
    most recently confirmed price. Seller performance figures join this order
    once orders exist to measure.
    """
    not_found = NotFound("product_not_found", "That product was not found.")
    product = db.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise not_found
    product = resolve_merged(db, product)
    if product.status != ProductStatus.APPROVED:
        raise not_found

    zone = None
    rates: dict[str, DeliveryRate] = {}
    if zone_code is not None:
        zone = db.scalar(
            select(DeliveryZone).where(DeliveryZone.code == zone_code, DeliveryZone.is_active)
        )
        if zone is None:
            raise NotFound("zone_not_found", "That delivery zone was not found.")
        rates = {
            r.method: r
            for r in db.scalars(
                select(DeliveryRate).where(DeliveryRate.zone_id == zone.id, DeliveryRate.is_active)
            )
        }

    min_level = settings_store.get_int(db, "sellers.min_level_to_publish")
    query = (
        _live_offers()
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .where(
            ProductVariant.product_id == product.id,
            ProductVariant.is_active,
            Seller.verification_level >= min_level,
        )
    )
    if variant_id is not None:
        query = query.where(Offer.variant_id == variant_id)
    sink_before = _sink_before(db)

    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for offer, inventory, seller, store in db.execute(query).all():
        row = _public_row(offer, inventory, seller, store)
        options = [
            rates[method]
            for method, offered in (
                (DeliveryMode.SELLER_RIDER.value, offer.delivers_by_seller_rider),
                (DeliveryMode.PARTNER_COURIER.value, offer.delivers_by_partner_courier),
            )
            if offered and method in rates
        ]
        cheapest = min(options, key=lambda r: (r.fee_santim, r.promised_hours), default=None)
        row["delivery_fee_santim"] = cheapest.fee_santim if cheapest else None
        row["delivery_method"] = cheapest.method if cheapest else None
        row["delivery_promised_hours"] = cheapest.promised_hours if cheapest else None
        row["total_santim"] = offer.price_santim + (cheapest.fee_santim if cheapest else 0)
        sunk = offer.price_confirmed_at < sink_before
        row["price_is_fresh"] = not sunk
        key = (
            not row["in_stock"],
            sunk,
            zone is not None and cheapest is None,
            row["total_santim"],
            -seller.verification_level,
            -offer.price_confirmed_at.timestamp(),
            str(offer.id),
        )
        ranked.append((key, row))
    ranked.sort(key=lambda pair: pair[0])
    offers = [row for _, row in ranked]
    for index, row in enumerate(offers):
        row["is_default"] = index == 0 and row["in_stock"]
        row["default_reason"] = None
    if offers and offers[0]["is_default"]:
        offers[0]["default_reason"] = (
            "lowest_total_delivered" if offers[0]["delivery_fee_santim"] is not None
            else "lowest_price"
        )  # fmt: skip
    in_stock_prices = [row["price_santim"] for row in offers if row["in_stock"]]
    return {
        "product_slug": product.slug,
        "zone_code": zone.code if zone else None,
        "offer_count": len(offers),
        "lowest_price_santim": min(in_stock_prices) if in_stock_prices else None,
        "offers": offers,
    }


def next_best_offer(
    db: Session, variant_id: uuid.UUID, *, zone_code: str | None, exclude_seller_id: uuid.UUID
) -> dict[str, Any] | None:
    """The best offer in stock for the same variant from another seller, by
    the product page's own ranking (blueprint C-26), or None when there is
    none. Used when a seller declines an order or lets it expire."""
    row = db.execute(
        select(Product.slug)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .where(ProductVariant.id == variant_id)
    ).first()
    excluded = db.scalar(select(Store.slug).where(Store.seller_id == exclude_seller_id))
    if row is None:
        return None
    try:
        ranked = product_offers(db, row.slug, zone_code=zone_code, variant_id=variant_id)
    except NotFound:
        # The product was withdrawn, or the buyer's zone closed: nothing to suggest.
        return None
    for offer in ranked["offers"]:
        if offer["in_stock"] and offer["store_slug"] != excluded:
            return dict(offer, product_slug=ranked["product_slug"])
    return None


def store_price_list(
    db: Session, store_slug: str, language: str, *, limit: int
) -> list[dict[str, Any]]:
    """A store's live offers with product names: the shareable price list (S-10)."""
    min_level = settings_store.get_int(db, "sellers.min_level_to_publish")
    rows = db.execute(
        _live_offers()
        .add_columns(ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            Store.slug == store_slug,
            Seller.verification_level >= min_level,
            Product.status == ProductStatus.APPROVED,
            ProductVariant.is_active,
        )
        .order_by(Offer.id)
        .limit(limit)
    ).all()
    names = _product_names(db, {product.id for *_, product in rows}, language)
    labels = variant_labels(db, (product for *_, product in rows), language)
    out = []
    for offer, inventory, seller, store, variant, product in rows:
        row = _public_row(offer, inventory, seller, store)
        row["product_slug"] = product.slug
        row["product_name"] = names.get(product.id, "")
        row["variant_attributes"] = variant.attribute_values
        row["variant_label"] = labels.get(variant.id, "")
        out.append(row)
    return out


def held_offers(
    db: Session, language: str, *, before: uuid.UUID | None, limit: int
) -> list[dict[str, Any]]:
    """Offers under a staff takedown (D-032), newest takedown first, with the
    reason staff gave, for the moderation queue where a hold is lifted."""
    query = (
        select(Offer, ProductVariant, Product, Store)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .join(Store, Store.seller_id == Offer.seller_id)
        .where(Offer.removed_by_staff_at.is_not(None))
        .order_by(Offer.removed_by_staff_at.desc(), Offer.id.desc())
        .limit(limit)
    )
    if before is not None:
        held_at = db.scalar(select(Offer.removed_by_staff_at).where(Offer.id == before))
        if held_at is None:
            # A cursor that is not a held offer (lifted since, or never one)
            # ends the list rather than starting it again.
            return []
        query = query.where(
            (Offer.removed_by_staff_at < held_at)
            | ((Offer.removed_by_staff_at == held_at) & (Offer.id < before))
        )
    rows = db.execute(query).all()
    products = {product.id: product for _, _, product, _ in rows}
    names = _product_names(db, set(products), language)
    labels = variant_labels(db, products.values(), language)
    reasons: dict[str, str] = {}
    if rows:
        for target_id, after in db.execute(
            select(AuditLog.target_id, AuditLog.after)
            .where(
                AuditLog.action == "offer.staff_remove",
                AuditLog.target_type == "offer",
                AuditLog.target_id.in_([str(offer.id) for offer, *_ in rows]),
            )
            .order_by(AuditLog.id)
        ).all():
            # The latest takedown's reason wins.
            if isinstance(after, dict) and isinstance(after.get("reason"), str):
                reasons[target_id] = after["reason"]
    return [
        {
            "id": offer.id,
            "seller_id": offer.seller_id,
            "store_slug": store.slug,
            "store_name": store.name,
            "product_slug": product.slug,
            "product_name": names.get(product.id, ""),
            "variant_label": labels.get(variant.id, ""),
            "condition": offer.condition,
            "price_santim": offer.price_santim,
            "status": offer.status,
            "removed_by_staff_at": offer.removed_by_staff_at,
            "reason": reasons.get(str(offer.id)),
        }
        for offer, variant, product, store in rows
    ]


# -- the price-history chart (blueprint C-21, D.7; D-106) ----------------------------------

# PROVISIONAL (P-106-2): the chart looks back this many days.
PRICE_HISTORY_DAYS = 90
_ADDIS = timezone(timedelta(hours=3), "EAT")  # Ethiopia keeps UTC+3 all year
_CONDITION_ORDER = [c.value for c in Condition]


def price_history(
    db: Session, slug: str, *, variant_id: uuid.UUID | None, now: datetime | None = None
) -> dict[str, Any]:
    """The lowest price of one version, day by day, for each condition
    (blueprint C-21), from the price changes already recorded (every offer's
    first price and each change since, `offer_price_history`).

    It is drawn from the offers a buyer can see today, the same ones the
    offers table lists: an offer counts from the day it was made, at the
    price it had at the end of each day (Addis Ababa time; today, now).
    Nothing is stored: like the best offer, the chart is read, never kept.
    Each series holds a step only where its lowest price changed."""
    not_found = NotFound("product_not_found", "That product was not found.")
    product = db.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise not_found
    product = resolve_merged(db, product)
    if product.status != ProductStatus.APPROVED:
        raise not_found
    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id == product.id, ProductVariant.is_active)
            .order_by(ProductVariant.position, ProductVariant.id)
        )
    )
    chosen = next((v for v in variants if v.id == variant_id), None) if variant_id else None
    if variant_id is not None and chosen is None:
        raise NotFound("variant_not_found", "That version of the product was not found.")
    chosen = chosen or (variants[0] if variants else None)
    now = now or datetime.now(UTC)
    today = now.astimezone(_ADDIS).date()
    first_day = today - timedelta(days=PRICE_HISTORY_DAYS - 1)
    out: dict[str, Any] = {
        "product_slug": product.slug,
        "variant_id": chosen.id if chosen else None,
        "days": PRICE_HISTORY_DAYS,
        "from_day": first_day,
        "to_day": today,
        "series": [],
    }
    if chosen is None:
        return out
    min_level = settings_store.get_int(db, "sellers.min_level_to_publish")
    offers: dict[uuid.UUID, Offer] = {
        offer.id: offer
        for offer, *_ in db.execute(
            _live_offers().where(
                Offer.variant_id == chosen.id, Seller.verification_level >= min_level
            )
        ).all()
    }
    changes: dict[uuid.UUID, list[tuple[datetime, int]]] = {key: [] for key in offers}
    if offers:
        for offer_id, changed_at, price in db.execute(
            select(
                OfferPriceHistory.offer_id,
                OfferPriceHistory.changed_at,
                OfferPriceHistory.new_price_santim,
            )
            .where(OfferPriceHistory.offer_id.in_(offers), OfferPriceHistory.changed_at <= now)
            .order_by(OfferPriceHistory.changed_at, OfferPriceHistory.id)
        ):
            changes[offer_id].append((changed_at, price))
    for key, history in changes.items():
        if not history:  # every offer records its first price; this guards an older row
            history.append((offers[key].created_at, offers[key].price_santim))
    for condition in _CONDITION_ORDER:
        mine = [changes[key] for key, offer in offers.items() if offer.condition == condition]
        if not mine:
            continue
        steps = _lowest_by_day(mine, first_day, today, now)
        if not steps:
            continue
        prices = [price for _, price in steps]
        out["series"].append({
            "condition": condition,
            "offers": len(mine),
            "current_santim": prices[-1],
            "lowest_santim": min(prices),
            "highest_santim": max(prices),
            "steps": [{"day": day, "price_santim": price} for day, price in steps],
        })  # fmt: skip
    return out


def _lowest_by_day(
    offers: list[list[tuple[datetime, int]]], first_day: date, today: date, now: datetime
) -> list[tuple[date, int]]:
    """The lowest end-of-day price of these offers, as the days where it changed."""
    steps: list[tuple[date, int]] = []
    seen = [0] * len(offers)  # per offer: how many of its changes are before the day's end
    day = first_day
    while day <= today:
        # The end of the day; for today, this moment (a change made now counts).
        end = (
            now + timedelta(microseconds=1)
            if day == today
            else datetime.combine(day + timedelta(days=1), time(), _ADDIS)
        )
        lowest: int | None = None
        for index, history in enumerate(offers):
            while seen[index] < len(history) and history[seen[index]][0] < end:
                seen[index] += 1
            if seen[index]:
                price = history[seen[index] - 1][1]
                lowest = price if lowest is None else min(lowest, price)
        if lowest is not None and (not steps or steps[-1][1] != lowest):
            steps.append((day, lowest))
        day += timedelta(days=1)
    return steps
