"""SMS switched off, and the audit's sign-in findings M2, M3 and M4 (D-101;
task items 3 to 6). `docs/reports/2026-11-19-independent-audit.md`, section 9.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import StaffRole, TelegramInitDataUse
from markx.audit.models import AuditLog
from markx.core import ratelimit, settings_store
from markx.core.config import Config
from markx.notifications.sms import read_dev_sms_inbox
from markx.ops import checks
from tests.conftest import ApiClient, error_code, let_resend_cooldown_pass
from tests.deployment.test_production_config import production
from tests.factories import STAFF_PASSWORD, make_staff, telegram_init_data

TMA = {"X-MarkX-Client": "tma"}


# -- item 3: SMS switched off ---------------------------------------------------------------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_server_starts_with_sms_switched_off(env: str) -> None:
    config = Config(**production(env=env, sms_provider="off", sms_api_url=None, sms_sender_id=None))
    assert config.sms_on is False


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_server_still_refuses_the_fake_sms_sender(env: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_SMS_PROVIDER must be a real SMS provider"):
        Config(**production(env=env, sms_provider="fake"))


@pytest.mark.parametrize(
    ("missing", "named"),
    [("sms_api_url", "MARKX_SMS_API_URL"), ("sms_sender_id", "MARKX_SMS_SENDER_ID")],
)
def test_switching_sms_on_still_needs_every_provider_setting(missing: str, named: str) -> None:
    with pytest.raises(ValidationError, match=named):
        Config(**production(**{missing: None}))


@pytest.mark.parametrize(
    ("unsafe", "named"),
    [
        ({"bot_check_provider": "fake"}, "MARKX_BOT_CHECK_PROVIDER must be a real bot check"),
        ({"telegram_push_provider": "fake"}, "MARKX_TELEGRAM_PUSH_PROVIDER"),
        ({"cookie_secure": False}, "MARKX_COOKIE_SECURE must be true"),
    ],
)
def test_switching_sms_off_relaxes_nothing_else(unsafe: dict[str, Any], named: str) -> None:
    with pytest.raises(ValidationError, match=named):
        Config(**production(sms_provider="off", **unsafe))


def test_with_sms_off_no_code_is_sent_or_counted(sms_off: object) -> None:
    client = ApiClient()
    asked = client.post("/auth/otp/request", json={"phone": "0911445566", "language": "en"})
    assert asked.status_code == 403
    assert error_code(asked) == "sms_sign_in_off"
    assert read_dev_sms_inbox("+251911445566") == []
    assert ratelimit.current("sms:daily", timedelta(days=1)) == 0
    verify = client.post("/auth/otp/verify", json={"phone": "0911445566", "code": "123456"})
    assert verify.status_code == 403
    assert error_code(verify) == "sms_sign_in_off"
    assert client.get("/auth/methods").json() == {
        "telegram": False,
        "sms": False,
        "staff_phone_password": False,
    }


def test_with_sms_off_staff_cannot_skip_telegram(db: Session, sms_off: object) -> None:
    """PROVISIONAL P-101-8: no way around Telegram while SMS is off; the
    answer is the same whether or not the number is staff's."""
    secret = make_staff(db, "0911000100")
    for phone in ("0911000100", "0911999999"):
        refused = ApiClient().post(
            "/auth/staff/sign-in",
            json={"phone": phone, "password": STAFF_PASSWORD,
                  "totp_code": pyotp.TOTP(secret).now()},
        )  # fmt: skip
        assert refused.status_code == 403
        assert error_code(refused) == "staff_telegram_required"


def test_with_sms_off_no_notification_sms_is_sent(db: Session, sms_off: object) -> None:
    from markx.notifications import sms

    with pytest.raises(RuntimeError, match="SMS is switched off"):
        sms.get_sms_sender()


# -- item 4 (M4): Telegram start-up data is accepted once, for minutes ---------------------


def _linked(telegram_id: int) -> None:
    client = ApiClient()
    client.sign_in("0911234567")
    data = telegram_init_data(telegram_id, auth_date=int(time.time()) - 5)
    assert client.post("/me/telegram", json={"init_data": data}).status_code == 200


@pytest.fixture
def _linking(telegram_linking: object) -> None:
    pass


@pytest.mark.usefixtures("_linking")
def test_the_same_start_up_data_signs_in_only_once(db: Session) -> None:
    _linked(777001)
    data = telegram_init_data(777001)
    first = ApiClient().post("/auth/telegram", json={"init_data": data}, headers=TMA)
    assert first.status_code == 200
    replay = ApiClient().post("/auth/telegram", json={"init_data": data}, headers=TMA)
    assert replay.status_code == 403
    assert error_code(replay) == "telegram_data_used"
    db.rollback()
    assert db.scalar(text("select count(*) from sessions where transport = 'header'")) == 1


