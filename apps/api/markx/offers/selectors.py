"""Read queries for offers. Nothing here changes data.

The ranking of offers on a product page is computed on every read and never
stored (blueprint D.7, G.4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.catalog.models import Product, ProductStatus, ProductTranslation, ProductVariant
from markx.catalog.selectors import resolve_merged
from markx.core import settings_store
from markx.core.errors import NotFound
from markx.delivery.models import DeliveryMode, DeliveryRate, DeliveryZone
from markx.offers.models import (
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
    sink_before: datetime,
) -> dict[str, Any]:  # fmt: skip
    available = inventory.on_hand - inventory.reserved
    return {
        "id": offer.id,
        "variant_id": offer.variant_id,
        "product_id": product.id,
        "product_slug": product.slug,
        "product_name": name,
        "variant_attributes": variant.attribute_values,
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
    sink_before = _sink_before(db)
    return [
        _seller_row(offer, inventory, variant, product, names.get(product.id, ""), sink_before)
        for offer, inventory, variant, product in rows
    ]


def seller_offer_detail(
    db: Session, seller_id: uuid.UUID, offer_id: uuid.UUID, language: str
) -> dict[str, Any]:
    row = db.execute(_seller_query(seller_id).where(Offer.id == offer_id)).first()
    if row is None:
        raise NotFound("offer_not_found", "That offer was not found.")
    offer, inventory, variant, product = row
    names = _product_names(db, {product.id}, language)
    out = _seller_row(
        offer, inventory, variant, product, names.get(product.id, ""), _sink_before(db)
    )
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
    out = []
    for offer, inventory, seller, store, variant, product in rows:
        row = _public_row(offer, inventory, seller, store)
        row["product_slug"] = product.slug
        row["product_name"] = names.get(product.id, "")
        row["variant_attributes"] = variant.attribute_values
        out.append(row)
    return out
