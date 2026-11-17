"""The audit trail and the takedown queue for staff (blueprint C.4, D.18
AD-03, AD-17). Both are read-only views of what is already recorded."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client

MODERATORS = {StaffRole.SUPER_ADMIN, StaffRole.OPERATIONS, StaffRole.CATALOGUE}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


# -- the takedown queue -------------------------------------------------------------------


def _take_down(bazaar: Bazaar, offer_id: str, reason: str) -> None:
    response = bazaar.staff.post(f"/admin/offers/{offer_id}/remove", json={"reason": reason})
    assert response.status_code == 200, response.text


def test_the_queue_lists_held_offers_with_their_reason_until_lifted(bazaar: Bazaar) -> None:
    assert bazaar.staff.get("/admin/offers/held").json() == []
    _take_down(bazaar, bazaar.a128["id"], "Counterfeit reported")
    _take_down(bazaar, bazaar.b128["id"], "Stolen goods reported")
    held = bazaar.staff.get("/admin/offers/held", params={"lang": "en"}).json()
    assert [o["id"] for o in held] == [bazaar.b128["id"], bazaar.a128["id"]]
    newest = held[0]
    assert (newest["store_slug"], newest["store_name"]) == ("beta", "Beta")
    assert (newest["product_name"], newest["variant_label"]) == (
        "Samsung Galaxy A16",
        "Black · 128 GB",
    )
    assert (newest["status"], newest["reason"], newest["condition"]) == (
        "removed", "Stolen goods reported", "new",
    )  # fmt: skip
    assert newest["price_santim"] == 1_790_000
    assert newest["seller_id"] == bazaar.b_id
    amharic = bazaar.staff.get("/admin/offers/held").json()[0]
    assert amharic["product_name"] == "ሳምሰንግ ጋላክሲ A16"

    page = bazaar.staff.get("/admin/offers/held", params={"limit": 1}).json()
    rest = bazaar.staff.get(
        "/admin/offers/held", params={"limit": 1, "before": page[0]["id"]}
    ).json()
    assert [o["id"] for o in page + rest] == [o["id"] for o in held]

    lifted = bazaar.staff.post(
        f"/admin/offers/{bazaar.b128['id']}/restore", json={"reason": "Invoice checked"}
    )
    assert lifted.status_code == 200, lifted.text
    assert [o["id"] for o in bazaar.staff.get("/admin/offers/held").json()] == [bazaar.a128["id"]]


def test_a_seller_own_removal_is_not_in_the_queue(bazaar: Bazaar) -> None:
    removed = bazaar.a.delete(f"/seller/{bazaar.a_id}/offers/{bazaar.a256['id']}")
    assert removed.status_code == 200, removed.text
    assert bazaar.staff.get("/admin/offers/held").json() == []


@pytest.mark.parametrize("role", list(StaffRole))
def test_who_sees_the_takedown_queue(bazaar: Bazaar, db: DbSession, role: StaffRole) -> None:
    _take_down(bazaar, bazaar.a128["id"], "Counterfeit reported")
    staff = staff_client(db, "0911000300", role)
    response = staff.get("/admin/offers/held")
    if role in MODERATORS:
        assert response.status_code == 200, response.text
        assert [o["id"] for o in response.json()] == [bazaar.a128["id"]]
    else:
        assert response.status_code == 403
        assert error_code(response) == "permission_denied"


def test_sellers_and_visitors_never_see_the_takedown_queue(bazaar: Bazaar) -> None:
    _take_down(bazaar, bazaar.a128["id"], "Counterfeit reported")
    assert ApiClient().get("/admin/offers/held").status_code == 401
    for seller in (bazaar.a, bazaar.b):
        response = seller.get("/admin/offers/held")
        assert response.status_code == 403
        assert error_code(response) == "staff_only"
    unknown = bazaar.staff.get("/admin/offers/held", params={"before": str(uuid.uuid4())})
    assert unknown.status_code == 200
    assert unknown.json() == []
