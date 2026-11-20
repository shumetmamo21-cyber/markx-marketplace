"""Offers and inventory (blueprint D.7, G.4, G.9, P7).

An offer is one seller's terms for one variant. Many sellers attach offers to
the same variant; each controls only its own price and stock.

Functions that take a `Seller` trust the caller to have loaded it for the
person acting (routes use `require_seller`). An offer is always looked up
together with the seller it must belong to, so another seller's offer id is
simply "not found".

Locking. An offer row is locked with FOR NO KEY UPDATE (`key_share=True`),
never plain FOR UPDATE. A stock movement's foreign key takes a key-share lock
on its offer; a plain FOR UPDATE would block that, and a seller editing an
offer while a buyer holds its stock would deadlock (a test reproduces it).

Stock rules (G.9), enforced here and by CHECK constraints on `inventory`:

* Stock changes only through this module, and every change writes an
  `inventory_movements` row in the same transaction.
* `hold_stock` is one conditional UPDATE that succeeds only if enough is
  free. Two buyers racing for the last unit cannot both win, whatever the
  isolation level, because the second UPDATE waits for the first and then
  sees its result.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.catalog.models import Product, ProductStatus, ProductVariant
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.notifications import service as notifications
from markx.offers.models import (
    Condition,
    Inventory,
    InventoryMovement,
    MovementReason,
    Offer,
    OfferPriceHistory,
    OfferStatus,
)
from markx.search import service as search
from markx.sellers.models import Seller, SellerMember, SellerRole, SellerStatus
from markx.trust import conflict

MAX_PRICE_SANTIM = 10_000_000_000  # ETB 100 million: a typing mistake, not a price
MAX_STOCK = 1_000_000
# Blueprint D.3: used phones only from Level 2 upward.
# PROVISIONAL (F-04, D-083): every used item needs Level 2, in every category,
# not only phones; narrow it per category later if one needs it.
#   The engineer's guess at the founder's request; THE FOUNDER MUST CONFIRM OR
#   CHANGE IT BEFORE MARKX GOES LIVE.
USED_GOODS_MIN_LEVEL = 2


def _now() -> datetime:
    return datetime.now(UTC)


# -- guards ----------------------------------------------------------------------


def _require_trading(seller: Seller) -> None:
    """Only an approved, unsuspended seller changes its listings."""
    if seller.status != SellerStatus.ACTIVE:
        raise Conflict(
            "seller_not_active", "Your store must be approved and active to manage offers."
        )


def _check_price(price_santim: int) -> None:
    if not 0 < price_santim <= MAX_PRICE_SANTIM:
        raise ValidationFailed("price_invalid", "Enter a price above zero.")


def _check_condition(seller: Seller, condition: str) -> None:
    if condition == Condition.USED and seller.verification_level < USED_GOODS_MIN_LEVEL:
        raise PermissionDenied(
            "used_goods_need_level_two", "Used items can be sold from verification level 2."
        )


def get_own_offer(
    db: Session, seller_id: uuid.UUID, offer_id: uuid.UUID, *, lock: bool = False
) -> Offer:
    query = select(Offer).where(Offer.id == offer_id, Offer.seller_id == seller_id)
    if lock:
        query = query.with_for_update(key_share=True)
    offer = db.scalar(query)
    if offer is None:
        raise NotFound("offer_not_found", "That offer was not found.")
    return offer


def _offer_snapshot(offer: Offer) -> dict[str, object]:
    return {
        "status": offer.status,
        "price_santim": offer.price_santim,
        "condition": offer.condition,
        "warranty_months": offer.warranty_months,
        "delivers_by_seller_rider": offer.delivers_by_seller_rider,
        "delivers_by_partner_courier": offer.delivers_by_partner_courier,
        "offers_shop_collection": offer.offers_shop_collection,
    }


# -- stock primitives ------------------------------------------------------------


def _movement(
    db: Session,
    offer_id: uuid.UUID,
    *,
    delta_on_hand: int,
    delta_reserved: int,
    on_hand_after: int,
    reserved_after: int,
    reason: MovementReason,
    reference_type: str | None,
    reference_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
) -> None:
    # Search keeps "in stock" and the lowest in-stock price: only a move that
    # takes an offer in or out of stock changes a search document.
    available_after = on_hand_after - reserved_after
    available_before = available_after - delta_on_hand + delta_reserved
    if (available_before > 0) != (available_after > 0):
        search.queue_for_offers(db, [offer_id])
    db.add(
        InventoryMovement(
            offer_id=offer_id,
            delta_on_hand=delta_on_hand,
            delta_reserved=delta_reserved,
            on_hand_after=on_hand_after,
            reserved_after=reserved_after,
            reason=reason.value,
            reference_type=reference_type,
            reference_id=reference_id,
            actor_user_id=actor_user_id,
            # The wall clock at the moment of writing, not the transaction's
            # start time: every movement is written while its inventory row is
            # locked, so this orders an offer's movements exactly, even several
            # written by one transaction.
            created_at=func.clock_timestamp(),
        )
    )
    db.flush()


_HOLD = text(
    """
    update inventory
       set reserved = reserved + :qty, updated_at = now()
     where offer_id = :offer_id
       and on_hand - reserved >= :qty
    returning on_hand, reserved
    """
)
_RELEASE = text(
    """
    update inventory
       set reserved = reserved - :qty, updated_at = now()
     where offer_id = :offer_id
       and reserved >= :qty
    returning on_hand, reserved
    """
)
_COMMIT = text(
    """
    update inventory
       set reserved = reserved - :qty, on_hand = on_hand - :qty, updated_at = now()
     where offer_id = :offer_id
       and reserved >= :qty
    returning on_hand, reserved
    """
)


def _positive(quantity: int) -> None:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("quantity must be a whole number above zero")


def hold_stock(
    db: Session,
    offer_id: uuid.UUID,
    quantity: int,
    *,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> bool:
    """Reserve stock for an order line (blueprint G.9).

    Returns False when not enough is free; the caller then rolls the whole
    order back. Checkout must call this for its lines in a fixed order (by
    offer id) so two orders can never deadlock.
    """
    _positive(quantity)
    row = db.execute(_HOLD, {"offer_id": offer_id, "qty": quantity}).first()
    if row is None:
        return False
    _movement(
        db, offer_id, delta_on_hand=0, delta_reserved=quantity, on_hand_after=row.on_hand,
        reserved_after=row.reserved, reason=MovementReason.RESERVE,
        reference_type=reference_type, reference_id=reference_id, actor_user_id=actor_user_id,
    )  # fmt: skip
    return True


def release_stock(
    db: Session,
    offer_id: uuid.UUID,
    quantity: int,
    *,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Give held stock back: the order was declined, cancelled or expired."""
    _positive(quantity)
    row = db.execute(_RELEASE, {"offer_id": offer_id, "qty": quantity}).first()
    if row is None:
        raise RuntimeError(f"offer {offer_id} does not hold {quantity} reserved units to release")
    _movement(
        db, offer_id, delta_on_hand=0, delta_reserved=-quantity, on_hand_after=row.on_hand,
        reserved_after=row.reserved, reason=MovementReason.RELEASE,
        reference_type=reference_type, reference_id=reference_id, actor_user_id=actor_user_id,
    )  # fmt: skip


