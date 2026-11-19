"""The admin back end (blueprint D.18, C.4, P11; D-065): the audit-log viewer,
switches and risk limits, staff accounts, the dispatch board and the
business dashboard, each for exactly the roles C.4 names, and every change
in the audit log with before and after values.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.admin import service as admin
from markx.audit.models import AuditLog
from markx.audit.service import Actor
from markx.core import settings_store
from markx.core.errors import Conflict
from markx.worker.runner import run_once
from tests.api.test_fulfilment import _both_parts_delivered, _confirm, _two_seller_order
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client

ROLES = (
    StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.CATALOGUE, StaffRole.FINANCE,
)  # fmt: skip


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


@pytest.fixture
def staff(db: DbSession, bazaar: Bazaar) -> dict[StaffRole, ApiClient]:
    clients = {role: staff_client(db, f"09110003{i:02d}", role) for i, role in enumerate(ROLES)}
    clients[StaffRole.SUPER_ADMIN] = bazaar.staff
    return clients


def _allowed(
    staff: dict[StaffRole, ApiClient], method: str, path: str, **kw: Any
) -> set[StaffRole]:
    allowed = set()
    for role, client in staff.items():
        response = client.request(method, path, **kw)
        if response.status_code < 400:
            allowed.add(role)
        else:
            assert response.status_code == 403, (role, path, response.text)
    return allowed


def test_each_tool_opens_for_exactly_the_roles_c4_names(
    staff: dict[StaffRole, ApiClient], bazaar: Bazaar
) -> None:
    # The catalogue role appears in none of these sets: it may open none.
    super_admin, ops, support, finance = (
        StaffRole.SUPER_ADMIN, StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.FINANCE,
    )  # fmt: skip
    assert _allowed(staff, "GET", "/admin/audit-log") == {super_admin, finance}
    assert _allowed(staff, "GET", "/admin/staff") == {super_admin}
    assert _allowed(staff, "GET", "/admin/settings") == {super_admin, ops}
    assert _allowed(staff, "GET", "/admin/dispatch-board") == {super_admin, ops}
    assert _allowed(staff, "GET", "/admin/dashboard") == {super_admin, ops, support, finance}
    # Not staff at all: a seller, a visitor.
    for path in ("/admin/audit-log", "/admin/settings", "/admin/dashboard"):
        assert error_code(bazaar.a.get(path)) == "staff_only"
        assert ApiClient().get(path).status_code == 401


def test_operations_change_risk_limits_and_only_the_super_administrator_the_rest(
    staff: dict[StaffRole, ApiClient], db: DbSession
) -> None:
    ops = staff[StaffRole.OPERATIONS]
    rows = {row["key"]: row for row in ops.get("/admin/settings").json()}
    assert rows["orders.max_order_value_santim"]["may_change"] is True
    assert rows["sellers.invite_only"]["may_change"] is False
    changed = ops.put("/admin/settings/orders.max_order_value_santim", json={"value": 5_000_000})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["value"], changed.json()["is_overridden"]) == (5_000_000, True)
    refused = ops.put("/admin/settings/sellers.invite_only", json={"value": False})
    assert refused.status_code == 403
    db.rollback()
    assert settings_store.get_setting(db, "sellers.invite_only") is True

    super_admin = staff[StaffRole.SUPER_ADMIN]
    assert (
        super_admin.put("/admin/settings/sellers.invite_only", json={"value": False}).status_code
        == 200
    )
    bad = super_admin.put("/admin/settings/orders.max_order_value_santim", json={"value": "lots"})
    assert error_code(bad) == "setting_invalid"
    assert error_code(super_admin.put("/admin/settings/no.such_key", json={"value": 1})) == (
        "setting_not_found"
    )
    db.rollback()
    entries = db.scalars(
        select(AuditLog).where(AuditLog.action == "setting.change").order_by(AuditLog.id)
    ).all()
    assert [(e.target_id, e.before, e.after) for e in entries] == [
        ("orders.max_order_value_santim", {"value": 30_000_000}, {"value": 5_000_000}),
        ("sellers.invite_only", {"value": True}, {"value": False}),
    ]


def test_the_audit_log_viewer_filters_and_pages(
    staff: dict[StaffRole, ApiClient], db: DbSession
) -> None:
    super_admin = staff[StaffRole.SUPER_ADMIN]
    for value in (3, 4, 5):
        assert (
            super_admin.put(
                "/admin/settings/orders.max_open_direct_orders", json={"value": value}
            ).status_code
            == 200
        )
    finance = staff[StaffRole.FINANCE]
    found = finance.get("/admin/audit-log", params={"action": "setting.change"}).json()
    assert [e["after"]["value"] for e in found] == [5, 4, 3]  # newest first
    page = finance.get("/admin/audit-log", params={"action": "setting.", "limit": 2}).json()
    assert len(page) == 2
    rest = finance.get(
        "/admin/audit-log", params={"action": "setting.", "before": page[-1]["id"]}
    ).json()
    assert [e["after"]["value"] for e in page + rest] == [5, 4, 3]
    by_target = finance.get(
        "/admin/audit-log",
        params={"target_type": "setting", "target_id": "orders.max_open_direct_orders"},
    ).json()
    assert len(by_target) == 3
    assert finance.get("/admin/audit-log", params={"action": "x;drop"}).status_code == 422


def test_staff_accounts_are_created_changed_and_switched_off_safely(
    staff: dict[StaffRole, ApiClient], db: DbSession
) -> None:
    super_admin = staff[StaffRole.SUPER_ADMIN]
    created = super_admin.post(
        "/admin/staff",
        json={"phone": "0911000777", "name": "Hana", "role": "support",
              "password": "a long staff passphrase"},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["staff"]["role"] == "support"
    assert body["staff"]["phone_last4"] == "0777"
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    # The new member signs in with the password and the authenticator code.
    hana = ApiClient()
    signed_in = hana.post(
        "/auth/staff/sign-in",
        json={"phone": "0911000777", "password": "a long staff passphrase",
              "totp_code": pyotp.TOTP(body["totp_secret"]).now()},
    )  # fmt: skip
    assert signed_in.status_code == 200, signed_in.text
    assert hana.get("/admin/dashboard").status_code == 200

    # A new role ends the member's staff sessions: they sign in again.
    staff_id = body["staff"]["id"]
    promoted = super_admin.post(f"/admin/staff/{staff_id}/role", json={"role": "operations"})
    assert promoted.json()["role"] == "operations"
    assert hana.get("/admin/dashboard").status_code == 401
    # Switched off: refused at once, even with a fresh session.
    off = super_admin.post(f"/admin/staff/{staff_id}/active", json={"active": False,
                                                                  "reason": "Left MarkX"})  # fmt: skip
    assert off.json()["is_active"] is False
    again = ApiClient().post(
        "/auth/staff/sign-in",
        json={"phone": "0911000777", "password": "a long staff passphrase",
              "totp_code": pyotp.TOTP(body["totp_secret"]).now()},
    )  # fmt: skip
    assert again.status_code in (401, 403)

    # Nobody changes their own role or switches themselves off.
    own = next(
        row["id"] for row in super_admin.get("/admin/staff").json() if row["role"] == "super_admin"
    )
    assert error_code(super_admin.post(f"/admin/staff/{own}/role", json={"role": "support"})) == (
        "own_account"
    )
    assert (
        error_code(
            super_admin.post(f"/admin/staff/{own}/active", json={"active": False, "reason": "Oops"})
        )
        == "own_account"
    )
    # And the last active super administrator is never removed, whoever asks.
    with pytest.raises(Conflict) as refused:
        admin.set_staff_active(db, Actor(type="staff", user_id=uuid.uuid4()), uuid.UUID(own),
                               active=False, reason="Test")  # fmt: skip
    assert refused.value.code == "last_super_admin"
    db.rollback()
    actions = db.scalars(
        select(AuditLog.action)
        .where(AuditLog.target_type == "staff_member", AuditLog.target_id == staff_id)
        .order_by(AuditLog.id)
    ).all()
    changes = {"staff.create", "staff.change_role", "staff.deactivate"}
    assert [a for a in actions if a in changes] == [
        "staff.create", "staff.change_role", "staff.deactivate",
    ]  # fmt: skip
    # The refused sign-in after switching off is on record too.
    assert "staff.sign_in_failed" in actions


def test_the_dispatch_board_lists_parts_waiting_for_a_rider(
    staff: dict[StaffRole, ApiClient], bazaar: Bazaar
) -> None:
    _, order = _two_seller_order(bazaar)[1:]
    alpha_id, beta_id = _confirm(bazaar, order)
    board = staff[StaffRole.OPERATIONS].get("/admin/dispatch-board").json()
    # Alpha delivers by rider; Beta's buyer collects, so Beta is not on it.
    assert [(row["seller_order_id"], row["mode"], row["store_slug"]) for row in board] == [
        (alpha_id, "seller_rider", "alpha")
    ]
    assert board[0]["order_code"] == order["code"]
    assert board[0]["late"] is False
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{base}/ready").status_code == 200
    (ready,) = staff[StaffRole.OPERATIONS].get("/admin/dispatch-board").json()
    assert ready["status"] == "ready"  # still waiting for its rider
    dispatched = bazaar.a.post(f"{base}/dispatch", json={"rider_name": "Dawit"})
    assert dispatched.status_code == 200, dispatched.text
    assert staff[StaffRole.OPERATIONS].get("/admin/dispatch-board").json() == []
    assert beta_id


def test_the_business_dashboard_counts_without_naming_anyone(
    staff: dict[StaffRole, ApiClient], bazaar: Bazaar
) -> None:
    run_once(datetime.now(UTC), jobs=())  # the worker builds the search index
    assert ApiClient().get("/search", params={"q": "samsung"}).json()["total"] == 1
    assert ApiClient().get("/search", params={"q": "zzzz nothing"}).json()["total"] == 0
    buyer, order, alpha_id, beta_id, _ = _both_parts_delivered(bazaar)
    for part in (alpha_id, beta_id):  # "the goods are right": complete now
        done = buyer.post(f"/me/orders/{order['id']}/seller-orders/{part}/confirm-received")
        assert done.status_code == 200, done.text
    figures = staff[StaffRole.FINANCE].get("/admin/dashboard", params={"days": 30}).json()
    assert figures["orders"] == 1
    assert figures["seller_orders"] == 2
    assert figures["seller_orders_by_status"] == {"completed": 2}
    assert figures["completed_value_santim"] == 3_700_000 + 1_790_000
    assert figures["answered_share"] == 1.0
    assert figures["delivery_success_share"] == 1.0
    assert figures["median_minutes_to_confirm"] is not None
    assert figures["funnel"]["searches"] == 2
    assert figures["funnel"]["zero_result_searches"] == 1
    assert figures["funnel"]["orders"] == 1
    assert figures["live_offers"] == 3
    assert figures["products_with_offers"] == 1
    assert figures["offers_per_product"] == 3.0
    text = str(figures)
    assert "0911" not in text
    assert "alpha" not in text.lower()
    assert staff[StaffRole.FINANCE].get("/admin/dashboard", params={"days": 0}).status_code == 422
