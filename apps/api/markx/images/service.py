"""Product pictures and problem photos (blueprint F.6, D.5, S-06, C-16, AD-03; D-062).

Product pictures go through two steps:

1. **Upload** (staff for the catalogue, a seller for its own "real photo").
   The file is decoded and written out again (`sanitize_image`), so anything
   that is not a JPEG, PNG or WebP picture is refused and the camera's
   location data never reaches storage. The clean copy is kept privately as
   the picture's source, and a `product_images` row is created `processing`
   with a render queued through the outbox, in the same transaction.
2. **Render** (the worker). The source becomes WebP in two fixed sizes, a
   thumbnail of at most 30 KB and a main picture of at most 150 KB (D.26),
   with no metadata at all, written to public storage. The row becomes
   `ready`; only ready pictures are ever shown.

Staff remove a picture with a reason (AD-03); a seller withdraws its own.
Nothing is deleted: the row records who removed it, when and why.

Problem photos are evidence for a reported problem (C-16). They are private:
re-encoded to WebP without metadata at upload, kept in private storage,
never edited, and opened only through a five-minute link signed for the
person who asked for it, who must still be allowed to see the case.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Text, func, literal, select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.accounts.permissions import (
    SellerCapability,
    StaffCapability,
    seller_can,
    staff_can,
)
from markx.audit.service import Actor, record_by
from markx.catalog.models import (
    ImageKind,
    ImageStatus,
    Product,
    ProductImage,
    ProductStatus,
    ProductVariant,
)
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.core.images import (
    ImageTooComplex,
    NotAnImage,
    decode_clean,
    render_webp,
    sanitize_image,
)
from markx.core.security import constant_time_equal, sign
from markx.core.storage import StoredFileMissing, get_private_storage, get_public_storage
from markx.notifications.models import Outbox
from markx.offers.models import Offer, OfferStatus
from markx.orders.models import Order, SellerOrder
from markx.sellers.models import Seller, SellerMember, SellerStatus
from markx.trust.models import CaseStatus, DisputeCase, ProblemPhoto

TOPIC_RENDER = "images.render"

# Blueprint D.26: a thumbnail up to 30 KB, the main picture up to 150 KB.
THUMB_SIDE, THUMB_MAX_BYTES = 320, 30_000
MAIN_SIDE, MAIN_MAX_BYTES = 1200, 150_000
# Evidence is for staff to judge a problem, so it keeps more detail.
EVIDENCE_SIDE, EVIDENCE_MAX_BYTES = 1600, 600_000
PROBLEM_PHOTO_LINK_SECONDS = 300

# The first key of the advisory lock that serialises uploads to one product,
# so two at once cannot both pass the per-product limit. Spells "MXIM".
_UPLOAD_LOCK_SPACE = 0x4D58494D


def _now() -> datetime:
    return datetime.now(UTC)


def thumb_key(image: ProductImage) -> str:
    return f"{image.file_key}-{THUMB_SIDE}.webp"


def main_key(image: ProductImage) -> str:
    return f"{image.file_key}-{MAIN_SIDE}.webp"


# -- checking an upload ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CleanUpload:
    data: bytes
    width: int
    height: int


def clean_upload(db: Session, data: bytes) -> CleanUpload:
    """Refuse an empty, oversized or non-picture upload; otherwise return the
    picture decoded and written out again, without its metadata."""
    max_bytes = settings_store.get_int(db, "images.max_upload_bytes")
    if not data:
        raise ValidationFailed("image_empty", "The file is empty.")
    if len(data) > max_bytes:
        raise ValidationFailed(
            "image_too_large", f"The photo must be under {max_bytes // 1_000_000} MB."
        )
    try:
        clean, _ = sanitize_image(data)
        upright = decode_clean(clean)
    except NotAnImage as exc:
        raise ValidationFailed("image_not_a_photo", "Send a JPEG, PNG or WebP photo.") from exc
    return CleanUpload(data=clean, width=upright.width, height=upright.height)


def _lock_product_uploads(db: Session, product_id: uuid.UUID) -> None:
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                _UPLOAD_LOCK_SPACE, func.hashtext(literal(str(product_id), type_=Text))
            )
        )
    )


def _shown_count(db: Session, product_id: uuid.UUID, **where: Any) -> int:
    query = (
        select(func.count())
        .select_from(ProductImage)
        .where(ProductImage.product_id == product_id, ProductImage.status != ImageStatus.REMOVED)
    )
    for column, value in where.items():
        query = query.where(getattr(ProductImage, column) == value)
    return int(db.scalar(query) or 0)


def _store_and_queue(
    db: Session,
    actor: Actor,
    product: Product,
    upload: CleanUpload,
    *,
    kind: ImageKind,
    seller_id: uuid.UUID | None,
    position: int,
) -> ProductImage:
    image_id = uuid7()
    # Keys carry no personal data and cannot be guessed from the ids.
    token = secrets.token_hex(12)
    source_key = f"product-image-sources/{product.id}/{image_id}-{token}"
    get_private_storage().put(source_key, upload.data)
    image = ProductImage(
        id=image_id,
        product_id=product.id,
        seller_id=seller_id,
        kind=kind.value,
        file_key=f"products/{product.id}/{image_id}-{token}",
        source_key=source_key,
        width=upload.width,
        height=upload.height,
        position=position,
        status=ImageStatus.PROCESSING.value,
        uploaded_by_user_id=actor.user_id,
    )
    db.add(image)
    db.flush()
    db.add(Outbox(topic=TOPIC_RENDER, payload={"image_id": str(image.id)}))
    record_by(
        db, actor, "product_image.upload", "product_image", image.id,
        after={
            "product_id": str(product.id), "kind": kind.value,
            "seller_id": str(seller_id) if seller_id else None, "source_bytes": len(upload.data),
        },
    )  # fmt: skip
    db.flush()
    return image


# -- catalogue pictures (staff) ------------------------------------------------------------


def add_catalogue_image(
    db: Session, actor: Actor, product_id: uuid.UUID, data: bytes, *, position: int
) -> ProductImage:
    """A catalogue picture, by staff who curate the catalogue (C.4)."""
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("product_not_found", "That product was not found.")
    if product.status in (ProductStatus.ARCHIVED, ProductStatus.MERGED):
        raise Conflict("product_not_editable", "Pictures cannot be added to this product.")
    upload = clean_upload(db, data)
    _lock_product_uploads(db, product.id)
    limit = settings_store.get_int(db, "images.max_catalogue_per_product")
    if _shown_count(db, product.id, kind=ImageKind.CATALOGUE.value) >= limit:
        raise Conflict("too_many_images", f"A product may have at most {limit} pictures.")
    return _store_and_queue(
        db, actor, product, upload, kind=ImageKind.CATALOGUE, seller_id=None, position=position
    )


def remove_image(db: Session, actor: Actor, image_id: uuid.UUID, *, reason: str) -> ProductImage:
    """Staff take a picture down (AD-03), with a written reason. Logged."""
    image = db.scalar(select(ProductImage).where(ProductImage.id == image_id).with_for_update())
    if image is None:
        raise NotFound("image_not_found", "That picture was not found.")
    if image.status == ImageStatus.REMOVED:
        raise Conflict("image_already_removed", "That picture was already removed.")
    before = image.status
    _mark_removed(image, actor, reason)
    db.flush()
    record_by(
        db, actor, "product_image.remove", "product_image", image.id,
        before={"status": before},
        after={"status": image.status, "reason": reason, "kind": image.kind,
               "seller_id": str(image.seller_id) if image.seller_id else None},
    )  # fmt: skip
    return image


def _mark_removed(image: ProductImage, actor: Actor, reason: str) -> None:
    image.status = ImageStatus.REMOVED.value
    image.removed_at = _now()
    image.removed_reason = reason
    image.removed_by_user_id = actor.user_id


# -- real photos (sellers) ------------------------------------------------------------------


def _require_offer_manager(member: SellerMember) -> None:
    if not seller_can(member.role, SellerCapability.MANAGE_OFFERS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")


def add_real_photo(
    db: Session,
    actor: Actor,
    seller: Seller,
    member: SellerMember,
    product_id: uuid.UUID,
    data: bytes,
) -> ProductImage:
    """A seller's own photo of a product it sells, shown with a "Real photo"
    tag (D.5, S-06). Only for an approved product the seller has an offer on."""
    _require_offer_manager(member)
    if seller.status == SellerStatus.SUSPENDED:
        raise Conflict("seller_not_active", "A suspended store cannot add photos.")
    product = db.get(Product, product_id)
    if product is None or product.status != ProductStatus.APPROVED:
        raise NotFound("product_not_found", "That product was not found.")
    has_offer = db.scalar(
        select(func.count())
        .select_from(Offer)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .where(
            ProductVariant.product_id == product.id,
            Offer.seller_id == seller.id,
            Offer.status != OfferStatus.REMOVED,
        )
    )
    if not has_offer:
        raise Conflict(
            "no_offer_for_product", "Add an offer for this product before adding photos of it."
        )
    upload = clean_upload(db, data)
    _lock_product_uploads(db, product.id)
    limit = settings_store.get_int(db, "images.max_real_photos_per_seller")
    if _shown_count(db, product.id, seller_id=seller.id) >= limit:
        raise Conflict("too_many_images", f"A store may show at most {limit} photos of a product.")
    return _store_and_queue(
        db, actor, product, upload, kind=ImageKind.SELLER_REAL_PHOTO, seller_id=seller.id,
        position=0,
    )  # fmt: skip


def withdraw_real_photo(
    db: Session, actor: Actor, seller: Seller, member: SellerMember, image_id: uuid.UUID
) -> ProductImage:
    """The seller takes down its own photo. Another seller's photo, or a
    catalogue picture, is "not found"."""
    _require_offer_manager(member)
    image = db.scalar(
        select(ProductImage)
        .where(ProductImage.id == image_id, ProductImage.seller_id == seller.id)
        .with_for_update()
    )
    if image is None:
        raise NotFound("image_not_found", "That picture was not found.")
    if image.status == ImageStatus.REMOVED:
        raise Conflict("image_already_removed", "That picture was already removed.")
    before = image.status
    _mark_removed(image, actor, "withdrawn by the seller")
    db.flush()
    record_by(
        db, actor, "product_image.withdraw", "product_image", image.id,
        before={"status": before}, after={"status": image.status, "seller_id": str(seller.id)},
    )  # fmt: skip
    return image


# -- rendering (the worker) ---------------------------------------------------------------


def render_product_image(db: Session, image_id: uuid.UUID) -> ProductImage | None:
    """Render one picture's two WebP sizes and mark it ready. Safe to run
    twice: a picture that is no longer `processing` is left alone. A source
    that cannot be rendered marks the picture `failed`, which is final; a
    storage error raises, so the outbox tries again later."""
    image = db.scalar(select(ProductImage).where(ProductImage.id == image_id).with_for_update())
    if image is None or image.status != ImageStatus.PROCESSING:
        return image
    assert image.source_key is not None, "a picture in processing always has its source"
    source = get_private_storage().get(image.source_key)
    try:
        picture = decode_clean(source)
        thumb = render_webp(picture, longest_side=THUMB_SIDE, max_bytes=THUMB_MAX_BYTES)
        main = render_webp(picture, longest_side=MAIN_SIDE, max_bytes=MAIN_MAX_BYTES)
    except (NotAnImage, ImageTooComplex) as exc:
        image.status = ImageStatus.FAILED.value
        image.failure_reason = str(exc)[:500]
        db.flush()
        return image
    public = get_public_storage()
    public.put(thumb_key(image), thumb.data, "image/webp")
    public.put(main_key(image), main.data, "image/webp")
    image.width, image.height = main.width, main.height
    image.thumb_bytes, image.main_bytes = len(thumb.data), len(main.data)
    image.processed_at = _now()
    image.status = ImageStatus.READY.value
    db.flush()
    return image


def handle_render(db: Session, row: Outbox) -> None:
    """The outbox handler for `images.render`."""
    render_product_image(db, uuid.UUID(str(row.payload["image_id"])))


# -- problem photos (C-16) ------------------------------------------------------------------


def _open_case(db: Session, seller_order: SellerOrder) -> DisputeCase:
    case = db.scalar(select(DisputeCase).where(DisputeCase.seller_order_id == seller_order.id))
    if case is None:
        raise NotFound("problem_not_found", "No problem was reported on this order.")
    if case.status == CaseStatus.RESOLVED:
        raise Conflict("problem_already_resolved", "This problem has already been decided.")
    return case


def _add_problem_photo(
    db: Session, actor: Actor, seller_order: SellerOrder, *, author_type: str, data: bytes
) -> ProblemPhoto:
    """The caller holds the seller order's lock, which guards its case (D-050)."""
    assert actor.user_id is not None
    case = _open_case(db, seller_order)
    limit = settings_store.get_int(db, "images.max_problem_photos_per_side")
    count = db.scalar(
        select(func.count())
        .select_from(ProblemPhoto)
        .where(ProblemPhoto.case_id == case.id, ProblemPhoto.author_type == author_type)
    )
    if (count or 0) >= limit:
        raise Conflict("too_many_photos", f"At most {limit} photos can be added to a problem.")
    upload = clean_upload(db, data)
    try:
        rendered = render_webp(
            decode_clean(upload.data), longest_side=EVIDENCE_SIDE, max_bytes=EVIDENCE_MAX_BYTES
        )
    except (NotAnImage, ImageTooComplex) as exc:
        raise ValidationFailed("image_not_a_photo", "Send a JPEG, PNG or WebP photo.") from exc
    photo_id = uuid7()
    file_key = f"problem-photos/{case.id}/{photo_id}-{secrets.token_hex(16)}"
    get_private_storage().put(file_key, rendered.data)
    photo = ProblemPhoto(
        id=photo_id, case_id=case.id, author_type=author_type, uploaded_by_user_id=actor.user_id,
        file_key=file_key, width=rendered.width, height=rendered.height,
        size_bytes=len(rendered.data),
    )  # fmt: skip
    db.add(photo)
    db.flush()
    record_by(
        db, actor, "problem_photo.add", "problem_photo", photo.id,
        after={"case_id": str(case.id), "author_type": author_type, "size_bytes": len(rendered.data)},
    )  # fmt: skip
    return photo


