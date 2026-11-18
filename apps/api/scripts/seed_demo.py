"""Fill a LOCAL database with DEMO data, through the real API.

    cd apps/api && uv run python -m scripts.seed_demo

Everything is created the way a person would create it: staff curate the
catalogue and delivery zones, sellers are invited, sign in with a code,
apply with documents, are approved by staff and list offers, and a buyer
signs in and saves an address. Every rule, audit row and search document is
therefore produced by the same code as in production.

ALL OF IT IS DEMO DATA. The shops, people, phone numbers and prices are made
up for development. Nothing here is a real seller, buyer or market price.
The script refuses to run unless MARKX_ENV is `local`, and does nothing if
the demo staff account already exists.
"""

from __future__ import annotations

import io
import os
import sys
from datetime import UTC, datetime
from typing import Any

import pyotp
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from markx.accounts import service as accounts
from markx.accounts.models import StaffRole, User
from markx.core.config import get_config
from markx.core.db import session_scope
from markx.core.phone import normalize_phone
from markx.main import app
from markx.notifications.sms import read_dev_sms_inbox
from markx.worker.runner import run_once

STAFF_PHONE = "0911000900"
STAFF_PASSWORD = os.environ.get("MARKX_DEMO_STAFF_PASSWORD", "demo-only-staff-password-1")
BUYER_PHONE = "0911000950"


class Browser:
    """A browser session against the in-process API, as the web app sends it."""

    def __init__(self) -> None:
        self.http = TestClient(app, client=("203.0.113.50", 50000))

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"X-MarkX-Client": "web", **kwargs.pop("headers", {})}
        csrf = self.http.cookies.get("markx_csrf")
        if csrf and method != "GET":
            headers["X-CSRF-Token"] = csrf
        response = self.http.request(method, f"/api/v1{path}", headers=headers, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} failed: {response.status_code} {response.text}")
        return response.json() if response.content else None

    def sign_in(self, phone: str) -> None:
        self.call("POST", "/auth/otp/request", json={"phone": phone, "language": "en"})
        text = read_dev_sms_inbox(normalize_phone(phone))[-1]["text"]
        words = (w.strip(".።፦:") for w in text.replace("፦", " ").split())
        code = next(w for w in words if len(w) == 6 and w.isdigit())
        self.call("POST", "/auth/otp/verify", json={"phone": phone, "code": code})


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 224, 214)).save(buffer, "PNG")
    return buffer.getvalue()


