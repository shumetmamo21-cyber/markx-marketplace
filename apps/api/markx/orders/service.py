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

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import Address, User, UserStatus
from markx.accounts.permissions import SELLER_PERMISSIONS, SellerCapability, seller_can
from markx.audit.service import Actor, record_by
from markx.catalog import selectors as catalog_selectors
from markx.catalog.models import Product, ProductStatus, ProductVariant
from markx.core import settings_store
from markx.core.codes import new_order_code
from markx.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.core.money import Money
from markx.core.security import constant_time_equal, derive_numeric_code, hash_token, new_token
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
from markx.offers import service as offers
from markx.offers.models import Inventory, InventoryReservation, Offer, OfferStatus
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
from markx.orders.status import ENDED_WITHOUT_DELIVERY, OPEN, move_allowed
from markx.payments.models import (
    CommissionRule,
    FeeCharge,
    IntentStatus,
    PaymentAttempt,
    PaymentIntent,
    RuleScope,
)
from markx.sellers.models import Seller, SellerMember, SellerStatus, Store

MAX_CART_LINES = 30
EXPIRY_BATCH = 200
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
        db, user.id, "order.placed", {"order_id": str(order.id), "order_code": order.code}
    )
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
    if to in ENDED_WITHOUT_DELIVERY:
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
    db: Session, seller_order_ids: Sequence[uuid.UUID], *, actor_user_id: uuid.UUID | None, now: datetime
) -> None:  # fmt: skip
    """Give back the stock held for these seller orders and close what hung on
    them. Releases run in ascending offer id order across all of them."""
    if not seller_order_ids:
        return
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
        update(Shipment)
        .where(
            Shipment.seller_order_id.in_(seller_order_ids),
            Shipment.status.in_((ShipmentStatus.PENDING, ShipmentStatus.READY)),
        )
        .values(status=ShipmentStatus.CANCELLED.value, updated_at=now)
    )
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
        _release_everything(db, [seller_order.id], actor_user_id=member.user_id, now=now)
        _notify_buyer(db, seller_order, order, "order.seller_declined")
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
    _release_everything(db, [seller_order.id], actor_user_id=user.id, now=now)
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
    _release_everything(db, [so.id for so in due], actor_user_id=None, now=now)
    for seller_order in due:
        order = _parent(db, seller_order)
        _notify_buyer(db, seller_order, order, "order.seller_did_not_answer")
        _notify_seller(db, seller_order, order, "order.expired_unanswered")
    return len(due)


# -- fulfilment: the second half of the life cycle (G.6, G.7, J.9, J.10) -----------------

_PAYABLE = frozenset({
    SellerOrderStatus.CONFIRMED, SellerOrderStatus.READY, SellerOrderStatus.OUT_FOR_DELIVERY,
    SellerOrderStatus.DELIVERED, SellerOrderStatus.COMPLETED,
})  # fmt: skip
_SHOWS_CODE = frozenset({SellerOrderStatus.READY, SellerOrderStatus.OUT_FOR_DELIVERY})


def handover_code(shipment: Shipment) -> str:
    """The one-time handover code (C-15), derived from the server secret, the
    shipment and its code version (D-011): the buyer's page can show it at
    any time and the database holds nothing that reveals it."""
    return derive_numeric_code("handover", str(shipment.id), str(shipment.code_version))


def shows_handover_code(status: str) -> bool:
    return status in _SHOWS_CODE


