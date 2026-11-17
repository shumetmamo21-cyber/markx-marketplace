"""Seller onboarding and management (blueprint D.3, D.4, P6).

Every function that takes a `Seller` trusts its caller to have loaded that
seller for the person acting: routes do it with `require_seller`, which only
ever returns a seller the caller is an active member of. Functions that take a
`seller_id` are for staff. Anything addressed by its own id (a document, a
member) is always looked up together with the seller it must belong to, so an
id from another seller is simply "not found".

Status rules, all enforced here and backed by CHECK constraints:

    review_state   draft -> pending -> approved
                   pending -> needs_documents -> pending
                   pending | needs_documents -> rejected
    status         applied -> active <-> suspended
                   applied | active | suspended -> closed
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import User
from markx.accounts.permissions import (
    RELEASE_1_SELLER_ROLES,
    SellerCapability,
    StaffCapability,
    seller_can,
    staff_can,
)
from markx.audit.service import Actor, record_by
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from markx.core.ids import uuid7
from markx.core.images import NotAnImage, sanitize_image
from markx.core.security import constant_time_equal, encrypt_text, sign
from markx.core.slugs import slugify
from markx.core.storage import StoredFileMissing, get_private_storage
from markx.notifications import service as notifications
from markx.orders.models import SellerOrder, SellerOrderStatus
from markx.sellers.models import (
    DocumentType,
    ReviewState,
    Seller,
    SellerDocument,
    SellerInvitation,
    SellerKind,
    SellerMember,
    SellerPayoutAccount,
    SellerRole,
    SellerStatus,
    Store,
)

DOCUMENT_LINK_SECONDS = 300  # blueprint D.3: links expire within five minutes
MAX_DOCUMENTS_PER_SELLER = 40
_TIN = re.compile(r"^[0-9]{10}$")
_ACCOUNT_NUMBER = re.compile(r"^[0-9]{6,30}$")
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

REQUIRED_DOCUMENTS: dict[str, tuple[DocumentType, ...]] = {
    SellerKind.BUSINESS: (
        DocumentType.OWNER_ID,
        DocumentType.BUSINESS_LICENCE,
        DocumentType.TIN_CERTIFICATE,
        DocumentType.SHOP_PHOTO,
    ),
    SellerKind.INDIVIDUAL: (DocumentType.OWNER_ID,),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


# -- lookups -------------------------------------------------------------------


def get_seller(db: Session, seller_id: uuid.UUID, *, lock: bool = False) -> Seller:
    """For staff routes. Seller routes use `require_seller` instead."""
    query = select(Seller).where(Seller.id == seller_id)
    if lock:
        # FOR NO KEY UPDATE: it serialises changes to the seller without
        # blocking rows elsewhere (offers, documents) that only reference it.
        query = query.with_for_update(key_share=True)
    seller = db.scalar(query)
    if seller is None:
        raise NotFound("seller_not_found", "That seller was not found.")
    return seller


def _lock(db: Session, seller: Seller) -> Seller:
    """Lock the seller's row and re-read it, so two requests that change its
    state, members or accounts run one after the other."""
    locked = db.scalar(
        select(Seller)
        .where(Seller.id == seller.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    assert locked is not None
    return locked


def get_store(db: Session, seller_id: uuid.UUID) -> Store:
    store = db.scalar(select(Store).where(Store.seller_id == seller_id))
    assert store is not None, "a seller is always created with its store"
    return store


def owner_user_id(db: Session, seller_id: uuid.UUID) -> uuid.UUID:
    owner = db.scalar(
        select(SellerMember.user_id).where(
            SellerMember.seller_id == seller_id,
            SellerMember.role == SellerRole.OWNER,
            SellerMember.is_active,
        )
    )
    assert owner is not None, "a seller always has an owner"
    return owner


def _seller_snapshot(seller: Seller) -> dict[str, Any]:
    return {
        "status": seller.status,
        "review_state": seller.review_state,
        "verification_level": seller.verification_level,
    }


def _refuse_own_seller(db: Session, actor: Actor, seller_id: uuid.UUID) -> None:
    """Nobody verifies themselves (blueprint C.5): a staff member who belongs to
    a seller may not take staff decisions about it."""
    if actor.user_id is None:
        return
    is_member = db.scalar(
        select(SellerMember.id).where(
            SellerMember.seller_id == seller_id,
            SellerMember.user_id == actor.user_id,
            SellerMember.is_active,
        )
    )
    if is_member is not None:
        raise PermissionDenied(
            "conflict_of_interest",
            "You belong to this seller, so another staff member must decide.",
        )


# -- verification checks ---------------------------------------------------------


def verification_checks(db: Session, seller: Seller) -> dict[str, bool]:
    """Exactly what was checked, for the badge (blueprint D.3) and for staff.

    A document counts only when staff accepted it and it has not expired.
    """
    accepted = set(
        db.scalars(
            select(SellerDocument.doc_type).where(
                SellerDocument.seller_id == seller.id,
                SellerDocument.review_status == "accepted",
                (SellerDocument.expires_on.is_(None)) | (SellerDocument.expires_on >= _today()),
            )
        )
    )
    return {
        "phone_confirmed": True,  # an account exists only for a number that received a code
        "identity_verified": DocumentType.OWNER_ID in accepted,
        "business_licence_verified": DocumentType.BUSINESS_LICENCE in accepted,
        "tin_verified": DocumentType.TIN_CERTIFICATE in accepted,
        "shop_photo_verified": DocumentType.SHOP_PHOTO in accepted,
        "shop_visited": seller.shop_visited_at is not None,
    }


def _missing_for_level(seller: Seller, checks: dict[str, bool], level: int) -> list[str]:
    """Which checks stand between this seller and a verification level
    (blueprint D.3, C.6). Level 0 needs nothing."""
    needed: list[str] = []
    if level >= 1:
        needed.append("identity_verified")
    if level >= 2:
        needed += [
            "business_licence_verified",
            "tin_verified",
            "shop_photo_verified",
            "shop_visited",
        ]
    missing = [name for name in needed if not checks[name]]
    if level >= 2 and seller.kind != SellerKind.BUSINESS:
        missing.append("business_seller")
    return missing


def application_missing(db: Session, seller: Seller) -> list[str]:
    """What the applicant still has to provide before submitting."""
    provided = set(
        db.scalars(
            select(SellerDocument.doc_type).where(
                SellerDocument.seller_id == seller.id,
                SellerDocument.review_status.in_(("pending", "accepted")),
            )
        )
    )
    missing = [f"document:{t.value}" for t in REQUIRED_DOCUMENTS[seller.kind] if t not in provided]
    has_account = db.scalar(
        select(SellerPayoutAccount.id).where(
            SellerPayoutAccount.seller_id == seller.id,
            SellerPayoutAccount.status.in_(("pending", "active")),
        )
    )
    if has_account is None:
        missing.append("payout_account")
    return missing


# -- invitations (staff) -----------------------------------------------------------


def create_invitation(
    db: Session, actor: Actor, *, raw_phone: str, note: str | None
) -> SellerInvitation:
    assert actor.user_id is not None
    phone = accounts.parse_phone(raw_phone)
    now = _now()
    # An invitation that ran out no longer blocks a new one.
    db.execute(
        update(SellerInvitation)
        .where(
            SellerInvitation.phone == phone,
            SellerInvitation.used_at.is_(None),
            SellerInvitation.revoked_at.is_(None),
            SellerInvitation.expires_at <= now,
        )
        .values(revoked_at=now)
    )
    days = settings_store.get_int(db, "sellers.invitation_valid_days")
    invitation = SellerInvitation(
        phone=phone,
        note=note,
        invited_by_user_id=actor.user_id,
        expires_at=now + timedelta(days=days),
    )
    db.add(invitation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("invitation_exists", "That number already has an open invitation.") from exc
    record_by(
        db, actor, "seller_invitation.create", "seller_invitation", invitation.id,
        after={"phone": phone, "expires_at": invitation.expires_at.isoformat()},
    )  # fmt: skip
    return invitation


def revoke_invitation(db: Session, actor: Actor, invitation_id: uuid.UUID) -> None:
    invitation = db.scalar(
        select(SellerInvitation).where(SellerInvitation.id == invitation_id).with_for_update()
    )
    if invitation is None:
        raise NotFound("invitation_not_found", "That invitation was not found.")
    if invitation.used_at is not None:
        raise Conflict("invitation_used", "That invitation was already used.")
    if invitation.revoked_at is None:
        invitation.revoked_at = _now()
        db.flush()
        record_by(
            db, actor, "seller_invitation.revoke", "seller_invitation", invitation.id,
            before={"phone": invitation.phone},
        )  # fmt: skip


def _open_invitation(db: Session, phone: str, *, lock: bool = False) -> SellerInvitation | None:
    query = select(SellerInvitation).where(
        SellerInvitation.phone == phone,
        SellerInvitation.used_at.is_(None),
        SellerInvitation.revoked_at.is_(None),
        SellerInvitation.expires_at > _now(),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def application_eligibility(db: Session, user: User) -> dict[str, bool]:
    invite_only = settings_store.get_bool(db, "sellers.invite_only")
    invited = _open_invitation(db, user.phone) is not None
    return {
        "invite_only": invite_only,
        "invited": invited,
        "may_apply": invited or not invite_only,
        "individual_enabled": settings_store.get_bool(db, "sellers.individual_enabled"),
    }


# -- the application (seller) ----------------------------------------------------


def _clean_tin(tin: str | None) -> str | None:
    if tin is None:
        return None
    compact = re.sub(r"[\s-]", "", tin)
    if not _TIN.fullmatch(compact):
        raise ValidationFailed("tin_invalid", "A TIN has ten digits.")
    return compact


def _check_pin(latitude: float | None, longitude: float | None) -> None:
    if (latitude is None) != (longitude is None):
        raise ValidationFailed("pin_incomplete", "Send both latitude and longitude, or neither.")


def _free_store_slug(db: Session, wanted: str) -> str:
    base = wanted[:50].strip("-")
    if len(base) < 3:
        base = "store"
    candidate = base
    while db.scalar(select(Store.id).where(Store.slug == candidate)) is not None:
        candidate = f"{base}-{secrets.token_hex(3)}"
    return candidate


@dataclass(frozen=True, slots=True)
class ApplicationInput:
    kind: str
    legal_name: str
    trade_name: str
    tin: str | None
    licence_number: str | None
    contact_phone: str
    shop_address: str
    shop_latitude: float | None
    shop_longitude: float | None
    store_slug: str | None = None


def start_application(db: Session, actor: Actor, user: User, data: ApplicationInput) -> Seller:
    """Create the seller, its owner and its store as a draft application.

    Nothing here is visible to buyers, and staff see it only once it is
    submitted. The applicant then adds documents and a payout account.
    """
    if data.kind == SellerKind.INDIVIDUAL and not settings_store.get_bool(
        db, "sellers.individual_enabled"
    ):
        raise PermissionDenied(
            "individual_sellers_disabled", "Only licensed businesses can apply at the moment."
        )
    tin = _clean_tin(data.tin)
    if data.kind == SellerKind.BUSINESS and tin is None:
        raise ValidationFailed("tin_required", "A business needs its TIN.")
    _check_pin(data.shop_latitude, data.shop_longitude)
    contact_phone = accounts.parse_phone(data.contact_phone)

    invitation = _open_invitation(db, user.phone, lock=True)
    if invitation is None and settings_store.get_bool(db, "sellers.invite_only"):
        raise PermissionDenied(
            "invitation_required", "MarkX is onboarding sellers by invitation for now."
        )

    # One application at a time per person. The user's row is the lock, so two
    # simultaneous requests cannot both pass this check.
    db.execute(select(User.id).where(User.id == user.id).with_for_update(key_share=True))
    in_progress = db.scalar(
        select(Seller.id)
        .join(SellerMember, SellerMember.seller_id == Seller.id)
        .where(
            SellerMember.user_id == user.id,
            SellerMember.role == SellerRole.OWNER,
            SellerMember.is_active,
            Seller.status == SellerStatus.APPLIED,
        )
    )
    if in_progress is not None:
        raise Conflict("application_in_progress", "You already have an application in progress.")

    seller = Seller(
        id=uuid7(),
        kind=data.kind,
        legal_name=data.legal_name,
        trade_name=data.trade_name,
        tin=tin,
        licence_number=data.licence_number,
        contact_phone=contact_phone,
        shop_address=data.shop_address,
        shop_latitude=data.shop_latitude,
        shop_longitude=data.shop_longitude,
        status=SellerStatus.APPLIED,
        review_state=ReviewState.DRAFT,
    )
    db.add(seller)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("tin_taken", "A seller with that TIN is already registered.") from exc

    slug = data.store_slug
    if slug is not None:
        if db.scalar(select(Store.id).where(Store.slug == slug)) is not None:
            raise Conflict("store_slug_taken", "That store link is taken.")
    else:
        slug = _free_store_slug(db, slugify(data.trade_name))
    db.add(SellerMember(seller_id=seller.id, user_id=user.id, role=SellerRole.OWNER))
    db.add(Store(seller_id=seller.id, slug=slug, name=data.trade_name))
    if invitation is not None:
        invitation.used_at = _now()
        invitation.used_by_seller_id = seller.id
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("store_slug_taken", "That store link is taken.") from exc
    record_by(
        db, actor, "seller.apply", "seller", seller.id,
        after={"kind": seller.kind, "trade_name": seller.trade_name, "store_slug": slug},
    )  # fmt: skip
    return seller


_EDITABLE_REVIEW_STATES = (ReviewState.DRAFT, ReviewState.NEEDS_DOCUMENTS)


def update_legal_details(
    db: Session,
    actor: Actor,
    seller: Seller,
    *,
    legal_name: str | None = None,
    trade_name: str | None = None,
    tin: str | None = None,
    licence_number: str | None = None,
    contact_phone: str | None = None,
    shop_address: str | None = None,
    shop_latitude: float | None = None,
    shop_longitude: float | None = None,
) -> Seller:
    """The owner corrects the application.

    Once it is with staff or approved, what staff verified is frozen: only the
    contact phone can still change. Anything else needs a new review.
    """
    seller = _lock(db, seller)
    verified_fields = (
        legal_name, trade_name, tin, licence_number, shop_address, shop_latitude, shop_longitude,
    )  # fmt: skip
    if (
        any(value is not None for value in verified_fields)
        and seller.review_state not in _EDITABLE_REVIEW_STATES
    ):
        raise Conflict(
            "application_locked",
            "These details were sent for verification and can no longer be changed here.",
        )
    before = {
        "legal_name": seller.legal_name,
        "trade_name": seller.trade_name,
        "tin": seller.tin,
        "licence_number": seller.licence_number,
        "contact_phone": seller.contact_phone,
        "shop_address": seller.shop_address,
    }
    if legal_name is not None:
        seller.legal_name = legal_name
    if trade_name is not None:
        seller.trade_name = trade_name
    if tin is not None:
        seller.tin = _clean_tin(tin)
    if licence_number is not None:
        seller.licence_number = licence_number
    if contact_phone is not None:
        seller.contact_phone = accounts.parse_phone(contact_phone)
    if shop_address is not None:
        seller.shop_address = shop_address
    if shop_latitude is not None or shop_longitude is not None:
        _check_pin(shop_latitude, shop_longitude)
        seller.shop_latitude = shop_latitude
        seller.shop_longitude = shop_longitude
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("tin_taken", "A seller with that TIN is already registered.") from exc
    after = {key: getattr(seller, key) for key in before}
    if after != before:
        record_by(db, actor, "seller.update_legal", "seller", seller.id, before=before, after=after)
    return seller


def submit_application(db: Session, actor: Actor, seller: Seller) -> Seller:
    seller = _lock(db, seller)
    if seller.status != SellerStatus.APPLIED or seller.review_state not in _EDITABLE_REVIEW_STATES:
        raise Conflict("application_not_editable", "This application was already submitted.")
    missing = application_missing(db, seller)
    if missing:
        raise ValidationFailed(
            "application_incomplete",
            "The application is missing some items.",
            details={"missing": missing},
        )
    before = _seller_snapshot(seller)
    seller.review_state = ReviewState.PENDING
    seller.submitted_at = _now()
    db.flush()
    record_by(
        db, actor, "seller.submit", "seller", seller.id,
        before=before, after=_seller_snapshot(seller),
    )  # fmt: skip
    return seller


# -- documents -----------------------------------------------------------------


def upload_document(
    db: Session,
    actor: Actor,
    seller: Seller,
    *,
    doc_type: DocumentType,
    data: bytes,
    expires_on: date | None,
) -> SellerDocument:
    """Store one document photo in private storage.

    The picture is decoded and written out again, so a file that only claims
    to be an image is refused and location data is dropped.
    """
    assert actor.user_id is not None
    max_bytes = settings_store.get_int(db, "sellers.document_max_bytes")
    if not data:
        raise ValidationFailed("document_empty", "The file is empty.")
    if len(data) > max_bytes:
        raise ValidationFailed(
            "document_too_large", f"The photo must be under {max_bytes // 1_000_000} MB."
        )
    if expires_on is not None and expires_on < _today():
        raise ValidationFailed("document_expired", "That document has already expired.")
    count = db.scalar(
        select(func.count())
        .select_from(SellerDocument)
        .where(SellerDocument.seller_id == seller.id)
    )
    if (count or 0) >= MAX_DOCUMENTS_PER_SELLER:
        raise Conflict("too_many_documents", "This seller has too many documents on file.")
    try:
        clean, content_type = sanitize_image(data)
    except NotAnImage as exc:
        raise ValidationFailed(
            "document_not_an_image", "Send a JPEG, PNG or WebP photo of the document."
        ) from exc

    document_id = uuid7()
    # The key carries no personal data and cannot be guessed from the ids.
    file_key = f"seller-documents/{seller.id}/{document_id}-{secrets.token_hex(16)}"
    get_private_storage().put(file_key, clean)
    document = SellerDocument(
        id=document_id,
        seller_id=seller.id,
        doc_type=doc_type.value,
        file_key=file_key,
        content_type=content_type,
        size_bytes=len(clean),
        expires_on=expires_on,
        uploaded_by_user_id=actor.user_id,
    )
    db.add(document)
    db.flush()
    record_by(
        db, actor, "seller_document.upload", "seller_document", document.id,
        after={"seller_id": str(seller.id), "doc_type": doc_type.value, "size_bytes": len(clean)},
    )  # fmt: skip
    return document


def _document_of(db: Session, seller_id: uuid.UUID, document_id: uuid.UUID) -> SellerDocument:
    document = db.scalar(
        select(SellerDocument).where(
            SellerDocument.id == document_id, SellerDocument.seller_id == seller_id
        )
    )
    if document is None:
        raise NotFound("document_not_found", "That document was not found.")
    return document


def _link_signature(document_id: uuid.UUID, viewer_user_id: uuid.UUID, expires: int) -> str:
    return sign(
        "seller-document-link", str(document_id), str(viewer_user_id), str(expires), length=43
    )


@dataclass(frozen=True, slots=True)
class DocumentLink:
    path: str
    expires_at: datetime


def issue_document_link(
    db: Session, actor: Actor, seller_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentLink:
    """A link to one document that works for five minutes, and only for the
    signed-in person it was issued to. Issuing it is logged."""
    assert actor.user_id is not None
    document = _document_of(db, seller_id, document_id)
    expires = int(_now().timestamp()) + DOCUMENT_LINK_SECONDS
    signature = _link_signature(document.id, actor.user_id, expires)
    record_by(
        db, actor, "seller_document.link_issued", "seller_document", document.id,
        after={"seller_id": str(seller_id), "expires": expires},
    )  # fmt: skip
    return DocumentLink(
        path=f"/api/v1/documents/{document.id}/content?expires={expires}&signature={signature}",
        expires_at=datetime.fromtimestamp(expires, UTC),
    )


@dataclass(frozen=True, slots=True)
class DocumentContent:
    data: bytes
    content_type: str


def open_document(
    db: Session,
    actor: Actor,
    document_id: uuid.UUID,
    *,
    expires: int,
    signature: str,
    staff_role: str | None,
) -> DocumentContent:
    """Serve a document through a signed link. Every view is logged (D.3).

    The link must be unexpired and signed for this viewer, and the viewer must
    *still* be allowed to see the document: staff who hold the capability, or
    the seller's owner. Every failure gives the same answer.
    """
    assert actor.user_id is not None
    invalid = PermissionDenied("document_link_invalid", "This link is not valid any more.")
    now = int(_now().timestamp())
    if not constant_time_equal(signature, _link_signature(document_id, actor.user_id, expires)):
        raise invalid
    if expires < now or expires > now + DOCUMENT_LINK_SECONDS:
        raise invalid
    document = db.get(SellerDocument, document_id)
    if document is None:
        raise invalid
    if staff_role is not None:
        allowed = staff_can(staff_role, StaffCapability.VIEW_DOCUMENTS)
    else:
        role = db.scalar(
            select(SellerMember.role).where(
                SellerMember.seller_id == document.seller_id,
                SellerMember.user_id == actor.user_id,
                SellerMember.is_active,
            )
        )
        allowed = role is not None and seller_can(role, SellerCapability.CHANGE_LEGAL_DETAILS)
    if not allowed:
        raise invalid
    try:
        data = get_private_storage().get(document.file_key)
    except StoredFileMissing as exc:
        raise NotFound("document_file_missing", "The file for this document is missing.") from exc
    record_by(
        db, actor, "seller_document.viewed", "seller_document", document.id,
        after={"seller_id": str(document.seller_id), "doc_type": document.doc_type},
    )  # fmt: skip
    return DocumentContent(data=data, content_type=document.content_type)


def review_document(
    db: Session,
    actor: Actor,
    seller_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    decision: str,
    note: str | None,
) -> SellerDocument:
    _refuse_own_seller(db, actor, seller_id)
    get_seller(db, seller_id, lock=True)
    document = _document_of(db, seller_id, document_id)
    if decision == "rejected" and not note:
        raise ValidationFailed("note_required", "Say why the document is rejected.")
    before = {"review_status": document.review_status}
    document.review_status = decision
    document.review_note = note
    document.reviewed_by_user_id = actor.user_id
    document.reviewed_at = _now()
    db.flush()
    record_by(
        db, actor, "seller_document.review", "seller_document", document.id,
        before=before, after={"review_status": decision, "note": note},
    )  # fmt: skip
    return document


# -- payout account --------------------------------------------------------------


def set_payout_account(
    db: Session,
    actor: Actor,
    seller: Seller,
    *,
    kind: str,
    provider_name: str,
    account_name: str,
    account_number: str,
) -> SellerPayoutAccount:
    """Record where the seller is paid (S-13). Collected now, used from Release 2.

    The first account is active at once. A later change waits out a cooling-off
    period before it replaces the active account, so a stolen session cannot
    silently redirect payouts. The number is stored encrypted; only its last
    four digits are ever shown again.
    """
    assert actor.user_id is not None
    number = re.sub(r"[\s-]", "", account_number)
    if not _ACCOUNT_NUMBER.fullmatch(number):
        raise ValidationFailed("account_number_invalid", "An account number has 6 to 30 digits.")
    seller = _lock(db, seller)
    now = _now()
    has_active = db.scalar(
        select(SellerPayoutAccount.id).where(
            SellerPayoutAccount.seller_id == seller.id, SellerPayoutAccount.status == "active"
        )
    )
    # Until staff approve the application nothing can be paid out, so the
    # applicant may correct the account freely.
    replace_now = has_active is None or seller.status == SellerStatus.APPLIED
    db.execute(
        update(SellerPayoutAccount)
        .where(
            SellerPayoutAccount.seller_id == seller.id,
            SellerPayoutAccount.status.in_(("pending", "active") if replace_now else ("pending",)),
        )
        .values(status="replaced")
    )
    if replace_now:
        status, effective_from = "active", now
    else:
        hours = settings_store.get_int(db, "sellers.payout_cooling_off_hours")
        status, effective_from = "pending", now + timedelta(hours=hours)
    account = SellerPayoutAccount(
        seller_id=seller.id,
        kind=kind,
        provider_name=provider_name,
        account_name=account_name,
        account_number_encrypted=encrypt_text(number),
        account_last4=number[-4:],
        status=status,
        effective_from=effective_from,
        created_by_user_id=actor.user_id,
    )
    db.add(account)
    db.flush()
    record_by(
        db, actor, "seller_payout_account.set", "seller", seller.id,
        after={
            "kind": kind, "provider_name": provider_name, "account_last4": account.account_last4,
            "status": status, "effective_from": effective_from.isoformat(),
        },
    )  # fmt: skip
    if status == "pending":
        # The owner hears about every change, in case it was not theirs.
        notifications.notify(
            db, owner_user_id(db, seller.id), "seller.payout_account_changed",
            {"seller_id": str(seller.id), "effective_from": effective_from.isoformat()},
        )  # fmt: skip
    return account


def activate_due_payout_accounts(db: Session, *, now: datetime | None = None) -> int:
    """Scheduled job: a pending account whose cooling-off period has passed
    replaces the active one. Returns how many accounts became active."""
    now = now or _now()
    due = list(
        db.scalars(
            select(SellerPayoutAccount)
            .where(
                SellerPayoutAccount.status == "pending", SellerPayoutAccount.effective_from <= now
            )
            .order_by(SellerPayoutAccount.seller_id)
            .with_for_update(skip_locked=True)
        )
    )
    for account in due:
        db.execute(
            update(SellerPayoutAccount)
            .where(
                SellerPayoutAccount.seller_id == account.seller_id,
                SellerPayoutAccount.status == "active",
            )
            .values(status="replaced")
        )
        account.status = "active"
        db.flush()
        record_by(
            db, Actor.system(), "seller_payout_account.activate", "seller", account.seller_id,
            after={"account_last4": account.account_last4},
        )  # fmt: skip
    return len(due)


# -- staff review ----------------------------------------------------------------


def _notify_owner(db: Session, seller: Seller, template: str, **params: Any) -> None:
    notifications.notify(
        db, owner_user_id(db, seller.id), template, {"seller_id": str(seller.id), **params}
    )


def _staff_seller(db: Session, actor: Actor, seller_id: uuid.UUID) -> Seller:
    _refuse_own_seller(db, actor, seller_id)
    return get_seller(db, seller_id, lock=True)


def request_documents(db: Session, actor: Actor, seller_id: uuid.UUID, *, note: str) -> Seller:
    seller = _staff_seller(db, actor, seller_id)
    if seller.status != SellerStatus.APPLIED or seller.review_state != ReviewState.PENDING:
        raise Conflict("not_awaiting_review", "This application is not waiting for review.")
    before = _seller_snapshot(seller)
    seller.review_state = ReviewState.NEEDS_DOCUMENTS
    seller.review_note = note
    seller.reviewed_by_user_id = actor.user_id
    seller.reviewed_at = _now()
    db.flush()
    record_by(
        db, actor, "seller.request_documents", "seller", seller.id,
        before=before, after={**_seller_snapshot(seller), "note": note},
    )  # fmt: skip
    _notify_owner(db, seller, "seller.documents_requested")
    return seller


def _require_level(db: Session, seller: Seller, level: int) -> None:
    missing = _missing_for_level(seller, verification_checks(db, seller), level)
    if missing:
        raise Conflict(
            "verification_requirements_unmet",
            f"Level {level} needs checks that are not complete.",
            details={"missing": missing},
        )


def approve_application(
    db: Session,
    actor: Actor,
    seller_id: uuid.UUID,
    *,
    verification_level: int,
    shop_visited: bool,
    payout_account_name_matches: bool,
) -> Seller:
    """Approve an application at Level 1 (identity) or Level 2 (business).

    Level 3 is earned from track record and is never given at approval
    (blueprint D.3). The level must be backed by accepted documents.
    """
    seller = _staff_seller(db, actor, seller_id)
    if seller.status != SellerStatus.APPLIED or seller.review_state != ReviewState.PENDING:
        raise Conflict("not_awaiting_review", "This application is not waiting for review.")
    if verification_level not in (1, 2):
        raise ValidationFailed("level_invalid", "An application is approved at level 1 or 2.")
    if not payout_account_name_matches:
        raise Conflict(
            "payout_account_unchecked",
            "The payout account must be in the seller's own name (blueprint D.3).",
        )
    now = _now()
    if shop_visited and seller.shop_visited_at is None:
        seller.shop_visited_at = now
    _require_level(db, seller, verification_level)
    before = _seller_snapshot(seller)
    seller.status = SellerStatus.ACTIVE
    seller.review_state = ReviewState.APPROVED
    seller.review_note = None
    seller.verification_level = verification_level
    seller.reviewed_by_user_id = actor.user_id
    seller.reviewed_at = now
    seller.verified_at = now
    seller.recheck_due_on = now.date() + timedelta(
        days=settings_store.get_int(db, "sellers.recheck_after_days")
    )
    db.flush()
    record_by(
        db, actor, "seller.approve", "seller", seller.id,
        before=before,
        after={**_seller_snapshot(seller), "checks": verification_checks(db, seller)},
    )  # fmt: skip
    _notify_owner(db, seller, "seller.application_approved", level=verification_level)
    return seller


def reject_application(db: Session, actor: Actor, seller_id: uuid.UUID, *, reason: str) -> Seller:
    seller = _staff_seller(db, actor, seller_id)
    if seller.status != SellerStatus.APPLIED or seller.review_state not in (
        ReviewState.PENDING,
        ReviewState.NEEDS_DOCUMENTS,
    ):
        raise Conflict("not_awaiting_review", "This application is not waiting for review.")
    before = _seller_snapshot(seller)
    # Closing the seller frees its TIN for a corrected application.
    seller.status = SellerStatus.CLOSED
    seller.review_state = ReviewState.REJECTED
    seller.review_note = reason
    seller.reviewed_by_user_id = actor.user_id
    seller.reviewed_at = _now()
    db.flush()
    record_by(
        db, actor, "seller.reject", "seller", seller.id,
        before=before, after={**_seller_snapshot(seller), "reason": reason},
    )  # fmt: skip
    _notify_owner(db, seller, "seller.application_rejected")
    return seller


def set_verification_level(
    db: Session,
    actor: Actor,
    seller_id: uuid.UUID,
    *,
    level: int,
    reason: str,
    shop_visited: bool = False,
) -> Seller:
    """Staff raise or lower an approved seller's level (blueprint C.5: levels
    are set by staff, and nobody can assign one to themselves).

    Raising needs the checks behind the level. Level 3 is given only to a
    seller already at Level 2. Lowering is always possible, with a reason.
    """
    seller = _staff_seller(db, actor, seller_id)
    if seller.review_state != ReviewState.APPROVED or seller.status == SellerStatus.CLOSED:
        raise Conflict("seller_not_approved", "Only an approved seller has a verification level.")
    if shop_visited and seller.shop_visited_at is None:
        seller.shop_visited_at = _now()
    if level > seller.verification_level:
        if level == 3 and seller.verification_level < 2:
            raise Conflict("level_three_is_earned", "Level 3 follows a track record at level 2.")
        _require_level(db, seller, min(level, 2))
    before = _seller_snapshot(seller)
    seller.verification_level = level
    db.flush()
    if before["verification_level"] != level:
        record_by(
            db, actor, "seller.set_verification_level", "seller", seller.id,
            before=before, after={**_seller_snapshot(seller), "reason": reason},
        )  # fmt: skip
        _notify_owner(db, seller, "seller.verification_level_changed", level=level)
    return seller


def complete_recheck(db: Session, actor: Actor, seller_id: uuid.UUID, *, note: str) -> Seller:
    """The yearly re-check (blueprint D.3): staff confirm that the documents
    behind the seller's level still stand, and the next check is scheduled."""
    seller = _staff_seller(db, actor, seller_id)
    if seller.review_state != ReviewState.APPROVED or seller.status == SellerStatus.CLOSED:
        raise Conflict("seller_not_approved", "Only an approved seller is re-checked.")
    _require_level(db, seller, min(seller.verification_level, 2))
    before = {"recheck_due_on": seller.recheck_due_on and seller.recheck_due_on.isoformat()}
    seller.recheck_due_on = _today() + timedelta(
        days=settings_store.get_int(db, "sellers.recheck_after_days")
    )
    db.flush()
    record_by(
        db, actor, "seller.recheck", "seller", seller.id,
        before=before, after={"recheck_due_on": seller.recheck_due_on.isoformat(), "note": note},
    )  # fmt: skip
    return seller


