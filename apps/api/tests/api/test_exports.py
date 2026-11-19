"""Data exports for an accountant (blueprint C.4, D.21, G.10, G.11, H.2;
D-068): only the super administrator and finance; whole Addis Ababa days;
exact amounts; no buyer data; seller text defused for spreadsheets; every
export in the audit log.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.exports.service import birr, period, text_cell
from markx.orders.deadlines import ADDIS_ABABA
from markx.payments.models import CommissionRule
from markx.sellers.models import Seller
from tests.api.test_reviews import Bought
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    market = Bazaar(db)
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(market.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    return market


def _today() -> str:
    return datetime.now(ADDIS_ABABA).date().isoformat()


def _csv(client: ApiClient, kind: str, first: str | None = None, last: str | None = None) -> Any:
    response = client.get(
        f"/admin/exports/{kind}",
        params={"first_day": first or _today(), "last_day": last or _today()},
    )
    return response


def _rows(response: Any) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.content.startswith("﻿".encode())  # a byte-order mark for spreadsheets
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_only_the_super_administrator_and_finance_export(bazaar: Bazaar, db: DbSession) -> None:
    allowed = {StaffRole.SUPER_ADMIN: bazaar.staff}
    allowed[StaffRole.FINANCE] = staff_client(db, "0911000304", StaffRole.FINANCE)
    for role, client in allowed.items():
        assert _csv(client, "fees").status_code == 200, role
    for i, role in enumerate((StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.CATALOGUE)):
        assert _csv(staff_client(db, f"09110003{i:02d}", role), "fees").status_code == 403
    assert error_code(_csv(bazaar.a, "fees")) == "staff_only"
    assert _csv(ApiClient(), "fees").status_code == 401


def test_the_four_exports_add_up_to_the_cent(bazaar: Bazaar, db: DbSession) -> None:
    """3% of 18,500.00 birr is 555.00; of 17,900.00, 537.00. The ledger holds
    both sides of each fee; the balances read the ledger."""
    Bought(bazaar, [(bazaar.a128, 1), (bazaar.b128, 1)])
    finance = staff_client(db, "0911000304", StaffRole.FINANCE)

    response = _csv(finance, "fees")
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "private, no-store"
    assert "attachment" in response.headers["content-disposition"]
    fees = _rows(response)
    assert sorted(
        (r["store"], r["item_value_etb"], r["fee_etb"], r["fee_santim"]) for r in fees
    ) == [
        ("alpha", "18500.00", "555.00", "55500"),
        ("beta", "17900.00", "537.00", "53700"),
    ]
    assert {r["seller_tin"] for r in fees} == {"0000000001", "0000000002"}

    ledger = _rows(_csv(finance, "ledger"))
    assert len(ledger) == 4
    debits = sum(int(r["amount_santim"]) for r in ledger if r["direction"] == "debit")
    credits = sum(int(r["amount_santim"]) for r in ledger if r["direction"] == "credit")
    assert debits == credits == 55500 + 53700

    orders = _rows(_csv(finance, "seller-orders"))
    assert {(r["store"], r["status"], r["fee_etb"]) for r in orders} == {
        ("alpha", "completed", "555.00"), ("beta", "completed", "537.00"),
    }  # fmt: skip
    # No buyer data at all: an accountant needs totals, not people.
    header = set(orders[0])
    assert not header & {"buyer", "phone", "name", "address", "buyer_user_id"}
    assert "0911555" not in str(orders)

    balances = _rows(_csv(finance, "seller-balances"))
    assert [(r["store"], r["charged_in_period_etb"], r["balance_at_end_etb"]) for r in balances] == [
        ("alpha", "555.00", "555.00"), ("beta", "537.00", "537.00"),
    ]  # fmt: skip

    # A period before anything happened: the header and nothing else, while
    # the balance at its end is zero too.
    yesterday = (datetime.now(ADDIS_ABABA).date() - timedelta(days=1)).isoformat()
    assert _rows(_csv(finance, "fees", yesterday, yesterday)) == []
    assert _rows(_csv(finance, "seller-balances", yesterday, yesterday)) == []

    db.rollback()
    exports = db.scalars(
        select(AuditLog).where(AuditLog.action == "data.export").order_by(AuditLog.id)
    ).all()
    assert [(e.target_id, e.after["rows"]) for e in exports] == [
        ("fees", 2), ("ledger", 4), ("seller-orders", 2), ("seller-balances", 2),
        ("fees", 0), ("seller-balances", 0),
    ]  # fmt: skip
    assert exports[0].after["from"] == _today()


def test_seller_typed_text_cannot_become_a_spreadsheet_formula(
    bazaar: Bazaar, db: DbSession
) -> None:
    Bought(bazaar, [(bazaar.a128, 1)])
    db.execute(
        update(Seller)
        .where(Seller.id == uuid.UUID(bazaar.a_id))
        .values(legal_name='=HYPERLINK("http://evil.example","Click")')
    )
    db.commit()
    (row,) = _rows(_csv(bazaar.staff, "fees"))
    assert row["seller_legal_name"] == '\'=HYPERLINK("http://evil.example","Click")'
    for dangerous in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx"):
        assert text_cell(dangerous).startswith("'")
    assert text_cell("Abebe Trading PLC") == "Abebe Trading PLC"


def test_periods_are_whole_addis_ababa_days_and_bounded(bazaar: Bazaar) -> None:
    p = period(date(2026, 11, 17), date(2026, 11, 17))
    assert p.start == datetime(2026, 11, 16, 21, 0, tzinfo=UTC)  # midnight in Addis
    assert p.end == datetime(2026, 11, 17, 21, 0, tzinfo=UTC)
    assert (birr(0), birr(5), birr(55500), birr(-150)) == ("0.00", "0.05", "555.00", "-1.50")
    assert error_code(_csv(bazaar.staff, "fees", "2026-11-17", "2026-11-16")) == "period_invalid"
    assert error_code(_csv(bazaar.staff, "fees", "2025-01-01", "2026-11-17")) == "period_too_long"
    assert _csv(bazaar.staff, "everything").status_code == 422
