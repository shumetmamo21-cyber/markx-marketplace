"""The login-code flow with delivery records, the resend cooldown and the SMS
monitoring (D-089). The fake sender, or a stand-in for the HTTPS adapter's
transport: no provider is contacted.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import OtpChallenge
from markx.core import settings_store
from markx.core.config import Config, get_config
from markx.notifications import sms
from markx.notifications.models import SmsMessage
from markx.notifications.sms import read_dev_sms_inbox
from markx.ops import checks
from tests.conftest import ApiClient, error_code, latest_code, let_resend_cooldown_pass

PHONE = "0911234567"
E164 = "+251911234567"
API_KEY = "test-only-sms-api-key-0123456789"


def _request(client: ApiClient, phone: str = PHONE, **extra: Any) -> Any:
    return client.post("/auth/otp/request", json={"phone": phone, **extra})


def _age(db: DbSession, seconds: float) -> None:
    """As if every delivery record was written this many seconds earlier."""
    db.execute(
        text("update sms_messages set created_at = created_at - make_interval(secs => :s)"),
        {"s": seconds},
    )
    db.commit()


# ------------------------------------------------------------ the cooldown


def test_a_second_code_within_a_minute_is_refused_with_the_wait(
    client: ApiClient, db: DbSession
) -> None:
    assert settings_store.get_int(db, "auth.otp_resend_cooldown_seconds") == 60
    assert _request(client).status_code == 200
    again = _request(client)
    assert again.status_code == 429
    assert error_code(again) == "otp_resend_too_soon"
    wait = again.json()["error"]["details"]["retry_after_seconds"]
    assert 59 <= wait <= 60
    assert again.headers["retry-after"] == str(wait)
    # Nothing was sent, and the first code is still the valid one.
    assert len(read_dev_sms_inbox(E164)) == 1
    assert len(db.scalars(select(SmsMessage)).all()) == 1
    assert db.scalars(select(OtpChallenge).where(OtpChallenge.consumed_at.is_(None))).one()


def test_the_wait_counts_down_and_then_a_new_code_is_sent(client: ApiClient, db: DbSession) -> None:
    _request(client)
    _age(db, 45)
    wait = _request(client).json()["error"]["details"]["retry_after_seconds"]
    assert 14 <= wait <= 15
    _age(db, 15)
    assert _request(client).status_code == 200
    assert len(read_dev_sms_inbox(E164)) == 2


def test_the_cooldown_is_per_number(client: ApiClient) -> None:
    assert _request(client).status_code == 200
    assert _request(client, "0922334455").status_code == 200
    # Every form of one number is one number.
    assert error_code(_request(client, "+251911234567")) == "otp_resend_too_soon"


def test_the_cooldown_is_a_setting(client: ApiClient, db: DbSession) -> None:
    settings_store.set_setting(db, "auth.otp_resend_cooldown_seconds", 300)
    db.commit()
    _request(client)
    _age(db, 120)
    wait = _request(client).json()["error"]["details"]["retry_after_seconds"]
    assert 179 <= wait <= 180
    settings_store.set_setting(db, "auth.otp_resend_cooldown_seconds", 0)
    db.commit()
    assert _request(client).status_code == 200


def test_a_send_that_certainly_failed_does_not_start_the_cooldown(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_http_adapter(monkeypatch, StandIn((503, b"{}")))
    assert error_code(_request(client)) == "sms_send_failed"
    _use_http_adapter(monkeypatch, StandIn((200, b'{"message_id": "m-2"}')))
    assert _request(client).status_code == 200


def test_a_send_that_may_have_gone_out_starts_the_cooldown(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_http_adapter(monkeypatch, StandIn(TimeoutError("timed out")))
    assert error_code(_request(client)) == "sms_send_failed"
    assert error_code(_request(client)) == "otp_resend_too_soon"


def test_two_requests_at_the_same_moment_send_one_code(make_client: Any) -> None:
    barrier = threading.Barrier(4)
    results: list[int] = []

    def ask() -> None:
        visitor = make_client()
        barrier.wait()
        results.append(_request(visitor).status_code)

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [200, 429, 429, 429]
    assert len(read_dev_sms_inbox(E164)) == 1


def test_the_cooldown_comes_after_the_bot_check_and_before_the_hourly_limit(
    client: ApiClient, db: DbSession
) -> None:
    _request(client)
    # The bot check still answers first, as before (D-085).
    assert error_code(_request(client, bot_token="bot")) == "bot_check_failed"
    # A refused early request does not use up the hour's allowance.
    for _ in range(10):
        assert error_code(_request(client)) == "otp_resend_too_soon"
    limit = settings_store.get_int(db, "auth.otp_per_phone_per_hour")
    for _ in range(limit - 1):
        let_resend_cooldown_pass(PHONE)
        assert _request(client).status_code == 200
    let_resend_cooldown_pass(PHONE)
    assert error_code(_request(client)) == "rate_limited"


def test_a_locked_number_is_still_told_it_is_locked(client: ApiClient, db: DbSession) -> None:
    _request(client)
    db.execute(
        text("insert into otp_locks (phone, locked_until) values (:p, now() + interval '15 min')"),
        {"p": E164},
    )
    db.commit()
    assert error_code(_request(client)) == "otp_locked"


# -------------------------------------------------------- delivery records


def test_a_sent_code_leaves_a_record_without_the_text_code_or_number(
    client: ApiClient, db: DbSession
) -> None:
    _request(client)
    code = latest_code(PHONE)
    record = db.scalars(select(SmsMessage)).one()
    challenge = db.scalars(select(OtpChallenge)).one()
    assert record.purpose == "login_code"
    assert record.otp_challenge_id == challenge.id
    assert record.notification_id is None
    assert record.provider == "fake"
    assert record.provider_message_id == f"fake-{record.id}"
    assert record.status == "accepted"
    assert record.error_code is None
    assert record.segments == 1
    assert record.completed_at is not None
    assert record.completed_at >= record.created_at
    assert bytes(record.phone_ref) == sms.phone_reference(E164)
    row_text = db.execute(text("select sms_messages::text from sms_messages")).scalar_one()
    for secret in (code, E164, "911234567", "MarkX code"):
        assert secret not in row_text
    columns = {c["name"] for c in db.execute(text(
        "select column_name as name from information_schema.columns "
        "where table_name = 'sms_messages'")).mappings()}  # fmt: skip
    assert not columns & {"text", "body", "message", "code", "phone"}
    # And still nothing in the outbox.
    assert db.execute(text("select count(*) from outbox")).scalar_one() == 0


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        ((401, b"{}"), "failed", "auth_failed"),
        ((429, b"{}"), "failed", "rate_limited"),
        ((500, b"{}"), "failed", "provider_unavailable"),
        (ConnectionRefusedError(111, "refused"), "failed", "connection_failed"),
        (TimeoutError("timed out"), "unknown", "timeout"),
        ((200, b"<html>"), "unknown", "malformed_response"),
    ],
)
def test_a_failed_send_is_recorded_and_the_person_is_told(
    client: ApiClient,
    db: DbSession,
    monkeypatch: pytest.MonkeyPatch,
    answer: Any,
    status: str,
    code: str,
) -> None:
    stand_in = StandIn(answer)
    _use_http_adapter(monkeypatch, stand_in)
    response = _request(client)
    assert response.status_code == 503
    assert error_code(response) == "sms_send_failed"
    record = db.scalars(select(SmsMessage)).one()
    assert (record.status, record.error_code, record.provider) == (status, code, "http")
    assert record.provider_message_id is None
    assert len(stand_in.calls) == 1  # no automatic retry of a login code


def test_an_accepted_send_through_the_https_adapter(
    client: ApiClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = StandIn((202, b'{"message_id": "prov-77"}'))
    _use_http_adapter(monkeypatch, stand_in)
    assert _request(client, language="am").status_code == 200
    record = db.scalars(select(SmsMessage)).one()
    assert (record.status, record.provider_message_id, record.segments) == (
        "accepted",
        "prov-77",
        1,
    )
    sent = json.loads(stand_in.calls[0][2])
    assert sent["to"] == E164
    assert sent["reference"] == str(record.id)
    assert "ኮድ" in sent["text"]
    # The real adapter writes nothing to the development inbox.
    assert read_dev_sms_inbox(E164) == []


def test_an_adapter_bug_is_recorded_and_does_not_leak(
    client: ApiClient,
    db: DbSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken:
        provider = "broken"

        def send(self, phone: str, text: str, *, reference: str) -> sms.SmsResult:
            raise RuntimeError("boom")

    monkeypatch.setattr(sms, "get_sms_sender", lambda: Broken())
    assert error_code(_request(client)) == "sms_send_failed"
    record = db.scalars(select(SmsMessage)).one()
    assert (record.status, record.error_code) == ("unknown", "send_error")
    assert E164 not in caplog.text


def test_the_database_refuses_a_record_that_breaks_the_rules(db: DbSession) -> None:
    good: dict[str, Any] = {
        "purpose": "login_code",
        "phone_ref": b"\x00" * 32,
        "otp_challenge_id": uuid.uuid4(),
        "provider": "fake",
        "status": "accepted",
        "segments": 1,
    }
    db.add(SmsMessage(**good))
    db.commit()
    for change in [
        {"purpose": "marketing"},
        {"status": "sent"},
        {"phone_ref": b"+251911234567"},
        {"otp_challenge_id": None},
        {"purpose": "notification"},
        {"segments": 0},
        {"status": "failed"},  # a failure needs its error code
        {"provider_message_id": ""},
    ]:
        db.add(SmsMessage(**{**good, **change}))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# -------------------------------------------------------------- monitoring


def _record(
    db: DbSession, status: str, *, minutes_ago: float = 5, error: str | None = None
) -> None:
    db.add(SmsMessage(purpose="login_code", phone_ref=b"\x01" * 32, otp_challenge_id=uuid.uuid4(),
                      provider="http", status=status, segments=1,
                      error_code=error or (None if status in ("accepted", "pending") else "timeout"),
                      created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago)))  # fmt: skip


def test_a_high_failure_share_in_the_last_hour_is_critical(db: DbSession) -> None:
    for _ in range(6):
        _record(db, "accepted")
    for _ in range(3):
        _record(db, "failed", error="auth_failed")
    _record(db, "unknown", error="timeout")
    _record(db, "failed", minutes_ago=90, error="auth_failed")  # outside the hour
    db.commit()
    (finding,) = checks.sms_failures(db, datetime.now(UTC))
    assert finding.key == "sms.failures"
    assert finding.severity == "critical"
    assert finding.details == {
        "attempted": 10,
        "not_confirmed": 4,
        "percent": 40,
        "by_error": {"auth_failed": 3, "timeout": 1},
    }
    assert "4 of the last hour's 10 SMS (40%)" in finding.summary


def test_a_low_share_or_too_few_messages_raise_nothing(db: DbSession) -> None:
    for _ in range(9):
        _record(db, "accepted")
    _record(db, "failed", error="rate_limited")
    db.commit()
    assert checks.sms_failures(db, datetime.now(UTC)) == []  # 10% < 20%
    settings_store.set_setting(db, "sms.failure_alert_percent", 10)
    db.commit()
    assert len(checks.sms_failures(db, datetime.now(UTC))) == 1
    settings_store.set_setting(db, "sms.failure_alert_min_messages", 11)
    db.commit()
    assert checks.sms_failures(db, datetime.now(UTC)) == []


def test_messages_without_a_final_status_are_reported(db: DbSession) -> None:
    _record(db, "pending", minutes_ago=20)
    _record(db, "unknown", minutes_ago=30)
    _record(db, "pending", minutes_ago=5)  # still within the 15 minutes
    _record(db, "accepted", minutes_ago=60)  # final
    _record(db, "pending", minutes_ago=60 * 25)  # older than a day: no longer reported
    db.commit()
    (finding,) = checks.sms_unfinished(db, datetime.now(UTC))
    assert finding.key == "sms.unfinished"
    assert finding.details == {"by_status": {"pending": 1, "unknown": 1}, "minutes": 15}
    settings_store.set_setting(db, "sms.unfinished_alert_minutes", 45)
    db.commit()
    assert checks.sms_unfinished(db, datetime.now(UTC)) == []


def test_the_new_checks_are_part_of_the_watch_and_the_budget_check_stays() -> None:
    assert {checks.sms_budget, checks.sms_failures, checks.sms_unfinished} <= set(checks.WATCH)


def test_a_failure_alert_names_no_number(db: DbSession) -> None:
    for _ in range(5):
        _record(db, "failed", error="auth_failed")
    db.commit()
    text_out = json.dumps([asdict(f) for f in checks.sms_failures(db, datetime.now(UTC))])
    assert "+251" not in text_out


# ----------------------------------------------------------------- helpers


class StandIn:
    def __init__(self, answer: tuple[int, bytes] | BaseException) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        self.calls.append((url, dict(headers), body, timeout))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _use_http_adapter(monkeypatch: pytest.MonkeyPatch, transport: StandIn) -> None:
    """The HTTPS adapter, configured as a real server would be, with its
    transport replaced by a stand-in."""
    config = get_config().model_copy(
        update={"sms_provider": "http", "sms_api_url": "https://sms.provider.example/v1",
                "sms_api_key": Config(sms_api_key=API_KEY).sms_api_key, "sms_sender_id": "MarkX"}
    )  # fmt: skip
    monkeypatch.setattr(sms, "get_config", lambda: config)
    monkeypatch.setattr(sms, "UrllibTransport", lambda: transport)
