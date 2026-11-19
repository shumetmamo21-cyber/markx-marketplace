"""One seller can never read or change another seller's data (blueprint C.5, G.11).

The P6 completion criterion: "A second seller cannot see or change the first
seller's data, in an automated test." Seller A is the attacker throughout.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.main import app
from markx.sellers.models import Seller, SellerDocument, SellerMember, SellerPayoutAccount, Store
from tests.conftest import ApiClient, error_code
from tests.factories import (
    make_seller,
    payout_body,
    staff_client,
    start_application,
    upload_document,
)

OPS = "0911000200"
A_PHONE = "0911000001"
B_PHONE = "0911000002"


class TwoSellers:
    def __init__(self, db: DbSession) -> None:
        self.staff = staff_client(db, OPS, StaffRole.OPERATIONS)
        self.a, self.a_id = make_seller(self.staff, A_PHONE, tin="0000000001", trade_name="Alpha")
        self.b, self.b_id = make_seller(self.staff, B_PHONE, tin="0000000002", trade_name="Beta")
        self.b_documents = self.b.get(f"/seller/{self.b_id}/documents").json()
        self.b_members = self.b.get(f"/seller/{self.b_id}/members").json()


@pytest.fixture
def two(db: DbSession) -> TwoSellers:
    return TwoSellers(db)


def _state(db: DbSession, seller_id: str) -> dict[str, Any]:
    """Everything seller-owned, read straight from the database."""
    db.rollback()
    seller = db.get(Seller, seller_id)
    assert seller is not None
    db.refresh(seller)
    store = db.scalar(select(Store).where(Store.seller_id == seller.id))
    assert store is not None
    db.refresh(store)

    def columns(row: Any) -> dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    return {
        "seller": columns(seller),
        "store": columns(store),
        "members": sorted(
            (str(m.user_id), m.role, m.is_active)
            for m in db.scalars(select(SellerMember).where(SellerMember.seller_id == seller.id))
        ),
        "documents": db.scalar(
            select(func.count()).select_from(SellerDocument).where(
                SellerDocument.seller_id == seller.id
            )
        ),
        "payout_accounts": sorted(
            (a.account_last4, a.status)
            for a in db.scalars(
                select(SellerPayoutAccount).where(SellerPayoutAccount.seller_id == seller.id)
            )
        ),
    }  # fmt: skip


# -- reading ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["", "/legal", "/documents", "/payout-accounts", "/store", "/members"],
)
def test_seller_a_cannot_read_seller_b(two: TwoSellers, path: str) -> None:
    own = two.a.get(f"/seller/{two.a_id}{path}")
    assert own.status_code == 200, own.text
    response = two.a.get(f"/seller/{two.b_id}{path}")
    assert response.status_code == 404
    assert error_code(response) == "seller_not_found"
    # Nothing of B's leaks into the refusal.
    for secret in ("Beta", "0000000002", "+251911000002", two.b_id):
        assert secret not in response.text


def test_another_sellers_id_looks_exactly_like_one_that_does_not_exist(two: TwoSellers) -> None:
    theirs = two.a.get(f"/seller/{two.b_id}/legal")
    nobody = two.a.get(f"/seller/{uuid.uuid4()}/legal")
    assert theirs.status_code == nobody.status_code == 404
    strip = re.compile(r'"request_id":"[^"]+"')
    assert strip.sub("", theirs.text) == strip.sub("", nobody.text)


def test_me_lists_only_my_own_sellers(two: TwoSellers) -> None:
    sellers = two.a.get("/me").json()["sellers"]
    assert [s["seller_id"] for s in sellers] == [two.a_id]


# -- changing --------------------------------------------------------------------


def test_seller_a_cannot_change_anything_of_seller_b(two: TwoSellers, db: DbSession) -> None:
    before = _state(db, two.b_id)
    b = two.b_id
    attempts = [
        two.a.patch(f"/seller/{b}/store", json={"name": "Hacked", "description": "Owned by A"}),
        two.a.patch(f"/seller/{b}/legal", json={"contact_phone": A_PHONE}),
        two.a.put(f"/seller/{b}/payout-account", json=payout_body(account_number="9999999999")),
        two.a.post(f"/seller/{b}/members", json={"phone": A_PHONE}),
        two.a.delete(f"/seller/{b}/members/{two.b_members[0]['id']}"),
        two.a.post(f"/seller/{b}/submit"),
        two.a.post(f"/seller/{b}/close"),
        upload_document(two.a, b, "other"),
        two.a.post(f"/seller/{b}/documents/{two.b_documents[0]['id']}/link"),
    ]
    for response in attempts:
        assert response.status_code == 404, response.text
        assert error_code(response) == "seller_not_found"
    assert _state(db, two.b_id) == before
    assert ApiClient().get("/catalog/stores/beta").json()["name"] == "Beta"


# -- manipulated identifiers -----------------------------------------------------


def test_b_document_id_under_a_seller_id_is_not_found(two: TwoSellers, db: DbSession) -> None:
    """A is a real owner of seller A, and swaps in an id that belongs to B."""
    document_id = two.b_documents[0]["id"]
    response = two.a.post(f"/seller/{two.a_id}/documents/{document_id}/link")
    assert response.status_code == 404
    assert error_code(response) == "document_not_found"
    assert (
        db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "seller_document.link_issued"
        )) == 0
    )  # fmt: skip


def test_b_member_id_under_a_seller_id_is_not_found(two: TwoSellers, db: DbSession) -> None:
    two.b.post(f"/seller/{two.b_id}/members", json={"phone": "0911000050"})
    manager = two.b.get(f"/seller/{two.b_id}/members").json()[1]
    before = _state(db, two.b_id)
    response = two.a.delete(f"/seller/{two.a_id}/members/{manager['id']}")
    assert response.status_code == 404
    assert error_code(response) == "member_not_found"
    assert _state(db, two.b_id) == before


def test_a_link_signed_for_b_does_not_open_for_a(two: TwoSellers, db: DbSession) -> None:
    """B's owner gets a link to B's own document; A obtains the URL."""
    link = two.b.post(f"/seller/{two.b_id}/documents/{two.b_documents[0]['id']}/link").json()
    assert two.b.http.get(link["url"]).status_code == 200

    stolen = two.a.http.get(link["url"])
    assert stolen.status_code == 403
    assert error_code(stolen) == "document_link_invalid"
    assert not stolen.content.startswith(b"\x89PNG")
    assert ApiClient().http.get(link["url"]).status_code == 401


def test_a_cannot_retarget_its_own_link_at_b_document(two: TwoSellers) -> None:
    own = two.a.get(f"/seller/{two.a_id}/documents").json()[0]
    link = two.a.post(f"/seller/{two.a_id}/documents/{own['id']}/link").json()["url"]
    forged = link.replace(own["id"], two.b_documents[0]["id"])
    response = two.a.http.get(forged)
    assert response.status_code == 403
    assert error_code(response) == "document_link_invalid"


def test_a_seller_id_in_the_body_or_query_is_never_trusted(two: TwoSellers, db: DbSession) -> None:
    before = _state(db, two.b_id)
    # Unknown fields are refused outright, so a smuggled seller_id is an error.
    response = two.a.patch(
        f"/seller/{two.a_id}/store", json={"name": "Alpha 2", "seller_id": two.b_id}
    )
    assert response.status_code == 422
    # In the query string it is ignored: the path decides, and A's store changes.
    response = two.a.patch(
        f"/seller/{two.a_id}/store", params={"seller_id": two.b_id}, json={"name": "Alpha 2"}
    )
    assert response.status_code == 200
    assert _state(db, two.b_id) == before
    assert ApiClient().get("/catalog/stores/alpha").json()["name"] == "Alpha 2"


def test_a_cannot_take_b_store_link_or_tin(two: TwoSellers, db: DbSession) -> None:
    c, c_id = start_application(two.staff, "0911000003", tin="0000000003", trade_name="Gamma")
    assert error_code(c.patch(f"/seller/{c_id}/store", json={"slug": "beta"})) == "store_slug_taken"
    assert error_code(c.patch(f"/seller/{c_id}/legal", json={"tin": "0000000002"})) == "tin_taken"
    assert db.scalar(select(Store.seller_id).where(Store.slug == "beta")) == uuid.UUID(two.b_id)


# -- every seller route, present and future ----------------------------------------


def _seller_scoped_routes() -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/v1/seller/{seller_id}"):
            routes += [(method.upper(), path.removeprefix("/api/v1")) for method in operations]
    return sorted(routes)


def test_there_are_seller_scoped_routes_to_check() -> None:
    assert len(_seller_scoped_routes()) >= 14


@pytest.mark.parametrize(("method", "template"), _seller_scoped_routes())
def test_every_seller_scoped_route_refuses_a_non_member(
    two: TwoSellers, db: DbSession, method: str, template: str
) -> None:
    """Runs over every route under /seller/{seller_id}, including ones added
    later: a signed-in member of another seller always gets "not found", and a
    visitor is always asked to sign in. Neither changes anything."""
    before = _state(db, two.b_id)
    path = template.replace("{seller_id}", two.b_id)
    path = re.sub(r"\{[a-z_]+\}", str(uuid.uuid4()), path)

    response = two.a.request(method, path, json={})
    assert response.status_code == 404, f"{method} {path}: {response.text}"
    assert error_code(response) == "seller_not_found"

    visitor = ApiClient().request(method, path, json={})
    assert visitor.status_code == 401, f"{method} {path}: {visitor.text}"
    assert _state(db, two.b_id) == before


# -- membership is what grants access, and only while it lasts ------------------------


def test_a_removed_member_loses_access_at_once(two: TwoSellers) -> None:
    two.b.post(f"/seller/{two.b_id}/members", json={"phone": "0911000050"})
    manager = ApiClient()
    manager.sign_in("0911000050")
    assert manager.get(f"/seller/{two.b_id}/store").status_code == 200

    member_id = two.b.get(f"/seller/{two.b_id}/members").json()[1]["id"]
    assert two.b.delete(f"/seller/{two.b_id}/members/{member_id}").status_code == 200
    # The same session, one request later.
    response = manager.get(f"/seller/{two.b_id}/store")
    assert response.status_code == 404
    assert error_code(response) == "seller_not_found"
    assert manager.get("/me").json()["sellers"] == []


def test_a_person_in_two_sellers_acts_only_for_the_one_in_the_path(two: TwoSellers) -> None:
    """A's owner is also B's manager: B's rules, not A's ownership, apply at B."""
    two.b.post(f"/seller/{two.b_id}/members", json={"phone": A_PHONE})
    assert {s["seller_id"]: s["role"] for s in two.a.get("/me").json()["sellers"]} == {
        two.a_id: "owner", two.b_id: "manager",
    }  # fmt: skip
    assert two.a.get(f"/seller/{two.b_id}/store").status_code == 200
    assert two.a.get(f"/seller/{two.a_id}/legal").status_code == 200
    for response in (
        two.a.get(f"/seller/{two.b_id}/legal"),
        two.a.get(f"/seller/{two.b_id}/payout-accounts"),
        two.a.get(f"/seller/{two.b_id}/documents"),
        two.a.post(f"/seller/{two.b_id}/close"),
    ):
        assert response.status_code == 403
        assert error_code(response) == "permission_denied"


def test_an_applicant_cannot_reach_a_trading_seller_either(two: TwoSellers) -> None:
    c, _ = start_application(two.staff, "0911000003", tin="0000000003")
    assert c.get(f"/seller/{two.b_id}").status_code == 404
    assert c.patch(f"/seller/{two.b_id}/store", json={"name": "Mine now"}).status_code == 404
