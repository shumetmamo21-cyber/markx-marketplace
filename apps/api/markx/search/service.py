"""Search documents: building them and keeping them fresh (blueprint F.7, F.8, P8).

One document per approved product, derived entirely from the catalogue and
the live offers, so it can be rebuilt at any time (D-051):

* `rebuild_document` reads the product as it is now and writes its document,
  or deletes it when the product is no longer approved. It is safe to run
  twice and in any order.
* A change that can alter a document queues a rebuild through the outbox, in
  the transaction that made the change, so the rebuild runs only after that
  change is committed and always reads it. The flush listener below catches
  every ORM change to the columns a document uses; stock and the two bulk
  offer updates queue explicitly (`queue_rebuild`, `queue_for_offers`).
* The worker's hourly `search.rebuild_all` job rebuilds every document, which
  repairs anything a change path forgot and keeps popularity current.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Text, delete, event, func, inspect, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.catalog.models import (
    Brand,
    Category,
    CategoryTranslation,
    Product,
    ProductAlias,
    ProductRequest,
    ProductStatus,
    ProductTranslation,
    ProductVariant,
)
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, ValidationFailed
from markx.core.ethiopic import normalize_text, skeleton_keys
from markx.core.phone import InvalidPhoneNumber, normalize_phone
from markx.notifications.models import Outbox
from markx.offers.models import Inventory, Offer, OfferStatus
from markx.orders.models import OrderItem, SellerOrder, SellerOrderStatus
from markx.search.models import SearchDocument, SearchSynonym
from markx.sellers.models import Seller, SellerStatus

TOPIC_REBUILD = "search.rebuild"


# -- building one document ---------------------------------------------------------


def _facet_values(value: Any) -> list[str]:
    if isinstance(value, bool) or value is None:
        return [] if value is None else [str(value).lower()]
    if isinstance(value, (str, int, float)):
        return [str(value).lower()]
    if isinstance(value, list):
        return [item for element in value for item in _facet_values(element)]
    return []


# The first key of the transaction-scoped advisory lock that serialises
# rebuilds of one product. Any fixed number would do; this one spells "MXSR".
_REBUILD_LOCK_SPACE = 0x4D585352


def _lock_product_rebuild(db: Session, product_id: uuid.UUID) -> None:
    """Only one transaction rebuilds a product's document at a time (D-057).

    Without it, two rebuilds of one product could overlap: the one that read
    the older state could write last and leave a stale "from" price until
    the hourly rebuild. Held until commit, so the second rebuild starts
    after the first is committed and, under READ COMMITTED, reads every
    change committed before it. A hash collision between two products only
    makes one wait for the other."""
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                _REBUILD_LOCK_SPACE, func.hashtext(literal(str(product_id), type_=Text))
            )
        )
    )


def rebuild_document(db: Session, product_id: uuid.UUID) -> SearchDocument | None:
    """Write the product's search document from what the database holds now,
    or delete it when the product is not approved (draft, archived, merged)."""
    _lock_product_rebuild(db, product_id)
    product = db.get(Product, product_id, populate_existing=True)
    if product is None or product.status != ProductStatus.APPROVED:
        db.execute(delete(SearchDocument).where(SearchDocument.product_id == product_id))
        return None

    category = db.get(Category, product.category_id)
    assert category is not None
    brand = db.get(Brand, product.brand_id) if product.brand_id else None
    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id == product.id, ProductVariant.is_active)
            .order_by(ProductVariant.position, ProductVariant.id)
        )
    )
    words: list[str] = []
    words += db.scalars(
        select(ProductTranslation.name)
        .where(ProductTranslation.product_id == product.id)
        .order_by(ProductTranslation.language)
    )
    if brand is not None:
        words.append(brand.name)
    if product.model:
        words.append(product.model)
    words += [v.model_code for v in variants if v.model_code]
    words += db.scalars(
        select(ProductAlias.alias)
        .where(ProductAlias.product_id == product.id)
        .order_by(ProductAlias.created_at, ProductAlias.id)
    )
    words += db.scalars(
        select(CategoryTranslation.name)
        .where(CategoryTranslation.category_id == category.id)
        .order_by(CategoryTranslation.language)
    )
    search_text = normalize_text(" ".join(words))

    # The offers a buyer may see, exactly as the product page filters them.
    live = db.execute(
        select(Offer, Inventory, Seller)
        .join(Inventory, Inventory.offer_id == Offer.id)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .where(
            ProductVariant.product_id == product.id,
            ProductVariant.is_active,
            Offer.status == OfferStatus.ACTIVE,
            Seller.status == SellerStatus.ACTIVE,
            Seller.verification_level >= settings_store.get_int(db, "sellers.min_level_to_publish"),
        )
    ).all()
    in_stock = [(o, s) for o, inv, s in live if inv.on_hand - inv.reserved > 0]

    facets: dict[str, set[str]] = {"condition": {o.condition for o, _ in in_stock}}
    for code, value in product.specs.items():
        facets.setdefault(code, set()).update(_facet_values(value))
    for variant in variants:
        for code, value in variant.attribute_values.items():
            facets.setdefault(code, set()).update(_facet_values(value))

    popularity = db.scalar(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
        .where(
            OrderItem.product_id == product.id,
            SellerOrder.status == SellerOrderStatus.COMPLETED,
        )
    )
    values: dict[str, Any] = {
        "search_text": search_text,
        "tsv": func.to_tsvector("simple", search_text),
        "skeleton_keys": skeleton_keys(search_text),
        "category_id": category.id,
        "category_path": category.path,
        "brand_id": product.brand_id,
        "facets": {code: sorted(found) for code, found in facets.items() if found},
        "min_price_santim": min((o.price_santim for o, _ in in_stock), default=None),
        "offer_count": len(live),
        "seller_count": len({s.id for _, _, s in live}),
        "in_stock": bool(in_stock),
        "best_seller_level": max((s.verification_level for _, _, s in live), default=0),
        "freshest_price_at": max((o.price_confirmed_at for o, _, _ in live), default=None),
        "popularity": int(popularity or 0),
        "updated_at": func.now(),
    }
    db.execute(
        insert(SearchDocument)
        .values(product_id=product.id, **values)
        .on_conflict_do_update(index_elements=[SearchDocument.product_id], set_=values)
    )
    return db.get(SearchDocument, product.id, populate_existing=True)


def rebuild_all(db: Session) -> int:
    """Every document, rebuilt (the hourly safety net, and the first fill).
    Returns how many products were looked at."""
    ids = list(
        db.scalars(
            select(Product.id)
            .where(Product.status == ProductStatus.APPROVED)
            .union(select(SearchDocument.product_id))
        )
    )
    for product_id in sorted(ids):
        rebuild_document(db, product_id)
    return len(ids)


def handle_rebuild(db: Session, row: Outbox) -> None:
    """The outbox handler for `search.rebuild`."""
    rebuild_document(db, uuid.UUID(str(row.payload["product_id"])))


# -- queueing --------------------------------------------------------------------


def queue_rebuild(db: Session, product_ids: Iterable[uuid.UUID]) -> None:
    """Rebuild these products' documents once this transaction commits."""
    for product_id in sorted(set(product_ids)):
        db.add(Outbox(topic=TOPIC_REBUILD, payload={"product_id": str(product_id)}))