def _buyer_seller_order(
    db: Session, user: User, order_id: uuid.UUID, seller_order_id: uuid.UUID, *, lock: bool
) -> SellerOrder:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.buyer_user_id == user.id))
    if order is None:
        raise NotFound("order_not_found", "That order was not found.")
    query = select(SellerOrder).where(
        SellerOrder.id == seller_order_id, SellerOrder.order_id == order.id
    )
    if lock:
        query = query.with_for_update(key_share=True).execution_options(populate_existing=True)
    seller_order = db.scalar(query)
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    return seller_order


def _seller_seller_order(
    db: Session,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    *,
    lock: bool,
) -> SellerOrder:
    if not seller_can(member.role, SellerCapability.HANDLE_ORDERS):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    query = select(SellerOrder).where(
        SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller.id
    )
    if lock:
        query = query.with_for_update(key_share=True).execution_options(populate_existing=True)
    seller_order = db.scalar(query)
    if seller_order is None:
        raise NotFound("order_not_found", "That order was not found.")
    return seller_order


def buyer_add_problem_photo(
    db: Session,
    actor: Actor,
    user: User,
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    data: bytes,
) -> ProblemPhoto:
    seller_order = _buyer_seller_order(db, user, order_id, seller_order_id, lock=True)
    return _add_problem_photo(db, actor, seller_order, author_type="buyer", data=data)


