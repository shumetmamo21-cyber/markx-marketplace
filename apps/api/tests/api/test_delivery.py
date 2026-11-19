"""Delivery zones and flat fees (blueprint D.13, AD-05), and who may change them (C.4)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from tests.conftest import ApiClient, error_code
from tests.factories import make_zone, staff_client

OPS = "0911000200"


def test_operations_staff_build_a_zone_with_areas_and_fees(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    zone = make_zone(staff, "bole", areas=("Bole Medhanialem", "Bole Rwanda"))
    assert zone["code"] == "bole"
    assert [a["name_en"] for a in zone["areas"]] == ["Bole Medhanialem", "Bole Rwanda"]
    assert {r["method"]: r["fee_santim"] for r in zone["rates"]} == {
        "seller_rider": 15_000,
        "partner_courier": 20_000,
    }


def test_anyone_can_read_active_zones_and_fees_before_checkout(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    make_zone(staff, "bole")
    response = ApiClient().get("/delivery/zones")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    [zone] = response.json()
    assert zone["name_en"] == "Bole"
    assert len(zone["areas"]) == 1
    assert len(zone["rates"]) == 2


def test_inactive_zones_areas_and_rates_are_hidden_from_the_public(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    bole = make_zone(staff, "bole", areas=("Bole Medhanialem", "Bole Rwanda"))
    piassa = make_zone(staff, "piassa", areas=("Piassa",))

    assert (
        staff.patch(f"/admin/delivery/zones/{piassa['id']}", json={"is_active": False}).status_code
        == 200
    )
    area_id = bole["areas"][0]["id"]
    assert (
        staff.patch(f"/admin/delivery/areas/{area_id}", json={"is_active": False}).status_code
        == 200
    )
    staff.put(
        f"/admin/delivery/zones/{bole['id']}/rates",
        json={
            "method": "partner_courier",
            "fee_santim": 20_000,
            "promised_hours": 24,
            "is_active": False,
        },
    )

    [public] = ApiClient().get("/delivery/zones").json()
    assert public["code"] == "bole"
    assert [a["name_en"] for a in public["areas"]] == ["Bole Rwanda"]
    assert [r["method"] for r in public["rates"]] == ["seller_rider"]
    # Staff still see everything.
    assert len(staff.get("/admin/delivery/zones").json()) == 2


def test_setting_a_rate_again_replaces_it_and_records_before_and_after(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    zone = make_zone(staff, "bole", courier_fee=None)
    response = staff.put(
        f"/admin/delivery/zones/{zone['id']}/rates",
        json={"method": "seller_rider", "fee_santim": 18_000, "promised_hours": 6},
    )
    assert response.status_code == 200
    assert response.json()["fee_santim"] == 18_000
    [zone_now] = staff.get("/admin/delivery/zones").json()
    assert len(zone_now["rates"]) == 1  # replaced, not duplicated

    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "delivery_rate.set")
        .order_by(AuditLog.occurred_at)
    ).all()
    assert len(entries) == 2
    assert entries[0].before is None
    assert entries[1].before == {"fee_santim": 15_000, "promised_hours": 24, "is_active": True}
    assert entries[1].after["fee_santim"] == 18_000
    assert entries[1].actor_type == "staff"
    assert entries[1].request_id


def test_every_zone_change_is_audited(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    zone = make_zone(staff, "bole")
    staff.patch(f"/admin/delivery/zones/{zone['id']}", json={"name_en": "Bole District"})
    actions = db.scalars(
        select(AuditLog.action)
        .where(AuditLog.action.like("delivery%"))
        .order_by(AuditLog.occurred_at)
    ).all()
    assert actions == [
        "delivery_zone.create",
        "delivery_area.create",
        "delivery_rate.set",
        "delivery_rate.set",
        "delivery_zone.update",
    ]
    update = db.scalars(select(AuditLog).where(AuditLog.action == "delivery_zone.update")).one()
    assert update.before["name_en"] == "Bole"
    assert update.after["name_en"] == "Bole District"


def test_a_zone_code_is_unique(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    make_zone(staff, "bole")
    again = staff.post(
        "/admin/delivery/zones", json={"code": "bole", "name_am": "ቦሌ", "name_en": "Bole"}
    )
    assert again.status_code == 409
    assert error_code(again) == "zone_code_taken"


@pytest.mark.parametrize(
    "body",
    [
        {"code": "Bole", "name_am": "ቦሌ", "name_en": "Bole"},  # upper case
        {"code": "1bole", "name_am": "ቦሌ", "name_en": "Bole"},  # starts with a digit
        {"code": "bole", "name_am": "", "name_en": "Bole"},  # empty name
        {"code": "bole", "name_am": "ቦሌ"},  # missing name
    ],
)
def test_a_malformed_zone_is_refused(db: DbSession, body: dict[str, str]) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    assert staff.post("/admin/delivery/zones", json=body).status_code == 422


@pytest.mark.parametrize(
    "rate",
    [
        {"method": "seller_rider", "fee_santim": -1, "promised_hours": 24},
        {"method": "seller_rider", "fee_santim": 15_000, "promised_hours": 0},
        {
            "method": "shop_collection",
            "fee_santim": 0,
            "promised_hours": 1,
        },  # collection has no rate
        {"method": "teleport", "fee_santim": 15_000, "promised_hours": 24},
        {
            "method": "seller_rider",
            "fee_santim": 150.5,
            "promised_hours": 24,
        },  # no fractions of a santim
    ],
)
def test_a_malformed_rate_is_refused(db: DbSession, rate: dict[str, object]) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    zone = make_zone(staff, "bole", rider_fee=None, courier_fee=None)
    assert staff.put(f"/admin/delivery/zones/{zone['id']}/rates", json=rate).status_code == 422


def test_a_rate_for_an_unknown_zone_is_refused(db: DbSession) -> None:
    staff = staff_client(db, OPS, StaffRole.OPERATIONS)
    response = staff.put(
        "/admin/delivery/zones/00000000-0000-7000-8000-000000000000/rates",
        json={"method": "seller_rider", "fee_santim": 1, "promised_hours": 1},
    )
    assert response.status_code == 404
    assert error_code(response) == "zone_not_found"


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        # Blueprint C.4: "Change delivery zones, rates and risk limits".
        (StaffRole.SUPER_ADMIN, True),
        (StaffRole.OPERATIONS, True),
        (StaffRole.SUPPORT, False),
        (StaffRole.CATALOGUE, False),
        (StaffRole.FINANCE, False),
    ],
)
def test_only_the_roles_the_blueprint_names_may_change_zones(
    db: DbSession, role: StaffRole, allowed: bool
) -> None:
    staff = staff_client(db, OPS, role)
    create = staff.post(
        "/admin/delivery/zones", json={"code": "bole", "name_am": "ቦሌ", "name_en": "Bole"}
    )
    listing = staff.get("/admin/delivery/zones")
    if allowed:
        assert create.status_code == 201
        assert listing.status_code == 200
    else:
        assert create.status_code == 403
        assert error_code(create) == "permission_denied"
        assert listing.status_code == 403
        assert ApiClient().get("/delivery/zones").json() == []


def test_a_customer_cannot_reach_the_admin_routes() -> None:
    customer = ApiClient()
    customer.sign_in("0911234567")
    response = customer.post(
        "/admin/delivery/zones", json={"code": "bole", "name_am": "ቦሌ", "name_en": "Bole"}
    )
    assert response.status_code == 403
    assert error_code(response) == "staff_only"
    assert customer.get("/admin/delivery/zones").status_code == 403


def test_a_staff_member_signed_in_by_phone_code_has_no_admin_access(db: DbSession) -> None:
    """A staff session needs the password and the authenticator (blueprint C.5)."""
    from tests.factories import make_staff

    make_staff(db, OPS, StaffRole.SUPER_ADMIN)
    by_phone_code = ApiClient()
    by_phone_code.sign_in(OPS)
    response = by_phone_code.get("/admin/delivery/zones")
    assert response.status_code == 403
    assert error_code(response) == "staff_only"


def test_a_visitor_cannot_reach_the_admin_routes() -> None:
    response = ApiClient().get("/admin/delivery/zones")
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"