def suspend_seller(db: Session, actor: Actor, seller_id: uuid.UUID, *, reason: str) -> Seller:
    seller = _staff_seller(db, actor, seller_id)
    if seller.status != SellerStatus.ACTIVE:
        raise Conflict("seller_not_active", "Only an active seller can be suspended.")
    before = _seller_snapshot(seller)
    seller.status = SellerStatus.SUSPENDED
    db.flush()
    record_by(
        db, actor, "seller.suspend", "seller", seller.id,
        before=before, after={**_seller_snapshot(seller), "reason": reason},
    )  # fmt: skip
    _notify_owner(db, seller, "seller.suspended")
    return seller


def reinstate_seller(db: Session, actor: Actor, seller_id: uuid.UUID, *, reason: str) -> Seller:
    seller = _staff_seller(db, actor, seller_id)
    if seller.status != SellerStatus.SUSPENDED:
        raise Conflict("seller_not_suspended", "Only a suspended seller can be reinstated.")
    before = _seller_snapshot(seller)
    seller.status = SellerStatus.ACTIVE
    db.flush()
    record_by(
        db, actor, "seller.reinstate", "seller", seller.id,
        before=before, after={**_seller_snapshot(seller), "reason": reason},
    )  # fmt: skip
    _notify_owner(db, seller, "seller.reinstated")
    return seller


