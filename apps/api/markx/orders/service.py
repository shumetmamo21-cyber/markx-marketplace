"""Cart, checkout and seller orders (blueprint D.10, D.11, G.5 to G.7, P9, P10).

`place_order`, `seller_respond`, `cancel_by_buyer` and
`expire_unanswered_orders` are the blueprint's critical operations (G.7). Each
runs in the caller's one transaction and is the only way to do what it does.

Nothing the browser sends is trusted. The browser says which offers, how many,
which address and which delivery method; every price, fee and total is read
again from the database here.

Locking. One operation may need several rows. They are always taken in this
order, and within a kind in ascending id order, so no two operations can each
hold what the other waits for:

    cart  ->  sellers  ->  offers  ->  seller orders  ->  stock (by offer id)

Rows that other rows point at (sellers, offers, seller orders) are locked with
FOR NO KEY UPDATE, never plain FOR UPDATE (D-027). Stock moves only through
`markx.offers.service`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import Address, User, UserStatus
from markx.accounts.permissions import SELLER_PERMISSIONS, SellerCapability, seller_can
from markx.audit import service as audit
from markx.audit.service import Actor
from markx.catalog import selectors as catalog_selectors
from markx.catalog.models import Product, ProductStatus, ProductVariant
from markx.core import settings_store
from markx.core.codes import new_order_code
from markx.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.core.money import Money
from markx.core.phone import InvalidPhoneNumber, normalize_phone
from markx.core.security import (
    constant_time_equal,
    derive_numeric_code,
    hash_token,
    new_token,
    sign,
)
from markx.delivery.models import (
    MAX_HANDOVER_ATTEMPTS,
    DeliveryArea,
    DeliveryMode,
    DeliveryRate,
    DeliveryZone,
    Shipment,
    ShipmentStatus,
    TrackingEvent,
)
from markx.delivery.selectors import active_rates_for_zone
from markx.notifications import service as notifications
from markx.offers import selectors as offer_selectors
from markx.offers import service as offers
from markx.offers.models import (
    Inventory,
    InventoryReservation,
    Offer,
    OfferStatus,
    ReservationStatus,
)
from markx.orders.deadlines import response_deadline
from markx.orders.models import (
    MAX_QUANTITY_PER_LINE,
    ActorType,
    Cart,
    CartItem,
    Order,
    OrderItem,
    OrderStatusEvent,
    PaymentMode,
    SellerOrder,
    SellerOrderStatus,
)
from markx.orders.status import (
    AWAITING_HANDOVER,
    CLOSED_WITH_REASON,
    OPEN,
    PAYABLE,
    move_allowed,
)
from markx.payments import ledger
from markx.payments.models import (
    CommissionRule,
    FeeCharge,
    IntentStatus,
    PaymentAttempt,
    PaymentIntent,
    RuleScope,
)
from markx.sellers.models import Seller, SellerMember, SellerStatus, Store
from markx.trust.models import CaseDecision, CaseStatus, DisputeCase, DisputeMessage

MAX_CART_LINES = 30
EXPIRY_BATCH = 200

logger = logging.getLogger("markx.orders")
HANDOVER_CODE_PURPOSE = "handover"
# A tracking link outlives the longest order: fourteen days of hold, delivery,
# the problem window, and time to read the message (D-048).
TRACKING_LINK_SECONDS = 60 * 24 * 3600
_RULE_ORDER = (RuleScope.SELLER, RuleScope.PLAN, RuleScope.CATEGORY, RuleScope.DEFAULT)


def _now() -> datetime:
    return datetime.now(UTC)


# -- the cart --------------------------------------------------------------------


def user_cart(db: Session, user_id: uuid.UUID, *, create: bool, lock: bool = False) -> Cart | None:
    """The signed-in person's cart. With `lock`, the row is held until the
    transaction ends, which makes one buyer's checkouts run one at a time."""
    query = select(Cart).where(Cart.user_id == user_id)
    if lock:
        query = query.with_for_update()
    cart = db.scalar(query)
    if cart is None and create:
        # Two first requests at once: the unique constraint lets one insert win.
        db.execute(
            insert(Cart)
            .values(id=uuid7(), user_id=user_id)
            .on_conflict_do_nothing(index_elements=[Cart.user_id])
        )
        cart = db.scalar(query)
    return cart


def cart_for_token(db: Session, token: str) -> Cart | None:
    """An anonymous visitor's cart, found by the secret in their cookie. Only
    the token's hash is stored, as for sessions."""
    return db.scalar(select(Cart).where(Cart.anon_token_hash == hash_token(token)))


def create_anonymous_cart(db: Session) -> tuple[Cart, str]:
    token = new_token()
    cart = Cart(id=uuid7(), anon_token_hash=hash_token(token))
    db.add(cart)
    db.flush()
    return cart, token


def merge_anonymous_cart(db: Session, user_id: uuid.UUID, token: str) -> None:
    """A visitor filled a cart and then signed in: the lines move to their own
    cart, and the anonymous cart is gone. For a line in both, the larger
    quantity is kept."""
    anonymous = cart_for_token(db, token)
    if anonymous is None:
        return
    own = user_cart(db, user_id, create=True, lock=True)
    assert own is not None
    existing = {
        item.offer_id: item
        for item in db.scalars(select(CartItem).where(CartItem.cart_id == own.id))
    }
    for item in db.scalars(
        select(CartItem).where(CartItem.cart_id == anonymous.id).order_by(CartItem.created_at)
    ):
        mine = existing.get(item.offer_id)
        if mine is not None:
            mine.quantity = max(mine.quantity, item.quantity)
            mine.price_seen_santim = item.price_seen_santim
        elif len(existing) < MAX_CART_LINES:
            moved = CartItem(
                cart_id=own.id,
                offer_id=item.offer_id,
                quantity=item.quantity,
                price_seen_santim=item.price_seen_santim,
            )
            db.add(moved)
            existing[item.offer_id] = moved
    db.flush()
    db.execute(delete(Cart).where(Cart.id == anonymous.id))


def _min_level(db: Session) -> int:
    return settings_store.get_int(db, "sellers.min_level_to_publish")


def _check_quantity(quantity: int) -> None:
    if not 1 <= quantity <= MAX_QUANTITY_PER_LINE:
        raise ValidationFailed(
            "quantity_invalid", f"Choose a quantity from 1 to {MAX_QUANTITY_PER_LINE}."
        )


def set_cart_item(db: Session, cart: Cart, offer_id: uuid.UUID, quantity: int) -> None:
    """Put an offer in the cart, or change how many. The price recorded is the
    offer's price now: that is what the buyer is looking at."""
    _check_quantity(quantity)
    price = db.scalar(
        select(Offer.price_santim)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            Offer.id == offer_id,
            Offer.status == OfferStatus.ACTIVE,
            Seller.status == SellerStatus.ACTIVE,
            Seller.verification_level >= _min_level(db),
            ProductVariant.is_active,
            Product.status == ProductStatus.APPROVED,
        )
    )
    if price is None:
        # An offer buyers cannot see looks exactly like one that does not exist.
        raise NotFound("offer_not_found", "That offer was not found.")
    in_cart = set(db.scalars(select(CartItem.offer_id).where(CartItem.cart_id == cart.id)))
    if offer_id not in in_cart and len(in_cart) >= MAX_CART_LINES:
        raise Conflict("cart_full", f"A cart holds up to {MAX_CART_LINES} different items.")
    db.execute(
        insert(CartItem)
        .values(
            id=uuid7(),
            cart_id=cart.id,
            offer_id=offer_id,
            quantity=quantity,
            price_seen_santim=price,
        )
        .on_conflict_do_update(
            index_elements=[CartItem.cart_id, CartItem.offer_id],
            set_={"quantity": quantity, "price_seen_santim": price},
        )
    )


def remove_cart_item(db: Session, cart: Cart, offer_id: uuid.UUID) -> None:
    db.execute(delete(CartItem).where(CartItem.cart_id == cart.id, CartItem.offer_id == offer_id))