def commit_stock(
    db: Session,
    offer_id: uuid.UUID,
    quantity: int,
    *,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Held stock leaves the shop: the order completed."""
    _positive(quantity)
    row = db.execute(_COMMIT, {"offer_id": offer_id, "qty": quantity}).first()
    if row is None:
        raise RuntimeError(f"offer {offer_id} does not hold {quantity} reserved units to commit")
    _movement(
        db, offer_id, delta_on_hand=-quantity, delta_reserved=-quantity,
        on_hand_after=row.on_hand, reserved_after=row.reserved, reason=MovementReason.COMMIT,
        reference_type=reference_type, reference_id=reference_id, actor_user_id=actor_user_id,
    )  # fmt: skip


def _set_on_hand(
    db: Session,
    offer: Offer,
    on_hand: int,
    *,
    reason: MovementReason,
    actor_user_id: uuid.UUID | None,
) -> Inventory:
    """Set the counted stock. The row lock makes the read-then-write safe
    against a concurrent hold, which waits and then sees the new count."""
    if not 0 <= on_hand <= MAX_STOCK:
        raise ValidationFailed("stock_invalid", "Enter a stock count from 0 upward.")
    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.offer_id == offer.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert inventory is not None, "an offer is always created with its inventory row"
    if on_hand < inventory.reserved:
        raise Conflict(
            "stock_below_reserved",
            f"{inventory.reserved} units are held for open orders; stock cannot go below that.",
            details={"reserved": inventory.reserved},
        )
    delta = on_hand - inventory.on_hand
    if delta != 0:
        inventory.on_hand = on_hand
        db.flush()
        _movement(
            db, offer.id, delta_on_hand=delta, delta_reserved=0, on_hand_after=on_hand,
            reserved_after=inventory.reserved, reason=reason, reference_type=None,
            reference_id=None, actor_user_id=actor_user_id,
        )  # fmt: skip
    return inventory


# -- offers (seller) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OfferInput:
    variant_id: uuid.UUID
    condition: str
    price_santim: int
    quantity: int
    warranty_months: int = 0
    warranty_note: str | None = None
    delivers_by_seller_rider: bool = False
    delivers_by_partner_courier: bool = False
    offers_shop_collection: bool = True
    low_stock_threshold: int = 2


def _check_delivery(rider: bool, courier: bool, collection: bool) -> None:
    if not (rider or courier or collection):
        raise ValidationFailed(
            "delivery_option_required", "Choose at least one way for the buyer to get the item."
        )


def create_offer(db: Session, actor: Actor, seller: Seller, data: OfferInput) -> Offer:
    """Attach the seller's offer to an approved product's variant (S-04).

    One offer per seller, variant and condition: the unique constraint decides,
    so two simultaneous requests cannot create two. An offer the seller removed
    earlier is brought back with the new terms instead.
    """
    _require_trading(seller)
    _check_price(data.price_santim)
    _check_condition(seller, data.condition)
    _check_delivery(
        data.delivers_by_seller_rider, data.delivers_by_partner_courier, data.offers_shop_collection
    )
    if not 0 <= data.quantity <= MAX_STOCK:
        raise ValidationFailed("stock_invalid", "Enter a stock count from 0 upward.")
    found = db.execute(
        select(ProductVariant, Product)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(ProductVariant.id == data.variant_id)
    ).first()
    if found is None or not found[0].is_active or found[1].status != ProductStatus.APPROVED:
        # A draft, a proposal still in review and an archived product all look
        # the same to a seller: there is nothing to attach an offer to.
        raise NotFound("variant_not_found", "That product version was not found.")

    now = _now()
    existing = db.scalar(
        select(Offer)
        .where(
            Offer.seller_id == seller.id,
            Offer.variant_id == data.variant_id,
            Offer.condition == data.condition,
        )
        .with_for_update(key_share=True)
    )
    if existing is not None:
        if existing.status != OfferStatus.REMOVED:
            raise Conflict(
                "offer_exists",
                "You already have an offer for this version and condition.",
                details={"offer_id": str(existing.id)},
            )
        if existing.removed_by_staff_at is not None:
            # Moderation holds: only staff can let this listing return.
            raise PermissionDenied(
                "offer_removed_by_staff",
                "MarkX staff took this listing down. Contact support to list it again.",
                details={"offer_id": str(existing.id)},
            )
        offer, old_price = existing, existing.price_santim
        offer.status = OfferStatus.ACTIVE
        offer.price_santim = data.price_santim
        offer.price_confirmed_at = now
        offer.stock_confirmed_at = now
        action = "offer.relist"
    else:
        offer, old_price = Offer(
            id=uuid7(), seller_id=seller.id, variant_id=data.variant_id, condition=data.condition,
            price_santim=data.price_santim, status=OfferStatus.ACTIVE,
            price_confirmed_at=now, stock_confirmed_at=now,
        ), None  # fmt: skip
        db.add(offer)
        action = "offer.create"
    offer.warranty_months = data.warranty_months
    offer.warranty_note = data.warranty_note
    offer.delivers_by_seller_rider = data.delivers_by_seller_rider
    offer.delivers_by_partner_courier = data.delivers_by_partner_courier
    offer.offers_shop_collection = data.offers_shop_collection
    try:
        db.flush()
    except IntegrityError as exc:
        # Lost a race with an identical request: the unique constraint held.
        db.rollback()
        raise Conflict(
            "offer_exists", "You already have an offer for this version and condition."
        ) from exc

    if existing is None:
        db.add(
            Inventory(offer_id=offer.id, on_hand=0, low_stock_threshold=data.low_stock_threshold)
        )
        db.flush()
    else:
        db.execute(
            update(Inventory)
            .where(Inventory.offer_id == offer.id)
            .values(low_stock_threshold=data.low_stock_threshold)
        )
    reason = MovementReason.INITIAL if existing is None else MovementReason.SELLER_ADJUST
    _set_on_hand(db, offer, data.quantity, reason=reason, actor_user_id=actor.user_id)
    if old_price != data.price_santim:
        db.add(
            OfferPriceHistory(
                offer_id=offer.id, old_price_santim=old_price, new_price_santim=data.price_santim,
                changed_by_user_id=actor.user_id, changed_at=now,
            )
        )  # fmt: skip
    db.flush()
    record_by(
        db, actor, action, "offer", offer.id,
        after={**_offer_snapshot(offer), "seller_id": str(seller.id),
               "variant_id": str(offer.variant_id), "quantity": data.quantity},
    )  # fmt: skip
    return offer


def update_offer(
    db: Session,
    actor: Actor,
    seller: Seller,
    offer_id: uuid.UUID,
    *,
    price_santim: int | None = None,
    warranty_months: int | None = None,
    warranty_note: str | None = None,
    delivers_by_seller_rider: bool | None = None,
    delivers_by_partner_courier: bool | None = None,
    offers_shop_collection: bool | None = None,
) -> Offer:
    """Quick edit (S-04, S-24). A price change is written to the price
    history and counts as confirming the price."""
    _require_trading(seller)
    offer = get_own_offer(db, seller.id, offer_id, lock=True)
    if offer.status == OfferStatus.REMOVED:
        raise Conflict("offer_removed", "That offer was removed. Create it again to relist.")
    before = _offer_snapshot(offer)
    now = _now()
    if price_santim is not None and price_santim != offer.price_santim:
        _check_price(price_santim)
        db.add(
            OfferPriceHistory(
                offer_id=offer.id, old_price_santim=offer.price_santim,
                new_price_santim=price_santim, changed_by_user_id=actor.user_id, changed_at=now,
            )
        )  # fmt: skip
        offer.price_santim = price_santim
    if price_santim is not None:
        # Sending the price, changed or not, is the seller confirming it.
        offer.price_confirmed_at = now
        if offer.status == OfferStatus.STALE:
            offer.status = OfferStatus.ACTIVE
    if warranty_months is not None:
        offer.warranty_months = warranty_months
    if warranty_note is not None:
        offer.warranty_note = warranty_note or None
    if delivers_by_seller_rider is not None:
        offer.delivers_by_seller_rider = delivers_by_seller_rider
    if delivers_by_partner_courier is not None:
        offer.delivers_by_partner_courier = delivers_by_partner_courier
    if offers_shop_collection is not None:
        offer.offers_shop_collection = offers_shop_collection
    _check_delivery(
        offer.delivers_by_seller_rider, offer.delivers_by_partner_courier,
        offer.offers_shop_collection,
    )  # fmt: skip
    db.flush()
    after = _offer_snapshot(offer)
    if after != before:
        record_by(db, actor, "offer.update", "offer", offer.id, before=before, after=after)
    return offer


def set_stock(
    db: Session,
    actor: Actor,
    seller: Seller,
    offer_id: uuid.UUID,
    *,
    on_hand: int,
    low_stock_threshold: int | None = None,
) -> Inventory:
    """The seller counts the shelf and types the number (`adjust_stock`, G.7).
    Stock held for open orders stays held."""
    _require_trading(seller)
    offer = get_own_offer(db, seller.id, offer_id, lock=True)
    if offer.status == OfferStatus.REMOVED:
        raise Conflict("offer_removed", "That offer was removed. Create it again to relist.")
    inventory = _set_on_hand(
        db, offer, on_hand, reason=MovementReason.SELLER_ADJUST, actor_user_id=actor.user_id
    )
    if low_stock_threshold is not None:
        inventory.low_stock_threshold = low_stock_threshold
    offer.stock_confirmed_at = _now()
    db.flush()
    return inventory


def _change_status(
    db: Session, actor: Actor, offer: Offer, new_status: OfferStatus, action: str,
    *, reason: str | None = None,
) -> Offer:  # fmt: skip
    before = {"status": offer.status}
    offer.status = new_status.value
    db.flush()
    after: dict[str, object] = {"status": offer.status}
    if reason is not None:
        after["reason"] = reason
    record_by(db, actor, action, "offer", offer.id, before=before, after=after)
    return offer


def pause_offer(db: Session, actor: Actor, seller: Seller, offer_id: uuid.UUID) -> Offer:
    _require_trading(seller)
    offer = get_own_offer(db, seller.id, offer_id, lock=True)
    if offer.status not in (OfferStatus.ACTIVE, OfferStatus.STALE):
        raise Conflict("offer_not_live", "Only a live offer can be paused.")
    return _change_status(db, actor, offer, OfferStatus.PAUSED, "offer.pause")


def resume_offer(db: Session, actor: Actor, seller: Seller, offer_id: uuid.UUID) -> Offer:
    """Resuming is a statement that the price and stock are right today."""
    _require_trading(seller)
    offer = get_own_offer(db, seller.id, offer_id, lock=True)
    if offer.status != OfferStatus.PAUSED:
        raise Conflict("offer_not_paused", "Only a paused offer can be resumed.")
    offer.price_confirmed_at = offer.stock_confirmed_at = _now()
    return _change_status(db, actor, offer, OfferStatus.ACTIVE, "offer.resume")


def remove_offer(db: Session, actor: Actor, seller: Seller, offer_id: uuid.UUID) -> Offer:
    """Take the offer down. The row stays: orders and price history point at it."""
    offer = get_own_offer(db, seller.id, offer_id, lock=True)
    if offer.status == OfferStatus.REMOVED:
        raise Conflict("offer_removed", "That offer was already removed.")
    return _change_status(db, actor, offer, OfferStatus.REMOVED, "offer.remove")


def confirm_offers(
    db: Session, actor: Actor, seller: Seller, offer_ids: list[uuid.UUID] | None = None
) -> int:
    """The one-tap check-in (S-08): "my prices and stock are still right".

    Confirms the given offers, or every live one, and brings stale offers
    back. Paused and removed offers are left alone. Returns how many.
    """
    _require_trading(seller)
    now = _now()
    # Lock the rows in id order before changing them. Two statements that each
    # update many offers (this one and the stale-offer job) could otherwise
    # lock the same rows in different orders and deadlock.
    query = (
        select(Offer.id)
        .where(
            Offer.seller_id == seller.id,
            Offer.status.in_((OfferStatus.ACTIVE, OfferStatus.STALE)),
        )
        .order_by(Offer.id)
        .with_for_update(key_share=True)
    )
    if offer_ids is not None:
        query = query.where(Offer.id.in_(offer_ids))
    locked = list(db.scalars(query))
    if not locked:
        return 0
    db.execute(
        update(Offer)
        .where(Offer.id.in_(locked))
        .values(
            status=OfferStatus.ACTIVE,
            price_confirmed_at=now,
            stock_confirmed_at=now,
            updated_at=now,
        )
    )
    search.queue_for_offers(db, locked)
    record_by(db, actor, "offer.confirm", "seller", seller.id, after={"offers": len(locked)})
    return len(locked)


# -- staff moderation --------------------------------------------------------------


def staff_remove_offer(db: Session, actor: Actor, offer_id: uuid.UUID, *, reason: str) -> Offer:
    """Listing moderation (AD-03): staff take an offer down, with a reason."""
    offer = db.scalar(select(Offer).where(Offer.id == offer_id).with_for_update(key_share=True))
    if offer is None:
        raise NotFound("offer_not_found", "That offer was not found.")
    conflict.refuse_conflict(
        db, actor, action="offer.staff_remove", target_type="offer", target_id=offer.id,
        seller_ids=[offer.seller_id],
    )  # fmt: skip
    if offer.removed_by_staff_at is not None:
        raise Conflict("offer_removed", "That offer was already removed.")
    # An offer the seller removed first is held too: removing it yourself
    # must not be a way to dodge a takedown and list it again tomorrow.
    offer.removed_by_staff_at = _now()
    _change_status(db, actor, offer, OfferStatus.REMOVED, "offer.staff_remove", reason=reason)
    _notify_owner(db, offer, "offer.removed_by_staff")
    return offer


def staff_restore_offer(db: Session, actor: Actor, offer_id: uuid.UUID, *, reason: str) -> Offer:
    """Staff lift a takedown. Nothing is published by this: the offer stays
    removed, and the seller may list it again with today's price and stock."""
    offer = db.scalar(select(Offer).where(Offer.id == offer_id).with_for_update(key_share=True))
    if offer is None:
        raise NotFound("offer_not_found", "That offer was not found.")
    conflict.refuse_conflict(
        db, actor, action="offer.staff_restore", target_type="offer", target_id=offer.id,
        seller_ids=[offer.seller_id],
    )  # fmt: skip
    if offer.removed_by_staff_at is None:
        raise Conflict("offer_not_held", "That offer was not taken down by staff.")
    offer.removed_by_staff_at = None
    db.flush()
    record_by(
        db, actor, "offer.staff_restore", "offer", offer.id,
        before={"held": True}, after={"held": False, "reason": reason},
    )  # fmt: skip
    _notify_owner(db, offer, "offer.restored_by_staff")
    return offer


def _notify_owner(db: Session, offer: Offer, template: str) -> None:
    owner = db.scalar(
        select(SellerMember.user_id).where(
            SellerMember.seller_id == offer.seller_id,
            SellerMember.role == SellerRole.OWNER,
            SellerMember.is_active,
        )
    )
    if owner is not None:
        notifications.notify(
            db, owner, template, {"seller_id": str(offer.seller_id), "offer_id": str(offer.id)}
        )


# -- scheduled ---------------------------------------------------------------------


def mark_stale_offers(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job (`expire_stale`, G.7): an offer whose price was not
    confirmed for `offers.stale_after_days` is hidden until the seller checks
    in (blueprint D.7). Returns how many offers went stale."""
    now = now or _now()
    cutoff = now - timedelta(days=settings_store.get_int(db, "offers.stale_after_days"))
    # Rows are locked in id order (see `confirm_offers`). An offer its seller
    # is editing this instant is skipped: the edit confirms it, and if not,
    # the next run picks it up. The job never waits on a seller.
    stale = list(
        db.scalars(
            select(Offer.id)
            .where(Offer.status == OfferStatus.ACTIVE, Offer.price_confirmed_at < cutoff)
            .order_by(Offer.id)
            .with_for_update(key_share=True, skip_locked=True)
        )
    )
    if stale:
        db.execute(
            update(Offer)
            .where(Offer.id.in_(stale))
            .values(status=OfferStatus.STALE, updated_at=now)
        )
        search.queue_for_offers(db, stale)
    if stale:
        record_by(
            db, Actor.system(), "offer.mark_stale", "offers", "batch",
            after={"offers": len(stale), "cutoff": cutoff.isoformat()},
        )  # fmt: skip
    return len(stale)