# Orders a store still has to act on: everything but the final states.
OPEN_ORDER_STATUSES = frozenset(
    {
        SellerOrderStatus.PLACED,
        SellerOrderStatus.CONFIRMED,
        SellerOrderStatus.PAID,
        SellerOrderStatus.READY,
        SellerOrderStatus.OUT_FOR_DELIVERY,
        SellerOrderStatus.DELIVERED,
        SellerOrderStatus.DELIVERY_FAILED,
        SellerOrderStatus.DISPUTED,
    }
)


def close_seller(db: Session, actor: Actor, seller: Seller) -> Seller:
    """The owner withdraws an application or closes the store. It is final:
    the seller is archived, never deleted (blueprint G.1)."""
    seller = _lock(db, seller)
    if seller.status == SellerStatus.CLOSED:
        raise Conflict("seller_closed", "This store is already closed.")
    # A closed store can no longer act on its orders, so every order still in
    # progress must be finished first (D-076). The seller row is locked, and
    # checkout locks the same row before it places an order, so no order can
    # slip in between this count and the close.
    in_progress = db.scalar(
        select(func.count())
        .select_from(SellerOrder)
        .where(
            SellerOrder.seller_id == seller.id,
            SellerOrder.status.in_([status.value for status in OPEN_ORDER_STATUSES]),
        )
    )
    if in_progress:
        raise Conflict(
            "open_orders_remain",
            "Finish, decline or cancel the store's open orders before closing it.",
            details={"open_orders": int(in_progress)},
        )
    before = _seller_snapshot(seller)
    seller.status = SellerStatus.CLOSED
    db.flush()
    record_by(
        db, actor, "seller.close", "seller", seller.id,
        before=before, after=_seller_snapshot(seller),
    )  # fmt: skip
    return seller


