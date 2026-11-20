"""A commission rule's cap per order is applied (D-099; D-086 and D-088 item 1).

Before D-099 `commission_rules.cap_santim` was stored and never used: a capped
rule charged its full rate, and `fee_charges.cap_applied` was always false.
Now the rule and its cap are copied onto each order line at placement with
the rate, and every fee calculation applies the cap: the estimate the shop
sees before confirming, and the fee charged at completion.

Commission stays at zero (D-088): these tests create rules only inside their
own throwaway database, as the existing fee tests do. No rule is created
anywhere else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.orders.models import OrderItem
from markx.payments.models import CommissionRule, FeeCharge, LedgerEntry
from tests.bazaar import Bazaar
from tests.factories import add_to_cart, checkout

CAP = 50_000  # 500 birr


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def _phone_rule(db: Session, bazaar: Bazaar, *, cap: int | None) -> CommissionRule:
    rule = CommissionRule(
        scope="category", payment_kind="direct",
        category_id=uuid.UUID(bazaar.catalog["phones"]), rate_bps=300, cap_santim=cap,
    )  # fmt: skip
    db.add(rule)
    db.commit()
    return rule


def _two_phones_from_alpha(bazaar: Bazaar) -> tuple[Any, dict[str, Any], str]:
    """One part with two lines, 18,500 and 21,000 birr: 3% would be 1,185 birr."""
    buyer, address = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"])
    add_to_cart(buyer, bazaar.a256["id"])
    response = checkout(buyer, address, {"alpha": "seller_rider"})
    assert response.status_code == 201, response.text
    order = response.json()
    return buyer, order, str(order["seller_orders"][0]["id"])


def _complete(bazaar: Bazaar, buyer: Any, order: dict[str, Any], part: str) -> None:
    base = f"/seller/{bazaar.a_id}/orders/{part}"
    for step in ("confirm", "ready", "dispatch"):
        assert bazaar.a.post(f"{base}/{step}", json={}).status_code == 200
    mine = buyer.get(f"/me/orders/{order['id']}").json()["seller_orders"][0]
    assert (
        bazaar.a.post(f"{base}/handover", json={"code": mine["handover_code"]}).status_code == 200
    )
    done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{part}/confirm-received")
    assert done.status_code == 200, done.text


def test_a_capped_rule_never_charges_more_than_its_cap(bazaar: Bazaar, db: Session) -> None:
    rule = _phone_rule(db, bazaar, cap=CAP)
    buyer, order, part = _two_phones_from_alpha(bazaar)
    base = f"/seller/{bazaar.a_id}/orders/{part}"

    # The rule and its cap are copied onto each line with the rate.
    db.rollback()
    lines = db.execute(
        select(OrderItem.commission_bps, OrderItem.commission_rule_id, OrderItem.commission_cap_santim)
    ).all()  # fmt: skip
    assert sorted(lines) == [(300, rule.id, CAP), (300, rule.id, CAP)]

    # The shop sees the capped fee before it confirms (blueprint D.19).
    assert bazaar.a.get(base).json()["estimated_fee_santim"] == CAP

    _complete(bazaar, buyer, order, part)
    assert bazaar.a.get(base).json()["fee_santim"] == CAP
    db.rollback()
    (charge,) = db.scalars(select(FeeCharge))
    assert (charge.item_value_santim, charge.amount_santim, charge.cap_applied) == (
        3_950_000,
        CAP,
        True,
    )
    debit = db.scalar(
        select(func.sum(LedgerEntry.amount_santim)).where(
            LedgerEntry.transaction_id == charge.ledger_transaction_id,
            LedgerEntry.direction == "debit",
        )
    )
    assert debit == CAP


def test_a_cap_the_fee_does_not_reach_and_no_cap_change_nothing(
    bazaar: Bazaar, db: Session
) -> None:
    _phone_rule(db, bazaar, cap=None)
    buyer, order, part = _two_phones_from_alpha(bazaar)
    assert bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{part}").json()["estimated_fee_santim"] == (
        55_500 + 63_000
    )
    _complete(bazaar, buyer, order, part)
    db.rollback()
    (charge,) = db.scalars(select(FeeCharge))
    assert (charge.amount_santim, charge.cap_applied) == (118_500, False)


def test_a_later_rule_never_changes_the_cap_of_an_order_already_placed(
    bazaar: Bazaar, db: Session
) -> None:
    """J.8: the rate and its cap are the ones in force at placement."""
    _phone_rule(db, bazaar, cap=CAP)
    buyer, order, part = _two_phones_from_alpha(bazaar)
    db.add(
        CommissionRule(
            scope="seller", payment_kind="direct", seller_id=uuid.UUID(bazaar.a_id),
            rate_bps=1000, cap_santim=10_000_000, valid_from=datetime.now(UTC),
        )
    )  # fmt: skip
    db.commit()
    _complete(bazaar, buyer, order, part)
    db.rollback()
    (charge,) = db.scalars(select(FeeCharge))
    assert (charge.amount_santim, charge.cap_applied) == (CAP, True)


def test_no_rule_still_means_no_fee_and_nothing_copied(bazaar: Bazaar, db: Session) -> None:
    """D-088: commission stays at zero; with no rule nothing is copied."""
    buyer, order, part = _two_phones_from_alpha(bazaar)
    db.rollback()
    assert db.execute(
        select(OrderItem.commission_bps, OrderItem.commission_rule_id, OrderItem.commission_cap_santim)
    ).all() == [(0, None, None), (0, None, None)]  # fmt: skip
    _complete(bazaar, buyer, order, part)
    db.rollback()
    (charge,) = db.scalars(select(FeeCharge))
    assert (charge.amount_santim, charge.cap_applied, charge.ledger_transaction_id) == (
        0,
        False,
        None,
    )


def test_the_database_refuses_a_cap_without_its_rule_or_below_zero(
    bazaar: Bazaar, db: Session
) -> None:
    _two_phones_from_alpha(bazaar)
    rule = _phone_rule(db, bazaar, cap=CAP)
    for sql, constraint in (
        ("update order_items set commission_cap_santim = 100", "commission_cap_has_rule"),
        (
            "update order_items set commission_rule_id = :rule, commission_cap_santim = -1",
            "commission_cap_non_negative",
        ),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            db.execute(text(sql), {"rule": rule.id})
        db.rollback()
