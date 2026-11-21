"""Signing in on the website with Telegram, with the phone number confirmed
by Telegram (D-101, decision SI-1; task items 1 and 2).

Telegram is played by `tests/telegram_play.py`: the webhook is called with
the test-only secret, the way Telegram would call it. No bot exists and
nothing reaches Telegram.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pyotp
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from markx.accounts import telegram_sign_in
from markx.accounts.models import TelegramSignIn, User
from markx.audit.models import AuditLog
from markx.notifications.models import Notification
from tests import telegram_play as tg
from tests.conftest import ApiClient, error_code
from tests.factories import STAFF_PASSWORD, make_staff

TG = 710_200_300
OTHER_TG = 710_200_999
PHONE = "251911223344"  # as Telegram sends it: no "+"
E164 = "+251911223344"


@pytest.fixture(autouse=True)
def _telegram_on(telegram_linking: object) -> None:
    """The bot configured with test-only values. Off: the first test."""


def _user(db: Session, phone: str = E164) -> User:
    db.rollback()
    user = db.scalar(select(User).where(User.phone == phone))
    assert user is not None
    return user


def _row(db: Session) -> TelegramSignIn:
    db.rollback()
    return db.scalars(select(TelegramSignIn).order_by(TelegramSignIn.created_at.desc())).first()  # type: ignore[return-value]


def _keyboard(answer: dict[str, Any]) -> dict[str, Any]:
    return dict(answer.get("reply_markup") or {})


def _asks_for_phone(answer: dict[str, Any]) -> bool:
    buttons = _keyboard(answer).get("keyboard") or [[{}]]
    return buttons[0][0].get("request_contact") is True


# -- switched off ------------------------------------------------------------------------------


def test_off_unless_the_bot_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from markx.accounts import telegram_link
    from markx.core.config import get_config

    monkeypatch.setattr(telegram_link, "get_config", get_config)
    browser = ApiClient()
    refused = browser.post("/auth/telegram/sign-in", json={"language": "en"})
    assert refused.status_code == 503
    assert error_code(refused) == "telegram_sign_in_unavailable"
    assert browser.get("/auth/methods").json()["telegram"] is False


# -- item 1: a person signs in with Telegram ----------------------------------------------


def test_a_new_person_signs_in_with_telegram_and_their_number_is_confirmed(db: Session) -> None:
    browser = ApiClient()
    assert browser.get("/auth/methods").json() == {
        "telegram": True,
        "sms": True,
        "staff_phone_password": True,
    }
    payload = tg.start(browser)
    assert tg.check(browser).json()["state"] == "waiting"

    opened = tg.open_link(payload, TG)
    assert opened["method"] == "sendMessage"
    assert opened["chat_id"] == TG
    assert _asks_for_phone(opened), "the bot offers Telegram's own share-my-number button"
    assert "only continue if you started signing in" in opened["text"].lower()
    assert "ማርክኤክስ" in opened["text"], "the bot speaks Amharic too"
    assert tg.check(browser).json()["state"] == "waiting_for_phone"

    shared = tg.share_phone(TG, PHONE)
    assert shared["text"] == telegram_sign_in.REPLIES["signed_in"]
    assert _keyboard(shared) == {"remove_keyboard": True}

    done = tg.check(browser)
    assert done.status_code == 200
    body = done.json()
    assert body["state"] == "signed_in"
    assert body["is_new_account"] is True
    assert body["me"]["phone"] == E164
    assert body["me"]["session_kind"] == "customer"
    assert browser.get("/me").json()["phone"] == E164
    user = _user(db)
    assert user.telegram_id == TG
    assert user.telegram_linked_at is not None


def test_a_sign_in_is_collected_once_and_only_by_the_browser_that_started_it() -> None:
    browser, stranger = ApiClient(), ApiClient()
    payload = tg.start(browser)
    tg.open_link(payload, TG)
    tg.share_phone(TG, PHONE)
    # Another browser, with no secret or its own, gets nothing.
    assert tg.check(stranger).json()["state"] == "none"
    tg.start(stranger)
    assert tg.check(stranger).json()["state"] == "waiting"
    assert tg.check(browser).json()["state"] == "signed_in"
    # Once only: the same secret again gives nothing.
    browser.http.cookies.set("markx_tg_sign_in", "x", path="/api/v1/auth/telegram/sign-in")
    assert tg.check(browser).json()["state"] == "none"


def test_the_browser_secret_is_http_only_and_nothing_is_stored_in_plain(db: Session) -> None:
    browser = ApiClient()
    response = browser.post("/auth/telegram/sign-in", json={"language": "am"})
    cookie = response.headers["set-cookie"]
    assert "markx_tg_sign_in=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth/telegram/sign-in" in cookie
    secret = browser.http.cookies.get("markx_tg_sign_in")
    token = response.json()["link"].split("start=si-")[1]
    assert secret not in response.text, "the browser's secret is never in the body"
    row = _row(db)
    assert row.token_hash == telegram_sign_in.token_hash(token)
    assert row.browser_hash == telegram_sign_in.browser_hash(secret)
    stored = db.execute(text("select t::text from telegram_sign_ins t")).scalar_one()
    assert token not in stored
    assert secret not in stored
    assert row.language == "am"


def test_a_link_works_once_and_for_one_telegram_account() -> None:
    browser = ApiClient()
    payload = tg.start(browser)
    assert _asks_for_phone(tg.open_link(payload, TG))
    again = tg.open_link(payload, OTHER_TG)
    assert again["text"] == telegram_sign_in.REPLIES["invalid"]
    # The other Telegram account cannot finish it either.
    assert (
        tg.share_phone(OTHER_TG, "251922334455")["text"]
        == telegram_sign_in.REPLIES["nothing_waiting"]
    )
    assert tg.check(browser).json()["state"] == "waiting_for_phone"


def test_an_unknown_or_malformed_payload_is_not_valid() -> None:
    assert tg.open_link("si-" + "A" * 43, TG)["text"] == telegram_sign_in.REPLIES["invalid"]


def test_a_sign_in_expires(db: Session) -> None:
    browser = ApiClient()
    payload = tg.start(browser)
    db.execute(
        text(
            "update telegram_sign_ins set created_at = created_at - interval '1 hour', "
            "expires_at = now() - interval '1 second'"
        )
    )
    db.commit()
    assert tg.check(browser).json()["state"] == "expired"
    assert tg.open_link(payload, TG)["text"] == telegram_sign_in.REPLIES["invalid"]


def test_the_link_lifetime_is_the_provisional_setting(db: Session) -> None:
    from markx.core import settings_store

    settings_store.set_setting(db, "auth.telegram_sign_in_minutes", 3)
    db.commit()
    tg.start(ApiClient())
    row = _row(db)
    assert row.expires_at - row.created_at == timedelta(minutes=3)


def test_a_new_start_replaces_the_browsers_earlier_one(db: Session) -> None:
    browser = ApiClient()
    first = tg.start(browser)
    tg.start(browser)
    assert tg.open_link(first, TG)["text"] == telegram_sign_in.REPLIES["invalid"]
    db.rollback()
    statuses = sorted(db.scalars(select(TelegramSignIn.status)).all())
    assert statuses == ["pending", "revoked"]


def test_starting_is_limited_per_address(db: Session) -> None:
    from markx.core import settings_store

    settings_store.set_setting(db, "auth.telegram_sign_ins_per_ip_per_hour", 2)
    db.commit()
    browser = ApiClient(ip="203.0.113.77")
    tg.start(browser)
    tg.start(browser)
    third = browser.post("/auth/telegram/sign-in", json={"language": "en"})
    assert third.status_code == 429


# -- item 2: the number Telegram confirms ------------------------------------------------------


def test_only_the_senders_own_number_counts() -> None:
    browser = ApiClient()
    tg.open_link(tg.start(browser), TG)
    someone_else = tg.share_phone(TG, "251922334455", owner=OTHER_TG)
    assert someone_else["text"] == telegram_sign_in.REPLIES["own_number_only"]
    assert _asks_for_phone(someone_else)
    no_owner = tg.share_phone(TG, "251922334455", owner=0)
    assert no_owner["text"] == telegram_sign_in.REPLIES["own_number_only"]
    forwarded = tg.share_phone(TG, PHONE, forward_origin={"type": "user"})
    assert forwarded["text"] == telegram_sign_in.REPLIES["own_number_only"]
    assert tg.check(browser).json()["state"] == "waiting_for_phone"
    tg.share_phone(TG, PHONE)
    assert tg.check(browser).json()["state"] == "signed_in"


@pytest.mark.parametrize("number", ["14155550100", "+447700900123", "251111234567", "not-a-number"])
def test_the_number_must_be_an_ethiopian_mobile_number(db: Session, number: str) -> None:
    browser = ApiClient()
    tg.open_link(tg.start(browser), TG)
    answer = tg.share_phone(TG, number)
    assert answer["text"] == telegram_sign_in.REPLIES["not_ethiopian"]
    body = tg.check(browser).json()
    assert body == {**body, "state": "refused", "reason": "phone_not_ethiopian", "me": None}
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_safaricom_numbers_are_ethiopian_mobile_numbers_too(db: Session) -> None:
    tg.sign_in(ApiClient(), TG, "+251712345678")
    assert _user(db, "+251712345678").telegram_id == TG


def test_an_existing_account_with_that_number_is_the_one_signed_in(db: Session) -> None:
    """Accounts made before SI-1 (by SMS, or by staff) keep their history:
    Telegram's confirmation of the number connects Telegram to them."""
    by_sms = ApiClient()
    by_sms.sign_in("0911223344")
    before = _user(db)
    assert before.telegram_id is None
    body = tg.sign_in(ApiClient(), TG, PHONE)
    assert body["is_new_account"] is False
    assert body["me"]["id"] == str(before.id)
    assert _user(db).telegram_id == TG
    db.rollback()
    methods = db.scalars(
        select(AuditLog.after["method"].astext).where(AuditLog.action == "telegram.linked")
    ).all()
    assert methods == ["telegram_sign_in"]