def clear_cart(db: Session, cart: Cart) -> None:
    db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))


def accept_cart_changes(db: Session, cart: Cart) -> int:
    """The buyer has seen the new prices and carries on (blueprint D.10:
    "opening the cart re-checks prices and stock and says what changed").
    Returns how many lines had a new price."""
    changed = 0
    rows = db.execute(
        select(CartItem, Offer.price_santim)
        .join(Offer, Offer.id == CartItem.offer_id)
        .where(CartItem.cart_id == cart.id)
    ).all()
    for item, price in rows:
        if item.price_seen_santim != price:
            item.price_seen_santim = price
            changed += 1
    db.flush()
    return changed


# -- reading the cart against live data ----------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    """One cart line beside everything it depends on, as the database has it now."""

    item: CartItem
    offer: Offer
    seller: Seller
    store: Store
    variant: ProductVariant
    product: Product
    available: int

    @property
    def price(self) -> Money:
        return Money(self.offer.price_santim, self.offer.currency)

    @property
    def total(self) -> Money:
        return self.price * self.item.quantity


def load_lines(db: Session, cart_id: uuid.UUID, *, lock: bool = False) -> list[Line]:
    """The cart's lines in ascending offer id order.

    With `lock`, the sellers and then the offers are locked first, each in id
    order, so prices and statuses cannot change under an order being placed.
    """
    items = list(
        db.scalars(select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.offer_id))
    )
    if not items:
        return []
    offer_ids = [item.offer_id for item in items]
    if lock:
        seller_ids = set(db.scalars(select(Offer.seller_id).where(Offer.id.in_(offer_ids))))
        db.execute(
            select(Seller.id)
            .where(Seller.id.in_(seller_ids))
            .order_by(Seller.id)
            .with_for_update(key_share=True)
        )
        db.execute(
            select(Offer.id)
            .where(Offer.id.in_(offer_ids))
            .order_by(Offer.id)
            .with_for_update(key_share=True)
        )
    rows = db.execute(
        select(Offer, Seller, Store, ProductVariant, Product, Inventory)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .join(Inventory, Inventory.offer_id == Offer.id)
        .where(Offer.id.in_(offer_ids))
        .execution_options(populate_existing=True)
    ).all()
    by_offer = {offer.id: (offer, seller, store, variant, product, inv) for offer, seller, store, variant, product, inv in rows}  # fmt: skip
    lines = []
    for item in items:
        offer, seller, store, variant, product, inventory = by_offer[item.offer_id]
        lines.append(
            Line(
                item=item, offer=offer, seller=seller, store=store, variant=variant,
                product=product, available=max(inventory.on_hand - inventory.reserved, 0),
            )
        )  # fmt: skip
    return lines


def line_problem(line: Line, min_level: int) -> str | None:
    """Why this line cannot be ordered right now, or None (G.5 step 2)."""
    if line.offer.status != OfferStatus.ACTIVE:
        return "offer_not_available"
    if line.seller.status != SellerStatus.ACTIVE or line.seller.verification_level < min_level:
        return "seller_not_available"
    if line.product.status != ProductStatus.APPROVED or not line.variant.is_active:
        return "product_not_available"
    return None


@dataclass(frozen=True, slots=True)
class DeliveryOption:
    method: DeliveryMode
    fee: Money
    promised_hours: int | None


def delivery_options(
    lines: Sequence[Line], rates: Mapping[DeliveryMode, DeliveryRate]
) -> list[DeliveryOption]:
    """The ways one seller's lines can reach the buyer's zone (blueprint J.9).

    A method counts only if every line in the group offers it, because a
    seller order travels as one shipment. A rider or courier also needs a fee
    for the zone. Collection at the shop is always free.
    """
    options = []
    for method, flag in (
        (DeliveryMode.SELLER_RIDER, "delivers_by_seller_rider"),
        (DeliveryMode.PARTNER_COURIER, "delivers_by_partner_courier"),
    ):
        rate = rates.get(method)
        if rate is not None and all(getattr(line.offer, flag) for line in lines):
            options.append(DeliveryOption(method, Money(rate.fee_santim), rate.promised_hours))
    if all(line.offer.offers_shop_collection for line in lines):
        options.append(DeliveryOption(DeliveryMode.SHOP_COLLECTION, Money.zero(), None))
    return options


def group_by_seller(lines: Iterable[Line]) -> list[list[Line]]:
    """Lines grouped by seller, the groups in ascending seller id order."""
    groups: dict[uuid.UUID, list[Line]] = {}
    for line in lines:
        groups.setdefault(line.seller.id, []).append(line)
    return [groups[seller_id] for seller_id in sorted(groups)]


# -- the quote -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SellerQuote:
    seller: Seller
    store: Store
    lines: list[Line]
    delivery: DeliveryOption
    items_total: Money

    @property
    def total(self) -> Money:
        return self.items_total + self.delivery.fee


@dataclass(frozen=True, slots=True)
class Quote:
    address: Address
    area: DeliveryArea
    zone: DeliveryZone
    groups: list[SellerQuote]
    items_total: Money
    delivery_total: Money
    price_changes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def grand_total(self) -> Money:
        return self.items_total + self.delivery_total

    @property
    def lines(self) -> list[Line]:
        return [line for group in self.groups for line in group.lines]


def build_quote(
    db: Session,
    user: User,
    cart: Cart,
    *,
    address_id: uuid.UUID,
    deliveries: Mapping[str, str],
    lock: bool = False,
) -> Quote:
    """Price the cart for one address and one delivery choice per store.

    Everything is recomputed from the database: the cart contributes only
    which offers and how many. `deliveries` maps a store's link name to the
    chosen method.
    """
    address = accounts.get_own_address(db, user.id, address_id)
    area = db.get(DeliveryArea, address.delivery_area_id)
    zone = db.get(DeliveryZone, area.zone_id) if area is not None else None
    if area is None or zone is None or not area.is_active or not zone.is_active:
        raise Conflict(
            "address_not_served", "MarkX does not deliver to that address at the moment."
        )

    lines = load_lines(db, cart.id, lock=lock)
    if not lines:
        raise ValidationFailed("cart_empty", "Your cart is empty.")
    min_level = _min_level(db)
    unavailable = [
        {"offer_id": str(line.offer.id), "reason": problem}
        for line in lines
        if (problem := line_problem(line, min_level)) is not None
    ]
    if unavailable:
        raise Conflict(
            "cart_item_unavailable",
            "Something in your cart can no longer be ordered.",
            details={"items": unavailable},
        )

    rates = active_rates_for_zone(db, zone.id)
    groups: list[SellerQuote] = []
    for group in group_by_seller(lines):
        store = group[0].store
        options = {option.method.value: option for option in delivery_options(group, rates)}
        chosen = deliveries.get(store.slug)
        if chosen is None:
            raise ValidationFailed(
                "delivery_choice_missing",
                f"Choose how to receive the items from {store.name}.",
                details={"store_slug": store.slug, "methods": sorted(options)},
            )
        if chosen not in options:
            raise Conflict(
                "delivery_method_unavailable",
                f"{store.name} cannot send these items that way to your area.",
                details={"store_slug": store.slug, "methods": sorted(options)},
            )
        items_total = Money.zero()
        for line in group:
            items_total += line.total
        groups.append(SellerQuote(group[0].seller, store, group, options[chosen], items_total))
    unknown = sorted(set(deliveries) - {group.store.slug for group in groups})
    if unknown:
        raise ValidationFailed(
            "delivery_choice_unknown",
            "A delivery choice was sent for a store that is not in the cart.",
            details={"store_slugs": unknown},
        )

    items_total, delivery_total = Money.zero(), Money.zero()
    for quoted in groups:
        items_total += quoted.items_total
        delivery_total += quoted.delivery.fee
    price_changes = [
        {
            "offer_id": str(line.offer.id),
            "price_seen_santim": line.item.price_seen_santim,
            "price_santim": line.offer.price_santim,
        }
        for line in lines
        if line.item.price_seen_santim != line.offer.price_santim
    ]
    return Quote(address, area, zone, groups, items_total, delivery_total, price_changes)


