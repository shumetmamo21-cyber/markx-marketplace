"""Data exports for an accountant (blueprint C.4 "export data", D.21, H.2; D-068).

Four CSV files, for a period of whole days in Addis Ababa time:

* `fees`             every fee MarkX charged on a completed seller order: the
                     only revenue of Release 1 (G.10 rule 4), with the
                     seller's legal name and TIN for invoicing;
* `ledger`           every ledger entry posted, both sides of each
                     transaction, as the double-entry record (G.10);
* `seller-orders`    every seller order placed, with its money and outcome
                     and **no buyer data**: an accountant needs totals, not
                     names, phones or addresses (G.11, H.5);
* `seller-balances`  what each seller owes MarkX in fees at the end of the
                     period, from the ledger, never recalculated (G.10 rule 5).

Amounts are written twice: exact birr with two decimals ("1110.00"), made
from whole santim with integer arithmetic, and the santim themselves. Text a
seller typed is defused against spreadsheet formula injection. Every export
is audit-logged (H.2), with its kind, period and row count.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.core.errors import ValidationFailed
from markx.orders.deadlines import ADDIS_ABABA
from markx.orders.models import Order, SellerOrder, SellerOrderStatus
from markx.payments.models import FeeCharge, LedgerAccount, LedgerEntry, LedgerTransaction
from markx.sellers.models import Seller, Store

KINDS = ("fees", "ledger", "seller-orders", "seller-balances")
MAX_DAYS = 366
# A cell starting with one of these is a formula to a spreadsheet (OWASP
# "CSV injection"); a leading apostrophe makes it plain text again.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True, slots=True)
class Period:
    first_day: date
    last_day: date

    @property
    def start(self) -> datetime:
        """Midnight at the start of the first day, Addis Ababa time."""
        return datetime.combine(self.first_day, time.min, ADDIS_ABABA)

    @property
    def end(self) -> datetime:
        """Midnight after the last day, Addis Ababa time (exclusive)."""
        return datetime.combine(self.last_day + timedelta(days=1), time.min, ADDIS_ABABA)


def period(first_day: date, last_day: date) -> Period:
    if last_day < first_day:
        raise ValidationFailed("period_invalid", "The last day comes before the first.")
    if (last_day - first_day).days + 1 > MAX_DAYS:
        raise ValidationFailed("period_too_long", f"Export at most {MAX_DAYS} days at a time.")
    return Period(first_day, last_day)


def birr(santim: int) -> str:
    """Exact birr with two decimals, from whole santim: never a float."""
    sign = "-" if santim < 0 else ""
    whole, part = divmod(abs(santim), 100)
    return f"{sign}{whole}.{part:02d}"


def local(moment: datetime | None) -> str:
    return moment.astimezone(ADDIS_ABABA).strftime("%Y-%m-%d %H:%M:%S") if moment else ""


def text_cell(value: str | None) -> str:
    """Seller-typed text, defused for spreadsheets."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_START) else value


# -- the four exports -------------------------------------------------------------------


def _fees(db: Session, p: Period) -> tuple[Sequence[str], Iterable[Sequence[Any]]]:
    header = (
        "completed_at_addis", "order_code", "store", "seller_legal_name", "seller_tin",
        "item_value_etb", "fee_etb", "fee_santim", "cap_applied", "ledger_transaction_id",
    )  # fmt: skip
    rows = db.execute(
        select(FeeCharge, SellerOrder, Order.code, Store.slug, Seller.legal_name, Seller.tin)
        .join(SellerOrder, SellerOrder.id == FeeCharge.seller_order_id)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Seller, Seller.id == SellerOrder.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .where(SellerOrder.completed_at >= p.start, SellerOrder.completed_at < p.end)
        .order_by(SellerOrder.completed_at, SellerOrder.id)
    ).all()
    return header, (
        (
            local(so.completed_at),
            code,
            store,
            text_cell(legal_name),
            text_cell(tin),
            birr(fee.item_value_santim),
            birr(fee.amount_santim),
            fee.amount_santim,
            "yes" if fee.cap_applied else "no",
            fee.ledger_transaction_id or "",
        )
        for fee, so, code, store, legal_name, tin in rows
    )


