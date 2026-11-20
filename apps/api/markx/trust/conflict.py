"""Staff conflict of interest (blueprint C.5; audit H1; D-098).

Nobody decides their own case. A member of staff may not take a staff action
on a store they belong to, on an order they placed, or on a review or report
they wrote themselves. Every staff action that decides or changes something
about a store, an order, an offer, a review or a report calls
`refuse_conflict` as soon as it has found the thing and before it changes
anything, so the person learns that another member of staff must handle it.

A refused attempt is written to the audit log in its own short transaction:
the request itself fails and rolls back, and the attempt must still be on
record.

There is no override. PROVISIONAL (P-098-1, D-098): when no other member of staff is
able to act, the case waits. The founder decides whether anything else should
happen then.
  The engineer's safest default; THE FOUNDER MUST CONFIRM OR CHANGE IT BEFORE
  MARKX GOES LIVE.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.audit import service as audit
from markx.audit.service import Actor
from markx.core.db import session_scope
from markx.core.errors import PermissionDenied
from markx.sellers.models import SellerMember

# The reason recorded in the audit log, and the error the person sees.
OWN_STORE = "own_store"
OWN_ORDER = "own_order"
OWN_SUBMISSION = "own_submission"

_ERRORS: dict[str, tuple[str, str]] = {
    OWN_STORE: (
        "conflict_of_interest",
        "You belong to this seller, so another staff member must decide.",
    ),
    OWN_ORDER: (
        "conflict_own_order",
        "You placed this order, so another staff member must handle it.",
    ),
    OWN_SUBMISSION: (
        "conflict_own_submission",
        "You wrote this yourself, so another staff member must handle it.",
    ),
}

REFUSED_ACTION = "staff.conflict_refused"


def _belongs_to(
    db: Session, user_id: uuid.UUID, seller_ids: Iterable[uuid.UUID]
) -> uuid.UUID | None:
    wanted = sorted(set(seller_ids))
    if not wanted:
        return None
    return db.scalar(
        select(SellerMember.seller_id)
        .where(
            SellerMember.seller_id.in_(wanted),
            SellerMember.user_id == user_id,
            SellerMember.is_active,
        )
        .limit(1)
    )


def refuse_conflict(
    db: Session,
    actor: Actor,
    *,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    seller_ids: Iterable[uuid.UUID | None] = (),
    buyer_user_id: uuid.UUID | None = None,
    author_user_ids: Iterable[uuid.UUID | None] = (),
) -> None:
    """Raise `PermissionDenied` when `actor` is a party to what they act on.

    `seller_ids`: the stores concerned; an active member of any is refused.
    `buyer_user_id`: the person who placed the order concerned.
    `author_user_ids`: who wrote the review or report concerned.
    """
    if actor.user_id is None:
        return
    reason: str | None = None
    seller_id = _belongs_to(db, actor.user_id, (s for s in seller_ids if s is not None))
    if seller_id is not None:
        reason = OWN_STORE
    elif buyer_user_id is not None and buyer_user_id == actor.user_id:
        reason = OWN_ORDER
    elif actor.user_id in set(author_user_ids):
        reason = OWN_SUBMISSION
    if reason is None:
        return
    with session_scope() as side:
        audit.record_by(
            side, actor, REFUSED_ACTION, target_type, target_id,
            after={"attempted": action, "reason": reason,
                   "seller_id": str(seller_id) if seller_id else None},
        )  # fmt: skip
    code, message = _ERRORS[reason]
    raise PermissionDenied(code, message)
