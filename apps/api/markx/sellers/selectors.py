"""Read queries for sellers and stores."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.accounts.permissions import seller_capabilities
from markx.orders.models import SellerOrder
from markx.sellers.models import (
    ReviewState,
    Seller,
    SellerDocument,
    SellerInvitation,
    SellerMember,
    SellerPayoutAccount,
    SellerStatus,
    Store,
)


def memberships_for_user(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SellerMember, Seller, Store.slug)
        .join(Seller, Seller.id == SellerMember.seller_id)
        .outerjoin(Store, Store.seller_id == Seller.id)
        .where(SellerMember.user_id == user_id, SellerMember.is_active)
        .order_by(Seller.created_at)
    ).all()
    return [
        {
            "seller_id": seller.id,
            "role": member.role,
            "capabilities": seller_capabilities(member.role),
            "trade_name": seller.trade_name,
            "status": seller.status,
            "review_state": seller.review_state,
            "verification_level": seller.verification_level,
            "store_slug": slug,
        }
        for member, seller, slug in rows
    ]


def members_of(db: Session, seller_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SellerMember, User)
        .join(User, User.id == SellerMember.user_id)
        .where(SellerMember.seller_id == seller_id, SellerMember.is_active)
        .order_by(SellerMember.created_at, SellerMember.id)
    ).all()
    return [
        {
            "id": member.id,
            "user_id": user.id,
            "name": user.name,
            "phone": user.phone,
            "role": member.role,
            "created_at": member.created_at,
        }
        for member, user in rows
    ]


def documents_of(db: Session, seller_id: uuid.UUID) -> list[SellerDocument]:
    return list(
        db.scalars(
            select(SellerDocument)
            .where(SellerDocument.seller_id == seller_id)
            .order_by(SellerDocument.created_at, SellerDocument.id)
        )
    )


def payout_accounts_of(db: Session, seller_id: uuid.UUID) -> list[SellerPayoutAccount]:
    """The active account and any change still cooling off. Never the number."""
    return list(
        db.scalars(
            select(SellerPayoutAccount)
            .where(
                SellerPayoutAccount.seller_id == seller_id,
                SellerPayoutAccount.status.in_(("active", "pending")),
            )
            .order_by(SellerPayoutAccount.status, SellerPayoutAccount.created_at)
        )
    )


def staff_seller_list(
    db: Session,
    *,
    status: str | None,
    review_state: str | None,
    recheck_due: bool,
    after: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    """The staff queue, oldest first. Keys are time-ordered, so the last id of
    one page is the cursor for the next (blueprint F.5)."""
    query = (
        select(Seller, Store.slug)
        .outerjoin(Store, Store.seller_id == Seller.id)
        .order_by(Seller.id)
        .limit(limit)
    )
    if status is not None:
        query = query.where(Seller.status == status)
    if review_state is not None:
        query = query.where(Seller.review_state == review_state)
    else:
        # A draft is the applicant's private work until it is submitted.
        query = query.where(Seller.review_state != ReviewState.DRAFT)
    if recheck_due:
        query = query.where(
            Seller.recheck_due_on <= func.current_date(), Seller.status != SellerStatus.CLOSED
        )
    if after is not None:
        query = query.where(Seller.id > after)
    return [
        {
            "id": seller.id,
            "kind": seller.kind,
            "trade_name": seller.trade_name,
            "legal_name": seller.legal_name,
            "status": seller.status,
            "review_state": seller.review_state,
            "verification_level": seller.verification_level,
            "submitted_at": seller.submitted_at,
            "recheck_due_on": seller.recheck_due_on,
            "store_slug": slug,
        }
        for seller, slug in db.execute(query).all()
    ]


def invitations(db: Session, *, limit: int) -> list[SellerInvitation]:
    return list(
        db.scalars(select(SellerInvitation).order_by(SellerInvitation.id.desc()).limit(limit))
    )


def completed_order_count(db: Session, seller_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(SellerOrder)
            .where(SellerOrder.seller_id == seller_id, SellerOrder.status == "completed")
        )
        or 0
    )


def public_store(db: Session, slug: str) -> tuple[Seller, Store] | None:
    """A store page exists only for a seller that is trading (blueprint D.1).
    An applicant's, a suspended and a closed store all look like no store."""
    row = db.execute(
        select(Seller, Store)
        .join(Store, Store.seller_id == Seller.id)
        .where(Store.slug == slug, Seller.status == SellerStatus.ACTIVE)
    ).first()
    return (row[0], row[1]) if row is not None else None
