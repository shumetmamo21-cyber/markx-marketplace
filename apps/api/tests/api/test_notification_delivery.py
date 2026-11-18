"""Notifications outside the app: Telegram, SMS, the delivery records, the
deadline reminder and the monitoring (D-092).

No real provider is used anywhere: the fake push sender, the fake SMS sender
and stand-ins that fail, time out or "crash" in a chosen place.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.core import settings_store
from markx.core.config import Config
from markx.notifications import delivery, push, texts
from markx.notifications import service as notifications
from markx.notifications.models import (
    Notification,
    NotificationDelivery,
    Outbox,
    SmsMessage,
)
from markx.notifications.push import PushErrorCode, PushSendError, PushStatus, read_dev_push_outbox
from markx.notifications.sms import (
    FakeSmsSender,
    SmsErrorCode,
    SmsSendError,
    SmsStatus,
    count_segments,
    dev_sms_inbox_path,
    read_dev_sms_inbox,
)
from markx.ops import checks
from markx.ops import service as ops
from markx.ops.models import OpsAlert
from markx.orders import service as orders
from markx.orders.models import SellerOrder, SellerOrderReminder
from markx.sellers.models import Seller, SellerMember
from markx.worker import outbox
from markx.worker.runner import run_once
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.deployment.test_production_config import production
from tests.factories import add_to_cart, checkout

NO_JOBS: tuple[Any, ...] = ()
CODE = "MX-7K3F9Q"
ORDER_ALERT = "order.seller_confirmed"  # an order alert with an SMS text


class Crash(BaseException):
    """The worker process dying: not an Exception, so nothing catches it."""


def _person(db: Session, phone: str, *, telegram_id: int | None = None, language: str = "en"):
    user = accounts.get_or_create_user_by_phone(db, accounts.parse_phone(phone), language)
    user.telegram_id = telegram_id
    # A linked Telegram always has its linking time (D-093, migration 0017).
    user.telegram_linked_at = datetime.now(UTC) if telegram_id is not None else None
    user.language = language
    db.commit()
    return user


def _alert(db: Session, user_id: uuid.UUID, template: str = ORDER_ALERT) -> Notification:
    n = notifications.notify(
        db, user_id, template,
        {"order_id": str(uuid.uuid4()), "seller_order_id": str(uuid.uuid4()), "order_code": CODE},
    )  # fmt: skip
    db.commit()
    return n


def _deliveries(db: Session) -> dict[tuple[str, str], tuple[str, str | None, int]]:
    db.rollback()
    return {
        (d.template, d.channel): (d.status, d.reason, d.attempts)
        for d in db.scalars(select(NotificationDelivery))
    }


def _sms_on(db: Session, **more: Any) -> None:
    settings_store.set_setting(db, "notifications.sms_enabled", True)
    for key, value in more.items():
        settings_store.set_setting(db, f"notifications.{key}", value)
    db.commit()


def _drain(now: datetime | None = None) -> Any:
    return run_once(now or datetime.now(UTC), jobs=NO_JOBS).outbox


# -- 1, 2: no Telegram provider on a real server --------------------------------------------


def test_a_real_server_without_a_telegram_provider_records_unavailable_and_never_crashes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit's defect: get_push_sender() raised on staging and production,
    so every notification for a linked Telegram user was retried eight times
    and given up. Now the delivery is `unavailable` at once, with its reason."""
    monkeypatch.delenv("MARKX_TELEGRAM_BOT_TOKEN", raising=False)
    real = Config(**production())
    monkeypatch.setattr(push, "get_config", lambda: real)
    assert push.get_push_sender() is None  # never raises

    user = _person(db, "0911000001", telegram_id=4242)
    notifications.notify(db, user.id, "seller.member_added", {})
    db.commit()
    report = run_once(datetime.now(UTC), jobs=NO_JOBS)
    assert report.ok
    assert (report.outbox.done, report.outbox.retried, report.outbox.failed) == (1, 0, 0)
    assert _deliveries(db) == {
        ("seller.member_added", "telegram"): ("unavailable", "telegram_provider_not_configured", 0)
    }
    assert read_dev_push_outbox() == []
    # The in-app message is there regardless of any provider.
    assert [n.template for n in notifications.list_for_user(db, user.id)] == ["seller.member_added"]
    assert db.scalar(select(Outbox.status)) == "done"

    # The watch says so, in words, without a phone number or a Telegram id.
    (finding,) = checks.notification_channel_unavailable(db, datetime.now(UTC))
    assert finding.key == "notifications.channel_unavailable"
    assert "4242" not in finding.summary
    assert "0911000001" not in finding.summary


