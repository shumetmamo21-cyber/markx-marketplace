"""Staff sign in with a password and an authenticator app (blueprint C.5, H.2)."""

from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from markx.accounts import service as accounts
from markx.accounts.models import StaffMember, StaffRole
from markx.audit.models import AuditLog
from markx.core.errors import ValidationFailed
from tests.conftest import ApiClient, error_code
from tests.factories import STAFF_PASSWORD, make_staff, staff_client

PHONE = "0911000100"


def _sign_in(
    client: ApiClient,
    secret: str,
    *,
    password: str = STAFF_PASSWORD,
    code: str | None = None,
    phone: str = PHONE,
):  # type: ignore[no-untyped-def]
    return client.post(
        "/auth/staff/sign-in",
        json={"phone": phone, "password": password, "totp_code": code or pyotp.TOTP(secret).now()},
    )


def test_password_and_authenticator_code_sign_staff_in(client: ApiClient, db: DbSession) -> None:
    secret = make_staff(db, PHONE, StaffRole.OPERATIONS)
    response = _sign_in(client, secret)
    assert response.status_code == 200
    me = response.json()["me"]
    assert me["session_kind"] == "staff"
    assert me["staff"]["role"] == "operations"
    assert "review_sellers" in me["staff"]["capabilities"]
    assert "manage_staff_and_settings" not in me["staff"]["capabilities"]


def test_the_authenticator_secret_is_stored_encrypted(db: DbSession) -> None:
    secret = make_staff(db, PHONE)
    stored = bytes(db.scalars(select(StaffMember)).one().totp_secret_encrypted)  # type: ignore[arg-type]
    assert secret.encode() not in stored
    assert accounts.decrypt_text(stored) == secret


def test_the_password_is_hashed_with_argon2id(db: DbSession) -> None:
    make_staff(db, PHONE)
    stored = db.scalars(select(StaffMember)).one().password_hash
    assert stored.startswith("$argon2id$")
    assert STAFF_PASSWORD not in stored


def test_a_short_password_is_refused(db: DbSession) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        accounts.create_staff(
            db,
            raw_phone=PHONE,
            name="X",
            role=StaffRole.SUPPORT,
            password="short",
            actor_user_id=None,
        )
    assert excinfo.value.code == "password_too_short"


@pytest.mark.parametrize(
    "case", ["wrong_password", "wrong_code", "unknown_phone", "non_ethiopian_phone"]
)
def test_every_failure_looks_the_same(client: ApiClient, db: DbSession, case: str) -> None:
    secret = make_staff(db, PHONE)
    if case == "wrong_password":
        response = _sign_in(client, secret, password="not the password!")
    elif case == "wrong_code":
        good = pyotp.TOTP(secret).now()
        response = _sign_in(client, secret, code=f"{(int(good) + 1) % 1_000_000:06d}")
    elif case == "unknown_phone":
        response = _sign_in(client, secret, phone="0911999999")
    else:
        response = _sign_in(client, secret, phone="+14155550100")
    assert response.status_code == 401
    assert error_code(response) == "staff_credentials_invalid"
    assert response.json()["error"]["details"] == {}
    assert "set-cookie" not in response.headers


def test_an_authenticator_code_cannot_be_replayed(client: ApiClient, db: DbSession) -> None:
    secret = make_staff(db, PHONE)
    code = pyotp.TOTP(secret).now()
    assert _sign_in(client, secret, code=code).status_code == 200
    replay = _sign_in(ApiClient(), secret, code=code)
    assert replay.status_code == 401
    assert error_code(replay) == "staff_credentials_invalid"


def test_five_failures_lock_the_staff_account(client: ApiClient, db: DbSession) -> None:
    secret = make_staff(db, PHONE)
    for _ in range(5):
        assert _sign_in(client, secret, password="wrong password!!").status_code == 401
    locked = _sign_in(client, secret)
    assert locked.status_code == 429
    assert error_code(locked) == "staff_locked"
    db.execute(text("update staff_members set locked_until = now() - interval '1 second'"))
    db.commit()
    assert _sign_in(client, secret).status_code == 200


def test_a_deactivated_staff_member_cannot_sign_in_and_loses_live_sessions(db: DbSession) -> None:
    client = staff_client(db, PHONE)
    assert client.get("/me").json()["staff"] is not None
    db.execute(text("update staff_members set is_active = false"))
    db.commit()
    assert client.get("/me").status_code == 401
    staff = db.scalars(select(StaffMember)).one()
    secret = accounts.decrypt_text(staff.totp_secret_encrypted)  # type: ignore[arg-type]
    assert _sign_in(ApiClient(), secret).status_code == 401


def test_a_phone_code_session_never_carries_staff_powers(db: DbSession) -> None:
    make_staff(db, PHONE)
    customer = ApiClient()
    me = customer.sign_in(PHONE)["me"]
    assert me["session_kind"] == "customer"
    assert me["staff"] is None


def test_sign_ins_and_failures_are_audited(client: ApiClient, db: DbSession) -> None:
    secret = make_staff(db, PHONE)
    _sign_in(client, secret, password="wrong password!!")
    _sign_in(client, secret)
    actions = db.scalars(select(AuditLog.action).order_by(AuditLog.occurred_at)).all()
    assert actions == ["staff.create", "staff.sign_in_failed", "staff.sign_in"]
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "staff.sign_in")).one()
    assert str(entry.ip) == "203.0.113.10"
    assert entry.request_id


def test_staff_sessions_are_short_lived(db: DbSession) -> None:
    client = staff_client(db, PHONE)
    minutes = db.execute(
        text(
            "select extract(epoch from (expires_at - created_at)) / 60, extract(epoch from (idle_expires_at - created_at)) / 60 from sessions where kind = 'staff'"
        )
    ).one()
    assert round(minutes[0]) == 720
    assert round(minutes[1]) == 30
    assert client.get("/me").status_code == 200