def _own_seller_order(
    db: Session, seller: Seller, member: SellerMember, seller_order_id: uuid.UUID
) -> tuple[SellerOrder, Order, Shipment]:
    """This seller's part of an order, locked, with its shipment. Only a
    member whose role handles orders; another seller's part is not found."""
    if not seller_can(member.role, SellerCapability.HANDLE_ORDERS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    if seller.status != SellerStatus.ACTIVE:
        raise Conflict("seller_not_active", "Your store must be active to handle orders.")
    seller_order = db.scalar(
        select(SellerOrder)
        .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    shipment = db.scalar(
        select(Shipment)
        .where(Shipment.seller_order_id == seller_order.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    assert shipment is not None, "a seller order is always created with its shipment"
    return seller_order, _parent(db, seller_order), shipment


def _track(
    db: Session,
    shipment: Shipment,
    status: ShipmentStatus,
    *,
    source: str,
    actor_user_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    """The shipment's status and its append-only history (J.10)."""
    shipment.status = status.value
    db.add(
        TrackingEvent(
            shipment_id=shipment.id,
            status=status.value,
            note=note,
            source=source,
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
    """Packed and waiting for pickup or collection (G.6 `ready`)."""
    now = now or _now()
    seller_order, order, shipment = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.READY, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.ready_at = now
    _track(db, shipment, ShipmentStatus.READY, source="seller", actor_user_id=member.user_id)
    _notify_buyer(db, seller_order, order, "order.ready")
    return seller_order


def dispatch(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    rider_name: str | None,
    rider_phone: str | None,
    now: datetime | None = None,
) -> SellerOrder:
    """With the rider (G.6 `out_for_delivery`), first time or after a failed
    attempt. A collection order is never dispatched."""
    now = now or _now()
    seller_order, order, shipment = _own_seller_order(db, seller, member, seller_order_id)
    if shipment.mode == DeliveryMode.SHOP_COLLECTION:
        raise Conflict(
            "collection_is_not_dispatched",
            "The buyer collects this order at the shop: enter their code at handover instead.",
        )
    _move(
        db, seller_order, SellerOrderStatus.OUT_FOR_DELIVERY, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=None, now=now,
    )  # fmt: skip
    if rider_name is not None:
        shipment.rider_name = rider_name
    if rider_phone is not None:
        shipment.rider_phone = accounts.parse_phone(rider_phone)
    shipment.dispatched_at = now
    shipment.failure_reason = None
    _track(
        db, shipment, ShipmentStatus.OUT_FOR_DELIVERY, source="seller", actor_user_id=member.user_id
    )
    _notify_buyer(db, seller_order, order, "order.out_for_delivery")
    return seller_order


def confirm_delivery(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    code: str,
    now: datetime | None = None,
) -> SellerOrder:
    """`confirm_delivery` (G.7): the buyer gives the code only after seeing the
    goods. A wrong code is counted even though the request fails; after
    `MAX_HANDOVER_ATTEMPTS` the shipment is locked until staff issue a new
    code. A right code marks `delivered` and starts the problem window."""
    now = now or _now()
    seller_order, order, shipment = _own_seller_order(db, seller, member, seller_order_id)
    if seller_order.status not in _SHOWS_CODE:
        raise Conflict("order_not_deliverable", "This order is not out for handover.")
    if (
        seller_order.status == SellerOrderStatus.READY
        and shipment.mode != DeliveryMode.SHOP_COLLECTION
    ):
        raise Conflict("order_not_dispatched", "Mark the order out for delivery first.")
    if shipment.handover_attempts >= MAX_HANDOVER_ATTEMPTS:
        raise PermissionDenied(
            "handover_locked", "Too many wrong codes. Ask MarkX support to issue a new code."
        )
    if not constant_time_equal(code.strip(), handover_code(shipment)):
        shipment.handover_attempts += 1
        left = MAX_HANDOVER_ATTEMPTS - shipment.handover_attempts
        record_by(
            db, Actor(type="user", user_id=member.user_id), "shipment.handover_code_wrong",
            "shipment", shipment.id, after={"attempts": shipment.handover_attempts},
        )  # fmt: skip
        # Remembered even though this request fails: the count is the guard.
        db.commit()
        raise PermissionDenied(
            "handover_code_wrong", "That is not the buyer's code.", details={"attempts_left": left}
        )
    _move(
        db, seller_order, SellerOrderStatus.DELIVERED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.delivered_at = now
    seller_order.problem_window_ends_at = now + timedelta(
        hours=settings_store.get_int(db, "orders.problem_window_hours")
    )
    shipment.delivered_at = now
    _track(db, shipment, ShipmentStatus.DELIVERED, source="seller", actor_user_id=member.user_id)
    _notify_buyer(db, seller_order, order, "order.delivered")
    return seller_order


def report_delivery_failure(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    reason: str,
    now: datetime | None = None,
) -> SellerOrder:
    now = now or _now()
    seller_order, order, shipment = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.DELIVERY_FAILED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=reason, now=now,
    )  # fmt: skip
    shipment.failure_reason = reason
    _track(
        db, shipment, ShipmentStatus.DELIVERY_FAILED, source="seller",
        actor_user_id=member.user_id, note=reason,
    )  # fmt: skip
    _notify_buyer(db, seller_order, order, "order.delivery_failed")
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
    """The goods go back to the shop (G.6 `returned`): the held stock returns."""
    now = now or _now()
    seller_order, order, shipment = _own_seller_order(db, seller, member, seller_order_id)
    _move(
        db, seller_order, SellerOrderStatus.RETURNED, actor_type=ActorType.SELLER,
        actor_user_id=member.user_id, reason=reason, now=now,
    )  # fmt: skip
    seller_order.closed_reason = reason
    _release_everything(db, [seller_order.id], actor_user_id=member.user_id, now=now)
    _track(
        db, shipment, ShipmentStatus.RETURNED, source="seller", actor_user_id=member.user_id,
        note=reason,
    )  # fmt: skip
    _notify_buyer(db, seller_order, order, "order.returned")
    return seller_order


def _complete(
    db: Session,
    seller_order: SellerOrder,
    order: Order,
    *,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """`complete_seller_order` (G.7): the held stock leaves the shop and the
    fee is charged, from the rate each line carried (D.19). Nothing moves money."""
    _move(
        db, seller_order, SellerOrderStatus.COMPLETED, actor_type=actor_type,
        actor_user_id=actor_user_id, reason=None, now=now,
    )  # fmt: skip
    seller_order.completed_at = now
    held = db.scalars(
        select(InventoryReservation)
        .join(OrderItem, OrderItem.id == InventoryReservation.order_item_id)
        .where(OrderItem.seller_order_id == seller_order.id, InventoryReservation.status == "held")
        .order_by(InventoryReservation.offer_id, InventoryReservation.id)
        .with_for_update(of=InventoryReservation)
    )
    for reservation in held:
        offers.commit_stock(
            db, reservation.offer_id, reservation.quantity, reference_type="order_item",
            reference_id=reservation.order_item_id, actor_user_id=actor_user_id,
        )  # fmt: skip
        reservation.status = "committed"
        reservation.closed_at = now
    fee = Money.zero()
    for item in db.scalars(select(OrderItem).where(OrderItem.seller_order_id == seller_order.id)):
        fee += Money(item.line_total_santim).portion_bps(item.commission_bps)
    db.add(
        FeeCharge(
            seller_order_id=seller_order.id,
            item_value_santim=seller_order.items_total_santim,
            amount_santim=fee.amount,
        )
    )
    seller_order.commission_santim = fee.amount
    db.flush()
    _notify_seller(db, seller_order, order, "order.completed")
    _notify_buyer(db, seller_order, order, "order.completed")


def confirm_receipt(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> SellerOrder:
    """The buyer closes a delivered part early instead of waiting out the
    problem window (G.6 `delivered -> completed: buyer confirms`)."""
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
        raise Conflict("order_not_delivered", "This order has not been handed over yet.")
    _complete(db, seller_order, order, actor_type=ActorType.BUYER, actor_user_id=user.id, now=now)
    return seller_order


def complete_delivered_orders(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job: a delivered part whose problem window passed without a
    report is completed by the system. Returns how many."""
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
    for seller_order in due:
        _complete(
            db, seller_order, _parent(db, seller_order), actor_type=ActorType.SYSTEM,
            actor_user_id=None, now=now,
        )  # fmt: skip
    return len(due)


def record_direct_payment(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    method: str,
    now: datetime | None = None,
) -> SellerOrder:
    """Release 1, direct payment (D.12, J.3): the buyer paid the seller, the
    seller checked their own banking or wallet app and says so. MarkX records
    the method and the time, as the seller's word. Never from a redirect."""
    now = now or _now()
    seller_order, order, _ = _own_seller_order(db, seller, member, seller_order_id)
    if order.payment_mode != PaymentMode.DIRECT:
        raise Conflict("not_a_direct_order", "Only a direct order is marked paid by the seller.")
    if seller_order.status not in _PAYABLE:
        raise Conflict(
            "order_not_payable",
            "Payment is recorded once the order is confirmed and before it ends.",
        )
    if seller_order.paid_at is not None:
        raise Conflict("already_paid", "This order is already marked paid.")
    intent = db.scalar(
        select(PaymentIntent)
        .where(
            PaymentIntent.seller_order_id == seller_order.id,
            PaymentIntent.status == IntentStatus.PENDING,
        )
        .with_for_update()
    )
    if intent is None:
        raise Conflict("payment_intent_missing", "No payment is due on this order.")
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
    seller_order.paid_method = method
    seller_order.paid_at = now
    db.flush()
    record_by(
        db, Actor(type="user", user_id=member.user_id), "seller_order.record_payment",
        "seller_order", seller_order.id,
        after={"method": method, "amount_santim": intent.amount_santim, "reference": intent.reference},
    )  # fmt: skip
    _notify_buyer(db, seller_order, order, "order.payment_recorded")
    return seller_order
