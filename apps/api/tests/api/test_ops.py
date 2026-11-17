"""Operational monitoring (blueprint F.8, F.12, P2; D-064): the marketplace
notices what is wrong, alerts once, keeps the alert up to date, says when
it is over, and proves every day that its money and stock add up.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.core import ratelimit, settings_store
from markx.core.db import session_scope
from markx.notifications.models import Outbox
from markx.ops import alerts as ops_alerts
from markx.ops import service as ops
from markx.ops.alerts import TelegramAlertSender, read_dev_alerts
from markx.ops.models import OpsAlert
from markx.orders import service as orders
from markx.orders.models import SellerOrder
from markx.payments.models import CommissionRule
from markx.worker.models import ScheduledJob
from markx.worker.runner import run_once
from tests.api.test_fulfilment import _both_parts_delivered
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    market = Bazaar(db)
    db.add(
        CommissionRule(
            scope="category", payment_kind="direct",
            category_id=uuid.UUID(market.catalog["phones"]), rate_bps=300,
        )
    )  # fmt: skip
    db.commit()
    return market


def _job(report: Any, name: str) -> Any:
    return next(o for o in report.jobs if o.name == name)


def _watch(now: datetime) -> dict[str, int]:
    with session_scope() as session:
        found = ops.watch(session, now)
    return {"open": found}


def test_a_stuck_order_raises_one_alert_and_its_end_is_reported(
    bazaar: Bazaar, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-060 keeps one failing order from blocking the others; this makes
    sure somebody hears about it (F.12, "stuck orders")."""
    _, order, alpha_id, _, after = _both_parts_delivered(bazaar)
    real_charge_fee = orders.ledger.charge_fee

    def broken(session: DbSession, **kwargs: Any) -> Any:
        if kwargs["seller_order_id"] == uuid.UUID(alpha_id):
            raise RuntimeError("the fee could not be posted")
        return real_charge_fee(session, **kwargs)

    monkeypatch.setattr(orders.ledger, "charge_fee", broken)
    later = after + timedelta(minutes=40)  # past the 30 minutes' grace
    report = run_once(later)
    assert _job(report, "orders.complete_after_problem_window").result == 1  # Beta only
    assert _job(report, "ops.watch").result == 1
    (alert,) = db.scalars(select(OpsAlert))
    assert (alert.key, alert.severity, alert.resolved_at) == (
        "orders.stuck_delivered", "critical", None,
    )  # fmt: skip
    assert order["code"] in alert.summary
    # The founder heard about it once, through the outbox, with no personal data.
    (sent,) = read_dev_alerts()
    assert (sent["state"], sent["key"]) == ("opened", "orders.stuck_delivered")
    assert order["code"] in sent["text"]
    assert "0911" not in sent["text"]

    # Still stuck five minutes on: the same alert is touched, nobody is told twice.
    run_once(later + timedelta(minutes=6))
    db.rollback()
    (alert,) = db.scalars(select(OpsAlert))
    assert alert.occurrences == 2
    assert len(read_dev_alerts()) == 1

    # The fault is fixed: the order completes and the alert resolves.
    monkeypatch.setattr(orders.ledger, "charge_fee", real_charge_fee)
    report = run_once(later + timedelta(minutes=12))
    assert _job(report, "orders.complete_after_problem_window").result == 1
    db.rollback()
    (alert,) = db.scalars(select(OpsAlert).execution_options(populate_existing=True))
    assert alert.resolved_at is not None
    assert [m["state"] for m in read_dev_alerts()] == ["opened", "resolved"]
    assert read_dev_alerts()[1]["text"].startswith("Resolved: ")


def test_failing_jobs_failed_messages_and_the_sms_budget_are_noticed(db: DbSession) -> None:
    now = datetime.now(UTC)
    db.add(ScheduledJob(name="orders.expire_unanswered", next_run_at=now, consecutive_failures=3,
                        last_error="OperationalError: the database went away"))  # fmt: skip
    db.add(Outbox(topic="notify.push", payload={}, status="failed", attempts=8,
                  finished_at=now, last_error="no Telegram adapter"))  # fmt: skip
    settings_store.set_setting(db, "auth.sms_daily_budget", 10)
    db.commit()
    for _ in range(8):
        ratelimit.hit("sms:daily", 1000, timedelta(days=1))
    assert _watch(now)["open"] == 3
    found = {a.key: a for a in db.scalars(select(OpsAlert))}
    assert set(found) == {"job.failing:orders.expire_unanswered", "outbox.failed", "sms.budget"}
    assert found["sms.budget"].severity == "warning"
    assert "8 of 10" in found["sms.budget"].summary
    assert found["outbox.failed"].details == {"by_topic": {"notify.push": 1}}

    # The budget runs out: the warning becomes critical, and that is news.
    for _ in range(2):
        ratelimit.hit("sms:daily", 1000, timedelta(days=1))
    with session_scope() as session:
        ops.watch(session, now)
        opened = session.scalars(
            select(Outbox).where(Outbox.topic == ops.TOPIC_ALERT).order_by(Outbox.id)
        ).all()
    db.rollback()
    budget = db.scalar(select(OpsAlert).where(OpsAlert.key == "sms.budget"))
    assert budget is not None
    assert budget.severity == "critical"
    assert sum(1 for row in opened if row.payload["alert_id"] == str(budget.id)) == 2


