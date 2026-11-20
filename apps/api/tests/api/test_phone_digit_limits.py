"""Sign-in limits, cool-downs, lockouts and duplicate-account checks hold
whatever digits a phone number is typed in (pull request #6 review; B-3, D-098).

D-098 reads any decimal digit (Arabic-Indic, Persian, full-width...) as the
digit 0 to 9 it stands for. Every limit is keyed on the number as stored, so
typing the same number in another script must never be a way around one:
not the resend cool-down, not the hourly code limit, not the lock after five
wrong codes, not the staff lock after five failed sign-ins, and not the
checks that one number is one account, one staff member, one open invitation
and one team membership. Before D-098 these numbers were refused or caused a
server error, so none of these tests could pass.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import cycle
from typing import Any

import pyotp
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole, User
from markx.core import settings_store
from markx.notifications.sms import read_dev_sms_inbox
from tests.api.test_phone_digits import arabic, full_width, mixed, persian
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code, latest_code, let_resend_cooldown_pass
from tests.factories import STAFF_PASSWORD, make_staff, staff_client

PLAIN = "0911778001"
E164 = "+251911778001"
# The plain form first, then every other style D-098 accepts.
STYLES: list[Callable[[str], str]] = [lambda phone: phone, arabic, persian, full_width, mixed]


def _request(client: ApiClient, phone: str) -> Any:
    return client.post("/auth/otp/request", json={"phone": phone})


def _verify(client: ApiClient, phone: str, code: str) -> Any:
    return client.post("/auth/otp/verify", json={"phone": phone, "code": code})


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# -- the resend cool-down -------------------------------------------------------------------


def test_the_resend_cooldown_holds_across_digit_styles(client: ApiClient) -> None:
    assert _request(client, PLAIN).status_code == 200
    for style in STYLES:
        again = _request(client, style(PLAIN))
        assert again.status_code == 429, style(PLAIN)
        assert error_code(again) == "otp_resend_too_soon"
    assert len(read_dev_sms_inbox(E164)) == 1


# -- the hourly limit per number --------------------------------------------------------------


def test_the_hourly_code_limit_counts_every_digit_style_as_one_number(
    client: ApiClient, db: DbSession
) -> None:
    limit = settings_store.get_int(db, "auth.otp_per_phone_per_hour")
    styles = cycle(STYLES)
    for _ in range(limit):
        let_resend_cooldown_pass(PLAIN)
        assert _request(client, next(styles)(PLAIN)).status_code == 200
    for style in STYLES:
        let_resend_cooldown_pass(PLAIN)
        over = _request(client, style(PLAIN))
        assert over.status_code == 429, style(PLAIN)
        assert error_code(over) == "rate_limited"
    assert len(read_dev_sms_inbox(E164)) == limit


# -- the lock after five wrong codes -------------------------------------------------------------


def test_five_wrong_codes_in_mixed_digit_styles_lock_the_number_in_every_style(
    client: ApiClient,
) -> None:
    assert _request(client, PLAIN).status_code == 200
    code = latest_code(PLAIN)
    styles = cycle(STYLES[1:])
    for expected_left in (4, 3, 2, 1):
        wrong = _verify(client, next(styles)(PLAIN), _wrong(code))
        assert wrong.json()["error"]["details"]["attempts_left"] == expected_left
    fifth = _verify(client, next(styles)(PLAIN), _wrong(code))
    assert fifth.status_code == 429
    assert error_code(fifth) == "otp_locked"
    # The right code, in any style, is refused while the number is locked,
    # and no new code is sent to it in any style.
    for style in STYLES:
        assert error_code(_verify(client, style(PLAIN), code)) == "otp_locked"
        let_resend_cooldown_pass(PLAIN)
        assert error_code(_request(client, style(PLAIN))) == "otp_locked"
    assert len(read_dev_sms_inbox(E164)) == 1


# -- the staff lock after five failed sign-ins ------------------------------------------------------


def test_five_failed_staff_sign_ins_in_mixed_digit_styles_lock_the_account(
    db: DbSession,
) -> None:
    phone = "0911778002"
    secret = make_staff(db, phone, StaffRole.SUPPORT)
    styles = cycle(STYLES[1:])
    for _ in range(5):
        failed = ApiClient().post(
            "/auth/staff/sign-in",
            json={"phone": next(styles)(phone), "password": "wrong password!!",
                  "totp_code": pyotp.TOTP(secret).now()},
        )  # fmt: skip
        assert failed.status_code == 401
    for style in STYLES:
        locked = ApiClient().post(
            "/auth/staff/sign-in",
            json={"phone": style(phone), "password": STAFF_PASSWORD,
                  "totp_code": pyotp.TOTP(secret).now()},
        )  # fmt: skip
        assert locked.status_code == 429, style(phone)
        assert error_code(locked) == "staff_locked"


# -- one number, one account -------------------------------------------------------------------


def test_signing_in_in_every_digit_style_reaches_one_account(db: DbSession) -> None:
    ids = set()
    for style in STYLES:
        client = ApiClient()
        let_resend_cooldown_pass(PLAIN)
        assert _request(client, style(PLAIN)).status_code == 200
        assert _verify(client, style(PLAIN), latest_code(PLAIN)).status_code == 200
        ids.add(client.get("/me").json()["id"])
    db.rollback()
    assert len(ids) == 1
    assert db.scalar(select(func.count()).select_from(User).where(User.phone == E164)) == 1


def test_one_number_is_one_staff_member_whatever_its_digits(db: DbSession) -> None:
    admin = staff_client(db, "0911778003", StaffRole.SUPER_ADMIN)
    body = {"name": "Hana", "role": "support", "password": "a long staff passphrase"}
    created = admin.post("/admin/staff", json={"phone": "0911778004", **body})
    assert created.status_code == 201, created.text
    for style in STYLES:
        again = admin.post("/admin/staff", json={"phone": style("0911778004"), **body})
        assert again.status_code == 409, style("0911778004")
        assert error_code(again) == "staff_exists"


def test_one_number_has_one_open_invitation_whatever_its_digits(db: DbSession) -> None:
    admin = staff_client(db, "0911778005", StaffRole.SUPER_ADMIN)
    invited = admin.post("/admin/sellers/invitations", json={"phone": "0911778006"})
    assert invited.status_code == 201, invited.text
    for style in STYLES:
        again = admin.post("/admin/sellers/invitations", json={"phone": style("0911778006")})
        assert again.status_code == 409, style("0911778006")
        assert error_code(again) == "invitation_exists"


def test_one_number_is_one_team_member_whatever_its_digits(db: DbSession) -> None:
    bazaar = Bazaar(db)
    members = f"/seller/{bazaar.a_id}/members"
    added = bazaar.a.post(members, json={"phone": "0911778007"})
    assert added.status_code == 201, added.text
    for style in STYLES:
        again = bazaar.a.post(members, json={"phone": style("0911778007")})
        assert again.status_code == 409, style("0911778007")
        assert error_code(again) == "already_member"