# -- commission ----------------------------------------------------------------------


def commission_bps(
    db: Session, *, payment_kind: str, seller: Seller, category_id: uuid.UUID, at: datetime
) -> int:
    """The fee rate in force for one order line (blueprint J.8): the most
    specific rule wins, seller, then plan, then category, then default.

    No rule means no fee. Direct orders carry none in year one (D.19), and
    that is true because no direct rule exists, not because it is assumed here.
    """
    in_force = list(
        db.scalars(
            select(CommissionRule)
            .where(
                CommissionRule.payment_kind == payment_kind,
                CommissionRule.valid_from <= at,
                (CommissionRule.valid_to.is_(None)) | (CommissionRule.valid_to > at),
            )
            .order_by(CommissionRule.valid_from.desc(), CommissionRule.id.desc())
        )
    )
    for scope in _RULE_ORDER:
        for rule in in_force:
            if rule.scope == scope and _rule_applies(rule, seller, category_id):
                return rule.rate_bps
    return 0


def _rule_applies(rule: CommissionRule, seller: Seller, category_id: uuid.UUID) -> bool:
    if rule.scope == RuleScope.SELLER:
        return rule.seller_id == seller.id
    if rule.scope == RuleScope.PLAN:
        return rule.plan == seller.plan
    if rule.scope == RuleScope.CATEGORY:
        return rule.category_id == category_id
    return rule.scope == RuleScope.DEFAULT


# -- place_order (G.5) -----------------------------------------------------------------


def _new_code(db: Session) -> str:
    for _ in range(10):
        code = new_order_code()
        if db.scalar(select(Order.id).where(Order.code == code)) is None:
            return code
    raise RuntimeError("could not find a free order code")


def _address_snapshot(quote: Quote) -> dict[str, Any]:
    address, area, zone = quote.address, quote.area, quote.zone
    return {
        "address_id": str(address.id),
        "recipient_name": address.recipient_name,
        "phone": address.phone,
        "phone2": address.phone2,
        "area_name_am": area.name_am,
        "area_name_en": area.name_en,
        "zone_code": zone.code,
        "zone_name_am": zone.name_am,
        "zone_name_en": zone.name_en,
        "city": zone.city,
        "landmark": address.landmark,
        "latitude": address.latitude,
        "longitude": address.longitude,
        "driver_notes": address.driver_notes,
    }


@dataclass(frozen=True, slots=True)
class _ProductCopy:
    """What an order line copies from the catalogue, in both languages."""

    title_am: str
    title_en: str
    variant_labels: dict[uuid.UUID, tuple[str, str]]


def _product_copy(db: Session, product: Product) -> _ProductCopy:
    am = catalog_selectors.product_out(db, product, "am")
    en = catalog_selectors.product_out(db, product, "en")
    english = {variant["id"]: str(variant["label"]) for variant in en["variants"]}
    return _ProductCopy(
        # A product may have a name in one language only; fall back to it.
        title_am=str(am["name_am"] or am["name"]),
        title_en=str(en["name_en"] or en["name"]),
        variant_labels={
            variant["id"]: (str(variant["label"]), english.get(variant["id"], ""))
            for variant in am["variants"]
        },
    )


def _order_handlers(db: Session, seller_id: uuid.UUID) -> list[uuid.UUID]:
    """The members of a seller who are told about its orders (blueprint C.3)."""
    roles = [role.value for role in SELLER_PERMISSIONS[SellerCapability.HANDLE_ORDERS]]
    return list(
        db.scalars(
            select(SellerMember.user_id)
            .where(
                SellerMember.seller_id == seller_id,
                SellerMember.is_active,
                SellerMember.role.in_(roles),
            )
            .order_by(SellerMember.created_at)
        )
    )


def _notify_seller(db: Session, seller_order: SellerOrder, order: Order, template: str) -> None:
    for user_id in _order_handlers(db, seller_order.seller_id):
        notifications.notify(
            db, user_id, template,
            {
                "seller_id": str(seller_order.seller_id),
                "seller_order_id": str(seller_order.id),
                "order_code": order.code,
            },
        )  # fmt: skip


def _notify_buyer(db: Session, seller_order: SellerOrder, order: Order, template: str) -> None:
    notifications.notify(
        db, order.buyer_user_id, template,
        {"order_id": str(order.id), "seller_order_id": str(seller_order.id), "order_code": order.code},
    )  # fmt: skip


def next_best_offers(db: Session, seller_order: SellerOrder, order: Order) -> list[dict[str, Any]]:
    """For each line of a seller order, the best offer in stock for the same
    variant from another seller (C-26), ranked as on the product page for the
    buyer's delivery zone. Lines with no other offer are left out."""
    zone_code = order.address_snapshot.get("zone_code")
    found = []
    for item in db.scalars(
        select(OrderItem).where(OrderItem.seller_order_id == seller_order.id).order_by(OrderItem.id)
    ):
        offer = offer_selectors.next_best_offer(
            db, item.variant_id, zone_code=zone_code, exclude_seller_id=seller_order.seller_id
        )
        if offer is not None:
            found.append({"order_item_id": item.id, "quantity": item.quantity, "offer": offer})
    return found


def _suggest_next_best(db: Session, seller_order: SellerOrder, order: Order) -> None:
    """The seller declined or stayed silent: point the buyer at the next-best
    offer for each line (C-26). Identifiers only; the page reads the live
    price, which may have changed by the time the buyer looks."""
    for found in next_best_offers(db, seller_order, order):
        notifications.notify(
            db, order.buyer_user_id, "order.next_best_offer",
            {
                "order_id": str(order.id),
                "seller_order_id": str(seller_order.id),
                "order_code": order.code,
                "order_item_id": str(found["order_item_id"]),
                "variant_id": str(found["offer"]["variant_id"]),
                "product_slug": found["offer"]["product_slug"],
                "offer_id": str(found["offer"]["id"]),
            },
        )  # fmt: skip


def open_order_count(db: Session, user_id: uuid.UUID) -> int:
    """How many of this buyer's orders still have a part in progress."""
    return int(
        db.scalar(
            select(func.count(func.distinct(SellerOrder.order_id)))
            .join(Order, Order.id == SellerOrder.order_id)
            .where(Order.buyer_user_id == user_id, SellerOrder.status.in_(list(OPEN)))
        )
        or 0
    )