@pytest.mark.usefixtures("_linking")
def test_reordering_the_fields_does_not_make_it_new() -> None:
    _linked(777001)
    data = telegram_init_data(777001)
    assert (
        ApiClient().post("/auth/telegram", json={"init_data": data}, headers=TMA).status_code == 200
    )
    shuffled = "&".join(reversed(data.split("&")))
    replay = ApiClient().post("/auth/telegram", json={"init_data": shuffled}, headers=TMA)
    assert error_code(replay) == "telegram_data_used"


@pytest.mark.usefixtures("_linking")
def test_start_up_data_older_than_five_minutes_is_refused() -> None:
    _linked(777001)
    old = telegram_init_data(777001, auth_date=int(time.time()) - 6 * 60)
    response = ApiClient().post("/auth/telegram", json={"init_data": old}, headers=TMA)
    assert response.status_code == 403
    assert error_code(response) == "telegram_data_expired"
    fresh = telegram_init_data(777001, auth_date=int(time.time()) - 4 * 60)
    assert (
        ApiClient().post("/auth/telegram", json={"init_data": fresh}, headers=TMA).status_code
        == 200
    )


@pytest.mark.usefixtures("_linking")
def test_a_refused_sign_in_does_not_use_the_data_up(db: Session) -> None:
    """Not linked yet: the Mini App confirms the number, links, and signs in
    with the same start-up data."""
    data = telegram_init_data(777002)
    first = ApiClient().post("/auth/telegram", json={"init_data": data}, headers=TMA)
    assert error_code(first) == "telegram_not_linked"
    client = ApiClient()
    client.sign_in("0922334455")
    assert client.post("/me/telegram", json={"init_data": data}).status_code == 200
    assert (
        ApiClient().post("/auth/telegram", json={"init_data": data}, headers=TMA).status_code == 200
    )
    db.rollback()
    purposes = sorted(db.scalars(select(TelegramInitDataUse.purpose)).all())
    assert purposes == ["sign_in"]


@pytest.mark.usefixtures("_linking")
def test_linking_again_with_the_same_data_stays_harmless() -> None:
    """Single use is for sign-ins: linking needs a MarkX session already."""
    data = telegram_init_data(777003)
    client = ApiClient()
    client.sign_in("0922334455")
    assert client.post("/me/telegram", json={"init_data": data}).status_code == 200
    assert client.post("/me/telegram", json={"init_data": data}).status_code == 200


@pytest.mark.usefixtures("_linking")
def test_old_data_cannot_link_either() -> None:
    client = ApiClient()
    client.sign_in("0922334455")
    old = telegram_init_data(777004, auth_date=int(time.time()) - 6 * 60)
    response = client.post("/me/telegram", json={"init_data": old})
    assert (response.status_code, error_code(response)) == (403, "telegram_data_expired")


def test_used_start_up_data_is_forgotten_after_two_days(db: Session) -> None:
    from markx.ops import retention

    db.add(TelegramInitDataUse(digest=b"\x01" * 32, purpose="sign_in"))
    db.commit()
    db.execute(text("update telegram_init_data_uses set used_at = now() - interval '3 days'"))
    db.commit()
    assert retention.prune(db, datetime.now(UTC)) == 1


# -- item 5 (M3): no lock-out by an outsider, no telling which numbers are staff ----------

STAFF_PHONE = "0911000100"


def _staff_attempt(
    secret: str, *, ip: str, password: str = STAFF_PASSWORD, phone: str = STAFF_PHONE
) -> Any:
    return ApiClient(ip=ip).post(
        "/auth/staff/sign-in",
        json={"phone": phone, "password": password, "totp_code": pyotp.TOTP(secret).now()},
    )


def test_an_outsider_cannot_lock_a_staff_member_out(db: Session) -> None:
    secret = make_staff(db, STAFF_PHONE)
    for _ in range(12):
        _staff_attempt(secret, ip="198.51.100.50", password="a wrong guess!!")
    # The outsider is locked out, from their address...
    assert _staff_attempt(secret, ip="198.51.100.50").status_code == 401
    # ...and the staff member, elsewhere, is not.
    assert _staff_attempt(secret, ip="203.0.113.20").status_code == 200


