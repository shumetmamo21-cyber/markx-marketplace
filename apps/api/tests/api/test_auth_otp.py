"""Phone sign-in (blueprint D.2, H.2, P3 completion criteria)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import OtpChallenge, Session, User
from markx.core import settings_store
from markx.notifications.sms import read_dev_sms_inbox
from tests.conftest import ApiClient, error_code, latest_code

PHONE = "0911234567"
E164 = "+251911234567"


def _request(client: ApiClient, phone: str = PHONE, **extra: object):  # type: ignore[no-untyped-def]
    return client.post("/auth/otp/request", json={"phone": phone, **extra})


def _verify(client: ApiClient, code: str, phone: str = PHONE):  # type: ignore[no-untyped-def]
    return client.post("/auth/otp/verify", json={"phone": phone, "code": code})


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def test_requesting_a_code_sends_one_sms_and_masks_the_number(client: ApiClient) -> None:
    response = _request(client)
    assert response.status_code == 200
    assert response.json() == {"phone_masked": "+2519••••4567", "expires_in_seconds": 300}
    messages = read_dev_sms_inbox(E164)
    assert len(messages) == 1
    assert len(latest_code(PHONE)) == 6


def test_only_a_keyed_hash_of_the_code_is_stored(client: ApiClient, db: DbSession) -> None:
    _request(client)
    code = latest_code(PHONE)
    challenge = db.scalars(select(OtpChallenge)).one()
    assert len(bytes(challenge.code_hash)) == 32
    assert code.encode() not in bytes(challenge.code_hash)
    # Nothing in the row, read back as text, contains the code.
    row_text = db.execute(text("select otp_challenges::text from otp_challenges")).scalar_one()
    assert code not in row_text
    # No outbox row carries it either.
    assert db.execute(text("select count(*) from outbox")).scalar_one() == 0


def test_the_correct_code_signs_in_and_creates_the_account(client: ApiClient, db: DbSession) -> None:
    assert db.scalar(select(User)) is None
    _request(client)
    response = _verify(client, latest_code(PHONE))
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_account"] is True
    assert body["session_token"] is None  # cookie clients never see the token
    assert body["me"]["phone"] == E164
    assert body["me"]["session_kind"] == "customer"
    assert body["me"]["staff"] is None
    assert db.scalars(select(User)).one().phone == E164

    me = client.get("/me")
    assert me.status_code == 200 and me.json()["phone"] == E164


def test_session_cookie_is_not_readable_by_scripts(client: ApiClient) -> None:
    _request(client)
    response = _verify(client, latest_code(PHONE))
    set_cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookies if c.startswith("markx_session="))
    csrf_cookie = next(c for c in set_cookies if c.startswith("markx_csrf="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_only_the_token_hash_is_stored(client: ApiClient, db: DbSession) -> None:
    client.sign_in(PHONE)
    token = client.http.cookies.get("markx_session")
    assert token
    stored = bytes(db.scalars(select(Session)).one().token_hash)
    assert token.encode() != stored and len(stored) == 32


def test_second_sign_in_reuses_the_account(client: ApiClient, db: DbSession) -> None:
    client.sign_in(PHONE)
    again = ApiClient().sign_in(PHONE)
    assert again["is_new_account"] is False
    assert len(db.scalars(select(User)).all()) == 1


@pytest.mark.parametrize(
    "form", ["0911234567", "911234567", "+251911234567", "251911234567", "00251911234567", "0911 23 45 67"]
)
def test_every_phone_form_reaches_the_same_account(form: str, db: DbSession) -> None:
    ApiClient().sign_in("0911234567")
    ApiClient().sign_in(form)
    assert [u.phone for u in db.scalars(select(User)).all()] == [E164]


@pytest.mark.parametrize("phone", ["+14155550100", "0811234567", "091123456", "+441632960961"])
def test_only_ethiopian_mobile_numbers_are_accepted(client: ApiClient, phone: str) -> None:
    response = _request(client, phone)
    assert response.status_code == 422
    assert error_code(response) == "phone_invalid"
    assert read_dev_sms_inbox(E164) == []


def test_a_wrong_code_is_refused_and_counts_down(client: ApiClient) -> None:
    _request(client)
    code = latest_code(PHONE)
    response = _verify(client, _wrong(code))
    assert response.status_code == 400
    assert error_code(response) == "otp_invalid"
    assert response.json()["error"]["details"] == {"attempts_left": 4}
    # The right code still works after one mistake.
    assert _verify(client, code).status_code == 200


def test_five_wrong_codes_lock_the_number_for_fifteen_minutes(client: ApiClient, db: DbSession) -> None:
    _request(client)
    code = latest_code(PHONE)
    for expected_left in (4, 3, 2, 1):
        response = _verify(client, _wrong(code))
        assert response.json()["error"]["details"]["attempts_left"] == expected_left
    fifth = _verify(client, _wrong(code))
    assert fifth.status_code == 429 and error_code(fifth) == "otp_locked"
    assert fifth.json()["error"]["details"]["retry_after_seconds"] == 900
    assert fifth.headers["retry-after"] == "900"

    # While locked, even the correct code is refused, and no new code is sent.
    assert error_code(_verify(client, code)) == "otp_locked"
    again = _request(client)
    assert again.status_code == 429 and error_code(again) == "otp_locked"
    assert len(read_dev_sms_inbox(E164)) == 1

    # After the lock passes, sign-in works again.
    db.execute(text("update otp_locks set locked_until = now() - interval '1 second'"))
    db.commit()
    assert _request(client).status_code == 200
    assert _verify(client, latest_code(PHONE)).status_code == 200


def test_an_expired_code_is_refused(client: ApiClient, db: DbSession) -> None:
    _request(client)
    code = latest_code(PHONE)
    db.execute(update(OtpChallenge).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    response = _verify(client, code)
    assert response.status_code == 400 and error_code(response) == "otp_expired"


def test_a_code_cannot_be_used_twice(client: ApiClient) -> None:
    _request(client)
    code = latest_code(PHONE)
    assert _verify(client, code).status_code == 200
    assert error_code(_verify(ApiClient(), code)) == "otp_expired"


def test_a_new_code_cancels_the_previous_one(client: ApiClient) -> None:
    _request(client)
    first = latest_code(PHONE)
    _request(client)
    second = latest_code(PHONE)
    if first != second:
        assert error_code(_verify(client, first)) == "otp_invalid"
    assert _verify(client, second).status_code == 200


def test_a_code_for_one_number_does_not_work_for_another(client: ApiClient) -> None:
    _request(client, "0911234567")
    code = latest_code("0911234567")
    _request(client, "0922334455")
    other = latest_code("0922334455")
    if code != other:
        assert error_code(_verify(client, code, "0922334455")) == "otp_invalid"


def test_requests_beyond_the_per_number_limit_are_refused(client: ApiClient, db: DbSession) -> None:
    limit = settings_store.get_int(db, "auth.otp_per_phone_per_hour")
    for _ in range(limit):
        assert _request(client).status_code == 200
    over = _request(client)
    assert over.status_code == 429 and error_code(over) == "rate_limited"
    assert int(over.headers["retry-after"]) > 0
    assert len(read_dev_sms_inbox(E164)) == limit
    # Another number is unaffected by this number's limit.
    assert _request(client, "0922334455").status_code == 200


def test_requests_beyond_the_per_address_limit_are_refused(client: ApiClient, db: DbSession) -> None:
    settings_store.set_setting(db, "auth.otp_per_ip_per_hour", 3)
    db.commit()
    for i in range(3):
        assert _request(client, f"09112345{i:02d}").status_code == 200
    over = _request(client, "0911234599")
    assert over.status_code == 429 and error_code(over) == "rate_limited"


def test_the_bot_check_runs_before_any_sms(client: ApiClient) -> None:
    response = _request(client, bot_token="bot")
    assert response.status_code == 403 and error_code(response) == "bot_check_failed"
    assert read_dev_sms_inbox(E164) == []


def test_the_daily_sms_budget_cuts_off_sending(client: ApiClient, db: DbSession) -> None:
    settings_store.set_setting(db, "auth.sms_daily_budget", 2)
    db.commit()
    assert _request(client, "0911000001").status_code == 200
    assert _request(client, "0911000002").status_code == 200
    spent = _request(client, "0911000003")
    assert spent.status_code == 503 and error_code(spent) == "sms_budget_spent"
    assert read_dev_sms_inbox("+251911000003") == []


def test_me_requires_a_session(client: ApiClient) -> None:
    response = client.get("/me")
    assert response.status_code == 401 and error_code(response) == "not_authenticated"


def test_sign_out_ends_the_session(client: ApiClient) -> None:
    client.sign_in(PHONE)
    token = client.http.cookies.get("markx_session")
    assert client.post("/auth/sign-out").status_code == 200
    # Even if a copy of the cookie survives, the server no longer honours it.
    stale = ApiClient()
    stale.http.cookies.set("markx_session", token)
    assert stale.get("/me").status_code == 401


def test_sign_out_everywhere_ends_every_device(client: ApiClient) -> None:
    client.sign_in(PHONE)
    other = ApiClient()
    other.sign_in(PHONE)
    assert other.get("/me").status_code == 200
    assert client.post("/auth/sign-out-everywhere").status_code == 200
    assert other.get("/me").status_code == 401
    assert client.get("/me").status_code == 401


def test_signing_in_again_replaces_the_session(client: ApiClient) -> None:
    client.sign_in(PHONE)
    old = client.http.cookies.get("markx_session")
    client.sign_in(PHONE)
    new = client.http.cookies.get("markx_session")
    assert old != new
    stale = ApiClient()
    stale.http.cookies.set("markx_session", old)
    assert stale.get("/me").status_code == 401


def test_idle_and_absolute_expiry(client: ApiClient, db: DbSession) -> None:
    client.sign_in(PHONE)
    assert client.get("/me").status_code == 200
    db.execute(update(Session).values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    assert client.get("/me").status_code == 401

    fresh = ApiClient()
    fresh.sign_in("0922334455")
    db.execute(text("update sessions set created_at = now() - interval '100 days', expires_at = now() - interval '1 second' where revoked_at is null"))
    db.commit()
    assert fresh.get("/me").status_code == 401


def test_a_new_sign_in_on_another_device_leaves_a_notice(client: ApiClient) -> None:
    client.sign_in(PHONE)
    assert client.get("/me").json()["unread_notifications"] == 0
    ApiClient().sign_in(PHONE)
    notices = client.get("/me/notifications").json()
    assert [n["template"] for n in notices] == ["auth.new_sign_in"]


def test_a_blocked_account_cannot_sign_in(client: ApiClient, db: DbSession) -> None:
    client.sign_in(PHONE)
    db.execute(update(User).values(status="blocked"))
    db.commit()
    assert client.get("/me").status_code == 401
    _request(client)
    response = _verify(client, latest_code(PHONE))
    assert response.status_code == 403 and error_code(response) == "account_blocked"


def test_profile_update_and_language_is_remembered(client: ApiClient) -> None:
    client.sign_in(PHONE)
    response = client.patch("/me", json={"name": "  Abebe   Kebede ", "language": "am"})
    assert response.status_code == 200
    assert response.json()["name"] == "Abebe Kebede"
    assert client.get("/me").json()["language"] == "am"
    assert client.patch("/me", json={"language": "fr"}).status_code == 422


def test_logs_never_contain_codes_tokens_or_full_phone_numbers(
    client: ApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _request(client)
    code = latest_code(PHONE)
    _verify(client, _wrong(code))
    _verify(client, code)
    token = client.http.cookies.get("markx_session")
    client.get("/me")
    logged = "\n".join(
        f"{r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("markx")
    )
    assert logged, "expected request logs"
    assert code not in logged
    assert token not in logged
    assert E164 not in logged and PHONE not in logged