def test_a_person_without_telegram_is_recorded_as_skipped(db: Session) -> None:
    user = _person(db, "0911000001")
    notifications.notify(db, user.id, "seller.member_added", {})
    db.commit()
    assert _drain().done == 1
    assert _deliveries(db) == {
        ("seller.member_added", "telegram"): ("skipped", "no_telegram_linked", 0)
    }


def test_a_linked_person_is_pushed_through_the_fake_and_the_delivery_is_accepted(
    db: Session,
) -> None:
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)
    _drain()
    (sent,) = read_dev_push_outbox()
    assert (sent["telegram_id"], sent["template"]) == (4242, ORDER_ALERT)
    status, reason, attempts = _deliveries(db)[(ORDER_ALERT, "telegram")]
    assert (status, reason, attempts) == ("accepted", None, 1)
    # Reached by Telegram, so no SMS even if it were on (it is off).
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("skipped", "sms_notifications_disabled", 0)


# -- 3, 4: SMS off by default, on through the switch -------------------------------------------


def test_notification_sms_is_off_by_default(db: Session) -> None:
    assert settings_store.get_bool(db, "notifications.sms_enabled") is False
    user = _person(db, "0911000001")
    _alert(db, user.id)
    _drain()
    assert read_dev_sms_inbox("+251911000001") == []
    assert db.scalar(select(func.count()).select_from(SmsMessage)) == 0
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("skipped", "sms_notifications_disabled", 0)


def test_the_switch_sends_order_alerts_through_the_fake_sms_provider(db: Session) -> None:
    _sms_on(db)
    user = _person(db, "0911000001", language="am")
    alert = _alert(db, user.id)
    # Something that is not an order alert never goes by SMS.
    notifications.notify(db, user.id, "seller.member_added", {})
    db.commit()
    _drain()
    (message,) = read_dev_sms_inbox("+251911000001")
    assert CODE in message["text"]
    assert message["text"] == texts.render(ORDER_ALERT, {"order_code": CODE}, "am")
    record = db.scalar(select(SmsMessage))
    assert record is not None
    assert (record.purpose, record.notification_id, record.status) == (
        "notification",
        alert.id,
        "accepted",
    )
    row = db.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "sms"))
    assert row is not None
    assert (row.status, row.sms_message_id, row.provider) == ("accepted", record.id, "fake")
    assert ("seller.member_added", "sms") not in _deliveries(db)


def test_sms_goes_to_telegram_users_only_when_telegram_cannot_reach_them(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db)
    linked = _person(db, "0911000001", telegram_id=4242)
    _alert(db, linked.id)
    _drain()
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("skipped", "reached_by_telegram", 0)

    # No push provider at all: SMS is the only channel left for them.
    monkeypatch.setattr(outbox, "get_push_sender", lambda: None)
    _alert(db, linked.id, "order.delivered")
    _drain()
    assert _deliveries(db)[("order.delivered", "sms")][0] == "accepted"
    assert _deliveries(db)[("order.delivered", "telegram")][0] == "unavailable"


# -- 5: only the store's order handlers --------------------------------------------------------


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


def _member(db: Session, seller_id: str, phone: str, role: str, *, active: bool = True) -> Any:
    user = _person(db, phone, telegram_id=int(phone[-6:]))
    db.add(
        SellerMember(seller_id=uuid.UUID(seller_id), user_id=user.id, role=role, is_active=active)
    )
    db.commit()
    return user


def _order(bazaar: Bazaar) -> tuple[ApiClient, dict[str, Any]]:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    response = checkout(buyer, address_id, {"alpha": "seller_rider"})
    assert response.status_code == 201, response.text
    return buyer, dict(response.json())