def _staff() -> tuple[Browser, str]:
    with session_scope() as db:
        created = accounts.create_staff(
            db, raw_phone=STAFF_PHONE, name="Demo Administrator", role=StaffRole.SUPER_ADMIN,
            password=STAFF_PASSWORD, actor_user_id=None,
        )  # fmt: skip
        secret = created.totp_secret
    staff = Browser()
    staff.call(
        "POST", "/auth/staff/sign-in",
        json={"phone": STAFF_PHONE, "password": STAFF_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )  # fmt: skip
    return staff, secret


def _catalogue(staff: Browser) -> dict[str, Any]:
    def post(path: str, body: dict[str, Any]) -> Any:
        return staff.call("POST", path, json=body)

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
                {"code": "64gb", "label_am": "64 ጊባ", "label_en": "64 GB"},
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
                {"code": "white", "label_am": "ነጭ", "label_en": "White"},
                {"code": "green", "label_am": "አረንጓዴ", "label_en": "Green"},
            ],
        },
    )  # fmt: skip
    screen = post(
        "/admin/catalog/attributes",
        {"code": "screen_inches", "data_type": "number", "unit": "in", "name_am": "ስክሪን",
         "name_en": "Screen"},
    )  # fmt: skip
    for category, attribute, flags in (
        (electronics, colour, {"is_variant_defining": True, "is_filterable": True}),
        (
            phones,
            storage,
            {"is_variant_defining": True, "is_filterable": True, "is_required": True},
        ),
        (phones, screen, {"is_required": True}),
    ):
        staff.call(
            "PUT", f"/admin/catalog/categories/{category['id']}/attributes/{attribute['id']}",
            json=flags,
        )  # fmt: skip
    brands = {
        name: post("/admin/catalog/brands", {"name": name})["id"]
        for name in ("Samsung", "Tecno", "Infinix", "Apple", "Xiaomi")
    }
    products = {}
    for key, brand, model, name_am, name_en, screen_in, variants, aliases in (
        ("a16", "Samsung", "SM-A165F", "ሳምሰንግ ጋላክሲ A16", "Samsung Galaxy A16", 6.7,
         [("128gb", "black"), ("256gb", "black")], ["ሳምሰንግ A16"]),
        ("spark", "Tecno", "KJ5", "ቴክኖ ስፓርክ 20", "Tecno Spark 20", 6.6,
         [("128gb", "blue"), ("256gb", "black")], []),
        ("hot", "Infinix", "X6528", "ኢንፊኒክስ ሆት 40i", "Infinix Hot 40i", 6.56,
         [("128gb", "black")], []),
        ("iphone", "Apple", "A2633", "አይፎን 13", "Apple iPhone 13", 6.1,
         [("128gb", "white"), ("256gb", "black")], ["iphone"]),
        ("redmi", "Xiaomi", "23108RN04Y", "ሻዎሚ ሬድሚ 13C", "Xiaomi Redmi 13C", 6.74,
         [("64gb", "green"), ("128gb", "black")], ["redmi"]),
    ):  # fmt: skip
        product = post(
            "/admin/catalog/products",
            {
                "category_id": phones["id"], "brand_id": brands[brand], "model": model,
                "name_am": name_am, "name_en": name_en,
                "description_en": f"DEMO listing. {name_en}, {screen_in} inch screen.",
                "description_am": f"የማሳያ መረጃ። {name_am}፣ {screen_in} ኢንች ስክሪን።",
                "specs": {"screen_inches": screen_in},
                "variants": [
                    {"attribute_values": {"storage": s, "colour": c}} for s, c in variants
                ],
                "status": "approved",
            },
        )  # fmt: skip
        for alias in aliases:
            post(f"/admin/catalog/products/{product['id']}/aliases", {"alias": alias})
        products[key] = product
    return products


def _zones(staff: Browser) -> str:
    first_area = ""
    for code, name_am, name_en, areas, rider, courier in (
        ("bole", "ቦሌ", "Bole", [("ቦሌ መድኃኔዓለም", "Bole Medhanialem"), ("ቦሌ አትላስ", "Bole Atlas")],
         15_000, 20_000),
        ("piassa", "ፒያሳ", "Piassa", [("ፒያሳ", "Piassa"), ("አራት ኪሎ", "Arat Kilo")], 12_000, 18_000),
        ("merkato", "መርካቶ", "Merkato", [("መርካቶ", "Merkato")], 10_000, None),
    ):  # fmt: skip
        zone = staff.call(
            "POST",
            "/admin/delivery/zones",
            json={"code": code, "name_am": name_am, "name_en": name_en},
        )
        for area_am, area_en in areas:
            area = staff.call(
                "POST", f"/admin/delivery/zones/{zone['id']}/areas",
                json={"name_am": area_am, "name_en": area_en},
            )  # fmt: skip
            first_area = first_area or area["id"]
        for method, fee in (("seller_rider", rider), ("partner_courier", courier)):
            if fee is not None:
                staff.call(
                    "PUT", f"/admin/delivery/zones/{zone['id']}/rates",
                    json={"method": method, "fee_santim": fee, "promised_hours": 24},
                )  # fmt: skip
    return first_area


def _seller(staff: Browser, phone: str, tin: str, legal: str, trade: str, slug: str,
            address: str) -> tuple[Browser, str]:  # fmt: skip
    staff.call("POST", "/admin/sellers/invitations", json={"phone": phone})
    seller = Browser()
    seller.sign_in(phone)
    application = seller.call(
        "POST", "/seller/applications",
        json={
            "kind": "business", "legal_name": legal, "trade_name": trade, "tin": tin,
            "licence_number": f"AA/14/2/{tin[-6:]}/2018", "contact_phone": phone,
            "shop_address": address, "store_slug": slug,
        },
    )  # fmt: skip
    seller_id = application["id"]
    for doc_type in ("owner_id", "business_licence", "tin_certificate", "shop_photo"):
        seller.call(
            "POST", f"/seller/{seller_id}/documents", data={"doc_type": doc_type},
            files={"file": ("demo.png", _png(), "image/png")},
        )  # fmt: skip
    seller.call(
        "PUT", f"/seller/{seller_id}/payout-account",
        json={"kind": "bank", "provider_name": "Demo Bank", "account_name": legal,
              "account_number": f"1000{tin}"},
    )  # fmt: skip
    seller.call("POST", f"/seller/{seller_id}/submit")
    detail = staff.call("GET", f"/admin/sellers/{seller_id}")
    for document in detail["documents"]:
        staff.call(
            "POST", f"/admin/sellers/{seller_id}/documents/{document['id']}/review",
            json={"decision": "accepted"},
        )  # fmt: skip
    staff.call(
        "POST", f"/admin/sellers/{seller_id}/approve",
        json={"verification_level": 2, "shop_visited": True, "payout_account_name_matches": True},
    )  # fmt: skip
    return seller, seller_id


