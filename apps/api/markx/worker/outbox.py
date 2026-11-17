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
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.core.db import session_scope
from markx.notifications.models import Notification, Outbox
from markx.notifications.push import get_push_sender
from markx.notifications.service import TOPIC_PUSH
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
    """Send an in-app notification on to the person's Telegram, if they have
    linked it. The in-app record already exists; this adds the push."""
    payload: dict[str, Any] = row.payload
    notification = db.get(Notification, uuid.UUID(str(payload["notification_id"])))
    if notification is None:
        return  # the person's account, and its notifications, were deleted
    user = db.get(User, notification.user_id)
    if user is None or user.telegram_id is None or user.status != "active":
        return  # no channel to push to; the in-app list is the record
    # The delivery record, written with the row's completion: both or neither.
    db.add(
        Notification(
            user_id=user.id,
            channel="telegram",
            template=notification.template,
            params=notification.params,
        )
    )
    db.flush()
    get_push_sender().send(
        telegram_id=user.telegram_id,
        template=notification.template,
        params=dict(notification.params),
        language=user.language,
        idempotency_key=str(row.id),
    )


HANDLERS: dict[str, Handler] = {
    TOPIC_PUSH: push_notification,
    search.TOPIC_REBUILD: search.handle_rebuild,
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
    limit: int = DEFAULT_BATCH,
    handlers: Mapping[str, Handler] = HANDLERS,
) -> DrainReport:
    """Handle due rows, oldest first, until none is left or `limit` is reached."""
    now = now or datetime.now(UTC)
    report = DrainReport()
    for _ in range(limit):
        outcome = _handle_next(now, handlers)
        if outcome is None:
            break
        setattr(report, outcome, getattr(report, outcome) + 1)
    return report
