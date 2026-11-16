"""Who among staff may review sellers and open documents (blueprint C.4)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.main import app
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client, start_application, submit_application

OPS = "0911000200"
ALLOWED = {StaffRole.SUPER_ADMIN, StaffRole.OPERATIONS}


def _pending_seller(db: DbSession) -> tuple[ApiClient, str, str]:
    ops = staff_client(db, OPS, StaffRole.OPERATIONS)
    seller, seller_id = start_application(ops, "0911000001")
    submit_application(seller, seller_id)
    document_id = ops.get(f"/admin/sellers/{seller_id}").json()["documents"][0]["id"]
    return seller, seller_id, document_id


def _calls(seller_id: str, document_id: str) -> list[tuple[str, str, dict[str, object] | None]]:
    base = f"/admin/sellers/{seller_id}"
    return [
        ("GET", "/admin/sellers", None),
        ("GET", "/admin/sellers/invitations", None),
        ("POST", "/admin/sellers/invitations", {"phone": "0911000077"}),
        ("GET", base, None),
        ("POST", f"{base}/documents/{document_id}/link", None),
        ("POST", f"{base}/documents/{document_id}/review", {"decision": "accepted"}),
        ("POST", f"{base}/request-documents", {"reason": "Need a clearer licence"}),
    ]


@pytest.mark.parametrize("role", list(StaffRole))
def test_only_the_super_administrator_and_operations_review_sellers(
    db: DbSession, role: StaffRole
) -> None:
    _, seller_id, document_id = _pending_seller(db)
    staff = staff_client(db, "0911000300", role)
    for method, path, body in _calls(seller_id, document_id):
        response = staff.request(method, path, json=body)
        if role in ALLOWED:
            assert response.status_code in (200, 201), f"{role} {method} {path}: {response.text}"
        else:
            assert response.status_code == 403, f"{role} {method} {path}"
            assert error_code(response) == "permission_denied"


@pytest.mark.parametrize("role", [r for r in StaffRole if r not in ALLOWED])
def test_other_staff_roles_decide_nothing_and_change_nothing(
    db: DbSession, role: StaffRole
) -> None:
    _, seller_id, _ = _pending_seller(db)
    staff = staff_client(db, "0911000300", role)
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    base = f"/admin/sellers/{seller_id}"
    for path, body in (
        ("approve", {"verification_level": 1, "payout_account_name_matches": True}),
        ("reject", {"reason": "Not allowed to decide"}),
        ("verification-level", {"level": 3, "reason": "Not allowed"}),
        ("suspend", {"reason": "Not allowed"}),
        ("reinstate", {"reason": "Not allowed"}),
        ("recheck", {"reason": "Not allowed"}),
    ):
        response = staff.post(f"{base}/{path}", json=body)
        assert response.status_code == 403, path
        assert error_code(response) == "permission_denied"
    db.rollback()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_before


def _admin_seller_routes() -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/v1/admin/sellers"):
            routes += [(method.upper(), path.removeprefix("/api/v1")) for method in operations]
    return sorted(routes)


@pytest.mark.parametrize(("method", "template"), _admin_seller_routes())
def test_every_staff_seller_route_is_closed_to_everyone_else(
    db: DbSession, method: str, template: str
) -> None:
    """A visitor, a customer, a seller owner, and a staff member who signed in
    with a phone code instead of password and authenticator."""
    seller, seller_id, document_id = _pending_seller(db)
    path = (
        template.replace("{seller_id}", seller_id)
        .replace("{document_id}", document_id)
        .replace("{invitation_id}", str(uuid.uuid4()))
    )
    assert ApiClient().request(method, path, json={}).status_code == 401

    customer = ApiClient()
    customer.sign_in("0911000099")
    staff_by_phone_code = ApiClient()
    staff_by_phone_code.sign_in(OPS)
    for client in (customer, seller, staff_by_phone_code):
        response = client.request(method, path, json={})
        assert response.status_code == 403, f"{method} {path}: {response.text}"
        assert error_code(response) == "staff_only"


def test_the_route_sweep_covers_the_staff_routes() -> None:
    assert len(_admin_seller_routes()) >= 13