def test_only_the_stores_order_handlers_hear_about_its_orders(bazaar: Bazaar, db: Session) -> None:
    handler = _member(db, bazaar.a_id, "0911000061", "orders")
    manager = _member(db, bazaar.a_id, "0911000062", "manager")
    catalogue = _member(db, bazaar.a_id, "0911000063", "catalogue")
    finance = _member(db, bazaar.a_id, "0911000064", "finance")
    gone = _member(db, bazaar.a_id, "0911000065", "orders", active=False)
    other = _member(db, bazaar.b_id, "0911000066", "orders")
    owner_id = db.scalar(
        select(SellerMember.user_id).where(
            SellerMember.seller_id == uuid.UUID(bazaar.a_id), SellerMember.role == "owner"
        )
    )
    _order(bazaar)
    told = set(
        db.scalars(
            select(Notification.user_id).where(Notification.template == "order.placed_for_seller")
        )
    )
    assert told == {owner_id, handler.id, manager.id}
    assert not told & {catalogue.id, finance.id, gone.id, other.id}

    # The handler leaves the store before the worker runs: Telegram is skipped.
    db.execute(
        SellerMember.__table__.update()
        .where(SellerMember.user_id == handler.id)
        .values(is_active=False)
    )
    db.commit()
    _drain()
    db.rollback()
    by_user = {
        n.user_id: d
        for d, n in db.execute(
            select(NotificationDelivery, Notification)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.template == "order.placed_for_seller",
                NotificationDelivery.channel == "telegram",
            )
        ).all()
    }
    assert (by_user[handler.id].status, by_user[handler.id].reason) == (
        "skipped",
        "recipient_not_authorized",
    )
    assert by_user[manager.id].status == "accepted"
    # Telegram ids are the phones' last six digits (see _member).
    pushed = {line["telegram_id"] for line in read_dev_push_outbox()}
    assert 62 in pushed
    assert not pushed & {61, 63, 64, 65, 66}


def test_a_closed_store_or_a_foreign_order_is_never_delivered(bazaar: Bazaar, db: Session) -> None:
    handler = _member(db, bazaar.a_id, "0911000061", "orders")
    _, order = _order(bazaar)
    so_id = order["seller_orders"][0]["id"]
    # A notification that names another store's order is refused outside the app.
    n = notifications.notify(
        db, handler.id, "order.placed_for_seller",
        {"seller_id": bazaar.b_id, "seller_order_id": so_id, "order_code": order["code"]},
    )  # fmt: skip
    db.commit()
    assert delivery.recipient_may_receive(db, n, handler) == "recipient_not_authorized"
    db.execute(
        Seller.__table__.update().where(Seller.id == uuid.UUID(bazaar.a_id)).values(status="closed")
    )
    db.commit()
    own = db.scalar(
        select(Notification)
        .where(
            Notification.user_id == handler.id, Notification.template == "order.placed_for_seller"
        )
        .order_by(Notification.created_at)
    )
    assert own is not None
    assert delivery.recipient_may_receive(db, own, handler) == "recipient_not_authorized"


# -- 6: no personal data in any outside text --------------------------------------------------


BUYER = {
    "order_code": CODE,
    "recipient_name": "Abebe Kebede",
    "phone": "+251911223344",
    "landmark": "Behind the Bole Medhanialem church",
    "handover_code": "482913",
    "buyer_name": "Abebe",
}


@pytest.mark.parametrize("template", sorted(texts.ORDER_TEXTS))
@pytest.mark.parametrize("language", ["en", "am"])
def test_no_outside_text_carries_personal_data(template: str, language: str) -> None:
    words = texts.ORDER_TEXTS[template][language]
    assert texts.placeholders(words) <= {"code"}
    rendered = texts.render(template, BUYER, language)
    for key, value in BUYER.items():
        if key != "order_code":
            assert value not in rendered, (template, key)
    assert count_segments(rendered).segments <= texts.MAX_SEGMENTS_PER_TEXT
    assert rendered.startswith("MarkX")


