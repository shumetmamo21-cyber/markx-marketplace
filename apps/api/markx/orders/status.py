"""The seller order life cycle (blueprint G.6). Pure rules, no database.

`ALLOWED_MOVES` is the state diagram, arrow for arrow. The service refuses any
other move, and so does a trigger in the database (migration 0007); a test
checks that the two agree on all 196 pairs of states.
"""

from __future__ import annotations

from collections.abc import Iterable

from markx.orders.models import SellerOrderStatus as S

ALLOWED_MOVES: dict[S, frozenset[S]] = {
    S.PLACED: frozenset({S.CONFIRMED, S.DECLINED, S.EXPIRED, S.CANCELLED}),
    S.CONFIRMED: frozenset({S.READY, S.PAID, S.EXPIRED, S.CANCELLED}),
    S.PAID: frozenset({S.READY, S.REFUNDED}),
    S.READY: frozenset({S.OUT_FOR_DELIVERY, S.DELIVERED, S.CANCELLED}),
    S.OUT_FOR_DELIVERY: frozenset({S.DELIVERED, S.DELIVERY_FAILED}),
    S.DELIVERY_FAILED: frozenset({S.OUT_FOR_DELIVERY, S.RETURNED}),
    S.DELIVERED: frozenset({S.COMPLETED, S.DISPUTED}),
    S.DISPUTED: frozenset({S.COMPLETED, S.REFUNDED}),
    S.DECLINED: frozenset(),
    S.EXPIRED: frozenset(),
    S.CANCELLED: frozenset(),
    S.RETURNED: frozenset(),
    S.COMPLETED: frozenset(),
    S.REFUNDED: frozenset(),
}

# Ended before the goods changed hands: the held stock goes back (G.6).
ENDED_WITHOUT_DELIVERY = frozenset({S.DECLINED, S.EXPIRED, S.CANCELLED})
# Ended with a reason worth keeping on the row, for either side to read.
CLOSED_WITH_REASON = ENDED_WITHOUT_DELIVERY | {S.RETURNED}
# The handover code is live: the buyer sees it, the seller or rider enters it.
AWAITING_HANDOVER = frozenset({S.READY, S.OUT_FOR_DELIVERY, S.DELIVERY_FAILED})
# The goods have been handed over (D.12): only now may the seller record that
# the buyer paid them directly. Never in advance (F-09, option 2; D-087): a
# payment recorded before the handover could leave an order that cannot go
# ahead with the buyer's money and no way back. The database refuses the same
# (`trg_seller_orders_payment_at_handover`).
PAYABLE = frozenset({S.DELIVERED, S.COMPLETED, S.DISPUTED})
FINAL = frozenset(state for state, moves in ALLOWED_MOVES.items() if not moves)
OPEN = frozenset(ALLOWED_MOVES) - FINAL
_HANDED_OVER = frozenset({S.DELIVERED, S.COMPLETED, S.DISPUTED})


def move_allowed(current: str, new: str) -> bool:
    try:
        return S(new) in ALLOWED_MOVES[S(current)]
    except ValueError:
        return False


def contact_visible(status: str, confirmed: bool) -> bool:
    """Buyer and seller see each other's phone number only after the seller
    confirms the order (blueprint C.5), and not once it ended undelivered."""
    return confirmed and status not in ENDED_WITHOUT_DELIVERY


def derive_order_status(statuses: Iterable[str]) -> str:
    """The parent order has no status of its own (blueprint D.11): it is read
    off its seller orders every time.

    One seller order, or all alike: that status. Otherwise, in this order:
    still waiting for a seller; some handed over while others are on the way;
    everything ended (completed if anything was handed over, else cancelled);
    and in progress for the rest.
    """
    seen = {S(status) for status in statuses}
    if not seen:
        raise ValueError("an order always has at least one seller order")
    if len(seen) == 1:
        return next(iter(seen)).value
    if S.PLACED in seen:
        return "awaiting_seller"
    handed_over = seen & _HANDED_OVER
    still_moving = seen & (OPEN - _HANDED_OVER)
    if handed_over and still_moving:
        return "partly_delivered"
    if not still_moving:
        return "completed" if handed_over else "cancelled"
    return "in_progress"
