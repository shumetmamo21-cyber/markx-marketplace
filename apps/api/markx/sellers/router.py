"""Seller routes (blueprint F.5).

`/seller/...`        the seller dashboard, always scoped to one seller the
                     caller belongs to, through `require_seller`
`/admin/sellers/...` the staff queue (AD-01); staff sessions only
`/catalog/stores`    the public store page
`/documents/...`     private documents, through five-minute signed links
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from markx.accounts.deps import (
    CurrentPrincipal,
    Principal,
    SellerContext,
    load_seller_context,
    require_seller,
    require_staff,
)
from markx.accounts.models import SessionKind
from markx.accounts.permissions import (
    SellerCapability,
    StaffCapability,
    seller_can,
    seller_capabilities,
)
from markx.core import ratelimit, settings_store
from markx.core.errors import NotFound, PermissionDenied
from markx.core.http import Db
from markx.core.schemas import Ok
from markx.sellers import selectors, service
from markx.sellers.models import DocumentType, Seller, Store
from markx.sellers.schemas import (
    ApplicationIn,
    ApproveIn,
    DocumentLinkOut,
    DocumentOut,
    DocumentReviewIn,
    EligibilityOut,
    InvitationIn,
    InvitationOut,
    LegalOut,
    LegalUpdateIn,
    MemberIn,
    MemberOut,
    PayoutAccountIn,
    PayoutAccountOut,
    PublicStoreOut,
    ReasonIn,
    SellerAdminOut,
    SellerListItemOut,
    SellerOut,
    StoreBriefOut,
    StoreOut,
    StoreUpdateIn,
    VerificationLevelIn,
)

router = APIRouter(prefix="/seller", tags=["seller"])
admin_router = APIRouter(prefix="/admin/sellers", tags=["admin: sellers"])
public_router = APIRouter(tags=["stores"])

# Blueprint C.3, by capability. `AnyMember` is membership alone.
AnyMember = Annotated[SellerContext, Depends(require_seller())]
StoreEditor = Annotated[SellerContext, Depends(require_seller(SellerCapability.EDIT_STORE))]
TeamManager = Annotated[SellerContext, Depends(require_seller(SellerCapability.MANAGE_STAFF))]
LegalOwner = Annotated[
    SellerContext, Depends(require_seller(SellerCapability.CHANGE_LEGAL_DETAILS))
]
PayoutOwner = Annotated[
    SellerContext, Depends(require_seller(SellerCapability.CHANGE_PAYOUT_ACCOUNT))
]
ClosingOwner = Annotated[SellerContext, Depends(require_seller(SellerCapability.TRANSFER_OR_CLOSE))]

# Blueprint C.4.
SellerReviewer = Annotated[Principal, Depends(require_staff(StaffCapability.REVIEW_SELLERS))]
DocumentViewer = Annotated[Principal, Depends(require_staff(StaffCapability.VIEW_DOCUMENTS))]


def _seller_out(db: Db, context: SellerContext) -> SellerOut:
    seller, role = context.seller, context.member.role
    store = service.get_store(db, seller.id)
    is_owner = seller_can(role, SellerCapability.CHANGE_LEGAL_DETAILS)
    return SellerOut(
        id=seller.id,
        kind=seller.kind,
        trade_name=seller.trade_name,
        status=seller.status,
        review_state=seller.review_state,
        review_note=seller.review_note,
        verification_level=seller.verification_level,
        checks=service.verification_checks(db, seller),
        plan=seller.plan,
        submitted_at=seller.submitted_at,
        recheck_due_on=seller.recheck_due_on,
        store=StoreBriefOut(slug=store.slug, name=store.name),
        role=role,
        capabilities=seller_capabilities(role),
        missing=service.application_missing(db, seller) if is_owner else [],
    )


# -- applying --------------------------------------------------------------------


@router.get("/eligibility", response_model=EligibilityOut)
def read_eligibility(principal: CurrentPrincipal, db: Db) -> EligibilityOut:
    """Whether the signed-in person may apply to sell (invite-only at launch)."""
    return EligibilityOut(**service.application_eligibility(db, principal.user))


@router.post("/applications", response_model=SellerOut, status_code=201)
def start_application(
    body: ApplicationIn, principal: CurrentPrincipal, request: Request, db: Db
) -> SellerOut:
    if principal.session.kind == SessionKind.STAFF:
        raise PermissionDenied(
            "seller_session_required", "Sign in with your phone code to manage a store."
        )
    ratelimit.hit(f"seller-apply:{principal.user.id}", 5, timedelta(hours=1))
    seller = service.start_application(
        db, principal.actor(request), principal.user,
        service.ApplicationInput(
            kind=body.kind, legal_name=body.legal_name, trade_name=body.trade_name, tin=body.tin,
            licence_number=body.licence_number, contact_phone=body.contact_phone,
            shop_address=body.shop_address, shop_latitude=body.shop_latitude,
            shop_longitude=body.shop_longitude, store_slug=body.store_slug,
        ),
    )  # fmt: skip
    return _seller_out(db, load_seller_context(db, principal, seller.id, None))


@router.get("/{seller_id}", response_model=SellerOut)
def read_seller(context: AnyMember, db: Db) -> SellerOut:
    return _seller_out(db, context)


@router.get("/{seller_id}/legal", response_model=LegalOut)
def read_legal(context: LegalOwner) -> LegalOut:
    return LegalOut.model_validate(context.seller)


@router.patch("/{seller_id}/legal", response_model=LegalOut)
def update_legal(body: LegalUpdateIn, context: LegalOwner, request: Request, db: Db) -> LegalOut:
    seller = service.update_legal_details(
        db, context.principal.actor(request), context.seller, **body.model_dump()
    )
    return LegalOut.model_validate(seller)


@router.post("/{seller_id}/submit", response_model=SellerOut)
def submit_application(context: LegalOwner, request: Request, db: Db) -> SellerOut:
    service.submit_application(db, context.principal.actor(request), context.seller)
    return _seller_out(db, context)


@router.post("/{seller_id}/close", response_model=SellerOut)
def close_seller(context: ClosingOwner, request: Request, db: Db) -> SellerOut:
    service.close_seller(db, context.principal.actor(request), context.seller)
    return _seller_out(db, context)


# -- documents -------------------------------------------------------------------


@router.get("/{seller_id}/documents", response_model=list[DocumentOut])
def list_documents(context: LegalOwner, db: Db) -> list[DocumentOut]:
    return [DocumentOut.model_validate(d) for d in selectors.documents_of(db, context.seller.id)]


@router.post("/{seller_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    context: LegalOwner,
    request: Request,
    db: Db,
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    expires_on: Annotated[date | None, Form()] = None,
) -> DocumentOut:
    ratelimit.hit(f"seller-document:{context.seller.id}", 30, timedelta(hours=1))
    # Read one byte past the limit: enough to know the file is too large
    # without holding an arbitrarily large upload in memory.
    max_bytes = settings_store.get_int(db, "sellers.document_max_bytes")
    data = file.file.read(max_bytes + 1)
    document = service.upload_document(
        db, context.principal.actor(request), context.seller,
        doc_type=doc_type, data=data, expires_on=expires_on,
    )  # fmt: skip
    return DocumentOut.model_validate(document)


@router.post("/{seller_id}/documents/{document_id}/link", response_model=DocumentLinkOut)
def link_own_document(
    document_id: uuid.UUID, context: LegalOwner, request: Request, db: Db
) -> DocumentLinkOut:
    link = service.issue_document_link(
        db, context.principal.actor(request), context.seller.id, document_id
    )
    return DocumentLinkOut(url=link.path, expires_at=link.expires_at)


@public_router.get("/documents/{document_id}/content")
def read_document_content(
    document_id: uuid.UUID,
    principal: CurrentPrincipal,
    request: Request,
    db: Db,
    expires: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=20, max_length=64)],
) -> Response:
    """The file behind a signed link. The link alone is not enough: the same
    person it was issued to must be signed in, and still be allowed."""
    content = service.open_document(
        db, principal.actor(request), document_id, expires=expires, signature=signature,
        staff_role=principal.staff.role if principal.is_staff_session and principal.staff else None,
    )  # fmt: skip
    return Response(
        content=content.data,
        media_type=content.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# -- payout account --------------------------------------------------------------


@router.get("/{seller_id}/payout-accounts", response_model=list[PayoutAccountOut])
def list_payout_accounts(context: PayoutOwner, db: Db) -> list[PayoutAccountOut]:
    return [
        PayoutAccountOut.model_validate(a)
        for a in selectors.payout_accounts_of(db, context.seller.id)
    ]


@router.put("/{seller_id}/payout-account", response_model=PayoutAccountOut)
def set_payout_account(
    body: PayoutAccountIn, context: PayoutOwner, request: Request, db: Db
) -> PayoutAccountOut:
    ratelimit.hit(f"seller-payout:{context.seller.id}", 10, timedelta(hours=1))
    account = service.set_payout_account(
        db, context.principal.actor(request), context.seller, kind=body.kind,
        provider_name=body.provider_name, account_name=body.account_name,
        account_number=body.account_number,
    )  # fmt: skip
    return PayoutAccountOut.model_validate(account)


# -- store -----------------------------------------------------------------------


@router.get("/{seller_id}/store", response_model=StoreOut)
def read_store(context: AnyMember, db: Db) -> StoreOut:
    return StoreOut.model_validate(service.get_store(db, context.seller.id))


@router.patch("/{seller_id}/store", response_model=StoreOut)
def update_store(body: StoreUpdateIn, context: StoreEditor, request: Request, db: Db) -> StoreOut:
    store = service.update_store(
        db, context.principal.actor(request), context.seller, **body.model_dump()
    )
    return StoreOut.model_validate(store)


# -- members ---------------------------------------------------------------------


@router.get("/{seller_id}/members", response_model=list[MemberOut])
def list_members(context: TeamManager, db: Db) -> list[MemberOut]:
    return [MemberOut(**m) for m in selectors.members_of(db, context.seller.id)]


@router.post("/{seller_id}/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, context: TeamManager, request: Request, db: Db) -> MemberOut:
    ratelimit.hit(f"seller-member:{context.seller.id}", 20, timedelta(hours=1))
    member = service.add_member(
        db, context.principal.actor(request), context.seller, raw_phone=body.phone, role=body.role
    )
    return next(
        MemberOut(**m) for m in selectors.members_of(db, context.seller.id) if m["id"] == member.id
    )


@router.delete("/{seller_id}/members/{member_id}", response_model=Ok)
def remove_member(member_id: uuid.UUID, context: AnyMember, request: Request, db: Db) -> Ok:
    """Remove a team member (owner or manager), or leave the team yourself."""
    service.remove_member(
        db, context.principal.actor(request), context.seller, context.member, member_id
    )
    return Ok()


# -- public store page -----------------------------------------------------------


def _public_store_out(db: Db, seller: Seller, store: Store) -> PublicStoreOut:
    return PublicStoreOut(
        slug=store.slug,
        name=store.name,
        description=store.description,
        return_policy=store.return_policy,
        working_hours=store.working_hours,
        areas_served=list(store.areas_served),
        telegram_channel=store.telegram_channel,
        seller_kind=seller.kind,
        shop_address=seller.shop_address,
        shop_latitude=seller.shop_latitude,
        shop_longitude=seller.shop_longitude,
        verification_level=seller.verification_level,
        checks=service.verification_checks(db, seller),
        member_since=seller.verified_at or seller.created_at,
        completed_orders=selectors.completed_order_count(db, seller.id),
    )


@public_router.get("/catalog/stores/{slug}", response_model=PublicStoreOut)
def read_public_store(slug: str, db: Db, response: Response) -> PublicStoreOut:
    found = selectors.public_store(db, slug)
    if found is None:
        raise NotFound("store_not_found", "That store was not found.")
    response.headers["Cache-Control"] = "public, max-age=60"
    return _public_store_out(db, *found)


# -- staff: invitations ------------------------------------------------------------
# Declared before the `/{seller_id}` routes so "invitations" is not read as an id.


@admin_router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(
    _: SellerReviewer, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[InvitationOut]:
    return [InvitationOut.model_validate(i) for i in selectors.invitations(db, limit=limit)]


@admin_router.post("/invitations", response_model=InvitationOut, status_code=201)
def create_invitation(
    body: InvitationIn, staff: SellerReviewer, request: Request, db: Db
) -> InvitationOut:
    invitation = service.create_invitation(
        db, staff.actor(request), raw_phone=body.phone, note=body.note
    )
    return InvitationOut.model_validate(invitation)


@admin_router.delete("/invitations/{invitation_id}", response_model=Ok)
def revoke_invitation(
    invitation_id: uuid.UUID, staff: SellerReviewer, request: Request, db: Db
) -> Ok:
    service.revoke_invitation(db, staff.actor(request), invitation_id)
    return Ok()


# -- staff: the review queue -------------------------------------------------------


def _admin_out(db: Db, seller: Seller) -> SellerAdminOut:
    return SellerAdminOut(
        id=seller.id,
        kind=seller.kind,
        status=seller.status,
        review_state=seller.review_state,
        review_note=seller.review_note,
        verification_level=seller.verification_level,
        checks=service.verification_checks(db, seller),
        plan=seller.plan,
        created_at=seller.created_at,
        submitted_at=seller.submitted_at,
        reviewed_at=seller.reviewed_at,
        verified_at=seller.verified_at,
        shop_visited_at=seller.shop_visited_at,
        recheck_due_on=seller.recheck_due_on,
        legal=LegalOut.model_validate(seller),
        store=StoreOut.model_validate(service.get_store(db, seller.id)),
        members=[MemberOut(**m) for m in selectors.members_of(db, seller.id)],
        documents=[DocumentOut.model_validate(d) for d in selectors.documents_of(db, seller.id)],
        payout_accounts=[
            PayoutAccountOut.model_validate(a) for a in selectors.payout_accounts_of(db, seller.id)
        ],
    )


def _reviewable(db: Db, seller_id: uuid.UUID) -> Seller:
    seller = service.get_seller(db, seller_id)
    # A draft is the applicant's private work; staff see it once submitted.
    if seller.review_state == "draft":
        raise NotFound("seller_not_found", "That seller was not found.")
    return seller


@admin_router.get("", response_model=list[SellerListItemOut])
def list_sellers(
    _: SellerReviewer,
    db: Db,
    status: Literal["applied", "active", "suspended", "closed"] | None = None,
    review_state: Literal["pending", "needs_documents", "approved", "rejected"] | None = None,
    recheck_due: bool = False,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SellerListItemOut]:
    rows = selectors.staff_seller_list(
        db, status=status, review_state=review_state, recheck_due=recheck_due, after=after,
        limit=limit,
    )  # fmt: skip
    return [SellerListItemOut(**row) for row in rows]


@admin_router.get("/{seller_id}", response_model=SellerAdminOut)
def read_seller_for_review(seller_id: uuid.UUID, _: SellerReviewer, db: Db) -> SellerAdminOut:
    return _admin_out(db, _reviewable(db, seller_id))


@admin_router.post("/{seller_id}/documents/{document_id}/link", response_model=DocumentLinkOut)
def link_document_for_staff(
    seller_id: uuid.UUID, document_id: uuid.UUID, staff: DocumentViewer, request: Request, db: Db
) -> DocumentLinkOut:
    _reviewable(db, seller_id)
    link = service.issue_document_link(db, staff.actor(request), seller_id, document_id)
    return DocumentLinkOut(url=link.path, expires_at=link.expires_at)


@admin_router.post("/{seller_id}/documents/{document_id}/review", response_model=DocumentOut)
def review_document(
    seller_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentReviewIn,
    staff: DocumentViewer,
    request: Request,
    db: Db,
) -> DocumentOut:
    _reviewable(db, seller_id)
    document = service.review_document(
        db, staff.actor(request), seller_id, document_id, decision=body.decision, note=body.note
    )
    return DocumentOut.model_validate(document)


@admin_router.post("/{seller_id}/request-documents", response_model=SellerAdminOut)
def request_documents(
    seller_id: uuid.UUID, body: ReasonIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.request_documents(db, staff.actor(request), seller_id, note=body.reason)
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/approve", response_model=SellerAdminOut)
def approve(
    seller_id: uuid.UUID, body: ApproveIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.approve_application(
        db, staff.actor(request), seller_id, verification_level=body.verification_level,
        shop_visited=body.shop_visited,
        payout_account_name_matches=body.payout_account_name_matches,
    )  # fmt: skip
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/reject", response_model=SellerAdminOut)
def reject(
    seller_id: uuid.UUID, body: ReasonIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.reject_application(db, staff.actor(request), seller_id, reason=body.reason)
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/verification-level", response_model=SellerAdminOut)
def set_verification_level(
    seller_id: uuid.UUID, body: VerificationLevelIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.set_verification_level(
        db, staff.actor(request), seller_id, level=body.level, reason=body.reason,
        shop_visited=body.shop_visited,
    )  # fmt: skip
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/recheck", response_model=SellerAdminOut)
def complete_recheck(
    seller_id: uuid.UUID, body: ReasonIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.complete_recheck(db, staff.actor(request), seller_id, note=body.reason)
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/suspend", response_model=SellerAdminOut)
def suspend(
    seller_id: uuid.UUID, body: ReasonIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.suspend_seller(db, staff.actor(request), seller_id, reason=body.reason)
    return _admin_out(db, seller)


@admin_router.post("/{seller_id}/reinstate", response_model=SellerAdminOut)
def reinstate(
    seller_id: uuid.UUID, body: ReasonIn, staff: SellerReviewer, request: Request, db: Db
) -> SellerAdminOut:
    seller = service.reinstate_seller(db, staff.actor(request), seller_id, reason=body.reason)
    return _admin_out(db, seller)