def test_every_outside_text_exists_in_both_languages() -> None:
    for template, words in texts.ORDER_TEXTS.items():
        assert set(words) == {"en", "am"}, template
        assert texts.placeholders(words["en"]) == texts.placeholders(words["am"]), template
    assert set(texts.GENERIC_TEXT) == {"en", "am"}


def test_anything_but_an_order_code_is_refused() -> None:
    for bad in ("+251911223344", "Abebe", "MX-ABC123", "", None):
        with pytest.raises(texts.UnsafeText):
            texts.render(ORDER_ALERT, {"order_code": bad}, "en")
    assert (
        texts.render("something.else", {"order_code": "+251911223344"}, "en")
        == (texts.GENERIC_TEXT["en"])
    )


def test_the_bot_api_adapter_sends_only_the_order_code() -> None:
    sent: list[tuple[str, bytes]] = []

    def transport(url: str, headers: Any, body: bytes, timeout: float) -> tuple[int, bytes]:
        sent.append((url, body))
        return 200, b'{"ok": true, "result": {"message_id": 77}}'

    sender = push.BotApiPushSender(
        bot_token="123:TEST-ONLY", timeout_seconds=5, transport=transport
    )
    result = sender.send(
        telegram_id=4242, template=ORDER_ALERT, params=BUYER, language="en", idempotency_key="k"
    )
    assert result.provider_message_id == "77"
    ((url, body),) = sent
    assert url.endswith("/sendMessage")
    assert url.startswith("https://api.telegram.org/bot")
    for key, value in BUYER.items():
        if key != "order_code":
            assert value.encode() not in body
    assert "TEST-ONLY" not in repr(sender)


@pytest.mark.parametrize(
    ("answer", "code", "status"),
    [
        ((403, b"{}"), PushErrorCode.RECIPIENT_BLOCKED, PushStatus.FAILED),
        ((429, b"{}"), PushErrorCode.RATE_LIMITED, PushStatus.FAILED),
        ((502, b"{}"), PushErrorCode.PROVIDER_UNAVAILABLE, PushStatus.FAILED),
        ((200, b"not json"), PushErrorCode.MALFORMED_RESPONSE, PushStatus.UNKNOWN),
        (TimeoutError(), PushErrorCode.TIMEOUT, PushStatus.UNKNOWN),
        (ConnectionRefusedError(), PushErrorCode.CONNECTION_FAILED, PushStatus.FAILED),
    ],
)
def test_the_bot_api_adapter_maps_every_failure(answer: Any, code: Any, status: Any) -> None:
    def transport(*_: Any) -> tuple[int, bytes]:
        if isinstance(answer, BaseException):
            raise answer
        return answer  # type: ignore[no-any-return]

    sender = push.BotApiPushSender(
        bot_token="123:TEST-ONLY", timeout_seconds=5, transport=transport
    )
    with pytest.raises(PushSendError) as caught:
        sender.send(
            telegram_id=1, template=ORDER_ALERT, params=BUYER, language="am", idempotency_key="k"
        )
    assert (caught.value.code, caught.value.status) == (code, status)
    assert "TEST-ONLY" not in str(caught.value)


# -- 7: two budgets that never touch -----------------------------------------------------------


def test_notification_and_sign_in_budgets_are_independent(db: Session) -> None:
    _sms_on(db, sms_daily_budget=1, sms_cooldown_seconds=0)
    first, second = _person(db, "0911000001"), _person(db, "0911000002")
    _alert(db, first.id)
    _alert(db, second.id, "order.delivered")
    _drain()
    assert _deliveries(db)[(ORDER_ALERT, "sms")][0] == "accepted"
    assert _deliveries(db)[("order.delivered", "sms")][:2] == ("skipped", "sms_budget_spent")
    # The notification budget is spent; a sign-in code still goes out.
    client = ApiClient()
    response = client.post("/auth/otp/request", json={"phone": "0911000009", "language": "en"})
    assert response.status_code == 200, response.text
    now = datetime.now(UTC)
    (finding,) = checks.notification_sms_budget(db, now)
    assert (finding.key, finding.severity) == ("notifications.sms_budget", "critical")
    assert checks.sms_budget(db, now) == []

    # The other way round: the sign-in budget spent, order alerts still go.
    settings_store.set_setting(db, "auth.sms_daily_budget", 0)
    settings_store.set_setting(db, "notifications.sms_daily_budget", 100)
    db.commit()
    refused = ApiClient().post("/auth/otp/request", json={"phone": "0911000008", "language": "en"})
    assert error_code(refused) == "sms_budget_spent"
    third = _person(db, "0911000003")
    _alert(db, third.id, "order.completed")
    _drain()
    assert _deliveries(db)[("order.completed", "sms")][0] == "accepted"