# -- store -----------------------------------------------------------------------


def update_store(
    db: Session,
    actor: Actor,
    seller: Seller,
    *,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    return_policy: str | None = None,
    working_hours: str | None = None,
    areas_served: list[str] | None = None,
    telegram_channel: str | None = None,
) -> Store:
    seller = _lock(db, seller)
    store = get_store(db, seller.id)
    before = {
        "name": store.name, "slug": store.slug, "description": store.description,
        "return_policy": store.return_policy, "working_hours": store.working_hours,
        "areas_served": list(store.areas_served), "telegram_channel": store.telegram_channel,
    }  # fmt: skip
    if slug is not None and slug != store.slug:
        # Buyers and search engines keep the link once the store is public.
        if seller.status != SellerStatus.APPLIED:
            raise Conflict(
                "store_slug_locked", "The store link cannot change after the store is approved."
            )
        if not _SLUG.fullmatch(slug) or not 3 <= len(slug) <= 60:
            raise ValidationFailed("store_slug_invalid", "Use 3 to 60 letters, digits and hyphens.")
        store.slug = slug
    if name is not None:
        store.name = name
    if description is not None:
        store.description = description
    if return_policy is not None:
        store.return_policy = return_policy
    if working_hours is not None:
        store.working_hours = working_hours
    if areas_served is not None:
        store.areas_served = areas_served
    if telegram_channel is not None:
        store.telegram_channel = telegram_channel or None
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("store_slug_taken", "That store link is taken.") from exc
    after = {
        "name": store.name, "slug": store.slug, "description": store.description,
        "return_policy": store.return_policy, "working_hours": store.working_hours,
        "areas_served": list(store.areas_served), "telegram_channel": store.telegram_channel,
    }  # fmt: skip
    if after != before:
        record_by(db, actor, "store.update", "store", store.id, before=before, after=after)
    return store