def products_of_offers(db: Session, offer_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(offer_ids)
    if not ids:
        return set()
    return set(
        db.scalars(
            select(ProductVariant.product_id)
            .join(Offer, Offer.variant_id == ProductVariant.id)
            .where(Offer.id.in_(ids))
        )
    )


def queue_for_offers(db: Session, offer_ids: Iterable[uuid.UUID]) -> None:
    """For a bulk statement that changed offers without the ORM seeing it."""
    queue_rebuild(db, products_of_offers(db, offer_ids))


# Which columns of which tables a document is built from. A change to any of
# them, through the ORM, queues a rebuild of the products it touches.
_OFFER_COLUMNS = (
    "status", "price_santim", "condition", "price_confirmed_at", "variant_id", "seller_id",
)  # fmt: skip
_PRODUCT_COLUMNS = ("status", "category_id", "brand_id", "model", "specs", "merged_into_id")
_VARIANT_COLUMNS = ("is_active", "attribute_values", "model_code", "product_id")
_SELLER_COLUMNS = ("status", "verification_level")


def _changed(obj: Any, columns: Iterable[str]) -> bool:
    state = inspect(obj)
    return any(state.attrs[name].history.has_changes() for name in columns)


@event.listens_for(Session, "before_flush")
def _queue_search_rebuilds(session: Session, _context: Any, _instances: Any) -> None:
    product_ids: set[uuid.UUID] = set()
    variant_ids: set[uuid.UUID] = set()
    seller_ids: set[uuid.UUID] = set()
    for obj in (*session.new, *session.dirty, *session.deleted):
        is_new = obj in session.new
        if isinstance(obj, Offer):
            if obj.variant_id is not None and (is_new or _changed(obj, _OFFER_COLUMNS)):
                variant_ids.add(obj.variant_id)
        elif isinstance(obj, Product):
            # A new product is a draft: it has no document until approved.
            if not is_new and _changed(obj, _PRODUCT_COLUMNS):
                product_ids.add(obj.id)
        elif isinstance(obj, (ProductTranslation, ProductAlias)):
            if obj.product_id is not None:
                product_ids.add(obj.product_id)
        elif isinstance(obj, ProductVariant):
            if obj.product_id is not None and (is_new or _changed(obj, _VARIANT_COLUMNS)):
                product_ids.add(obj.product_id)
        elif isinstance(obj, Seller) and not is_new and _changed(obj, _SELLER_COLUMNS):
            seller_ids.add(obj.id)
    if not (product_ids or variant_ids or seller_ids):
        return
    with session.no_autoflush:
        if variant_ids:
            product_ids.update(
                session.scalars(
                    select(ProductVariant.product_id).where(ProductVariant.id.in_(variant_ids))
                )
            )
        if seller_ids:
            product_ids.update(
                session.scalars(
                    select(ProductVariant.product_id)
                    .join(Offer, Offer.variant_id == ProductVariant.id)
                    .where(Offer.seller_id.in_(seller_ids), Offer.status != OfferStatus.REMOVED)
                )
            )
    queue_rebuild(session, product_ids)


# -- staff tools and the product-request form (D.8, AD-07) ------------------------


def add_synonym(db: Session, actor: Actor, *, term: str, expansion: str) -> SearchSynonym:
    """Searching `term` also searches `expansion` (AD-07). Audit-logged."""
    term_normalized, expansion_normalized = normalize_text(term), normalize_text(expansion)
    if not term_normalized or not expansion_normalized:
        raise ValidationFailed("synonym_empty", "Both words need letters or digits.")
    if term_normalized == expansion_normalized:
        raise ValidationFailed("synonym_same", "A word cannot be its own synonym.")
    if db.scalar(select(SearchSynonym.id).where(SearchSynonym.term_normalized == term_normalized)):
        raise Conflict("synonym_exists", "That word already has a synonym.")
    synonym = SearchSynonym(
        term=term.strip(), term_normalized=term_normalized,
        expansion=expansion.strip(), expansion_normalized=expansion_normalized,
    )  # fmt: skip
    db.add(synonym)
    db.flush()
    record_by(
        db, actor, "search.add_synonym", "search_synonym", synonym.id,
        after={"term": term_normalized, "expansion": expansion_normalized},
    )  # fmt: skip
    return synonym


def remove_synonym(db: Session, actor: Actor, synonym_id: uuid.UUID) -> None:
    synonym = db.get(SearchSynonym, synonym_id)
    if synonym is None:
        raise NotFound("synonym_not_found", "That synonym was not found.")
    record_by(
        db, actor, "search.remove_synonym", "search_synonym", synonym.id,
        before={"term": synonym.term_normalized, "expansion": synonym.expansion_normalized},
    )  # fmt: skip
    db.delete(synonym)
    db.flush()


def request_product(
    db: Session,
    *,
    query: str,
    note: str | None,
    contact_phone: str | None,
    user_id: uuid.UUID | None,
) -> ProductRequest:
    """ "Can't find it? Ask for it" from an empty search (D.8). Catalogue staff
    read the requests; nobody is promised an answer."""
    phone = None
    if contact_phone:
        try:
            phone = normalize_phone(contact_phone)
        except InvalidPhoneNumber as exc:
            raise ValidationFailed("phone_invalid", "Enter an Ethiopian mobile number.") from exc
    request = ProductRequest(query=query.strip(), note=note, contact_phone=phone, user_id=user_id)
    db.add(request)
    db.flush()
    return request