def test_the_cooldown_and_the_hourly_limit_per_person(db: Session) -> None:
    _sms_on(db, sms_cooldown_seconds=600)
    user = _person(db, "0911000001")
    _alert(db, user.id)
    _alert(db, user.id, "order.delivered")
    _drain()
    assert _deliveries(db)[(ORDER_ALERT, "sms")][0] == "accepted"
    assert _deliveries(db)[("order.delivered", "sms")][:2] == ("skipped", "sms_cooldown")
    assert len(read_dev_sms_inbox("+251911000001")) == 1

    _sms_on(db, sms_cooldown_seconds=0, sms_per_person_per_hour=2)
    for template in ("order.completed", "order.refunded"):
        _alert(db, user.id, template)
    _drain()
    reasons = {t: r for (t, c), (s, r, _) in _deliveries(db).items() if c == "sms"}
    assert sorted([reasons["order.completed"], reasons["order.refunded"]], key=str) == sorted(
        [None, "sms_person_hourly_limit"], key=str
    )


# -- 8, 9: the reminder before the deadline ---------------------------------------------------


def _reminders(db: Session) -> Counter[str]:
    db.rollback()
    return Counter(
        str(so_id)
        for so_id in db.scalars(
            select(Notification.params["seller_order_id"].astext).where(
                Notification.template == "order.approaching_response_deadline"
            )
        )
    )


def test_an_unanswered_order_is_reminded_once_before_its_deadline(
    bazaar: Bazaar, db: Session
) -> None:
    _, order = _order(bazaar)
    so_id = order["seller_orders"][0]["id"]
    deadline = datetime.fromisoformat(order["seller_orders"][0]["response_deadline"])

    # Not yet: more than the lead time (10 minutes) is left.
    assert orders.remind_approaching_deadline(db, now=deadline - timedelta(minutes=11)) == 0
    db.commit()
    assert _reminders(db) == Counter()
    assert orders.remind_approaching_deadline(db, now=deadline - timedelta(minutes=9)) == 1
    db.commit()
    # Never twice, however often the job runs.
    for minutes in (8, 5, 1):
        assert (
            orders.remind_approaching_deadline(db, now=deadline - timedelta(minutes=minutes)) == 0
        )
        db.commit()
    assert _reminders(db) == Counter({so_id: 1})  # the owner, Alpha's one order handler
    assert db.scalar(select(func.count()).select_from(SellerOrderReminder)) == 1
    # The reminder reaches the owner's Telegram... no: the owner has none linked.
    _drain()
    assert _deliveries(db)[("order.approaching_response_deadline", "telegram")][:2] == (
        "skipped",
        "no_telegram_linked",
    )


def test_answered_cancelled_or_expired_orders_are_never_reminded(
    bazaar: Bazaar, db: Session
) -> None:
    buyer, address_id = bazaar.buyer()
    parts, order_ids = [], []
    for _ in range(3):
        add_to_cart(buyer, bazaar.a128["id"], 1)
        response = checkout(buyer, address_id, {"alpha": "seller_rider"})
        assert response.status_code == 201, response.text
        parts.append(response.json()["seller_orders"][0])
        order_ids.append(response.json()["id"])
    base = f"/seller/{bazaar.a_id}/orders"
    assert bazaar.a.post(f"{base}/{parts[0]['id']}/confirm").status_code == 200
    declined = bazaar.a.post(f"{base}/{parts[1]['id']}/decline", json={"reason": "out_of_stock"})
    assert declined.status_code == 200, declined.text
    cancelled = buyer.post(
        f"/me/orders/{order_ids[2]}/seller-orders/{parts[2]['id']}/cancel", json={}
    )
    assert cancelled.status_code == 200, cancelled.text
    deadline = datetime.fromisoformat(parts[0]["response_deadline"])
    for minutes in (9, 5, 1):
        assert (
            orders.remind_approaching_deadline(db, now=deadline - timedelta(minutes=minutes)) == 0
        )
        db.commit()

    # One the shop never answers expires; it is not reminded afterwards.
    _, late = _order(bazaar)
    late_part = late["seller_orders"][0]
    late_deadline = datetime.fromisoformat(late_part["response_deadline"])
    assert orders.expire_unanswered_orders(db, now=late_deadline) == 1
    db.commit()
    assert orders.remind_approaching_deadline(db, now=late_deadline - timedelta(minutes=5)) == 0
    db.commit()
    assert _reminders(db) == Counter()