def test_returning_with_the_same_telegram_and_number_reaches_the_same_account() -> None:
    first = tg.sign_in(ApiClient(), TG, PHONE)
    second = tg.sign_in(ApiClient(), TG, PHONE)
    assert first["me"]["id"] == second["me"]["id"]
    assert second["is_new_account"] is False


def test_a_number_tied_to_another_telegram_account_is_never_moved(db: Session) -> None:
    """PROVISIONAL P-101-6: numbers are recycled; support decides (F-24)."""
    tg.sign_in(ApiClient(), TG, PHONE)
    browser = ApiClient()
    tg.open_link(tg.start(browser), OTHER_TG)
    assert tg.share_phone(OTHER_TG, PHONE)["text"] == telegram_sign_in.REPLIES["refused"]
    body = tg.check(browser).json()
    assert (body["state"], body["reason"], body["me"]) == (
        "refused",
        "phone_on_other_telegram",
        None,
    )
    assert _user(db).telegram_id == TG


def test_a_new_number_on_the_same_telegram_account_becomes_the_accounts_number(
    db: Session,
) -> None:
    """PROVISIONAL P-101-6: Telegram confirmed the new number, nobody else has it."""
    first = tg.sign_in(ApiClient(), TG, PHONE)
    second = tg.sign_in(ApiClient(), TG, "251922000111")
    assert second["me"]["id"] == first["me"]["id"]
    assert second["me"]["phone"] == "+251922000111"
    db.rollback()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "account.phone_changed")).one()
    assert entry.before == {"phone": "+2519••••3344"}
    assert entry.after == {"phone": "+2519••••0111", "confirmed_by": "telegram"}
    templates = db.scalars(select(Notification.template)).all()
    assert "auth.phone_changed" in templates


