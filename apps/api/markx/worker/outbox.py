"""Draining the outbox (blueprint D.16, F.8, F.9).

A row is written in the transaction that caused it, so a rolled-back change
never has one. The worker handles one row per transaction:

    lock one due row (FOR UPDATE SKIP LOCKED)  ->  run its handler
        ->  mark it done  ->  commit

* Two workers never take the same row: the second skips a locked row.
* A worker that dies mid-row commits nothing: the lock goes with its
  connection and the row is pending again, untouched.
* A handler that raises loses its own database work (a savepoint), the row
  waits a growing delay, and the next row is handled as usual.
* A row is marked done in the same transaction as the handler's database
  work, so that work happens exactly once. A message that leaves the server
  carries the row's id as an idempotency key; see D-034 for the one case in
  which the outside world could see it twice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.core.db import session_scope
from markx.images import service as images
from markx.notifications import delivery
from markx.notifications.models import Outbox
from markx.notifications.push import get_push_sender
from markx.notifications.service import TOPIC_PUSH
from markx.notifications.sms import get_sms_sender
from markx.ops import service as ops
from markx.reviews import service as reviews
from markx.search import service as search

logger = logging.getLogger("markx.worker.outbox")

MAX_ATTEMPTS = 8
RETRY_BASE = timedelta(seconds=30)
RETRY_MAX = timedelta(hours=1)
DEFAULT_BATCH = 100

Handler = Callable[[Session, Outbox], None]


class UnknownTopic(Exception):
    pass


def retry_delay(attempts: int) -> timedelta:
    """Thirty seconds, then one minute, two, four ... up to an hour."""
    return min(RETRY_BASE * (1 << min(max(attempts - 1, 0), 30)), RETRY_MAX)


# -- handlers --------------------------------------------------------------------


def push_notification(db: Session, row: Outbox) -> None:
    """Carry an in-app notification to the channels outside the app: the
    person's Telegram, and SMS for order alerts when that is switched on
    (D-092). The in-app record already exists and never depends on a
    provider. A channel with no provider is recorded `unavailable`, never
    raised; a channel that should be tried again raises DeliveryRetry, and
    the row is retried after its growing delay."""
    # Looked up here, not bound at import, so a test can swap a sender.
    delivery.deliver(
        db, row, delivery.Senders(push=lambda: get_push_sender(), sms=lambda: get_sms_sender())
    )


HANDLERS: dict[str, Handler] = {
    TOPIC_PUSH: push_notification,
    search.TOPIC_REBUILD: search.handle_rebuild,
    images.TOPIC_RENDER: images.handle_render,
    ops.TOPIC_ALERT: ops.handle_alert,
    reviews.TOPIC_RECOUNT: reviews.handle_recount,
}


# -- the dispatcher ----------------------------------------------------------------


@dataclass(slots=True)
class DrainReport:
    done: int = 0
    retried: int = 0
    failed: int = 0

    @property
    def handled(self) -> int:
        return self.done + self.retried + self.failed


def _handle_next(now: datetime, handlers: Mapping[str, Handler]) -> str | None:
    """Handle one due row in one transaction. Returns what happened to it, or
    None when no row is due and free."""
    with session_scope() as db:
        row = db.scalar(
            select(Outbox)
            .where(Outbox.status == "pending", Outbox.run_after <= now)
            .order_by(Outbox.run_after, Outbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.attempts += 1
        try:
            handler = handlers.get(row.topic)
            if handler is None:
                raise UnknownTopic(f"no handler for outbox topic {row.topic!r}")
            with db.begin_nested():
                handler(db, row)
        except Exception as exc:
            row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                row.finished_at = datetime.now(UTC)
                # Blueprint F.8: a job that keeps failing raises an alert.
                logger.critical(
                    "outbox message gave up",
                    exc_info=exc,
                    extra={"outbox_id": str(row.id), "topic": row.topic, "attempts": row.attempts},
                )
                return "failed"
            row.run_after = now + retry_delay(row.attempts)
            logger.warning(
                "outbox message will be retried",
                extra={
                    "outbox_id": str(row.id),
                    "topic": row.topic,
                    "attempts": row.attempts,
                    "error": row.last_error,
                },
            )
            return "retried"
        row.status = "done"
        row.last_error = None
        row.finished_at = datetime.now(UTC)
        return "done"


def drain(
    now: datetime | None = None,
    *,
    limit: int | None = DEFAULT_BATCH,
    handlers: Mapping[str, Handler] = HANDLERS,
) -> DrainReport:
    """Handle due rows, oldest first, until none is left or `limit` rows were
    handled. `limit=None` handles every row due at `now` (D-082). That ends:
    each row is handled once per call, and leaves it done, failed, or due
    again only after `now` (a retry is always scheduled later than `now`)."""
    now = now or datetime.now(UTC)
    report = DrainReport()
    while limit is None or report.handled < limit:
        outcome = _handle_next(now, handlers)
        if outcome is None:
            break
        setattr(report, outcome, getattr(report, outcome) + 1)
    return report
