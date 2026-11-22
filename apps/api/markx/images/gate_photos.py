"""A photo of the buyer's gate on an address (blueprint D.10, C-08, G.2; D-107).

A buyer may add one photo of their gate to a saved address, so whoever
brings the order finds the right door. The photo is private, exactly like
problem photos (C-16):

- **Stored privately.** The upload is checked like every picture
  (`images.service.clean_upload`), decoded and written out again as WebP,
  so nothing but its pixels survives: no camera metadata, no location. It
  goes to private storage under an unguessable key and is never edited or
  deleted (the table is append-only).
- **Opened only through a five-minute link** signed for the person who
  asked (and, for a shop, for that one order), who must be signed in as
  that person and *still* be allowed when the file is fetched.
- **Seen only by the people delivering the order.** Besides the buyer who
  took it: an active member of the shop whose order it is, in a role that
  handles orders and sees buyers' contacts (owner, manager, orders; C.3),
  while the shop is delivering it to the door: confirmed and not yet handed
  over (`DELIVERING`), by the shop's rider or the partner courier, never for
  collection at the shop. Staff never see it: they do not deliver, and the
  dispatch board shows no address. Every view by a shop is audited.

Each order keeps the photo's id in its address snapshot, so changing the
address's photo later never changes what an order shows.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.accounts.models import Address, GatePhoto
from markx.accounts.permissions import SellerCapability, seller_can
from markx.audit.service import Actor, record_by
from markx.core.errors import NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.core.images import ImageTooComplex, NotAnImage, decode_clean, render_webp
from markx.core.security import constant_time_equal, sign
from markx.core.storage import StoredFileMissing, get_private_storage
from markx.delivery.models import DeliveryMode, Shipment
from markx.images.service import clean_upload
from markx.orders.models import Order, SellerOrder
from markx.orders.models import SellerOrderStatus as S
from markx.sellers.models import SellerMember

# PROVISIONAL (P-107-2, D-107): enough to recognise a gate on a phone.
GATE_SIDE, GATE_MAX_BYTES = 1200, 300_000
LINK_SECONDS = 300
# PROVISIONAL (P-107-3, D-107): the shop is delivering it to the door, from
# its confirmation until the goods change hands (or come back).
DELIVERING = frozenset({S.CONFIRMED, S.PAID, S.READY, S.OUT_FOR_DELIVERY, S.DELIVERY_FAILED})
# Every one of these, and nothing else, opens the photo to a shop member.
_SHOP_CAPABILITIES = (SellerCapability.HANDLE_ORDERS, SellerCapability.SEE_BUYER_CONTACT)


def _now() -> datetime:
    return datetime.now(UTC)


# -- the buyer -------------------------------------------------------------------------


def _own_address(db: Session, user_id: uuid.UUID, address_id: uuid.UUID) -> Address:
    address = db.scalar(
        select(Address)
        .where(Address.id == address_id, Address.user_id == user_id, Address.archived_at.is_(None))
        .with_for_update()
    )
    if address is None:
        # The same answer whether the address is missing or someone else's.
        raise NotFound("address_not_found", "That address was not found.")
    return address


def set_gate_photo(
    db: Session, actor: Actor, user_id: uuid.UUID, address_id: uuid.UUID, data: bytes
) -> Address:
    """Add or replace the gate photo of one of the buyer's own addresses. The
    old photo's file stays: an order placed with it still shows it."""
    address = _own_address(db, user_id, address_id)
    upload = clean_upload(db, data)
    try:
        rendered = render_webp(
            decode_clean(upload.data), longest_side=GATE_SIDE, max_bytes=GATE_MAX_BYTES
        )
    except (NotAnImage, ImageTooComplex) as exc:
        raise ValidationFailed("image_not_a_photo", "Send a JPEG, PNG or WebP photo.") from exc
    photo_id = uuid7()
    file_key = f"gate-photos/{photo_id}-{secrets.token_hex(16)}"
    get_private_storage().put(file_key, rendered.data, "image/webp")
    photo = GatePhoto(
        id=photo_id, user_id=user_id, file_key=file_key, width=rendered.width,
        height=rendered.height, size_bytes=len(rendered.data),
    )  # fmt: skip
    db.add(photo)
    db.flush()
    before = str(address.gate_photo_id) if address.gate_photo_id else None
    address.gate_photo_id = photo.id
    db.flush()
    record_by(
        db, actor, "address.gate_photo_set", "address", address.id,
        before={"gate_photo_id": before},
        after={"gate_photo_id": str(photo.id), "size_bytes": len(rendered.data)},
    )  # fmt: skip
    return address


def remove_gate_photo(
    db: Session, actor: Actor, user_id: uuid.UUID, address_id: uuid.UUID
) -> Address:
    address = _own_address(db, user_id, address_id)
    if address.gate_photo_id is not None:
        before = str(address.gate_photo_id)
        address.gate_photo_id = None
        db.flush()
        record_by(
            db, actor, "address.gate_photo_removed", "address", address.id,
            before={"gate_photo_id": before}, after={"gate_photo_id": None},
        )  # fmt: skip
    return address


