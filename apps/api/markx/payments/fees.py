"""The fee on one seller's part of an order (blueprint J.8, D-099). Pure, no database.

The one place a fee is calculated: at completion (`orders.service`) and for
the estimate the seller sees before confirming (`orders.selectors`).

Each order line carries the rate, the rule and the rule's optional cap
copied at placement (D-042, D-099), so a later change to a rule never alters
a past order. The blueprint gives each rule "an optional cap per order"
(section D, "Commission rules"); a part is one seller's order, the thing the
seller is charged for, so the cap limits the fee on all of the part's lines
charged under that rule together. No fee can exceed it.

Lines placed before D-099 have no rule copied. Their cap was never stored
on the line, so their fee stays as it was charged (rate only); no rule with
a cap existed then (D-086, D-088).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from markx.core.money import Money


@dataclass(frozen=True, slots=True)
class FeeLine:
    line_total_santim: int
    commission_bps: int
    commission_rule_id: uuid.UUID | None
    commission_cap_santim: int | None


@dataclass(frozen=True, slots=True)
class Fee:
    amount: Money
    cap_applied: bool


def seller_order_fee(lines: Iterable[FeeLine]) -> Fee:
    """The fee for one part: each line's share at its own rate (rounded half
    up to a santim, as `Money.portion_bps` does), then each rule's cap on the
    sum of its lines. `cap_applied` is true when a cap lowered the fee."""
    by_rule: dict[uuid.UUID, tuple[Money, int | None]] = {}
    total = Money.zero()
    for line in lines:
        if line.commission_cap_santim is not None and line.commission_rule_id is None:
            raise ValueError("a capped line must name the rule its cap came from")
        share = Money(line.line_total_santim).portion_bps(line.commission_bps)
        if line.commission_rule_id is None:
            total += share
            continue
        before, cap = by_rule.get(line.commission_rule_id, (Money.zero(), None))
        if line.commission_rule_id in by_rule and cap != line.commission_cap_santim:
            raise ValueError("lines of one rule must carry the same cap")
        by_rule[line.commission_rule_id] = (before + share, line.commission_cap_santim)
    cap_applied = False
    for uncapped, cap in by_rule.values():
        if cap is not None and uncapped.amount > cap:
            total += Money(cap)
            cap_applied = True
        else:
            total += uncapped
    return Fee(total, cap_applied)