def _ledger(db: Session, p: Period) -> tuple[Sequence[str], Iterable[Sequence[Any]]]:
    header = (
        "posted_at_addis", "transaction_id", "kind", "reference_type", "reference_id",
        "description", "account_code", "account_name", "direction", "amount_etb",
        "amount_santim",
    )  # fmt: skip
    rows = db.execute(
        select(LedgerTransaction, LedgerEntry, LedgerAccount)
        .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerTransaction.created_at >= p.start, LedgerTransaction.created_at < p.end)
        .order_by(LedgerTransaction.created_at, LedgerTransaction.id, LedgerEntry.direction.desc())
    ).all()
    return header, (
        (
            local(txn.created_at),
            txn.id,
            txn.kind,
            txn.reference_type,
            txn.reference_id,
            text_cell(txn.description),
            account.code,
            text_cell(account.name),
            entry.direction,
            birr(entry.amount_santim),
            entry.amount_santim,
        )
        for txn, entry, account in rows
    )


def _seller_orders(db: Session, p: Period) -> tuple[Sequence[str], Iterable[Sequence[Any]]]:
    header = (
        "placed_at_addis", "order_code", "store", "status", "items_total_etb",
        "delivery_fee_etb", "total_etb", "fee_etb", "paid_method", "completed_at_addis",
        "closed_reason",
    )  # fmt: skip
    rows = db.execute(
        select(SellerOrder, Order.code, Store.slug)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Store, Store.seller_id == SellerOrder.seller_id)
        .where(SellerOrder.created_at >= p.start, SellerOrder.created_at < p.end)
        .order_by(SellerOrder.created_at, SellerOrder.id)
    ).all()
    return header, (
        (
            local(so.created_at),
            code,
            store,
            so.status,
            birr(so.items_total_santim),
            birr(so.delivery_fee_santim),
            birr(so.total_santim),
            birr(so.commission_santim) if so.status == SellerOrderStatus.COMPLETED else "",
            so.paid_method or "",
            local(so.completed_at),
            text_cell(so.closed_reason),
        )
        for so, code, store in rows
    )


def _seller_balances(db: Session, p: Period) -> tuple[Sequence[str], Iterable[Sequence[Any]]]:
    """Per seller: fees charged in the period, and the balance of its
    receivable account at the end of the period (debits less credits)."""
    header = (
        "store", "seller_legal_name", "seller_tin", "charged_in_period_etb",
        "balance_at_end_etb", "balance_at_end_santim",
    )  # fmt: skip
    signed = case(
        (LedgerEntry.direction == "debit", LedgerEntry.amount_santim),
        else_=-LedgerEntry.amount_santim,
    )
    in_period = (LedgerTransaction.created_at >= p.start) & (LedgerTransaction.created_at < p.end)
    rows = db.execute(
        select(
            Store.slug,
            Seller.legal_name,
            Seller.tin,
            func.coalesce(
                func.sum(
                    case(
                        (in_period & (LedgerEntry.direction == "debit"), LedgerEntry.amount_santim),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(signed), 0),
        )
        .select_from(LedgerAccount)
        .join(Seller, Seller.id == LedgerAccount.seller_id)
        .join(Store, Store.seller_id == Seller.id)
        .join(LedgerEntry, LedgerEntry.account_id == LedgerAccount.id)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(
            LedgerAccount.code.startswith("seller_receivable:"),
            LedgerTransaction.created_at < p.end,
        )
        .group_by(Store.slug, Seller.legal_name, Seller.tin)
        .order_by(Store.slug)
    ).all()
    return header, (
        (
            store,
            text_cell(name),
            text_cell(tin),
            birr(int(charged)),
            birr(int(balance)),
            int(balance),
        )
        for store, name, tin, charged, balance in rows
    )


_BUILDERS = {
    "fees": _fees,
    "ledger": _ledger,
    "seller-orders": _seller_orders,
    "seller-balances": _seller_balances,
}


@dataclass(frozen=True, slots=True)
class Export:
    filename: str
    content: bytes
    rows: int


def export(db: Session, actor: Actor, kind: str, p: Period) -> Export:
    """Build one export and record that it was taken (H.2)."""
    header, rows = _BUILDERS[kind](db, p)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    record_by(
        db, actor, "data.export", "export", kind,
        after={"kind": kind, "from": p.first_day.isoformat(), "to": p.last_day.isoformat(),
               "rows": count},
    )  # fmt: skip
    # A byte-order mark, so spreadsheet programs read Amharic text as UTF-8.
    content = "﻿".encode() + out.getvalue().encode("utf-8")
    return Export(
        filename=f"markx-{kind}-{p.first_day.isoformat()}-to-{p.last_day.isoformat()}.csv",
        content=content,
        rows=count,
    )