def test_an_order_placed_too_close_to_its_deadline_is_not_reminded(
    bazaar: Bazaar, db: Session
) -> None:
    """With less than the lead time between the order and its deadline, a
    reminder would only repeat the "new order" message."""
    _, order = _order(bazaar)
    so_id = uuid.UUID(order["seller_orders"][0]["id"])
    deadline = datetime.fromisoformat(order["seller_orders"][0]["response_deadline"])
    db.execute(
        SellerOrder.__table__.update()
        .where(SellerOrder.id == so_id)
        .values(created_at=deadline - timedelta(minutes=5))
    )
    db.commit()
    assert orders.remind_approaching_deadline(db, now=deadline - timedelta(minutes=1)) == 0


def test_the_worker_runs_the_reminder_job(bazaar: Bazaar, db: Session) -> None:
    _, order = _order(bazaar)
    deadline = datetime.fromisoformat(order["seller_orders"][0]["response_deadline"])
    jobs = {o.name: o.result for o in run_once(deadline - timedelta(minutes=3)).jobs}
    assert jobs["orders.remind_approaching_deadline"] == 1


# -- 10: failures raise the monitoring signal --------------------------------------------------


class RefusingSms:
    provider = "stand-in"

    def __init__(self, code: SmsErrorCode, status: SmsStatus = SmsStatus.FAILED) -> None:
        self.code, self.status, self.calls = code, status, 0

    def send(self, phone: str, text: str, *, reference: str) -> Any:
        self.calls += 1
        raise SmsSendError(self.code, status=self.status)


def test_repeated_failures_open_an_alert_without_personal_data(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db, sms_cooldown_seconds=0)
    stand_in = RefusingSms(SmsErrorCode.AUTH_FAILED)
    monkeypatch.setattr(outbox, "get_sms_sender", lambda: stand_in)
    for n in range(3):
        _alert(db, _person(db, f"091100000{n + 1}").id)
    _drain()
    # A wrong key is not worth retrying: failed at once, the rows are done.
    assert stand_in.calls == 3
    db.rollback()
    assert Counter(
        db.execute(
            select(NotificationDelivery.status, NotificationDelivery.reason).where(
                NotificationDelivery.channel == "sms"
            )
        ).all()
    ) == {("failed", "auth_failed"): 3}
    now = datetime.now(UTC) + timedelta(seconds=1)
    assert ops.watch(db, now) >= 1
    db.commit()
    alert = db.scalar(select(OpsAlert).where(OpsAlert.key == "notifications.delivery_failures"))
    assert alert is not None
    assert alert.severity == "critical"
    assert "sms:auth_failed: 3" in alert.summary
    for phone in ("0911000001", "911000001", "+251911000001"):
        assert phone not in alert.summary
        assert phone not in str(alert.details)


def test_half_sent_deliveries_are_reported_as_stale(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)

    class Dies:
        provider = "stand-in"

        def send(self, **_: Any) -> None:
            raise Crash

    monkeypatch.setattr(outbox, "get_push_sender", Dies)
    with pytest.raises(Crash):
        _drain()
    assert checks.stale_notification_deliveries(db, datetime.now(UTC)) == []
    (finding,) = checks.stale_notification_deliveries(db, datetime.now(UTC) + timedelta(hours=1))
    assert finding.details["by_state"] == {"telegram:sending": 1}


