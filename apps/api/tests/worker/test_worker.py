"""The background worker (blueprint F.8, D.16, P2).

Every test drives the worker by calling one pass of its own loop with a clock
it controls. Nothing here sleeps to let time pass.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core.db import session_scope
from markx.notifications import service as notifications
from markx.notifications.models import Notification, Outbox
from markx.notifications.push import read_dev_push_outbox
from markx.offers.models import Offer
from markx.sellers.models import SellerPayoutAccount
from markx.worker import jobs as scheduled
from markx.worker import outbox
from markx.worker.models import ScheduledJob
from markx.worker.runner import main, run_once
from tests.factories import (
    make_catalog,
    make_offer,
    make_product,
    make_seller,
    payout_body,
    staff_client,
)

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
NO_JOBS: tuple[scheduled.Job, ...] = ()


class Crash(BaseException):
    """The process dying: nothing in the worker may catch it."""


def _queue(db: Session, topic: str = "test.topic", **payload: Any) -> uuid.UUID:
    row = notifications.enqueue(db, topic, payload, run_after=T0)
    db.flush()
    db.commit()
    return row.id


def _row(db: Session, outbox_id: uuid.UUID) -> Outbox:
    db.rollback()
    row = db.get(Outbox, outbox_id)
    assert row is not None
    db.refresh(row)
    return row


class Recorder:
    """A handler that remembers what it was given."""

    def __init__(self) -> None:
        self.seen: list[uuid.UUID] = []
        self._lock = threading.Lock()

    def __call__(self, db: Session, row: Outbox) -> None:
        with self._lock:
            self.seen.append(row.id)


# -- scheduled jobs ------------------------------------------------------------------


def test_the_worker_runs_the_jobs_that_were_waiting_for_it(db: Session) -> None:
    """`mark_stale_offers` and `activate_due_payout_accounts` were written and
    tested in session two and called by nothing. The worker calls them, and
    the order expiry job beside them."""
    staff = staff_client(db, "0911000200", StaffRole.SUPER_ADMIN)
    product = make_product(staff, make_catalog(staff))
    seller, seller_id = make_seller(staff, "0911000001")
    offer = make_offer(seller, seller_id, product["variants"][0]["id"])
    changed = seller.put(
        f"/seller/{seller_id}/payout-account", json=payout_body(account_number="2000999988887777")
    )
    assert changed.json()["status"] == "pending"

    now = datetime.now(UTC)
    report = run_once(now)
    assert {o.name: o.result for o in report.jobs} == {
        "orders.expire_unanswered": 0,
        "orders.complete_after_problem_window": 0,
        "orders.cancel_overdue_fulfilment": 0,
        "offers.mark_stale": 0,
        "sellers.activate_due_payout_accounts": 0,
        "search.rebuild_all": 1,  # the one approved product
        "sellers.weekly_report": 0,  # the seller did not exist last week (D-069)
        "reviews.recount_all": 0,  # no review yet (D-066)
        "retention.prune": 0,  # nothing old enough (F-08, D-083)
        "ops.reconcile": 0,  # nothing out of line (D-064)
        "ops.watch": 0,
    }

    # Fifteen days on, the price is unconfirmed and the cooling-off has passed.
    later = now + timedelta(days=15)
    report = run_once(later)
    outcomes = {o.name: (o.ok, o.result) for o in report.jobs}
    # The rate-limit counters this test's requests left are now old (F-08).
    pruned_ok, pruned = outcomes.pop("retention.prune")
    assert pruned_ok
    assert pruned is not None
    assert pruned >= 1
    assert outcomes == {
        "orders.expire_unanswered": (True, 0),
        "orders.complete_after_problem_window": (True, 0),
        "orders.cancel_overdue_fulfilment": (True, 0),
        "offers.mark_stale": (True, 1),
        "sellers.activate_due_payout_accounts": (True, 1),
        "search.rebuild_all": (True, 1),
        "sellers.weekly_report": (True, 1),  # its first whole week has ended
        "reviews.recount_all": (True, 0),
        "ops.reconcile": (True, 0),
        "ops.watch": (True, 0),
    }
    db.rollback()
    assert db.scalar(select(Offer.status).where(Offer.id == offer["id"])) == "stale"
    accounts_now = dict(
        db.execute(select(SellerPayoutAccount.account_last4, SellerPayoutAccount.status)).all()
    )
    assert accounts_now == {"6789": "replaced", "7777": "active"}
    # The system is named as the actor (blueprint C.2).
    actors = set(
        db.scalars(
            select(AuditLog.actor_type).where(
                AuditLog.action.in_(("offer.mark_stale", "seller_payout_account.activate"))
            )
        )
    )
    assert actors == {"system"}


def test_a_job_runs_when_it_is_due_and_not_before(db: Session) -> None:
    runs: list[datetime] = []
    job = scheduled.Job("test.hourly", timedelta(hours=1), lambda _, now: runs.append(now) or 7)

    assert [o.result for o in scheduled.run_due_jobs(T0, [job])] == [7]
    assert scheduled.run_due_jobs(T0, [job]) == []
    assert scheduled.run_due_jobs(T0 + timedelta(minutes=59), [job]) == []
    assert len(scheduled.run_due_jobs(T0 + timedelta(hours=1), [job])) == 1
    assert runs == [T0, T0 + timedelta(hours=1)]
    state = db.get(ScheduledJob, "test.hourly")
    assert state is not None
    assert state.next_run_at == T0 + timedelta(hours=2)
    assert (state.last_result, state.consecutive_failures, state.last_error) == (7, 0, None)


def test_a_job_that_raises_does_not_stop_the_others(db: Session) -> None:
    ran: list[str] = []

    def broken(session: Session, now: datetime) -> int:
        # Its own half-finished work must vanish with it.
        notifications.enqueue(session, "test.orphan", {})
        session.flush()
        raise RuntimeError("the job broke")

    jobs = [
        scheduled.Job("test.first", timedelta(hours=1), lambda *_: ran.append("first") or 1),
        scheduled.Job("test.broken", timedelta(hours=1), broken),
        scheduled.Job("test.last", timedelta(hours=1), lambda *_: ran.append("last") or 1),
    ]
    report = run_once(T0, jobs=jobs, handlers={})
    assert ran == ["first", "last"]
    assert [(o.name, o.ok) for o in report.jobs] == [
        ("test.first", True), ("test.broken", False), ("test.last", True),
    ]  # fmt: skip
    state = db.get(ScheduledJob, "test.broken")
    assert state is not None
    assert state.consecutive_failures == 1
    assert state.last_error == "RuntimeError: the job broke"
    assert state.next_run_at == T0 + timedelta(minutes=1)
    assert db.scalar(select(func.count()).select_from(Outbox)) == 0


def test_a_failing_job_waits_longer_each_time_and_recovers(db: Session) -> None:
    healthy = False

    def flaky(_: Session, __: datetime) -> int:
        if not healthy:
            raise RuntimeError("still broken")
        return 3

    job = scheduled.Job("test.flaky", timedelta(minutes=5), flaky)
    now, waits = T0, []
    for _ in range(8):
        assert [o.ok for o in scheduled.run_due_jobs(now, [job])] == [False]
        db.rollback()
        state = db.get(ScheduledJob, "test.flaky")
        assert state is not None
        db.refresh(state)
        # Not due again until the delay has passed.
        assert scheduled.run_due_jobs(state.next_run_at - timedelta(seconds=1), [job]) == []
        waits.append(state.next_run_at - now)
        now = state.next_run_at
    assert waits == [timedelta(minutes=m) for m in (1, 2, 4, 8, 16, 32, 60, 60)]

    healthy = True
    assert [o.result for o in scheduled.run_due_jobs(now, [job])] == [3]
    db.refresh(state)
    assert (state.consecutive_failures, state.last_error) == (0, None)
    assert state.next_run_at == now + timedelta(minutes=5)


def test_a_job_that_keeps_failing_raises_an_alert(caplog: pytest.LogCaptureFixture) -> None:
    def broken(_: Session, __: datetime) -> int:
        raise RuntimeError("down")

    job = scheduled.Job("test.alert", timedelta(minutes=5), broken)
    levels = []
    now = T0
    for _ in range(scheduled.ALERT_AFTER_FAILURES):
        caplog.clear()
        with caplog.at_level("ERROR", logger="markx.worker.jobs"):
            scheduled.run_due_jobs(now, [job])
        levels.append(caplog.records[-1].levelname)
        now += timedelta(hours=2)
    assert levels == ["ERROR", "ERROR", "CRITICAL"]


def test_two_workers_never_run_the_same_job_at_once(db: Session) -> None:
    started, release = threading.Event(), threading.Event()
    runs: list[int] = []

    def slow(_: Session, __: datetime) -> int:
        runs.append(1)
        started.set()
        assert release.wait(timeout=30)
        return 1

    job = scheduled.Job("test.slow", timedelta(hours=1), slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(scheduled.run_due_jobs, T0, [job])
        assert started.wait(timeout=30)
        # The second worker finds the job taken and moves on without waiting.
        assert scheduled.run_due_jobs(T0, [job]) == []
        release.set()
        assert [o.ok for o in first.result(timeout=30)] == [True]
    assert runs == [1]
    assert scheduled.run_due_jobs(T0, [job]) == []


def test_a_worker_that_dies_in_a_job_leaves_it_due(db: Session) -> None:
    def dies(session: Session, _: datetime) -> int:
        notifications.enqueue(session, "test.orphan", {})
        session.flush()
        raise Crash

    with pytest.raises(Crash):
        scheduled.run_due_jobs(T0, [scheduled.Job("test.dies", timedelta(hours=1), dies)])
    state = db.get(ScheduledJob, "test.dies")
    assert state is not None
    assert (state.next_run_at, state.last_started_at, state.consecutive_failures) == (T0, None, 0)
    assert db.scalar(select(func.count()).select_from(Outbox)) == 0
    # The next worker picks it up.
    again = scheduled.Job("test.dies", timedelta(hours=1), lambda *_: 5)
    assert [o.result for o in scheduled.run_due_jobs(T0, [again])] == [5]


# -- the outbox ----------------------------------------------------------------------


def test_a_committed_message_is_delivered_exactly_once(db: Session) -> None:
    """Blueprint P2: "one queued in a committed transaction is sent exactly once"."""
    outbox_id = _queue(db)
    handler = Recorder()
    for _ in range(3):
        run_once(T0, jobs=NO_JOBS, handlers={"test.topic": handler})
    assert handler.seen == [outbox_id]
    row = _row(db, outbox_id)
    assert (row.status, row.attempts, row.last_error) == ("done", 1, None)
    assert row.finished_at is not None


def test_a_message_from_a_rolled_back_transaction_is_never_sent(db: Session) -> None:
    """Blueprint P2: "a message queued in a transaction that rolls back is never sent"."""

    class Failed(Exception):
        pass

    def change_that_fails() -> None:
        with session_scope() as session:
            notifications.enqueue(session, "test.topic", {"n": 1}, run_after=T0)
            session.flush()
            raise Failed

    with pytest.raises(Failed):
        change_that_fails()
    handler = Recorder()
    report = run_once(T0, jobs=NO_JOBS, handlers={"test.topic": handler})
    assert report.outbox.handled == 0
    assert handler.seen == []


def test_a_message_is_not_delivered_before_its_time(db: Session) -> None:
    outbox_id = _queue(db)
    db.execute(update(Outbox).values(run_after=T0 + timedelta(minutes=10)))
    db.commit()
    handler = Recorder()
    assert outbox.drain(T0, handlers={"test.topic": handler}).handled == 0
    assert outbox.drain(T0 + timedelta(minutes=10), handlers={"test.topic": handler}).done == 1
    assert handler.seen == [outbox_id]


def test_a_failed_delivery_is_retried_after_a_growing_delay(db: Session) -> None:
    outbox_id = _queue(db)
    calls: list[datetime] = []
    working = False

    def handler(session: Session, row: Outbox) -> None:
        calls.append(now)
        # Database work done before the failure is undone with it.
        notifications.enqueue(session, "test.side-effect", {})
        session.flush()
        if not working:
            raise ConnectionError("the provider is down")

    handlers = {"test.topic": handler}
    now, waits = T0, []
    for attempt in range(1, 5):
        report = outbox.drain(now, handlers=handlers)
        assert (report.done, report.retried, report.failed) == (0, 1, 0)
        row = _row(db, outbox_id)
        assert (row.status, row.attempts) == ("pending", attempt)
        assert row.last_error == "ConnectionError: the provider is down"
        # Too early: nothing happens.
        assert outbox.drain(row.run_after - timedelta(seconds=1), handlers=handlers).handled == 0
        waits.append(row.run_after - now)
        now = row.run_after
    assert waits == [timedelta(seconds=s) for s in (30, 60, 120, 240)]
    assert db.scalar(select(func.count()).select_from(Outbox)) == 1

    working = True
    assert outbox.drain(now, handlers=handlers).done == 1
    row = _row(db, outbox_id)
    assert (row.status, row.attempts, row.last_error) == ("done", 5, None)
    assert len(calls) == 5
    # The handler's database work is kept exactly once: on the run that succeeded.
    assert db.scalar(select(func.count()).select_from(Outbox)) == 2


def test_a_message_that_keeps_failing_is_given_up_with_an_alert(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    outbox_id = _queue(db)

    def handler(_: Session, __: Outbox) -> None:
        raise ValueError("bad payload")

    now = T0
    with caplog.at_level("CRITICAL", logger="markx.worker.outbox"):
        for _ in range(outbox.MAX_ATTEMPTS):
            outbox.drain(now, handlers={"test.topic": handler})
            now += timedelta(hours=2)
    row = _row(db, outbox_id)
    assert (row.status, row.attempts) == ("failed", outbox.MAX_ATTEMPTS)
    assert [r.message for r in caplog.records] == ["outbox message gave up"]
    assert outbox.drain(now + timedelta(days=30), handlers={"test.topic": handler}).handled == 0


def test_one_bad_message_does_not_block_the_rest(db: Session) -> None:
    bad = _queue(db, "test.bad")
    unknown = _queue(db, "test.nobody-handles-this")
    good = [_queue(db, n=n) for n in range(3)]
    handler = Recorder()

    def broken(_: Session, __: Outbox) -> None:
        raise RuntimeError("no")

    report = run_once(T0, jobs=NO_JOBS, handlers={"test.topic": handler, "test.bad": broken})
    assert (report.outbox.done, report.outbox.retried) == (3, 2)
    assert handler.seen == good
    assert _row(db, bad).status == "pending"
    assert _row(db, unknown).last_error == (
        "UnknownTopic: no handler for outbox topic 'test.nobody-handles-this'"
    )


def test_two_workers_never_take_the_same_message(db: Session) -> None:
    held = _queue(db, n=0)
    others = [_queue(db, n=n) for n in range(1, 4)]
    started, release = threading.Event(), threading.Event()
    seen_by_first: list[uuid.UUID] = []

    def slow(_: Session, row: Outbox) -> None:
        seen_by_first.append(row.id)
        if row.id == held:
            started.set()
            assert release.wait(timeout=30)

    second = Recorder()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(outbox.drain, T0, handlers={"test.topic": slow})
        assert started.wait(timeout=30)
        # The first worker is in the middle of `held`. The second skips it,
        # takes everything else, and does not wait.
        report = outbox.drain(T0, handlers={"test.topic": second})
        assert report.done == 3
        assert second.seen == others
        release.set()
        assert first.result(timeout=30).done == 1
    assert seen_by_first == [held]
    assert {_row(db, i).attempts for i in (held, *others)} == {1}


def test_many_workers_deliver_every_message_exactly_once(db: Session) -> None:
    ids = []
    for n in range(120):
        ids.append(notifications.enqueue(db, "test.topic", {"n": n}, run_after=T0))
    db.commit()
    ids = [row.id for row in ids]
    handler = Recorder()
    barrier = threading.Barrier(8)

    def worker(_: int) -> int:
        barrier.wait(timeout=30)
        return outbox.drain(T0, limit=1000, handlers={"test.topic": handler}).done

    with ThreadPoolExecutor(max_workers=8) as pool:
        done = list(pool.map(worker, range(8)))
    assert sum(done) == 120
    assert Counter(handler.seen) == Counter(ids)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "done")) == 120


def test_a_worker_that_dies_in_the_middle_of_a_message_does_not_lose_it(db: Session) -> None:
    outbox_id = _queue(db)

    def dies(session: Session, _: Outbox) -> None:
        notifications.enqueue(session, "test.side-effect", {})
        session.flush()
        raise Crash

    with pytest.raises(Crash):
        outbox.drain(T0, handlers={"test.topic": dies})
    # Nothing of the dead worker's transaction survived: the message is as it was.
    row = _row(db, outbox_id)
    assert (row.status, row.attempts, row.last_error, row.run_after) == ("pending", 0, None, T0)
    assert db.scalar(select(func.count()).select_from(Outbox)) == 1

    handler = Recorder()
    assert outbox.drain(T0, handlers={"test.topic": handler}).done == 1
    assert handler.seen == [outbox_id]


def test_a_failing_handler_does_not_stop_the_scheduled_jobs_or_the_pass(db: Session) -> None:
    _queue(db, "test.bad")
    ran: list[str] = []

    def broken(_: Session, __: Outbox) -> None:
        raise RuntimeError("no")

    job = scheduled.Job("test.job", timedelta(hours=1), lambda *_: ran.append("job") or 0)
    report = run_once(T0, jobs=[job], handlers={"test.bad": broken})
    assert ran == ["job"]
    assert report.outbox.retried == 1


# -- the notification handler ----------------------------------------------------------


def _person(db: Session, phone: str, telegram_id: int | None) -> uuid.UUID:
    user = accounts.get_or_create_user_by_phone(db, accounts.parse_phone(phone))
    user.telegram_id = telegram_id
    db.commit()
    return user.id


def test_a_notification_is_pushed_to_telegram_once_and_recorded(db: Session) -> None:
    user_id = _person(db, "0911000001", telegram_id=4242)
    notifications.notify(db, user_id, "seller.application_approved", {"level": 2})
    db.commit()
    for _ in range(2):
        run_once(datetime.now(UTC), jobs=NO_JOBS)

    sent = read_dev_push_outbox()
    assert len(sent) == 1
    row = db.scalar(select(Outbox))
    assert row is not None
    assert sent[0] == {
        "telegram_id": 4242,
        "template": "seller.application_approved",
        "params": {"level": 2},
        "language": "am",
        "idempotency_key": str(row.id),
        "sent_at": sent[0]["sent_at"],
    }
    channels = Counter(db.scalars(select(Notification.channel)))
    assert channels == {"in_app": 1, "telegram": 1}
    # The in-app list shows one message, not the delivery record as a second.
    assert len(notifications.list_for_user(db, user_id)) == 1


def test_a_person_without_telegram_gets_the_in_app_message_only(db: Session) -> None:
    user_id = _person(db, "0911000001", telegram_id=None)
    notifications.notify(db, user_id, "seller.member_added", {})
    db.commit()
    report = run_once(datetime.now(UTC), jobs=NO_JOBS)
    assert report.outbox.done == 1
    assert read_dev_push_outbox() == []
    assert Counter(db.scalars(select(Notification.channel))) == {"in_app": 1}


def test_a_push_that_fails_leaves_no_delivery_record_and_is_retried(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _person(db, "0911000001", telegram_id=4242)
    notifications.notify(db, user_id, "seller.suspended", {})
    db.commit()

    class Down:
        def send(self, **_: Any) -> None:
            raise ConnectionError("telegram is unreachable")

    monkeypatch.setattr(outbox, "get_push_sender", Down)
    now = datetime.now(UTC)
    assert run_once(now, jobs=NO_JOBS).outbox.retried == 1
    db.rollback()
    assert Counter(db.scalars(select(Notification.channel))) == {"in_app": 1}

    monkeypatch.undo()
    assert run_once(now + timedelta(minutes=1), jobs=NO_JOBS).outbox.done == 1
    db.rollback()
    assert Counter(db.scalars(select(Notification.channel))) == {"in_app": 1, "telegram": 1}
    assert len(read_dev_push_outbox()) == 1


# -- the process ---------------------------------------------------------------------


def test_the_command_runs_one_pass_and_exits(db: Session) -> None:
    user_id = _person(db, "0911000001", telegram_id=None)
    notifications.notify(db, user_id, "seller.member_added", {})
    db.commit()
    assert main(["--once"]) == 0
    db.rollback()
    assert db.scalar(select(Outbox.status)) == "done"
    assert set(db.scalars(select(ScheduledJob.name))) == {j.name for j in scheduled.JOBS}


def test_the_command_handles_everything_that_is_due_not_one_batch(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-082: a backlog bigger than one batch (here 220 messages that waited
    half an hour) is handled by one `--once`. The running worker keeps its
    batches of 100, and starts the next at once when a batch was full."""
    waited = datetime.now(UTC) - timedelta(minutes=30)
    rows = [
        notifications.enqueue(db, "test.topic", {"n": n}, run_after=waited)
        for n in range(2 * outbox.DEFAULT_BATCH + 20)
    ]
    db.flush()
    ids = [row.id for row in rows]
    db.commit()
    handler = Recorder()
    monkeypatch.setitem(outbox.HANDLERS, "test.topic", handler)

    # One pass of the running worker: one batch, the rest left for the next.
    assert run_once(jobs=NO_JOBS).outbox.done == outbox.DEFAULT_BATCH
    # `--once`: the other 120, more than a batch, all of them.
    assert main(["--once"]) == 0
    assert Counter(handler.seen) == Counter(ids)
    db.rollback()
    assert set(db.scalars(select(Outbox.status).where(Outbox.topic == "test.topic"))) == {"done"}