def test_a_new_number_that_belongs_to_another_account_is_refused(db: Session) -> None:
    """One number, one account."""
    tg.sign_in(ApiClient(), TG, PHONE)
    ApiClient().sign_in("0922000111")  # someone else, by SMS
    browser = ApiClient()
    tg.open_link(tg.start(browser), TG)
    tg.share_phone(TG, "251922000111")
    body = tg.check(browser).json()
    assert (body["state"], body["reason"]) == ("refused", "phone_in_use")
    assert _user(db).telegram_id == TG
    assert _user(db, "+251922000111").telegram_id is None


def test_a_blocked_account_cannot_sign_in_with_telegram(db: Session) -> None:
    tg.sign_in(ApiClient(), TG, PHONE)
    db.execute(text("update users set status = 'blocked'"))
    db.commit()
    browser = ApiClient()
    tg.open_link(tg.start(browser), TG)
    tg.share_phone(TG, PHONE)
    body = tg.check(browser).json()
    assert (body["state"], body["reason"]) == ("refused", "account_inactive")


def test_a_shared_number_with_nothing_waiting_does_nothing(db: Session) -> None:
    answer = tg.share_phone(TG, PHONE)
    assert answer["text"] == telegram_sign_in.REPLIES["nothing_waiting"]
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_a_second_sign_in_tells_the_person_in_the_app(db: Session) -> None:
    first = ApiClient()
    tg.sign_in(first, TG, PHONE)
    tg.sign_in(ApiClient(), TG, PHONE)
    db.rollback()
    assert db.scalars(select(Notification.template)).all() == ["auth.new_sign_in"]


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        return task(index)

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(run, range(workers)))