def test_a_locked_attempt_looks_exactly_like_a_wrong_one(db: Session) -> None:
    secret = make_staff(db, STAFF_PHONE)
    for _ in range(5):
        _staff_attempt(secret, ip="198.51.100.51", password="a wrong guess!!")
    locked = _staff_attempt(secret, ip="198.51.100.51")
    unknown = _staff_attempt(secret, ip="198.51.100.51", phone="0911999999")
    wrong = _staff_attempt(secret, ip="198.51.100.52", password="a wrong guess!!")
    for response in (locked, unknown, wrong):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "staff_credentials_invalid"
        assert response.json()["error"]["details"] == {}
        assert "retry-after" not in {k.lower() for k in response.headers}


def test_many_staff_numbers_and_many_strangers_give_the_same_answers(db: Session) -> None:
    """Enumeration: whatever a stranger tries, a staff number and any other
    number answer alike, before and after any lock."""
    secret = make_staff(db, STAFF_PHONE)
    answers = set()
    for phone in (STAFF_PHONE, "0911999999"):
        for _ in range(7):
            response = _staff_attempt(secret, ip="198.51.100.53", password="guess!!!!", phone=phone)
            answers.add((response.status_code, response.json()["error"]["code"]))
    assert answers == {(401, "staff_credentials_invalid")}


def test_the_lock_lasts_the_provisional_minutes(db: Session) -> None:
    settings_store.set_setting(db, "auth.staff_failures_before_lock", 2)
    db.commit()
    secret = make_staff(db, STAFF_PHONE)
    for _ in range(2):
        _staff_attempt(secret, ip="198.51.100.54", password="a wrong guess!!")
    assert _staff_attempt(secret, ip="198.51.100.54").status_code == 401
    db.execute(text("delete from rate_limit_counters where bucket like 'staff-login:fail:%'"))
    db.commit()
    assert _staff_attempt(secret, ip="198.51.100.54").status_code == 200


def test_many_failures_on_one_staff_account_alert_the_founder(db: Session) -> None:
    secret = make_staff(db, STAFF_PHONE, StaffRole.SUPPORT)
    for i in range(10):
        _staff_attempt(secret, ip=f"198.51.100.{100 + i}", password="a wrong guess!!")
    db.rollback()
    findings = checks.staff_sign_in_failures(db, datetime.now(UTC))
    assert [f.key for f in findings] == ["staff.sign_in_failures"]
    assert "+251" not in str(findings[0].details)
    assert "+251" not in findings[0].summary


def test_a_few_failures_do_not_alert(db: Session) -> None:
    secret = make_staff(db, STAFF_PHONE)
    for _ in range(3):
        _staff_attempt(secret, ip="198.51.100.60", password="a wrong guess!!")
    db.rollback()
    assert checks.staff_sign_in_failures(db, datetime.now(UTC)) == []


# -- item 6 (M2): no one person, number or address spends the shared SMS budget -----------


def _ask(phone: str, ip: str) -> Any:
    let_resend_cooldown_pass(phone)
    return ApiClient(ip=ip).post("/auth/otp/request", json={"phone": phone, "language": "en"})


def _earlier_today(bucket: str, count: int) -> None:
    """Codes already counted earlier today in `bucket` (the hourly limits
    allow only so many an hour, so a whole day is arranged, not sent)."""
    for _ in range(count):
        ratelimit.hit(bucket, 1_000_000, timedelta(days=1))


# With the default budget of 500: a number may use 2% (10 codes a day), an
# address 5% (25) and a network 10% (50).


def test_one_number_uses_at_most_its_share_of_the_day() -> None:
    _earlier_today("sms:daily:phone:+251911000201", 10)
    refused = _ask("0911000201", "203.0.113.31")
    assert (refused.status_code, error_code(refused)) == (429, "sms_share_spent")
    assert read_dev_sms_inbox("+251911000201") == []
    assert _ask("0911000202", "203.0.113.31").status_code == 200


def test_one_address_uses_at_most_its_share_of_the_day() -> None:
    _earlier_today("sms:daily:ip:203.0.113.40", 25)
    refused = _ask("0911000301", "203.0.113.40")
    assert (refused.status_code, error_code(refused)) == (429, "sms_share_spent")
    assert _ask("0911000301", "203.0.113.41").status_code == 200


def test_one_network_uses_at_most_its_share_of_the_day() -> None:
    _earlier_today("sms:daily:net:203.0.113.0/24", 50)
    refused = _ask("0911000401", "203.0.113.99")
    assert (refused.status_code, error_code(refused)) == (429, "sms_share_spent")
    # Another network is not affected.
    assert _ask("0911000401", "198.51.100.9").status_code == 200