def seller_add_problem_photo(
    db: Session,
    actor: Actor,
    seller: Seller,
    member: SellerMember,
    seller_order_id: uuid.UUID,
    data: bytes,
) -> ProblemPhoto:
    seller_order = _seller_seller_order(db, seller, member, seller_order_id, lock=True)
    return _add_problem_photo(db, actor, seller_order, author_type="seller", data=data)


def _photos_of(db: Session, seller_order_id: uuid.UUID) -> list[ProblemPhoto]:
    return list(
        db.scalars(
            select(ProblemPhoto)
            .join(DisputeCase, DisputeCase.id == ProblemPhoto.case_id)
            .where(DisputeCase.seller_order_id == seller_order_id)
            .order_by(ProblemPhoto.created_at, ProblemPhoto.id)
        )
    )


def _photo_signature(photo_id: uuid.UUID, viewer_user_id: uuid.UUID, expires: int) -> str:
    return sign("problem-photo-link", str(photo_id), str(viewer_user_id), str(expires), length=43)


def _with_links(viewer_user_id: uuid.UUID, photos: list[ProblemPhoto]) -> list[dict[str, Any]]:
    expires = int(_now().timestamp()) + PROBLEM_PHOTO_LINK_SECONDS
    return [
        {
            "id": photo.id,
            "author_type": photo.author_type,
            "width": photo.width,
            "height": photo.height,
            "created_at": photo.created_at,
            "url": (
                f"/api/v1/problem-photos/{photo.id}/content?expires={expires}"
                f"&signature={_photo_signature(photo.id, viewer_user_id, expires)}"
            ),
            "url_expires_at": datetime.fromtimestamp(expires, UTC),
        }
        for photo in photos
    ]