def test_a_message_a_job_queues_goes_out_in_the_same_pass(db: Session) -> None:
    """D-082: a message a scheduled job queues (an alert, say) is stamped
    with the database's time inside the job, after the pass began; it is
    sent in that pass, not left for the next."""
    db.commit()

    def queues_a_message(session: Session, _: datetime) -> int:
        notifications.enqueue(session, "test.topic", {"from": "job"})
        return 1

    handler = Recorder()
    job = scheduled.Job("test.queues", timedelta(hours=1), queues_a_message)
    report = run_once(jobs=(job,), handlers={"test.topic": handler})
    assert [(o.name, o.ok) for o in report.jobs] == [("test.queues", True)]
    assert report.outbox.done == 1
    assert len(handler.seen) == 1


def test_a_pass_that_cannot_do_its_work_exits_with_an_error(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-079: `--once` exits 1 when a due job failed or the outbox could not
    be drained, so a script or scheduler that started it can tell."""
    from markx.worker import runner

    db.commit()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("the database went away")

    monkeypatch.setattr(runner.outbox, "drain", broken)
    report = runner.run_once()
    assert report.drain_error == "ConnectionError: the database went away"
    assert not report.ok
    assert main(["--once"]) == 1

    monkeypatch.undo()
    failing = scheduled.Job("test.always_fails", timedelta(minutes=5), broken)
    report = runner.run_once(jobs=(failing,))
    assert [(o.name, o.ok) for o in report.jobs] == [("test.always_fails", False)]
    assert not report.ok


def test_the_worker_connects_as_the_application_role() -> None:
    """The worker shares the API's configuration: the least-privileged role,
    which cannot rewrite history (blueprint C.2 "System", F.3)."""
    with session_scope() as session:
        assert session.execute(text("select current_user")).scalar_one() == "markx_app"