def test_hopping_addresses_within_one_network_is_counted_as_one(db: Session) -> None:
    # A budget of 200: an address's share is its hourly limit (20), and so
    # is the network's, so twenty addresses of one /24 share twenty codes.
    settings_store.set_setting(db, "auth.sms_daily_budget", 200)
    db.commit()
    for i in range(20):
        assert _ask(f"09110004{i:02d}", f"203.0.113.{50 + i}").status_code == 200
    next_ = _ask("0911000499", "203.0.113.200")
    assert (next_.status_code, error_code(next_)) == (429, "sms_share_spent")


def test_ipv6_networks_are_counted_per_64() -> None:
    _earlier_today("sms:daily:net:2001:db8:1:2::/64", 50)
    assert error_code(_ask("0911000599", "2001:db8:1:2::ff")) == "sms_share_spent"
    assert _ask("0911000598", "2001:db8:1:3::1").status_code == 200


def test_a_refused_share_does_not_spend_the_shared_budget() -> None:
    _earlier_today("sms:daily:phone:+251911000601", 10)
    for _ in range(3):
        _ask("0911000601", "203.0.113.70")
    assert ratelimit.current("sms:daily", timedelta(days=1)) == 0


def test_the_shared_budget_is_still_the_final_limit(db: Session) -> None:
    settings_store.set_setting(db, "auth.sms_daily_budget", 3)
    db.commit()
    for i, net in enumerate(("203.0.113.1", "198.51.100.1", "192.0.2.1")):
        assert _ask(f"09110007{i:02d}", net).status_code == 200
    spent = _ask("0911000799", "100.64.0.1")
    assert (spent.status_code, error_code(spent)) == (503, "sms_budget_spent")


def test_the_shares_scale_with_the_budget(db: Session) -> None:
    settings_store.set_setting(db, "auth.sms_daily_budget", 5000)
    db.commit()
    _earlier_today("sms:daily:phone:+251911000901", 10)
    assert _ask("0911000901", "203.0.113.90").status_code == 200  # 2% of 5000 is 100


def test_staff_are_alerted_before_the_budget_runs_out(db: Session) -> None:
    settings_store.set_setting(db, "auth.sms_daily_budget", 10)
    db.commit()
    nets = [f"10.{i}.0.1" for i in range(10)]
    for i in range(7):
        assert _ask(f"09110008{i:02d}", nets[i]).status_code == 200
    db.rollback()
    assert checks.sms_budget(db, datetime.now(UTC)) == []
    _ask("0911000807", nets[7])
    db.rollback()
    warned = checks.sms_budget(db, datetime.now(UTC))
    assert [(f.key, f.severity) for f in warned] == [("sms.budget", "warning")]
    for i in (8, 9):
        _ask(f"09110008{i:02d}", nets[i])
    db.rollback()
    assert [f.severity for f in checks.sms_budget(db, datetime.now(UTC))] == ["critical"]


def test_the_new_limits_are_provisional_settings() -> None:
    for key, number in (
        ("auth.telegram_sign_in_minutes", "P-101-1"),
        ("auth.telegram_sign_ins_per_ip_per_hour", "P-101-2"),
        ("auth.telegram_init_data_max_age_seconds", "P-101-3"),
        ("auth.staff_failures_before_lock", "P-101-4"),
        ("auth.staff_lock_minutes", "P-101-4"),
        ("auth.staff_failure_alert_per_hour", "P-101-5"),
        ("auth.sms_daily_share_per_phone_percent", "P-101-7"),
        ("auth.sms_daily_share_per_ip_percent", "P-101-7"),
        ("auth.sms_daily_share_per_network_percent", "P-101-7"),
    ):
        spec = settings_store.SETTINGS[key]
        assert spec.description.startswith(f"PROVISIONAL ({number})"), key
        assert "before going live" in spec.description, key


def test_the_rules_are_marked_provisional_where_they_live() -> None:
    from pathlib import Path

    markx = Path(accounts.__file__).resolve().parents[1]
    sign_in = (markx / "accounts" / "telegram_sign_in.py").read_text(encoding="utf-8")
    assert "PROVISIONAL P-101-6" in sign_in
    service = (markx / "accounts" / "service.py").read_text(encoding="utf-8")
    assert "PROVISIONAL\n    P-101-8" in service or "PROVISIONAL P-101-8" in service


def test_failures_are_still_audited_without_a_phone_number(db: Session) -> None:
    secret = make_staff(db, STAFF_PHONE)
    _staff_attempt(secret, ip="198.51.100.61", password="a wrong guess!!")
    db.rollback()
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "staff.sign_in_failed")
        )
        == 1
    )