# -- 12: retries, crashes and ambiguous outcomes -----------------------------------------------


def test_a_telegram_outage_is_retried_then_given_up_with_an_explicit_status(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)

    class Down:
        provider = "stand-in"
        calls = 0

        def send(self, **_: Any) -> None:
            Down.calls += 1
            raise PushSendError(PushErrorCode.PROVIDER_UNAVAILABLE)

    monkeypatch.setattr(outbox, "get_push_sender", Down)
    now = datetime.now(UTC)
    for attempt in range(1, delivery.MAX_DELIVERY_ATTEMPTS):
        report = _drain(now)
        assert report.retried == 1, attempt
        assert _deliveries(db)[(ORDER_ALERT, "telegram")] == (
            "retrying",
            "provider_unavailable",
            attempt,
        )
        now += timedelta(hours=2)
    assert _drain(now).done == 1
    assert _deliveries(db)[(ORDER_ALERT, "telegram")] == (
        "failed",
        "provider_unavailable",
        delivery.MAX_DELIVERY_ATTEMPTS,
    )
    assert Down.calls == delivery.MAX_DELIVERY_ATTEMPTS
    db.rollback()
    # The outbox row ends `done`, not given up: the delivery says what happened.
    assert db.scalar(select(Outbox.status)) == "done"
    # Nothing more is ever tried for it.
    assert _drain(now + timedelta(days=1)).handled == 0


def test_a_blocked_bot_is_failed_at_once(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)

    class Blocked:
        provider = "stand-in"

        def send(self, **_: Any) -> None:
            raise PushSendError(PushErrorCode.RECIPIENT_BLOCKED)

    monkeypatch.setattr(outbox, "get_push_sender", Blocked)
    assert _drain().done == 1
    assert _deliveries(db)[(ORDER_ALERT, "telegram")] == ("failed", "recipient_blocked", 1)


def test_telegram_crash_before_the_provider_answers_is_sent_again(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)

    class DiesBeforeSending:
        provider = "stand-in"

        def send(self, **_: Any) -> None:
            raise Crash

    monkeypatch.setattr(outbox, "get_push_sender", DiesBeforeSending)
    with pytest.raises(Crash):
        _drain()
    # The attempt was committed as begun; the outbox row is pending, untouched.
    assert _deliveries(db)[(ORDER_ALERT, "telegram")] == ("sending", None, 1)
    db.rollback()
    assert db.scalar(select(Outbox.status)) == "pending"

    monkeypatch.undo()
    assert _drain().done == 1
    assert _deliveries(db)[(ORDER_ALERT, "telegram")] == ("accepted", "interrupted", 2)
    assert len(read_dev_push_outbox()) == 1