# -- members ---------------------------------------------------------------------


def add_member(
    db: Session, actor: Actor, seller: Seller, *, raw_phone: str, role: str
) -> SellerMember:
    """Add a person, by phone number, to the seller's team.

    Release 1 has the owner and manager roles (blueprint D.4), so the only
    role that can be given is manager; ownership is not handed out here.
    """
    if role == SellerRole.OWNER or role not in RELEASE_1_SELLER_ROLES:
        raise ValidationFailed("role_not_available", "Only the manager role can be given for now.")
    seller = _lock(db, seller)
    if seller.kind == SellerKind.INDIVIDUAL:
        raise Conflict("individual_has_no_team", "An individual seller has no team members.")
    phone = accounts.parse_phone(raw_phone)
    user = accounts.get_or_create_user_by_phone(db, phone)
    member = db.scalar(
        select(SellerMember).where(
            SellerMember.seller_id == seller.id, SellerMember.user_id == user.id
        )
    )
    if member is not None and member.is_active:
        raise Conflict("already_member", "That person is already in the team.")
    seats = settings_store.get_int(db, "sellers.starter_seats")
    active = db.scalar(
        select(func.count())
        .select_from(SellerMember)
        .where(SellerMember.seller_id == seller.id, SellerMember.is_active)
    )
    if (active or 0) >= seats:
        raise Conflict("seat_limit_reached", f"This plan has {seats} team seats.")
    if member is None:
        member = SellerMember(seller_id=seller.id, user_id=user.id, role=role)
        db.add(member)
    else:
        member.role = role
        member.is_active = True
    member.invited_by_user_id = actor.user_id
    db.flush()
    record_by(
        db, actor, "seller_member.add", "seller_member", member.id,
        after={"seller_id": str(seller.id), "user_id": str(user.id), "role": role},
    )  # fmt: skip
    notifications.notify(db, user.id, "seller.member_added", {"seller_id": str(seller.id)})
    return member


def remove_member(
    db: Session, actor: Actor, seller: Seller, acting: SellerMember, member_id: uuid.UUID
) -> None:
    """Remove a team member, or leave the team yourself.

    The owner can never be removed (blueprint C.2). Access ends at once: every
    request re-checks the membership.
    """
    seller = _lock(db, seller)
    member = db.scalar(
        select(SellerMember).where(
            SellerMember.id == member_id,
            SellerMember.seller_id == seller.id,
            SellerMember.is_active,
        )
    )
    if member is None:
        raise NotFound("member_not_found", "That team member was not found.")
    leaving = member.id == acting.id
    if not leaving and not seller_can(acting.role, SellerCapability.MANAGE_STAFF):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    if member.role == SellerRole.OWNER:
        raise Conflict("owner_cannot_be_removed", "A store always has its owner.")
    member.is_active = False
    db.flush()
    record_by(
        db, actor, "seller_member.remove", "seller_member", member.id,
        before={"seller_id": str(seller.id), "user_id": str(member.user_id), "role": member.role},
    )  # fmt: skip
