"""The ledger (blueprint G.2, G.10): balanced, append-only postings.

A posting is one `ledger_transactions` row with its entries, written in the
caller's transaction. The database refuses, at commit, a transaction whose
debits and credits differ (migration 0003). Accounts are created the first
time they are posted to; their codes are fixed here so a statement can be
read off the ledger without a separate calculation (G.10 rule 5).

MarkX never holds a buyer's money (G.10 rule 1). The only posting in Release 1
is the fee a seller owes MarkX when a direct seller order completes: a
receivable from the seller against commission income.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.core.ids import uuid7
from markx.core.money import Money
from markx.payments.models import AccountKind, LedgerAccount, LedgerEntry, LedgerTransaction

COMMISSION_INCOME = "commission_income"


def account(
    db: Session, code: str, *, kind: AccountKind, name: str, seller_id: uuid.UUID | None = None
) -> LedgerAccount:
    """The account with this code, created on first use."""
    found = db.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
    if found is not None:
        return found
    db.execute(
        insert(LedgerAccount)
        .values(id=uuid7(), code=code, kind=kind.value, name=name, seller_id=seller_id)
        .on_conflict_do_nothing(index_elements=[LedgerAccount.code])
    )
    found = db.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
    assert found is not None
    return found


def seller_receivable(db: Session, seller_id: uuid.UUID) -> LedgerAccount:
    """What a seller owes MarkX in fees on direct orders, to be invoiced."""
    return account(
        db, f"seller_receivable:{seller_id}", kind=AccountKind.ASSET,
        name="Fees receivable from seller", seller_id=seller_id,
    )  # fmt: skip


def post(
    db: Session,
    *,
    idempotency_key: str,
    kind: str,
    reference_type: str,
    reference_id: uuid.UUID,
    description: str,
    debits: Sequence[tuple[LedgerAccount, Money]],
    credits: Sequence[tuple[LedgerAccount, Money]],
) -> LedgerTransaction:
    """Write one balanced transaction. Every amount must be above zero; the
    database checks the balance again at commit."""
    total_debit, total_credit = Money.zero(), Money.zero()
    for _, amount in debits:
        total_debit += amount
    for _, amount in credits:
        total_credit += amount
    if total_debit != total_credit:
        raise ValueError(f"ledger posting is not balanced: {total_debit} against {total_credit}")
    txn = LedgerTransaction(
        id=uuid7(), idempotency_key=idempotency_key, kind=kind,
        reference_type=reference_type, reference_id=reference_id, description=description,
    )  # fmt: skip
    db.add(txn)
    db.flush()
    for direction, lines in (("debit", debits), ("credit", credits)):
        for acct, amount in lines:
            entry = LedgerEntry(
                transaction_id=txn.id, account_id=acct.id, direction=direction,
                amount_santim=amount.amount, currency=amount.currency,
            )  # fmt: skip
            db.add(entry)
    db.flush()
    return txn


def charge_fee(
    db: Session, *, seller_id: uuid.UUID, seller_order_id: uuid.UUID, fee: Money, order_code: str
) -> LedgerTransaction:
    """The fee on a completed direct seller order (G.10 rule 4): the seller
    owes it to MarkX. Posted once per seller order."""
    income = account(db, COMMISSION_INCOME, kind=AccountKind.INCOME, name="Commission income")
    return post(
        db,
        idempotency_key=f"fee:{seller_order_id}",
        kind="fee_charge",
        reference_type="seller_order",
        reference_id=seller_order_id,
        description=f"Fee on {order_code}",
        debits=[(seller_receivable(db, seller_id), fee)],
        credits=[(income, fee)],
    )