def test_the_daily_reconciliation_finds_money_and_stock_out_of_line(
    bazaar: Bazaar, db: DbSession, migrator_engine: Engine
) -> None:
    """F.12: order totals equal their parts and lines; fees equal the ledger;
    reserved stock equals its reservations. The database's own constraints
    stop most of this; the reconciliation catches what they cannot."""
    _, order, alpha_id, _, after = _both_parts_delivered(bazaar)
    run_once(after)  # both parts complete, fees charged
    report = run_once(after + timedelta(days=1, minutes=1))
    assert _job(report, "ops.reconcile").result == 0
    assert [(a.key, a.summary) for a in db.scalars(select(OpsAlert))] == []

    # Something writes around the service layer (a hand edit, a bad script).
    with migrator_engine.begin() as connection:
        connection.execute(
            text("update orders set items_total_santim = items_total_santim + 100, "
                 "grand_total_santim = grand_total_santim + 100 where code = :code"),
            {"code": order["code"]},
        )  # fmt: skip
        connection.execute(
            text("update seller_orders set commission_santim = commission_santim + 1 where id = :id"),
            {"id": alpha_id},
        )  # fmt: skip
        connection.execute(
            text("update inventory set reserved = reserved + 1 where offer_id = :id"),
            {"id": bazaar.a256["id"]},
        )
    report = run_once(after + timedelta(days=2, minutes=2))
    assert _job(report, "ops.reconcile").result == 3
    db.rollback()
    found = {a.key: a for a in db.scalars(select(OpsAlert))}
    assert set(found) == {"reconcile.order_totals", "reconcile.fees", "reconcile.stock"}
    assert found["reconcile.order_totals"].details["order_codes"] == [order["code"]]
    assert "differ from their part's commission" in found["reconcile.fees"].summary
    assert all(a.severity == "critical" for a in found.values())


def test_who_may_read_the_operations_status(bazaar: Bazaar, db: DbSession) -> None:
    run_once(datetime.now(UTC))
    path = "/admin/ops/status"
    for i, role in enumerate((StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.FINANCE)):
        response = staff_client(db, f"09110003{i:02d}", role).get(path)
        assert response.status_code == 200, (role, response.text)
    body = bazaar.staff.get(path).json()
    assert {job["name"] for job in body["jobs"]} >= {"ops.watch", "ops.reconcile"}
    assert body["open_alerts"] == []
    catalogue = staff_client(db, "0911000309", StaffRole.CATALOGUE)
    assert catalogue.get(path).status_code == 403
    assert error_code(bazaar.a.get(path)) == "staff_only"
    assert ApiClient().get(path).status_code == 401
    assert bazaar.staff.get("/admin/ops/alerts").json() == []


def test_an_outside_monitor_can_tell_the_worker_is_down(db: DbSession) -> None:
    """F.12, P2: the uptime monitor polls this; five quiet minutes is down."""
    visitor = ApiClient()
    never = visitor.get("/healthz/worker")
    assert never.status_code == 503
    assert never.json()["worker"] == "late"
    run_once(datetime.now(UTC))
    up = visitor.get("/healthz/worker")
    assert up.status_code == 200, up.text
    assert up.json()["worker"] == "up"
    db.execute(
        update(ScheduledJob).values(last_started_at=datetime.now(UTC) - timedelta(minutes=6))
    )
    db.commit()
    assert visitor.get("/healthz/worker").status_code == 503


def test_alerts_go_to_the_founders_telegram_group_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(request: Any, timeout: float) -> Answer:
        sent.append((request.full_url, request.data.decode(), timeout))
        return Answer(b"{}")

    monkeypatch.setattr(ops_alerts.urllib.request, "urlopen", fake_urlopen)
    sender = TelegramAlertSender("123:test-token", "-1001")
    sender.send(text="3 parts are stuck (MX-ABCDEF).", severity="critical", state="opened",
                key="orders.stuck_delivered")  # fmt: skip
    ((url, body, timeout),) = sent
    assert url == "https://api.telegram.org/bot123:test-token/sendMessage"
    assert "chat_id=-1001" in body
    assert "MX-ABCDEF" in body
    assert timeout == ops_alerts.TELEGRAM_TIMEOUT_SECONDS

    class Refused(Answer):
        status = 500

    monkeypatch.setattr(ops_alerts.urllib.request, "urlopen", lambda *_a, **_k: Refused(b""))
    with pytest.raises(RuntimeError):  # the outbox will retry it
        sender.send(text="x", severity="critical", state="opened", key="k")
    # Without the group's id, alerts are never sent to Telegram.
    assert not isinstance(ops_alerts.get_alert_sender(), TelegramAlertSender)


def test_seller_order_ids_in_findings_are_never_personal(bazaar: Bazaar, db: DbSession) -> None:
    """Findings name order codes and counts; never a buyer's phone or name."""
    _both_parts_delivered(bazaar)
    db.execute(
        update(SellerOrder).values(problem_window_ends_at=datetime.now(UTC) - timedelta(hours=1))
    )
    db.commit()
    # Completion would fix it; look before the job runs.
    with session_scope() as session:
        assert ops.watch(session, datetime.now(UTC)) == 1
    (alert,) = db.scalars(select(OpsAlert))
    assert "0911" not in alert.summary
    assert "0911" not in str(alert.details)


def test_a_broken_check_is_reported_and_never_stops_the_others(
    db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watch is what reports failing jobs, so one check that breaks (a
    bad query, say) must become an alert itself, not take the watch down."""
    from markx.ops import checks

    def broken(session: DbSession, now: datetime) -> list[checks.Finding]:
        session.execute(text("select * from no_such_table"))
        return []

    monkeypatch.setattr(checks, "WATCH", (broken, *checks.WATCH))
    now = datetime.now(UTC)
    db.add(ScheduledJob(name="orders.expire_unanswered", next_run_at=now, consecutive_failures=3))
    db.commit()
    assert _watch(now)["open"] == 2
    keys = {a.key for a in db.scalars(select(OpsAlert))}
    assert keys == {"ops.check_failed:broken", "job.failing:orders.expire_unanswered"}