def place_order(
    db: Session,
    user: User,
    *,
    address_id: uuid.UUID,
    deliveries: Mapping[str, str],
    payment_method: str,
    expected_total_santim: int,
    idempotency_key: str,
    channel: str = "web",
    now: datetime | None = None,
) -> tuple[Order, bool]:
    """Turn the buyer's cart into one order with a seller order per seller.

    Returns the order and whether it already existed: the same idempotency key
    sent again returns the first order and changes nothing. Any refusal raises,
    and the caller's rollback undoes every stock hold taken so far.
    """
    now = now or _now()
    # The cart row is the buyer's lock: two submissions wait for each other,
    # so the second one finds the order the first one made.
    cart = user_cart(db, user.id, create=True, lock=True)
    assert cart is not None
    existing = db.scalar(
        select(Order).where(
            Order.buyer_user_id == user.id, Order.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing, True
    if user.status != UserStatus.ACTIVE:
        raise PermissionDenied("account_not_active", "This account cannot place orders.")

    quote = build_quote(db, user, cart, address_id=address_id, deliveries=deliveries, lock=True)
    if quote.price_changes:
        raise Conflict(
            "price_changed",
            "A price changed since you last looked. Check your cart and try again.",
            details={"items": quote.price_changes},
        )
    # The total the buyer agreed to on the review step. It is compared, never
    # used: a browser that sends a lower figure is refused, not obeyed.
    if expected_total_santim != quote.grand_total.amount:
        raise Conflict(
            "total_changed",
            "The total is not what you were shown. Check your order and try again.",
            details={"total_santim": quote.grand_total.amount},
        )
    own = set(
        db.scalars(
            select(SellerMember.seller_id).where(
                SellerMember.user_id == user.id,
                SellerMember.is_active,
                SellerMember.seller_id.in_([group.seller.id for group in quote.groups]),
            )
        )
    )
    if own:
        raise PermissionDenied(
            "own_store",
            "You cannot order from a store you work for.",
            details={
                "store_slugs": sorted(g.store.slug for g in quote.groups if g.seller.id in own)
            },
        )
    if quote.grand_total.amount > settings_store.get_int(db, "orders.max_order_value_santim"):
        raise Conflict("order_too_large", "This order is above the largest total MarkX accepts.")
    if open_order_count(db, user.id) >= settings_store.get_int(db, "orders.max_open_direct_orders"):
        raise Conflict(
            "too_many_open_orders", "Finish or cancel an open order before placing another."
        )

    # Step 3: hold stock for every line, in ascending offer id order, before
    # anything else is written. One line short ends the whole order.
    item_ids = {line.offer.id: uuid7() for line in quote.lines}
    for line in sorted(quote.lines, key=lambda held: held.offer.id):
        if not offers.hold_stock(
            db, line.offer.id, line.item.quantity, reference_type="order_item",
            reference_id=item_ids[line.offer.id], actor_user_id=user.id,
        ):  # fmt: skip
            raise Conflict(
                "out_of_stock",
                "An item in your cart just sold out.",
                details={"offer_id": str(line.offer.id), "requested": line.item.quantity},
            )

    deadline = response_deadline(
        now,
        window_minutes=settings_store.get_int(db, "orders.response_window_minutes"),
        open_hour=settings_store.get_int(db, "orders.business_open_hour"),
        close_hour=settings_store.get_int(db, "orders.business_close_hour"),
    )
    order = Order(
        id=uuid7(),
        code=_new_code(db),
        buyer_user_id=user.id,
        payment_mode=PaymentMode.DIRECT.value,
        items_total_santim=quote.items_total.amount,
        delivery_total_santim=quote.delivery_total.amount,
        grand_total_santim=quote.grand_total.amount,
        address_snapshot=_address_snapshot(quote),
        delivery_zone_id=quote.zone.id,
        channel=channel,
        language=user.language,
        idempotency_key=idempotency_key,
    )
    db.add(order)
    db.flush()

    copies: dict[uuid.UUID, _ProductCopy] = {}
    seller_orders: list[SellerOrder] = []
    for index, group in enumerate(quote.groups, start=1):
        seller_order = SellerOrder(
            id=uuid7(),
            order_id=order.id,
            seller_id=group.seller.id,
            status=SellerOrderStatus.PLACED.value,
            items_total_santim=group.items_total.amount,
            delivery_fee_santim=group.delivery.fee.amount,
            total_santim=group.total.amount,
            response_deadline=deadline,
        )
        db.add(seller_order)
        db.flush()
        seller_orders.append(seller_order)
        for line in group.lines:
            product = line.product
            if product.id not in copies:
                copies[product.id] = _product_copy(db, product)
            copy = copies[product.id]
            label_am, label_en = copy.variant_labels.get(line.variant.id, ("", ""))
            db.add(
                OrderItem(
                    id=item_ids[line.offer.id],
                    seller_order_id=seller_order.id,
                    offer_id=line.offer.id,
                    product_id=product.id,
                    variant_id=line.variant.id,
                    # The line's own copy: it never reads the catalogue again (G.8 rule 4).
                    title_am=copy.title_am,
                    title_en=copy.title_en,
                    variant_label_am=label_am,
                    variant_label_en=label_en,
                    condition=line.offer.condition,
                    warranty_months=line.offer.warranty_months,
                    unit_price_santim=line.price.amount,
                    quantity=line.item.quantity,
                    line_total_santim=line.total.amount,
                    commission_bps=commission_bps(
                        db, payment_kind="direct", seller=group.seller,
                        category_id=product.category_id, at=now,
                    ),
                )
            )  # fmt: skip
        db.flush()
        for line in group.lines:
            # One reservation beside each hold (D-030). It expires with the
            # seller's response window; the worker returns the stock after it.
            db.add(
                InventoryReservation(
                    offer_id=line.offer.id,
                    order_item_id=item_ids[line.offer.id],
                    quantity=line.item.quantity,
                    expires_at=deadline,
                )
            )
        db.add(
            Shipment(
                seller_order_id=seller_order.id,
                mode=group.delivery.method.value,
                fee_santim=group.delivery.fee.amount,
                promised_hours=group.delivery.promised_hours,
            )
        )
        # What is due to this seller, paid to the seller directly. MarkX
        # records it and never holds the money (blueprint J.1).
        db.add(
            PaymentIntent(
                order_id=order.id,
                seller_order_id=seller_order.id,
                reference=f"{order.code}-{index}",
                amount_santim=group.total.amount,
                method=payment_method,
            )
        )
        db.add(
            OrderStatusEvent(
                seller_order_id=seller_order.id,
                from_status=None,
                to_status=SellerOrderStatus.PLACED.value,
                actor_type=ActorType.BUYER.value,
                actor_user_id=user.id,
                occurred_at=func.clock_timestamp(),
            )
        )
        db.flush()
        _notify_seller(db, seller_order, order, "order.placed_for_seller")
    notifications.notify(
        db, user.id, "order.placed",
        {
            "order_id": str(order.id),
            "order_code": order.code,
            # The page that opens from a Telegram or SMS message without sign-in (D.14).
            "tracking_path": issue_tracking_link(order, now=now).path,
        },
    )  # fmt: skip
    clear_cart(db, cart)
    db.flush()
    return order, False


# -- moving a seller order (G.6) -------------------------------------------------------


def _move(
    db: Session,
    seller_order: SellerOrder,
    to: SellerOrderStatus,
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    reason: str | None,
    now: datetime,
) -> None:
    """The one place a seller order changes status. Only the arrows of the
    state diagram are allowed, and every move writes its event (D.11)."""
    current = seller_order.status
    if not move_allowed(current, to.value):
        raise Conflict(
            "order_move_not_allowed", f"An order that is {current} cannot become {to.value}."
        )
    seller_order.status = to.value
    if to == SellerOrderStatus.CONFIRMED:
        seller_order.confirmed_at = now
    if to in CLOSED_WITH_REASON:
        seller_order.closed_reason = reason
    db.add(
        OrderStatusEvent(
            seller_order_id=seller_order.id,
            from_status=current,
            to_status=to.value,
            actor_type=actor_type.value,
            actor_user_id=actor_user_id,
            reason=reason,
            # The wall clock, so two moves in one transaction keep their order (D-028).
            occurred_at=func.clock_timestamp(),
        )
    )
    db.flush()


def _release_everything(
    db: Session,
    seller_order_ids: Sequence[uuid.UUID],
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """Give back the stock held for these seller orders and close what hung on
    them. The caller holds the seller orders' locks. Shipments not yet on the
    road are cancelled first, each with its tracking event, then releases run
    in ascending offer id order across all of them."""
    if not seller_order_ids:
        return
    waiting = db.scalars(
        select(Shipment)
        .where(
            Shipment.seller_order_id.in_(seller_order_ids),
            Shipment.status.in_((ShipmentStatus.PENDING, ShipmentStatus.READY)),
        )
        .order_by(Shipment.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    for shipment in list(waiting):
        _track(db, shipment, ShipmentStatus.CANCELLED, actor_type=actor_type, actor_user_id=actor_user_id)  # fmt: skip
    held = db.scalars(
        select(InventoryReservation)
        .join(OrderItem, OrderItem.id == InventoryReservation.order_item_id)
        .where(
            OrderItem.seller_order_id.in_(seller_order_ids),
            InventoryReservation.status == "held",
        )
        .order_by(InventoryReservation.offer_id, InventoryReservation.id)
        .with_for_update(of=InventoryReservation)
    )
    for reservation in held:
        offers.release_stock(
            db, reservation.offer_id, reservation.quantity, reference_type="order_item",
            reference_id=reservation.order_item_id, actor_user_id=actor_user_id,
        )  # fmt: skip
        reservation.status = "released"
        reservation.closed_at = now
    db.flush()
    db.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.seller_order_id.in_(seller_order_ids),
            PaymentIntent.status == IntentStatus.PENDING,
        )
        .values(status=IntentStatus.CANCELLED.value)
    )


def _parent(db: Session, seller_order: SellerOrder) -> Order:
    order = db.get(Order, seller_order.order_id)
    assert order is not None
    return order


def seller_respond(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    accept: bool,
    reason: str | None = None,
    now: datetime | None = None,
) -> SellerOrder:
    """The seller confirms or declines its part of an order (G.7).

    Only a member whose role handles orders, only for this seller's own order,
    only while it is `placed` and inside the response window. A decline gives
    the stock back.
    """
    now = now or _now()
    if not seller_can(member.role, SellerCapability.HANDLE_ORDERS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    if seller_order.status != SellerOrderStatus.PLACED:
        raise Conflict("order_not_awaiting_response", "This order is no longer waiting for you.")
    if now >= seller_order.response_deadline:
        raise Conflict("response_window_closed", "The time to answer this order has passed.")
    order = _parent(db, seller_order)
    if accept:
        if seller.status != SellerStatus.ACTIVE:
            raise Conflict("seller_not_active", "Your store must be active to confirm orders.")
        _move(
            db, seller_order, SellerOrderStatus.CONFIRMED, actor_type=ActorType.SELLER,
            actor_user_id=member.user_id, reason=None, now=now,
        )  # fmt: skip
        # The stock stays held while the order is packed and delivered.
        hold_until = now + timedelta(days=settings_store.get_int(db, "orders.fulfilment_hold_days"))
        db.execute(
            update(InventoryReservation)
            .where(
                InventoryReservation.status == "held",
                InventoryReservation.order_item_id.in_(
                    select(OrderItem.id).where(OrderItem.seller_order_id == seller_order.id)
                ),
            )
            .values(expires_at=hold_until)
        )
        _notify_buyer(db, seller_order, order, "order.seller_confirmed")
    else:
        if not reason:
            raise ValidationFailed("reason_required", "Say why you cannot fulfil this order.")
        _move(
            db, seller_order, SellerOrderStatus.DECLINED, actor_type=ActorType.SELLER,
            actor_user_id=member.user_id, reason=reason, now=now,
        )  # fmt: skip
        _release_everything(
            db,
            [seller_order.id],
            actor_type=ActorType.SELLER,
            actor_user_id=member.user_id,
            now=now,
        )
        _notify_buyer(db, seller_order, order, "order.seller_declined")
        _suggest_next_best(db, seller_order, order)
    return seller_order


_BUYER_MAY_CANCEL_FROM = (SellerOrderStatus.PLACED, SellerOrderStatus.CONFIRMED)


def cancel_by_buyer(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> SellerOrder:
    """The buyer cancels one seller's part of their own order, before it is
    packed. The stock goes back and the seller is told."""
    now = now or _now()
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user.id))
    if order is None:
        # The same answer for another buyer's order and one that does not exist.
        raise NotFound("order_not_found", "That order was not found.")
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.order_id == order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    if seller_order.status not in _BUYER_MAY_CANCEL_FROM:
        raise Conflict("order_cannot_be_cancelled", "This order can no longer be cancelled here.")
    _move(
        db, seller_order, SellerOrderStatus.CANCELLED, actor_type=ActorType.BUYER,
        actor_user_id=user.id, reason=reason or "cancelled_by_buyer", now=now,
    )  # fmt: skip
    _release_everything(
        db, [seller_order.id], actor_type=ActorType.BUYER, actor_user_id=user.id, now=now
    )
    _notify_seller(db, seller_order, order, "order.cancelled_by_buyer")
    return seller_order


def expire_unanswered_orders(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job (`expire_stale`, G.7): a seller order nobody answered in
    time expires and its stock returns (P10: "a silent seller's order expires
    and releases its stock"). Returns how many expired.

    An order someone is acting on this instant is skipped; it is picked up on
    the next run if it is still unanswered.
    """
    now = now or _now()
    due = list(
        db.scalars(
            select(SellerOrder)
            .where(
                SellerOrder.status == SellerOrderStatus.PLACED,
                SellerOrder.response_deadline <= now,
            )
            .order_by(SellerOrder.id)
            .limit(EXPIRY_BATCH)
            .with_for_update(key_share=True, skip_locked=True)
        )
    )
    for seller_order in due:
        _move(
            db, seller_order, SellerOrderStatus.EXPIRED, actor_type=ActorType.SYSTEM,
            actor_user_id=None, reason="no_answer_in_time", now=now,
        )  # fmt: skip
    _release_everything(
        db, [so.id for so in due], actor_type=ActorType.SYSTEM, actor_user_id=None, now=now
    )
    for seller_order in due:
        order = _parent(db, seller_order)
        _notify_buyer(db, seller_order, order, "order.seller_did_not_answer")
        _suggest_next_best(db, seller_order, order)
        _notify_seller(db, seller_order, order, "order.expired_unanswered")
    return len(due)


# -- fulfilment: the second half of the life cycle (G.6, J.9, J.10) -----------------------


def handover_code(shipment: Shipment) -> str:
    """The buyer's one-time code (C-15). Derived, never stored (D-011): the
    buyer's page can show it again at any time, and a copy of the database
    reveals nothing. Raising `code_version` issues a new one."""
    return derive_numeric_code(HANDOVER_CODE_PURPOSE, str(shipment.id), str(shipment.code_version))


def _own_seller_order(
    db: Session, seller: Seller, member: SellerMember, seller_order_id: uuid.UUID
) -> SellerOrder:
    """This seller's own part of an order, locked, for a member who handles
    orders. Another seller's part looks exactly like one that does not exist."""
    if not seller_can(member.role, SellerCapability.HANDLE_ORDERS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    return _lock_seller_order(db, seller_order_id, seller_id=seller.id)


def _lock_seller_order(
    db: Session, seller_order_id: uuid.UUID, *, seller_id: uuid.UUID | None = None
) -> SellerOrder:
    query = select(SellerOrder).where(SellerOrder.id == seller_order_id)
    if seller_id is not None:
        query = query.where(SellerOrder.seller_id == seller_id)
    seller_order = db.scalar(
        query.with_for_update(key_share=True).execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    return seller_order


def _shipment(db: Session, seller_order: SellerOrder) -> Shipment:
    """The seller order's one shipment, locked after the seller order (the
    tracking events point at it, so never a plain FOR UPDATE: D-027)."""
    shipment = db.scalar(
        select(Shipment)
        .where(Shipment.seller_order_id == seller_order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    assert shipment is not None, "a seller order is always created with its shipment"
    return shipment


def _track(
    db: Session,
    shipment: Shipment,
    status: ShipmentStatus,
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    """Every change to a shipment writes its tracking event (J.10)."""
    shipment.status = status.value
    db.add(
        TrackingEvent(
            shipment_id=shipment.id,
            status=status.value,
            note=note,
            source=actor_type.value,
            actor_user_id=actor_user_id,
            occurred_at=func.clock_timestamp(),
        )
    )
    db.flush()


def mark_ready(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> SellerOrder:
    """The order is packed (`confirmed -> ready`). A rider or collection order
    now carries a live handover code; a partner-courier job would appear on
    the staff dispatch board (P11, not built), so for now the seller dispatches."""
    now = now or _now()
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.READY, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.ready_at = now
    shipment = _shipment(db, seller_order)
    _track(db, shipment, ShipmentStatus.READY, actor_type=ActorType.SELLER, actor_user_id=member.user_id)  # fmt: skip
    order = _parent(db, seller_order)
    template = (
        "order.ready_for_collection"
        if shipment.mode == DeliveryMode.SHOP_COLLECTION
        else "order.ready"
    )
    _notify_buyer(db, seller_order, order, template)
    return seller_order


def _dispatch(
    db: Session,
    seller_order: SellerOrder,
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    rider_name: str | None,
    rider_phone: str | None,
    now: datetime,
) -> SellerOrder:
    """`ready -> out_for_delivery`, or a retry after a failed handover."""
    shipment = _shipment(db, seller_order)
    if shipment.mode == DeliveryMode.SHOP_COLLECTION:
        raise Conflict(
            "collection_order",
            "The buyer collects this order at the shop: enter their handover code instead.",
        )
    _move(
        db, seller_order, SellerOrderStatus.OUT_FOR_DELIVERY, actor_type=actor_type,
        actor_user_id=actor_user_id, reason=None, now=now,
    )  # fmt: skip
    if shipment.dispatched_at is None:
        shipment.dispatched_at = now
    if rider_name is not None:
        shipment.rider_name = rider_name
    if rider_phone is not None:
        try:
            shipment.rider_phone = normalize_phone(rider_phone)
        except InvalidPhoneNumber as exc:
            raise ValidationFailed("phone_invalid", "Enter an Ethiopian mobile number.") from exc
    shipment.failure_reason = None
    _track(db, shipment, ShipmentStatus.OUT_FOR_DELIVERY, actor_type=actor_type, actor_user_id=actor_user_id)  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.out_for_delivery")
    return seller_order


def seller_dispatch(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    rider_name: str | None = None,
    rider_phone: str | None = None,
    now: datetime | None = None,
) -> SellerOrder:
    """The seller's rider leaves with the parcel (S-12)."""
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    return _dispatch(
        db, seller_order, actor_type=ActorType.SELLER, actor_user_id=member.user_id,
        rider_name=rider_name, rider_phone=rider_phone, now=now or _now(),
    )  # fmt: skip


def staff_dispatch(
    db: Session,
    actor: Actor,
    seller_order_id: uuid.UUID,
    *,
    rider_name: str | None = None,
    rider_phone: str | None = None,
    now: datetime | None = None,
) -> SellerOrder:
    """Staff send a parcel out, for a partner courier (J.9) or on a seller's
    behalf. Audit-logged; the event names the role, never the person."""
    seller_order = _lock_seller_order(db, seller_order_id)
    _dispatch(
        db, seller_order, actor_type=ActorType.STAFF, actor_user_id=actor.user_id,
        rider_name=rider_name, rider_phone=rider_phone, now=now or _now(),
    )  # fmt: skip
    audit.record_by(
        db, actor, "seller_order.dispatch", "seller_order", seller_order.id,
        after={"rider_name": rider_name},
    )  # fmt: skip
    return seller_order


def confirm_delivery(
    db: Session,
    seller_order: SellerOrder,
    *,
    code: str,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    now: datetime,
) -> SellerOrder:
    """The buyer gives the code and the goods change hands (G.7, C-15).

    The code is compared in constant time against the derived value. A wrong
    code counts, and the count is kept even though the request fails, as for
    login codes; after `MAX_HANDOVER_ATTEMPTS` nothing is accepted until
    staff issue a new code. A right code marks `delivered` and starts the
    problem window.
    """
    if seller_order.status not in (SellerOrderStatus.READY, SellerOrderStatus.OUT_FOR_DELIVERY):
        raise Conflict("order_not_awaiting_handover", "This order is not waiting for a handover.")
    shipment = _shipment(db, seller_order)
    if (
        seller_order.status == SellerOrderStatus.READY
        and shipment.mode != DeliveryMode.SHOP_COLLECTION
    ):
        raise Conflict("order_not_dispatched", "Dispatch the order before entering the code.")
    if shipment.handover_attempts >= MAX_HANDOVER_ATTEMPTS:
        raise Conflict(
            "handover_code_locked",
            "Too many wrong codes. Ask MarkX to issue the buyer a new code.",
        )
    if not constant_time_equal(code.strip(), handover_code(shipment)):
        shipment.handover_attempts += 1
        attempts_left = MAX_HANDOVER_ATTEMPTS - shipment.handover_attempts
        # The wrong attempt must be remembered even though this request fails.
        db.commit()
        if attempts_left <= 0:
            raise Conflict(
                "handover_code_locked",
                "Too many wrong codes. Ask MarkX to issue the buyer a new code.",
                details={"attempts_left": 0},
            )
        raise Conflict(
            "handover_code_wrong",
            "That is not the buyer's code.",
            details={"attempts_left": attempts_left},
        )
    _move(
        db, seller_order, SellerOrderStatus.DELIVERED, actor_type=actor_type,
        actor_user_id=actor_user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.delivered_at = now
    seller_order.problem_window_ends_at = now + timedelta(
        hours=settings_store.get_int(db, "orders.problem_window_hours")
    )
    shipment.delivered_at = now
    _track(db, shipment, ShipmentStatus.DELIVERED, actor_type=actor_type, actor_user_id=actor_user_id)  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.delivered")
    return seller_order


def seller_confirm_delivery(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    code: str,
    now: datetime | None = None,
) -> SellerOrder:
    """The seller, or its rider through the seller's account, enters the
    buyer's code at the door or at the counter."""
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    return confirm_delivery(
        db, seller_order, code=code, actor_type=ActorType.SELLER, actor_user_id=member.user_id,
        now=now or _now(),
    )  # fmt: skip


def report_delivery_failed(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    reason: str,
    now: datetime | None = None,
) -> SellerOrder:
    """The handover did not happen (`out_for_delivery -> delivery_failed`).
    The reason is recorded; a retry dispatches again."""
    now = now or _now()
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.DELIVERY_FAILED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=reason, now=now,
    )  # fmt: skip
    shipment = _shipment(db, seller_order)
    shipment.failure_reason = reason
    _track(
        db, shipment, ShipmentStatus.DELIVERY_FAILED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, note=reason,
    )  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.delivery_failed")
    return seller_order


def return_to_seller(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    reason: str,
    now: datetime | None = None,
) -> SellerOrder:
    """The goods go back to the shelf (`delivery_failed -> returned`): the
    held stock is released and the pending payment intent cancelled."""
    now = now or _now()
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.RETURNED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=reason, now=now,
    )  # fmt: skip
    _release_everything(
        db, [seller_order.id], actor_type=ActorType.SELLER, actor_user_id=member.user_id, now=now
    )
    shipment = _shipment(db, seller_order)
    _track(
        db, shipment, ShipmentStatus.RETURNED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, note=reason,
    )  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.returned")
    return seller_order


def _commit_held_stock(
    db: Session, seller_order: SellerOrder, *, actor_user_id: uuid.UUID | None, now: datetime
) -> None:
    """The goods are gone from the shop for good: every unit held for this
    seller order leaves `on_hand`, in ascending offer id order. The caller
    holds the seller order's lock. The only caller of `commit_stock`."""
    held = list(
        db.scalars(
            select(InventoryReservation)
            .join(OrderItem, OrderItem.id == InventoryReservation.order_item_id)
            .where(
                OrderItem.seller_order_id == seller_order.id,
                InventoryReservation.status == ReservationStatus.HELD,
            )
            .order_by(InventoryReservation.offer_id, InventoryReservation.id)
            .with_for_update(of=InventoryReservation)
        )
    )
    for reservation in held:
        offers.commit_stock(
            db, reservation.offer_id, reservation.quantity, reference_type="order_item",
            reference_id=reservation.order_item_id, actor_user_id=actor_user_id,
        )  # fmt: skip
        reservation.status = ReservationStatus.COMMITTED.value
        reservation.closed_at = now


def complete_seller_order(
    db: Session,
    seller_order: SellerOrder,
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    now: datetime,
) -> SellerOrder:
    """`delivered -> completed` (G.7): the stock leaves the shop and the fee
    is charged.

    The caller holds the seller order's lock. Each held reservation is
    committed in ascending offer id order through `commit_stock`, the only
    code that lowers `on_hand`; then the fee is computed from the rate copied
    onto each line at placement (D-042), on item value only (J.8), written to
    `fee_charges` and, when above zero, posted to the ledger (G.10 rule 4).
    """
    _move(
        db, seller_order, SellerOrderStatus.COMPLETED, actor_type=actor_type,
        actor_user_id=actor_user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.completed_at = now
    _commit_held_stock(db, seller_order, actor_user_id=actor_user_id, now=now)
    items = list(
        db.scalars(
            select(OrderItem)
            .where(OrderItem.seller_order_id == seller_order.id)
            .order_by(OrderItem.id)
        )
    )
    fee = Money.zero()
    for item in items:
        fee += Money(item.line_total_santim).portion_bps(item.commission_bps)
    seller_order.commission_santim = fee.amount
    order = _parent(db, seller_order)
    charge = FeeCharge(
        seller_order_id=seller_order.id,
        item_value_santim=seller_order.items_total_santim,
        amount_santim=fee.amount,
    )
    if fee.amount > 0:
        charge.ledger_transaction_id = ledger.charge_fee(
            db, seller_id=seller_order.seller_id, seller_order_id=seller_order.id, fee=fee,
            order_code=order.code,
        ).id  # fmt: skip
    db.add(charge)
    db.flush()
    _notify_buyer(db, seller_order, order, "order.completed")
    _notify_seller(db, seller_order, order, "order.completed_for_seller")
    return seller_order


def confirm_received(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> SellerOrder:
    """The buyer says the goods are right: the part completes at once instead
    of when the problem window closes (G.6)."""
    now = now or _now()
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user.id))
    if order is None:
        raise NotFound("order_not_found", "That order was not found.")
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.order_id == order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    if seller_order.status != SellerOrderStatus.DELIVERED:
        raise Conflict("order_not_delivered", "Only a delivered order can be confirmed received.")
    return complete_seller_order(
        db, seller_order, actor_type=ActorType.BUYER, actor_user_id=user.id, now=now
    )


def complete_after_problem_window(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job: a delivered seller order whose problem window passed
    without a report completes (G.6: "the window passed"). Returns how many.

    Each order completes in its own savepoint (D-060), so one that fails (a
    bug, a stock row out of line, a deadlock) is undone alone, stays
    `delivered`, is logged with its id and is tried again on the next run,
    while every other due order completes. The database's commit-time checks
    (the balanced ledger, the event for every status change) are made to run
    inside the savepoint too (`SET CONSTRAINTS ALL IMMEDIATE`), because a
    violation found only at the job's commit would undo every order at once.
    """
    now = now or _now()
    due = list(
        db.scalars(
            select(SellerOrder)
            .where(
                SellerOrder.status == SellerOrderStatus.DELIVERED,
                SellerOrder.problem_window_ends_at <= now,
            )
            .order_by(SellerOrder.id)
            .limit(EXPIRY_BATCH)
            .with_for_update(key_share=True, skip_locked=True)
        )
    )
    completed = 0
    for seller_order in due:
        seller_order_id = seller_order.id
        try:
            with db.begin_nested():
                complete_seller_order(
                    db, seller_order, actor_type=ActorType.SYSTEM, actor_user_id=None, now=now
                )
                # Every check that is deferred to commit runs here instead,
                # while this order's work can still be undone alone.
                db.execute(text("set constraints all immediate"))
        except Exception:
            logger.exception(
                "a seller order could not complete; it stays delivered and is tried again",
                extra={
                    "seller_order_id": str(seller_order_id),
                    "job": "complete_after_problem_window",
                },
            )
        else:
            completed += 1
        finally:
            # All four deferrable checks are declared INITIALLY DEFERRED.
            db.execute(text("set constraints all deferred"))
    return completed


def cancel_overdue_fulfilment(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job (D-043): a confirmed or ready seller order whose
    fulfilment hold on the stock has expired is cancelled and its stock
    returns. A parcel already on the road is never touched here."""
    now = now or _now()
    overdue = (
        select(OrderItem.seller_order_id)
        .join(InventoryReservation, InventoryReservation.order_item_id == OrderItem.id)
        .where(
            InventoryReservation.status == ReservationStatus.HELD,
            InventoryReservation.expires_at <= now,
        )
    )
    due = list(
        db.scalars(
            select(SellerOrder)
            .where(
                SellerOrder.status.in_((SellerOrderStatus.CONFIRMED, SellerOrderStatus.READY)),
                SellerOrder.id.in_(overdue),
            )
            .order_by(SellerOrder.id)
            .limit(EXPIRY_BATCH)
            .with_for_update(key_share=True, skip_locked=True)
        )
    )
    for seller_order in due:
        _move(
            db, seller_order, SellerOrderStatus.CANCELLED, actor_type=ActorType.SYSTEM,
            actor_user_id=None, reason="fulfilment_hold_expired", now=now,
        )  # fmt: skip
    _release_everything(
        db, [so.id for so in due], actor_type=ActorType.SYSTEM, actor_user_id=None, now=now
    )
    for seller_order in due:
        order = _parent(db, seller_order)
        _notify_buyer(db, seller_order, order, "order.cancelled_not_fulfilled")
        _notify_seller(db, seller_order, order, "order.cancelled_not_fulfilled_for_seller")
    return len(due)


def record_direct_payment(
    db: Session,
    seller: Seller,
    member: SellerMember,
    actor: Actor,
    seller_order_id: uuid.UUID,
    *,
    method: str,
    now: datetime | None = None,
) -> SellerOrder:
    """The seller says the buyer paid them directly (D.12, Release 1).

    Recorded as the seller's word, with the method and the server's time; the
    status does not move (`paid` belongs to Protected prepay). Never from a
    browser redirect: this is a signed-in member's deliberate action, and it
    is audit-logged.
    """
    now = now or _now()
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    if seller_order.status not in PAYABLE:
        raise Conflict("payment_not_recordable", "This order is not one the buyer owes you for.")
    if seller_order.paid_at is not None:
        raise Conflict("already_paid", "A payment was already recorded for this order.")
    intent = db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.seller_order_id == seller_order.id)
        .with_for_update(key_share=True)
    )
    assert intent is not None, "a seller order is always created with its payment intent"
    seller_order.paid_method = method
    seller_order.paid_at = now
    intent.status = IntentStatus.SUCCEEDED.value
    intent.method = method
    intent.settled_at = now
    db.add(
        PaymentAttempt(
            intent_id=intent.id,
            status="succeeded",
            raw_result={"recorded_by": "seller", "method": method},
            recorded_by_user_id=member.user_id,
        )
    )
    db.flush()
    audit.record_by(
        db, actor, "seller_order.record_payment", "seller_order", seller_order.id,
        after={"method": method, "amount_santim": intent.amount_santim},
    )  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.payment_recorded")
    return seller_order


def staff_reissue_handover_code(
    db: Session, actor: Actor, seller_order_id: uuid.UUID, *, reason: str
) -> SellerOrder:
    """Staff issue the buyer a new code, after a lockout or a leak: the
    version rises, so the old code is dead, and the attempt count restarts."""
    seller_order = _lock_seller_order(db, seller_order_id)
    if seller_order.status not in AWAITING_HANDOVER:
        raise Conflict("order_not_awaiting_handover", "This order is not waiting for a handover.")
    shipment = _shipment(db, seller_order)
    before = shipment.code_version
    shipment.code_version += 1
    shipment.handover_attempts = 0
    db.flush()
    audit.record_by(
        db, actor, "shipment.reissue_handover_code", "shipment", shipment.id,
        before={"code_version": before}, after={"code_version": shipment.code_version, "reason": reason},
    )  # fmt: skip
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.handover_code_reissued")
    return seller_order


# -- problems on a delivered order (D.17, G.6, G.7: open_dispute, resolve_dispute) ----------


def dispute_case(db: Session, seller_order_id: uuid.UUID) -> DisputeCase | None:
    return db.scalar(select(DisputeCase).where(DisputeCase.seller_order_id == seller_order_id))


def open_dispute(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    *,
    problem_type: str,
    description: str,
    now: datetime | None = None,
) -> SellerOrder:
    """The buyer reports a problem (`delivered -> disputed`, C-16), only on
    their own delivered order and only inside the problem window. The part no
    longer completes by itself: staff decide (`resolve_dispute`)."""
    now = now or _now()
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user.id))
    if order is None:
        raise NotFound("order_not_found", "That order was not found.")
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.order_id == order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    if seller_order.status != SellerOrderStatus.DELIVERED:
        raise Conflict(
            "order_not_delivered", "A problem can be reported only on a delivered order."
        )
    window_end = seller_order.problem_window_ends_at
    if window_end is None or now >= window_end:
        raise Conflict("problem_window_closed", "The time to report a problem has passed.")
    _move(
        db, seller_order, SellerOrderStatus.DISPUTED, actor_type=ActorType.BUYER,
        actor_user_id=user.id, reason=problem_type, now=now,
    )  # fmt: skip
    db.add(
        DisputeCase(
            seller_order_id=seller_order.id,
            opened_by_user_id=user.id,
            problem_type=problem_type,
            description=description,
            decision_due_at=now
            + timedelta(hours=settings_store.get_int(db, "orders.problem_decision_hours")),
        )
    )
    db.flush()
    _notify_buyer(db, seller_order, order, "order.problem_reported")
    _notify_seller(db, seller_order, order, "order.problem_reported_for_seller")
    return seller_order


def _add_dispute_message(
    db: Session, seller_order: SellerOrder, *, author_type: ActorType, user_id: uuid.UUID, body: str
) -> DisputeCase:
    """One side adds its account or evidence to an open case. The caller holds
    the seller order's lock, which is what guards the case."""
    case = dispute_case(db, seller_order.id)
    if case is None:
        raise NotFound("problem_not_found", "No problem was reported on this order.")
    if case.status == CaseStatus.RESOLVED:
        raise Conflict("problem_already_resolved", "This problem has already been decided.")
    db.add(
        DisputeMessage(
            case_id=case.id, author_type=author_type.value, author_user_id=user_id, body=body
        )
    )
    db.flush()
    return case


def seller_reply_to_dispute(
    db: Session, seller: Seller, member: SellerMember, seller_order_id: uuid.UUID, *, body: str
) -> SellerOrder:
    """The seller answers a reported problem (S-16)."""
    seller_order = _own_seller_order(db, seller, member, seller_order_id)
    case = _add_dispute_message(
        db, seller_order, author_type=ActorType.SELLER, user_id=member.user_id, body=body
    )
    if case.status == CaseStatus.OPEN:
        case.status = CaseStatus.SELLER_RESPONDED.value
        db.flush()
    _notify_buyer(db, seller_order, _parent(db, seller_order), "order.problem_seller_replied")
    return seller_order


def buyer_add_to_dispute(
    db: Session, user: User, order_id: uuid.UUID, seller_order_id: uuid.UUID, *, body: str
) -> SellerOrder:
    """The buyer adds to their own open case."""
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user.id))
    if order is None:
        raise NotFound("order_not_found", "That order was not found.")
    # Found together with the buyer's own order, so a stranger's guess never
    # locks someone else's row.
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.order_id == order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    _add_dispute_message(db, seller_order, author_type=ActorType.BUYER, user_id=user.id, body=body)
    _notify_seller(db, seller_order, order, "order.problem_buyer_added")
    return seller_order


def resolve_dispute(
    db: Session,
    actor: Actor,
    seller_order_id: uuid.UUID,
    *,
    decision: CaseDecision,
    reason: str,
    goods_returned: bool = False,
    now: datetime | None = None,
) -> SellerOrder:
    """Staff decide a reported problem (G.7, AD-09), with a written reason.

    `no_action`: the part completes as any other (`disputed -> completed`):
    the stock is committed and the fee charged.

    `seller_refunded`: `disputed -> refunded`. MarkX holds no money, so this
    records that the seller gave the buyer's money back directly (G.6). No fee
    is charged: the fee is charged only at completion, which a refunded part
    never reaches, so there is nothing to reverse (D-050). The held stock
    goes back on sale if staff say the goods went back to the shop, and
    leaves the shop's count otherwise (D-049).
    """
    now = now or _now()
    assert actor.user_id is not None, "a dispute is decided by a signed-in member of staff"
    seller_order = _lock_seller_order(db, seller_order_id)
    if seller_order.status != SellerOrderStatus.DISPUTED:
        raise Conflict("order_not_disputed", "No problem is waiting for a decision on this order.")
    case = dispute_case(db, seller_order.id)
    assert case is not None, "a disputed seller order always has its case"
    order = _parent(db, seller_order)
    if decision == CaseDecision.NO_ACTION:
        if goods_returned:
            raise ValidationFailed(
                "goods_returned_without_refund",
                "Goods that went back to the shop mean a refund, not a completed order.",
            )
        complete_seller_order(
            db, seller_order, actor_type=ActorType.STAFF, actor_user_id=actor.user_id, now=now
        )
    else:
        _move(
            db, seller_order, SellerOrderStatus.REFUNDED, actor_type=ActorType.STAFF,
            actor_user_id=actor.user_id, reason=decision.value, now=now,
        )  # fmt: skip
        if goods_returned:
            _release_everything(
                db,
                [seller_order.id],
                actor_type=ActorType.STAFF,
                actor_user_id=actor.user_id,
                now=now,
            )
        else:
            _commit_held_stock(db, seller_order, actor_user_id=actor.user_id, now=now)
            # Nothing is owed any more on a part the buyer never paid for.
            db.execute(
                update(PaymentIntent)
                .where(
                    PaymentIntent.seller_order_id == seller_order.id,
                    PaymentIntent.status == IntentStatus.PENDING,
                )
                .values(status=IntentStatus.CANCELLED.value)
            )
        _notify_buyer(db, seller_order, order, "order.refunded")
        _notify_seller(db, seller_order, order, "order.refunded_for_seller")
    case.status = CaseStatus.RESOLVED.value
    case.decision = decision.value
    case.decision_reason = reason
    case.resolved_by_user_id = actor.user_id
    case.resolved_at = now
    db.flush()
    audit.record_by(
        db, actor, "dispute.resolve", "dispute_case", case.id,
        before={"status": SellerOrderStatus.DISPUTED.value},
        after={
            "seller_order_id": str(seller_order.id), "decision": decision.value,
            "goods_returned": goods_returned, "reason": reason,
        },
    )  # fmt: skip
    return seller_order


# -- the tracking page by secure link (D.14, C-10) ------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackingLink:
    path: str
    expires_at: datetime


def _tracking_signature(order_id: uuid.UUID, expires: int) -> str:
    return sign("order-tracking-link", str(order_id), str(expires), length=43)


def issue_tracking_link(order: Order, *, now: datetime | None = None) -> TrackingLink:
    """A link to the buyer's order page that needs no sign-in. It cannot be
    guessed (a 256-bit signature over the order id and its expiry), it shows
    only what the buyer needs, and it never shows the handover code."""
    expires = int((now or _now()).timestamp()) + TRACKING_LINK_SECONDS
    return TrackingLink(
        path=f"/api/v1/track/{order.id}?expires={expires}&signature={_tracking_signature(order.id, expires)}",
        expires_at=datetime.fromtimestamp(expires, UTC),
    )


def open_tracking_link(
    db: Session, order_id: uuid.UUID, *, expires: int, signature: str, now: datetime | None = None
) -> Order:
    """The order behind a tracking link, or "not found" for a link that is
    forged, expired or for an order that does not exist: one answer for all."""
    invalid = NotFound("tracking_link_invalid", "This link is not valid any more.")
    moment = int((now or _now()).timestamp())
    if not constant_time_equal(signature, _tracking_signature(order_id, expires)):
        raise invalid
    if expires < moment or expires > moment + TRACKING_LINK_SECONDS:
        raise invalid
    order = db.get(Order, order_id)
    if order is None:
        raise invalid
    return order