def main() -> int:
    config = get_config()
    if config.env != "local":
        sys.stderr.write(f"Refusing: MARKX_ENV is {config.env!r}; demo data is for local only.\n")
        return 2
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.phone == normalize_phone(STAFF_PHONE))):
            sys.stdout.write("Demo data is already there; nothing to do.\n")
            return 0

    staff, secret = _staff()
    products = _catalogue(staff)
    area_id = _zones(staff)
    shops = [
        _seller(staff, "0911000901", "0000000901", "Demo Merkato Mobile PLC", "Merkato Mobile",
                "merkato-mobile", "Merkato, Anwar Mosque street, shop 4 (demo)"),
        _seller(staff, "0911000902", "0000000902", "Demo Bole Phone House PLC", "Bole Phone House",
                "bole-phone-house", "Bole Medhanialem, Alem Building, shop 12 (demo)"),
        _seller(staff, "0911000903", "0000000903", "Demo Piassa Electronics PLC",
                "Piassa Electronics", "piassa-electronics", "Piassa, near Taitu Hotel (demo)"),
    ]  # fmt: skip
    # (product, variant index, [(shop, price in birr, stock, condition, collection only)])
    listings = [
        ("a16", 0, [(0, 17_900, 6, "new", False), (1, 18_500, 3, "new", False),
                    (2, 18_200, 0, "new", False)]),
        ("a16", 1, [(1, 21_000, 2, "new", False)]),
        ("spark", 0, [(0, 12_400, 8, "new", True), (2, 12_900, 4, "new", False)]),
        ("spark", 1, [(1, 14_800, 2, "new", False)]),
        ("hot", 0, [(0, 11_200, 5, "new", False), (2, 11_600, 2, "new", False)]),
        ("iphone", 0, [(1, 46_000, 1, "used", False), (2, 58_500, 2, "new", False)]),
        ("redmi", 0, [(0, 9_800, 10, "new", True)]),
        ("redmi", 1, [(1, 11_900, 4, "new", False), (2, 11_700, 3, "new", False)]),
    ]  # fmt: skip
    for key, variant, offers in listings:
        variant_id = products[key]["variants"][variant]["id"]
        for shop, birr, stock, condition, collection_only in offers:
            browser, seller_id = shops[shop]
            browser.call(
                "POST", f"/seller/{seller_id}/offers",
                json={
                    "variant_id": variant_id, "condition": condition,
                    "price_santim": birr * 100, "quantity": stock,
                    "warranty_months": 12 if condition == "new" else 3,
                    "delivers_by_seller_rider": not collection_only,
                    "offers_shop_collection": True,
                },
            )  # fmt: skip

    buyer = Browser()
    buyer.sign_in(BUYER_PHONE)
    buyer.call(
        "POST", "/me/addresses",
        json={"recipient_name": "Demo Buyer", "phone": BUYER_PHONE, "delivery_area_id": area_id,
              "landmark": "Behind the demo building, blue gate"},
    )  # fmt: skip

    run_once(datetime.now(UTC), outbox_limit=None)  # the search documents, every message
    sys.stdout.write(
        "DEMO data created (local only; none of it is real).\n"
        f"  Staff sign-in: phone {STAFF_PHONE}, password {STAFF_PASSWORD}\n"
        f"  Staff authenticator secret: {secret}\n"
        f"  Sellers: 0911000901, 0911000902, 0911000903; buyer: {BUYER_PHONE}\n"
        "  Sign-in codes are written to the local SMS inbox (GET /api/v1/dev/sms-inbox).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