# -- links -----------------------------------------------------------------------------


def _signature(photo_id: uuid.UUID, viewer: uuid.UUID, order: str, expires: int) -> str:
    return sign("gate-photo-link", str(photo_id), str(viewer), order, str(expires), length=43)


def link(
    photo_id: uuid.UUID, viewer_user_id: uuid.UUID, *, seller_order_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """A five-minute link for one viewer (and, for a shop, one order)."""
    expires = int(_now().timestamp()) + LINK_SECONDS
    order = str(seller_order_id) if seller_order_id else "-"
    query = f"expires={expires}&signature={_signature(photo_id, viewer_user_id, order, expires)}"
    if seller_order_id:
        query = f"seller_order={seller_order_id}&{query}"
    return {
        "url": f"/api/v1/gate-photos/{photo_id}/content?{query}",
        "url_expires_at": datetime.fromtimestamp(expires, UTC),
    }


def _snapshot_photo(order: Order) -> uuid.UUID | None:
    raw = (order.address_snapshot or {}).get("gate_photo_id")
    return uuid.UUID(str(raw)) if raw else None


def visible_to_shop(seller_order: SellerOrder, order: Order, shipment: Shipment) -> bool:
    """Whether the shop is delivering this order to the buyer's door now, and
    the order carries a gate photo. The role is checked separately."""
    return (
        _snapshot_photo(order) is not None
        and shipment.mode != DeliveryMode.SHOP_COLLECTION
        and seller_order.confirmed_at is not None
        and seller_order.status in DELIVERING
    )


def _role_may_see(role: str | None) -> bool:
    return role is not None and all(seller_can(role, c) for c in _SHOP_CAPABILITIES)


def _delivering_row(
    db: Session, seller_order_id: uuid.UUID
) -> tuple[SellerOrder, Order, Shipment] | None:
    row = db.execute(
        select(SellerOrder, Order, Shipment)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Shipment, Shipment.seller_order_id == SellerOrder.id)
        .where(SellerOrder.id == seller_order_id)
    ).first()
    return (row[0], row[1], row[2]) if row else None


def shop_link(
    db: Session, seller_id: uuid.UUID, member: SellerMember, seller_order_id: uuid.UUID
) -> dict[str, Any]:
    """The gate photo of one of the shop's own orders, while it delivers it."""
    if not _role_may_see(member.role):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    found = _delivering_row(db, seller_order_id)
    if found is None or found[0].seller_id != seller_id:
        raise NotFound("order_not_found", "That order was not found.")
    seller_order, order, shipment = found
    photo_id = _snapshot_photo(order)
    if photo_id is None or not visible_to_shop(seller_order, order, shipment):
        raise NotFound("gate_photo_not_available", "There is no gate photo to show.")
    return link(photo_id, member.user_id, seller_order_id=seller_order.id)


def open_gate_photo(
    db: Session,
    actor: Actor,
    photo_id: uuid.UUID,
    *,
    seller_order_id: uuid.UUID | None,
    expires: int,
    signature: str,
    staff_session: bool,
) -> bytes:
    """The photo behind a signed link. The link must be unexpired and signed
    for this viewer (and order), and the viewer must *still* be allowed: the
    buyer who took it, or a member of the delivering shop as `visible_to_shop`
    and the role say. Staff sessions never. Every failure gives one answer."""
    assert actor.user_id is not None
    invalid = PermissionDenied("photo_link_invalid", "This link is not valid any more.")
    now = int(_now().timestamp())
    order_part = str(seller_order_id) if seller_order_id else "-"
    expected = _signature(photo_id, actor.user_id, order_part, expires)
    if not constant_time_equal(signature, expected):
        raise invalid
    if expires < now or expires > now + LINK_SECONDS or staff_session:
        raise invalid
    photo = db.get(GatePhoto, photo_id)
    if photo is None:
        raise invalid
    if seller_order_id is None:
        allowed = photo.user_id == actor.user_id
    else:
        found = _delivering_row(db, seller_order_id)
        allowed = False
        if found is not None:
            seller_order, order, shipment = found
            role = db.scalar(
                select(SellerMember.role).where(
                    SellerMember.seller_id == seller_order.seller_id,
                    SellerMember.user_id == actor.user_id,
                    SellerMember.is_active,
                )
            )
            allowed = (
                _snapshot_photo(order) == photo.id
                and visible_to_shop(seller_order, order, shipment)
                and _role_may_see(role)
            )
    if not allowed:
        raise invalid
    try:
        data = get_private_storage().get(photo.file_key)
    except StoredFileMissing as exc:
        raise NotFound("photo_file_missing", "The file for this photo is missing.") from exc
    if seller_order_id is not None:
        record_by(
            db, actor, "gate_photo.viewed", "gate_photo", photo.id,
            after={"seller_order_id": str(seller_order_id)},
        )  # fmt: skip
    return data
