"""Buyer addresses built around a landmark (blueprint D.10, C-08, C-19) and
data requests (C-28). One buyer never reaches another's rows (G.11)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import Address, StaffRole
from tests.conftest import ApiClient, error_code
from tests.factories import make_zone, staff_client

OPS = "0911000200"


@pytest.fixture
def zone(db: DbSession) -> dict[str, Any]:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    return make_zone(staff, "bole", areas=("Bole Medhanialem", "Bole Rwanda"))


def _address(area_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "recipient_name": "Abebe Kebede",
        "phone": "0911 23 45 67",
        "delivery_area_id": area_id,
        "landmark": "Behind Edna Mall, blue gate",
        **overrides,
    }


def test_a_buyer_saves_and_reuses_a_landmark_address(zone: dict[str, Any]) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    area = zone["areas"][0]
    response = buyer.post(
        "/me/addresses",
        json=_address(
            area["id"], phone2="0711223344", latitude=8.9955, longitude=38.7894,
            driver_notes="Call on arrival",
        ),
    )  # fmt: skip
    assert response.status_code == 201
    saved = response.json()
    assert saved["phone"] == "+251911234567"  # stored in international form
    assert saved["phone2"] == "+251711223344"
    assert saved["area_name_en"] == "Bole Medhanialem"
    assert saved["zone_id"] == zone["id"]
    assert saved["landmark"] == "Behind Edna Mall, blue gate"
    assert (saved["latitude"], saved["longitude"]) == (8.9955, 38.7894)

    listed = buyer.get("/me/addresses").json()
    assert [a["id"] for a in listed] == [saved["id"]]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"phone": "+14155550100"}, "phone_invalid"),
        ({"phone2": "12345678901"}, "phone_invalid"),
        ({"latitude": 9.0}, "map_pin_incomplete"),
        ({"longitude": 38.7}, "map_pin_incomplete"),
    ],
)
def test_bad_address_details_are_refused_with_a_clear_code(
    zone: dict[str, Any], overrides: dict[str, Any], code: str
) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    response = buyer.post("/me/addresses", json=_address(zone["areas"][0]["id"], **overrides))
    assert response.status_code == 422
    assert error_code(response) == code
    assert buyer.get("/me/addresses").json() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"landmark": ""},  # the landmark is the address
        {"landmark": "  "},
        {"recipient_name": "A"},
        {"latitude": 91, "longitude": 38},
        {"latitude": 9, "longitude": 181},
        {"unexpected": "field"},
    ],
)
def test_malformed_address_input_is_refused(
    zone: dict[str, Any], overrides: dict[str, Any]
) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    response = buyer.post("/me/addresses", json=_address(zone["areas"][0]["id"], **overrides))
    assert response.status_code == 422


def test_an_unknown_or_inactive_area_is_refused(db: DbSession, zone: dict[str, Any]) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    unknown = buyer.post("/me/addresses", json=_address("00000000-0000-7000-8000-000000000000"))
    assert unknown.status_code == 422
    assert error_code(unknown) == "area_unknown"

    area_id = zone["areas"][0]["id"]
    db.execute(Address.__table__.metadata.tables["delivery_areas"].update().values(is_active=False))
    db.commit()
    inactive = buyer.post("/me/addresses", json=_address(area_id))
    assert inactive.status_code == 422
    assert error_code(inactive) == "area_unknown"


def test_one_buyer_cannot_see_or_remove_another_buyers_address(zone: dict[str, Any]) -> None:
    alice, mallory = ApiClient(), ApiClient()
    alice.sign_in("0911234567")
    mallory.sign_in("0922334455")
    address_id = alice.post("/me/addresses", json=_address(zone["areas"][0]["id"])).json()["id"]

    assert mallory.get("/me/addresses").json() == []
    stolen = mallory.delete(f"/me/addresses/{address_id}")
    assert stolen.status_code == 404
    assert error_code(stolen) == "address_not_found"
    # The same answer as for an address that does not exist at all.
    missing = mallory.delete("/me/addresses/00000000-0000-7000-8000-000000000000")
    assert (missing.status_code, error_code(missing)) == (404, "address_not_found")
    assert len(alice.get("/me/addresses").json()) == 1


def test_removing_an_address_archives_it_and_keeps_the_row(
    db: DbSession, zone: dict[str, Any]
) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    address_id = buyer.post("/me/addresses", json=_address(zone["areas"][0]["id"])).json()["id"]
    assert buyer.delete(f"/me/addresses/{address_id}").status_code == 200
    assert buyer.get("/me/addresses").json() == []
    row = db.scalars(select(Address)).one()
    assert row.archived_at is not None
    # Removing it twice is a not-found, not an error.
    assert buyer.delete(f"/me/addresses/{address_id}").status_code == 404


def test_a_buyer_holds_at_most_ten_addresses(zone: dict[str, Any]) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911234567")
    area_id = zone["areas"][0]["id"]
    for i in range(10):
        assert (
            buyer.post("/me/addresses", json=_address(area_id, landmark=f"Gate {i}")).status_code
            == 201
        )
    over = buyer.post("/me/addresses", json=_address(area_id, landmark="Gate 11"))
    assert over.status_code == 409
    assert error_code(over) == "too_many_addresses"


def test_addresses_need_a_session(zone: dict[str, Any]) -> None:
    visitor = ApiClient()
    assert visitor.get("/me/addresses").status_code == 401
    assert visitor.post("/me/addresses", json=_address(zone["areas"][0]["id"])).status_code == 401


def test_a_person_can_ask_to_see_correct_or_delete_their_data() -> None:
    """Requirement C-28."""
    buyer, other = ApiClient(), ApiClient()
    buyer.sign_in("0911234567")
    other.sign_in("0922334455")
    for kind in ("export", "correct", "delete"):
        response = buyer.post("/me/data-requests", json={"kind": kind, "note": "please"})
        assert response.status_code == 201
        assert response.json()["status"] == "open"
    assert sorted(r["kind"] for r in buyer.get("/me/data-requests").json()) == [
        "correct",
        "delete",
        "export",
    ]
    assert other.get("/me/data-requests").json() == []
    assert buyer.post("/me/data-requests", json={"kind": "sell_my_data"}).status_code == 422
    assert ApiClient().get("/me/data-requests").status_code == 401