def buyer_problem_photos(
    db: Session, user: User, order_id: uuid.UUID, seller_order_id: uuid.UUID
) -> list[dict[str, Any]]:
    seller_order = _buyer_seller_order(db, user, order_id, seller_order_id, lock=False)
    return _with_links(user.id, _photos_of(db, seller_order.id))


def seller_problem_photos(
    db: Session, seller: Seller, member: SellerMember, seller_order_id: uuid.UUID
) -> list[dict[str, Any]]:
    seller_order = _seller_seller_order(db, seller, member, seller_order_id, lock=False)
    return _with_links(member.user_id, _photos_of(db, seller_order.id))


def staff_problem_photos(
    db: Session, actor: Actor, seller_order_id: uuid.UUID
) -> list[dict[str, Any]]:
    assert actor.user_id is not None
    if db.get(SellerOrder, seller_order_id) is None:
        raise NotFound("order_not_found", "That order was not found.")
    return _with_links(actor.user_id, _photos_of(db, seller_order_id))


def open_problem_photo(
    db: Session,
    actor: Actor,
    photo_id: uuid.UUID,
    *,
    expires: int,
    signature: str,
    staff_role: str | None,
) -> bytes:
    """The photo behind a signed link. The link must be unexpired and signed
    for this viewer, and the viewer must *still* be allowed: the buyer of the
    order, an active member of the seller who handles orders, or staff who
    handle cases. Every failure gives the same answer. Staff views are
    logged, as they are for documents."""
    assert actor.user_id is not None
    invalid = PermissionDenied("photo_link_invalid", "This link is not valid any more.")
    now = int(_now().timestamp())
    if not constant_time_equal(signature, _photo_signature(photo_id, actor.user_id, expires)):
        raise invalid
    if expires < now or expires > now + PROBLEM_PHOTO_LINK_SECONDS:
        raise invalid
    row = db.execute(
        select(ProblemPhoto, SellerOrder, Order)
        .join(DisputeCase, DisputeCase.id == ProblemPhoto.case_id)
        .join(SellerOrder, SellerOrder.id == DisputeCase.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .where(ProblemPhoto.id == photo_id)
    ).first()
    if row is None:
        raise invalid
    photo, seller_order, order = row
    if staff_role is not None:
        allowed = staff_can(staff_role, StaffCapability.HANDLE_CASES)
    elif order.buyer_user_id == actor.user_id:
        allowed = True
    else:
        role = db.scalar(
            select(SellerMember.role).where(
                SellerMember.seller_id == seller_order.seller_id,
                SellerMember.user_id == actor.user_id,
                SellerMember.is_active,
            )
        )
        allowed = role is not None and seller_can(role, SellerCapability.HANDLE_ORDERS)
    if not allowed:
        raise invalid
    try:
        data = get_private_storage().get(photo.file_key)
    except StoredFileMissing as exc:
        raise NotFound("photo_file_missing", "The file for this photo is missing.") from exc
    if staff_role is not None:
        record_by(
            db, actor, "problem_photo.viewed", "problem_photo", photo.id,
            after={"seller_order_id": str(seller_order.id)},
        )  # fmt: skip
    return data
