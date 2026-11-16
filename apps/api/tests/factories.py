"""Small builders for arranging test data through the real services."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import urlencode

import pyotp
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import StaffRole
from tests.conftest import ApiClient

STAFF_PASSWORD = "correct horse battery staple"


def make_staff(db: Session, phone: str, role: StaffRole = StaffRole.SUPER_ADMIN) -> str:
    """Create a staff account; returns its authenticator secret."""
    created = accounts.create_staff(
        db, raw_phone=phone, name="Staff Person", role=role, password=STAFF_PASSWORD,
        actor_user_id=None,
    )  # fmt: skip
    db.commit()
    return created.totp_secret


def staff_client(db: Session, phone: str, role: StaffRole = StaffRole.SUPER_ADMIN) -> ApiClient:
    """A signed-in staff browser, through the real password + authenticator sign-in."""
    secret = make_staff(db, phone, role)
    client = ApiClient()
    response = client.post(
        "/auth/staff/sign-in",
        json={"phone": phone, "password": STAFF_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text
    return client


def telegram_init_data(
    telegram_id: int, *, auth_date: int | None = None, bot_token: str | None = None, **extra: Any
) -> str:
    """Build start-up data exactly as Telegram signs it for a Mini App."""
    token = bot_token or os.environ["MARKX_TELEGRAM_BOT_TOKEN"]
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Abebe", **extra}, separators=(",", ":")
        ),
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def make_zone(
    staff: ApiClient,
    code: str = "bole",
    *,
    areas: tuple[str, ...] = ("Bole Medhanialem",),
    rider_fee: int | None = 15_000,
    courier_fee: int | None = 20_000,
) -> dict[str, Any]:
    """Create a delivery zone with areas and rates through the admin API."""
    response = staff.post(
        "/admin/delivery/zones",
        json={"code": code, "name_am": f"{code} (አማ)", "name_en": code.title()},
    )
    assert response.status_code == 201, response.text
    zone_id = response.json()["id"]
    for name in areas:
        created = staff.post(
            f"/admin/delivery/zones/{zone_id}/areas",
            json={"name_am": f"{name} (አማ)", "name_en": name},
        )
        assert created.status_code == 201, created.text
    for method, fee in (("seller_rider", rider_fee), ("partner_courier", courier_fee)):
        if fee is not None:
            put = staff.put(
                f"/admin/delivery/zones/{zone_id}/rates",
                json={"method": method, "fee_santim": fee, "promised_hours": 24},
            )
            assert put.status_code == 200, put.text
    zones = staff.get("/admin/delivery/zones").json()
    return next(z for z in zones if z["id"] == zone_id)


def make_catalog(staff: ApiClient) -> dict[str, Any]:
    """The launch wedge in miniature: Electronics > Phones, with typed attributes.

    storage and colour define variants; screen size is a required specification.
    Returns the ids tests need.
    """

    def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = staff.post(path, json=body)
        assert response.status_code == 201, response.text
        return dict(response.json())

    electronics = post(
        "/admin/catalog/categories",
        {"slug": "electronics", "name_am": "ኤሌክትሮኒክስ", "name_en": "Electronics"},
    )
    phones = post(
        "/admin/catalog/categories",
        {"slug": "phones", "name_am": "ስልኮች", "name_en": "Phones", "parent_id": electronics["id"]},
    )
    storage = post(
        "/admin/catalog/attributes",
        {
            "code": "storage", "data_type": "option", "name_am": "ማከማቻ", "name_en": "Storage",
            "options": [
                {"code": "128gb", "label_am": "128 ጊባ", "label_en": "128 GB"},
                {"code": "256gb", "label_am": "256 ጊባ", "label_en": "256 GB"},
            ],
        },
    )  # fmt: skip
    colour = post(
        "/admin/catalog/attributes",
        {
            "code": "colour", "data_type": "option", "name_am": "ቀለም", "name_en": "Colour",
            "options": [
                {"code": "black", "label_am": "ጥቁር", "label_en": "Black"},
                {"code": "blue", "label_am": "ሰማያዊ", "label_en": "Blue"},
            ],
        },
    )  # fmt: skip
    screen = post(
        "/admin/catalog/attributes",
        {
            "code": "screen_inches",
            "data_type": "number",
            "unit": "in",
            "name_am": "ስክሪን",
            "name_en": "Screen",
        },
    )
    os_attr = post(
        "/admin/catalog/attributes",
        {"code": "os", "data_type": "text", "name_am": "ሲስተም", "name_en": "Operating system"},
    )

    def attach(category: str, attribute: str, **flags: bool) -> None:
        response = staff.put(
            f"/admin/catalog/categories/{category}/attributes/{attribute}", json=flags
        )
        assert response.status_code == 200, response.text

    # Colour is set on Electronics and inherited by Phones.
    attach(electronics["id"], colour["id"], is_variant_defining=True, is_filterable=True)
    attach(
        phones["id"], storage["id"], is_variant_defining=True, is_filterable=True, is_required=True
    )
    attach(phones["id"], screen["id"], is_required=True)
    attach(phones["id"], os_attr["id"])
    samsung = post("/admin/catalog/brands", {"name": "Samsung"})
    return {
        "electronics": electronics["id"], "phones": phones["id"], "storage": storage["id"],
        "colour": colour["id"], "screen": screen["id"], "os": os_attr["id"], "samsung": samsung["id"],
    }  # fmt: skip


def phone_body(catalog: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "category_id": catalog["phones"],
        "brand_id": catalog["samsung"],
        "model": "SM-A165F",
        "name_am": "ሳምሰንግ ጋላክሲ A16",
        "name_en": "Samsung Galaxy A16",
        "description_en": "A 6.7 inch phone.",
        "specs": {"screen_inches": 6.7, "os": "Android 14"},
        "variants": [
            {
                "attribute_values": {"storage": "128gb", "colour": "black"},
                "model_code": "A16-128-BK",
            },
            {"attribute_values": {"storage": "256gb", "colour": "black"}},
        ],
        "status": "approved",
        **overrides,
    }


def make_product(staff: ApiClient, catalog: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    response = staff.post("/admin/catalog/products", json=phone_body(catalog, **overrides))
    assert response.status_code == 201, response.text
    return dict(response.json())