def test_telegram_crash_after_the_provider_accepted_can_send_twice(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented limit (D-034, D-092): Telegram has no idempotency key,
    so a worker that dies after Telegram took the message and before MarkX
    stored that sends it again. At-least-once: seen twice, never lost."""
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)
    real = push.FakePushSender(push.dev_push_outbox_path())

    class DiesAfterSending:
        provider = "fake"

        def send(self, **kwargs: Any) -> None:
            real.send(**kwargs)
            raise Crash

    monkeypatch.setattr(outbox, "get_push_sender", DiesAfterSending)
    with pytest.raises(Crash):
        _drain()
    monkeypatch.undo()
    _drain()
    sent = read_dev_push_outbox()
    assert len(sent) == 2
    # Both carry the same key, so an adapter that remembers keys could refuse one.
    assert sent[0]["idempotency_key"] == sent[1]["idempotency_key"]
    assert _deliveries(db)[(ORDER_ALERT, "telegram")][:2] == ("accepted", "interrupted")


def test_sms_crash_after_the_provider_accepted_is_never_sent_twice(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db)
    user = _person(db, "0911000001")
    _alert(db, user.id)
    real = FakeSmsSender(dev_sms_inbox_path())

    class DiesAfterSending:
        provider = "fake"

        def send(self, phone: str, text: str, *, reference: str) -> Any:
            real.send(phone, text, reference=reference)
            raise Crash

    monkeypatch.setattr(outbox, "get_sms_sender", DiesAfterSending)
    with pytest.raises(Crash):
        _drain()
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("sending", None, 1)
    assert db.scalar(select(SmsMessage.status)) == "pending"
    monkeypatch.undo()
    assert _drain().done == 1
    # At-most-once: unknown, flagged, and the one message is the only one.
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("unknown", "interrupted", 1)
    assert len(read_dev_sms_inbox("+251911000001")) == 1
    assert db.scalar(select(func.count()).select_from(SmsMessage)) == 1


def test_sms_crash_before_the_provider_answers_is_flagged_not_resent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db)
    user = _person(db, "0911000001")
    _alert(db, user.id)

    class DiesBeforeSending:
        provider = "fake"

        def send(self, phone: str, text: str, *, reference: str) -> Any:
            raise Crash

    monkeypatch.setattr(outbox, "get_sms_sender", DiesBeforeSending)
    with pytest.raises(Crash):
        _drain()
    monkeypatch.undo()
    _drain()
    # MarkX cannot tell this from the case above, so it is the same answer:
    # possibly lost, never doubled, and reported by the monitoring.
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("unknown", "interrupted", 1)
    assert read_dev_sms_inbox("+251911000001") == []
    settings_store.set_setting(db, "notifications.failure_alert_min", 1)
    db.commit()
    (finding,) = checks.notification_delivery_failures(db, datetime.now(UTC) + timedelta(seconds=1))
    assert finding.details["by_reason"] == {"sms:interrupted": 1}


def test_an_sms_timeout_is_unknown_and_never_retried(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db)
    user = _person(db, "0911000001")
    _alert(db, user.id)
    stand_in = RefusingSms(SmsErrorCode.TIMEOUT, SmsStatus.UNKNOWN)
    monkeypatch.setattr(outbox, "get_sms_sender", lambda: stand_in)
    assert _drain().done == 1
    assert _drain(datetime.now(UTC) + timedelta(hours=2)).handled == 0
    assert stand_in.calls == 1
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("unknown", "timeout", 1)
    assert db.scalar(select(SmsMessage.status)) == "unknown"


def test_an_sms_outage_is_retried_and_each_attempt_has_its_record(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sms_on(db)
    user = _person(db, "0911000001")
    _alert(db, user.id)
    stand_in = RefusingSms(SmsErrorCode.PROVIDER_UNAVAILABLE)
    monkeypatch.setattr(outbox, "get_sms_sender", lambda: stand_in)
    now = datetime.now(UTC)
    assert _drain(now).retried == 1
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("retrying", "provider_unavailable", 1)
    monkeypatch.undo()
    assert _drain(now + timedelta(minutes=5)).done == 1
    assert _deliveries(db)[(ORDER_ALERT, "sms")] == ("accepted", None, 2)
    db.rollback()
    assert sorted(db.scalars(select(SmsMessage.status))) == ["accepted", "failed"]
    assert len(read_dev_sms_inbox("+251911000001")) == 1


def test_a_second_pass_never_delivers_a_channel_twice(db: Session) -> None:
    _sms_on(db)
    user = _person(db, "0911000001", telegram_id=4242)
    _alert(db, user.id)
    for _ in range(3):
        _drain()
    assert len(read_dev_push_outbox()) == 1
    assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 2


def test_delivery_records_and_logs_hold_no_text_or_number(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _sms_on(db)
    user = _person(db, "0911000001")
    _alert(db, user.id)
    caplog.set_level("DEBUG")
    _drain()
    words = texts.render(ORDER_ALERT, {"order_code": CODE}, "en")
    row = db.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "sms"))
    assert row is not None
    stored = " ".join(str(getattr(row, c.key)) for c in NotificationDelivery.__table__.columns)
    assert words not in stored
    assert "911000001" not in stored
    for record in caplog.records:
        line = record.getMessage() + str(record.__dict__)
        assert "911000001" not in line
        assert words not in line


def test_the_bucket_names_agree() -> None:
    assert checks.NOTIFICATION_SMS_BUCKET == delivery.SMS_BUDGET_BUCKET
