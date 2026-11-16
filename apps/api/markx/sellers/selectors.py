"""Read queries for sellers and stores."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.accounts.permissions import seller_capabilities
from markx.sellers.models import Seller, SellerMember, Store


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
