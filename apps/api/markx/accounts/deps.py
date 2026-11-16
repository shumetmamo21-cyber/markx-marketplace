"""Who is asking (blueprint C.1: deny by default).

Every route that needs a signed-in person, a staff capability or a seller
capability declares it here. Nothing is trusted from the browser except the
session token, and that is checked against the database on every request.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select

from markx.accounts import service
from markx.accounts.models import Session, SessionKind, StaffMember, User
from markx.accounts.permissions import (
    SellerCapability,
    StaffCapability,
    seller_can,
    staff_can,
)
from markx.core.errors import NotAuthenticated, NotFound, PermissionDenied
from markx.core.http import CSRF_EXEMPT_PREFIXES, SAFE_METHODS, Db
from markx.core.security import constant_time_equal
from markx.sellers.models import Seller, SellerMember, SellerStatus

SESSION_COOKIE = "markx_session"
CSRF_COOKIE = "markx_csrf"
CSRF_HEADER = "x-csrf-token"


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    session: Session
    token: str
    staff: StaffMember | None

    @property
    def is_staff_session(self) -> bool:
        return self.session.kind == SessionKind.STAFF and self.staff is not None


@dataclass(frozen=True, slots=True)
class SellerContext:
    principal: Principal
    seller: Seller
    member: SellerMember


def presented_token(request: Request) -> tuple[str, str] | None:
    """The session token and how it arrived: a bearer header or a cookie."""
    authorization = request.headers.get("authorization", "")
    if authorization[:7].lower() == "bearer ":
        token = authorization[7:].strip()
        return (token, "header") if token else None
    cookie = request.cookies.get(SESSION_COOKIE)
    return (cookie, "cookie") if cookie else None


def get_optional_principal(request: Request, db: Db) -> Principal | None:
    presented = presented_token(request)
    if presented is None:
        return None
    token, transport = presented
    resolved = service.resolve_session(db, token)
    if resolved is None:
        return None
    session, user = resolved
    # A cookie session is not accepted as a bearer token, nor the reverse.
    if session.transport != transport:
        return None
    if (
        transport == "cookie"
        and request.method not in SAFE_METHODS
        and not request.url.path.startswith(CSRF_EXEMPT_PREFIXES)
    ):
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not constant_time_equal(supplied, service.csrf_token_for(token)):
            raise PermissionDenied("csrf_token_invalid", "Please reload the page and try again.")
    staff = None
    if session.kind == SessionKind.STAFF:
        staff = service.active_staff_for(db, user.id)
        if staff is None:
            # The staff account was deactivated after this session began.
            return None
    return Principal(user=user, session=session, token=token, staff=staff)


OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]


def get_principal(principal: OptionalPrincipal) -> Principal:
    if principal is None:
        raise NotAuthenticated("not_authenticated", "Please sign in.")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_staff(capability: StaffCapability) -> Callable[[Principal], Principal]:
    """Staff routes need a staff session, which only a password plus an
    authenticator code can create, and a role that holds the capability."""

    def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.is_staff_session or principal.staff is None:
            raise PermissionDenied("staff_only", "This area is for MarkX staff.")
        if not staff_can(principal.staff.role, capability):
            raise PermissionDenied("permission_denied", "Your role does not allow this.")
        return principal

    return dependency


def require_any_staff(principal: CurrentPrincipal) -> Principal:
    if not principal.is_staff_session:
        raise PermissionDenied("staff_only", "This area is for MarkX staff.")
    return principal


AnyStaff = Annotated[Principal, Depends(require_any_staff)]


def load_seller_context(
    db: Db, principal: Principal, seller_id: uuid.UUID, capability: SellerCapability | None
) -> SellerContext:
    row = db.execute(
        select(SellerMember, Seller)
        .join(Seller, Seller.id == SellerMember.seller_id)
        .where(
            SellerMember.seller_id == seller_id,
            SellerMember.user_id == principal.user.id,
            SellerMember.is_active,
        )
    ).first()
    if row is None:
        # The same answer for "no such seller" and "not your seller", so the
        # existence of another seller is never revealed.
        raise NotFound("seller_not_found", "That store was not found.")
    member, seller = row
    if seller.status == SellerStatus.CLOSED:
        raise PermissionDenied("seller_closed", "This store is closed.")
    if capability is not None and not seller_can(member.role, capability):
        raise PermissionDenied("permission_denied", "Your role in this store does not allow this.")
    return SellerContext(principal=principal, seller=seller, member=member)


def require_seller(
    capability: SellerCapability | None = None,
) -> Callable[[uuid.UUID, Principal, Db], SellerContext]:
    """Scope a route to one seller the caller belongs to (blueprint C.5)."""

    def dependency(seller_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> SellerContext:
        return load_seller_context(db, principal, seller_id, capability)

    return dependency
