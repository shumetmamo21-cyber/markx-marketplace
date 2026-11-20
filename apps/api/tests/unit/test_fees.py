"""The fee on one seller's part (`payments.fees`, D-099): each rule's cap per
order is applied, so no fee exceeds it. Money is whole santim, never a float."""

from __future__ import annotations

import uuid

import pytest

from markx.core.money import Money
from markx.payments.fees import Fee, FeeLine, seller_order_fee

PHONES = uuid.UUID("00000000-0000-7000-8000-000000000001")
CASES = uuid.UUID("00000000-0000-7000-8000-000000000002")


def line(total: int, bps: int, rule: uuid.UUID | None, cap: int | None = None) -> FeeLine:
    return FeeLine(
        line_total_santim=total, commission_bps=bps, commission_rule_id=rule,
        commission_cap_santim=cap,
    )  # fmt: skip


def test_no_rule_means_no_fee() -> None:
    assert seller_order_fee([line(1_850_000, 0, None)]) == Fee(Money.zero(), False)
    assert seller_order_fee([]) == Fee(Money.zero(), False)


def test_an_uncapped_rule_charges_its_rate_rounded_half_up_per_line() -> None:
    # 3% of 18,500.00 and of 21,000.50 birr: 555.00 and 630.015 -> 630.02.
    fee = seller_order_fee([line(1_850_000, 300, PHONES), line(2_100_050, 300, PHONES)])
    assert fee == Fee(Money(55_500 + 63_002), False)


def test_the_cap_limits_the_fee_on_all_of_a_parts_lines_of_its_rule_together() -> None:
    """The cap is per order, not per line: two phones in one part under a
    500 birr cap are charged 500 birr, not twice that."""
    fee = seller_order_fee(
        [line(1_850_000, 300, PHONES, 50_000), line(2_100_000, 300, PHONES, 50_000)]
    )
    assert fee == Fee(Money(50_000), True)


def test_a_cap_the_fee_does_not_reach_changes_nothing() -> None:
    assert seller_order_fee([line(1_000_000, 300, PHONES, 30_000)]) == Fee(Money(30_000), False)
    assert seller_order_fee([line(1_000_000, 300, PHONES, 30_001)]) == Fee(Money(30_000), False)
    assert seller_order_fee([line(1_000_000, 300, PHONES, 0)]) == Fee(Money.zero(), True)


def test_each_rule_has_its_own_cap() -> None:
    fee = seller_order_fee(
        [
            line(4_000_000, 400, PHONES, 50_000),  # 1,600 birr, capped at 500
            line(300_000, 1000, CASES, None),  # 300 birr, no cap
            line(900_000, 1000, CASES, None),  # 900 birr, no cap
        ]
    )
    assert fee == Fee(Money(50_000 + 30_000 + 90_000), True)


def test_lines_from_before_the_rule_was_copied_keep_their_rate() -> None:
    assert seller_order_fee([line(1_000_000, 300, None), line(1_000_000, 300, None)]) == Fee(
        Money(60_000), False
    )


def test_a_cap_without_its_rule_or_two_caps_for_one_rule_are_refused() -> None:
    with pytest.raises(ValueError, match="name the rule"):
        seller_order_fee([line(1_000_000, 300, None, 10_000)])
    with pytest.raises(ValueError, match="same cap"):
        seller_order_fee([line(1_000_000, 300, PHONES, 10_000), line(1, 300, PHONES, 20_000)])
