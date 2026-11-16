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


# -- sellers -------------------------------------------------------------------

REQUIRED_BUSINESS_DOCUMENTS = ("owner_id", "business_licence", "tin_certificate", "shop_photo")


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48)) -> bytes:
    """A real, decodable picture."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, fmt)
    return buffer.getvalue()


def application_body(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "business",
        "legal_name": "Abebe Electronics PLC",
        "trade_name": "Abebe Phones",
        "tin": "0012345678",
        "licence_number": "AA/14/2/000123/2018",
        "contact_phone": "0911000001",
        "shop_address": "Bole Medhanialem, Alem Building, shop 12",
        **overrides,
    }


def invite_seller(staff: ApiClient, phone: str) -> dict[str, Any]:
    response = staff.post("/admin/sellers/invitations", json={"phone": phone})
    assert response.status_code == 201, response.text
    return dict(response.json())


def upload_document(
    client: ApiClient, seller_id: str, doc_type: str, *, data: bytes | None = None, **form: Any
) -> Any:
    return client.post(
        f"/seller/{seller_id}/documents",
        data={"doc_type": doc_type, **form},
        files={"file": ("photo.png", data if data is not None else image_bytes(), "image/png")},
    )


def payout_body(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "bank",
        "provider_name": "Commercial Bank of Ethiopia",
        "account_name": "Abebe Electronics PLC",
        "account_number": "1000123456789",
        **overrides,
    }


def start_application(staff: ApiClient, phone: str, **overrides: Any) -> tuple[ApiClient, str]:
    """Invite a phone number, sign it in and open a draft application."""
    invite_seller(staff, phone)
    client = ApiClient()
    client.sign_in(phone)
    response = client.post("/seller/applications", json=application_body(**overrides))
    assert response.status_code == 201, response.text
    return client, str(response.json()["id"])


def submit_application(client: ApiClient, seller_id: str) -> None:
    """Upload the four business documents, add a payout account and submit."""
    for doc_type in REQUIRED_BUSINESS_DOCUMENTS:
        assert upload_document(client, seller_id, doc_type).status_code == 201
    assert client.put(f"/seller/{seller_id}/payout-account", json=payout_body()).status_code == 200
    response = client.post(f"/seller/{seller_id}/submit")
    assert response.status_code == 200, response.text


def approve_seller(staff: ApiClient, seller_id: str, level: int = 2) -> dict[str, Any]:
    """Accept every document and approve, the way operations staff do."""
    detail = staff.get(f"/admin/sellers/{seller_id}").json()
    for document in detail["documents"]:
        reviewed = staff.post(
            f"/admin/sellers/{seller_id}/documents/{document['id']}/review",
            json={"decision": "accepted"},
        )
        assert reviewed.status_code == 200, reviewed.text
    response = staff.post(
        f"/admin/sellers/{seller_id}/approve",
        json={
            "verification_level": level,
            "shop_visited": level >= 2,
            "payout_account_name_matches": True,
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def make_seller(
    staff: ApiClient, phone: str, *, tin: str = "0012345678", level: int = 2, **overrides: Any
) -> tuple[ApiClient, str]:
    """A verified, trading seller. Returns its owner's browser and the seller id."""
    client, seller_id = start_application(staff, phone, tin=tin, **overrides)
    submit_application(client, seller_id)
    approve_seller(staff, seller_id, level)
    return client, seller_id


# -- offers --------------------------------------------------------------------


def offer_body(variant_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "condition": "new",
        "price_santim": 1_850_000,
        "quantity": 5,
        "warranty_months": 12,
        "delivers_by_seller_rider": True,
        **overrides,
    }


def make_offer(
    client: ApiClient, seller_id: str, variant_id: str, **overrides: Any
) -> dict[str, Any]:
    response = client.post(f"/seller/{seller_id}/offers", json=offer_body(variant_id, **overrides))
    assert response.status_code == 201, response.text
    return dict(response.json())