def test_two_checks_at_the_same_moment_sign_in_once(db: Session) -> None:
    browser = ApiClient()
    tg.open_link(tg.start(browser), TG)
    tg.share_phone(TG, PHONE)
    secret = browser.http.cookies.get("markx_tg_sign_in")

    def check(_: int) -> str:
        twin = ApiClient()
        twin.http.cookies.set("markx_tg_sign_in", secret, path="/api/v1/auth/telegram/sign-in")
        return str(tg.check(twin).json()["state"])

    assert sorted(_race(4, check)) == ["none", "none", "none", "signed_in"]
    db.rollback()
    assert db.scalar(text("select count(*) from sessions")) == 1


def test_two_telegram_accounts_sharing_new_numbers_at_once_make_two_accounts(
    db: Session,
) -> None:
    browsers = [ApiClient(), ApiClient()]
    for browser, telegram_id in zip(browsers, (TG, OTHER_TG), strict=True):
        tg.open_link(tg.start(browser), telegram_id)
    numbers = ("251911000001", "251911000002")
    _race(2, lambda i: tg.share_phone((TG, OTHER_TG)[i], numbers[i]))
    assert [tg.check(b).json()["state"] for b in browsers] == ["signed_in", "signed_in"]
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == 2


# -- staff: their existing second step on top of Telegram ------------------------------------


def _staff_on_telegram(db: Session) -> tuple[ApiClient, str]:
    secret = make_staff(db, "0911223344")
    browser = ApiClient()
    tg.sign_in(browser, TG, PHONE)
    return browser, secret


def test_staff_sign_in_with_telegram_then_their_password_and_code(db: Session) -> None:
    browser, secret = _staff_on_telegram(db)
    assert browser.get("/me").json()["staff"] is None, "Telegram alone carries no staff powers"
    response = browser.post(
        "/auth/staff/step-up",
        json={"password": STAFF_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["me"]["session_kind"] == "staff"
    me = browser.get("/me").json()
    assert me["session_kind"] == "staff"
    assert me["staff"]["role"] == "super_admin"
    db.rollback()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "staff.sign_in")).one()
    assert entry.after == {"method": "telegram"}
    # The Telegram session was replaced, not kept beside the staff one.
    live = db.execute(
        text("select kind from sessions where revoked_at is null order by created_at")
    ).scalars()
    assert list(live) == ["staff"]


def test_the_staff_step_needs_the_password_and_the_code(db: Session) -> None:
    browser, secret = _staff_on_telegram(db)
    for body in (
        {"password": "not the password!", "totp_code": pyotp.TOTP(secret).now()},
        {"password": STAFF_PASSWORD, "totp_code": "000000"},
    ):
        refused = browser.post("/auth/staff/step-up", json=body)
        assert refused.status_code == 401
        assert error_code(refused) == "staff_credentials_invalid"
    assert browser.get("/me").json()["session_kind"] == "customer"


def test_the_staff_step_refuses_a_replayed_code(db: Session) -> None:
    browser, secret = _staff_on_telegram(db)
    code = pyotp.TOTP(secret).now()
    ok = browser.post("/auth/staff/step-up", json={"password": STAFF_PASSWORD, "totp_code": code})
    assert ok.status_code == 200
    again = ApiClient()
    tg.sign_in(again, TG, PHONE)
    replay = again.post("/auth/staff/step-up", json={"password": STAFF_PASSWORD, "totp_code": code})
    assert replay.status_code == 401


def test_five_failed_staff_steps_lock_the_account_for_its_owner(db: Session) -> None:
    browser, secret = _staff_on_telegram(db)
    for _ in range(5):
        browser.post(
            "/auth/staff/step-up",
            json={"password": "wrong password!!", "totp_code": pyotp.TOTP(secret).now()},
        )
    locked = browser.post(
        "/auth/staff/step-up",
        json={"password": STAFF_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert locked.status_code == 429
    assert error_code(locked) == "staff_locked"


def test_someone_who_is_not_staff_gets_the_ordinary_refusal() -> None:
    browser = ApiClient()
    tg.sign_in(browser, TG, PHONE)
    refused = browser.post(
        "/auth/staff/step-up", json={"password": STAFF_PASSWORD, "totp_code": "123456"}
    )
    assert refused.status_code == 401
    assert error_code(refused) == "staff_credentials_invalid"


def test_the_staff_step_needs_a_signed_in_person() -> None:
    refused = ApiClient().post(
        "/auth/staff/step-up", json={"password": STAFF_PASSWORD, "totp_code": "123456"}
    )
    assert refused.status_code == 401
