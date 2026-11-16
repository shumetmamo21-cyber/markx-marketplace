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
