"""Notifications (blueprint D.16, F.9).

The in-app record is written in the same transaction as the change that caused
it. Anything that must leave the server (Telegram, SMS) is queued in the outbox
in that same transaction, so a rolled-back change never sends a message.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from markx.notifications.models import Notification, Outbox

TOPIC_PUSH = "notify.push"


def enqueue(
    db: Session, topic: str, payload: dict[str, Any], *, run_after: datetime | None = None
) -> Outbox:
    row = Outbox(topic=topic, payload=payload)
    if run_after is not None:
        row.run_after = run_after
    db.add(row)
    return row


def notify(
    db: Session, user_id: uuid.UUID, template: str, params: dict[str, Any] | None = None
) -> Notification:
    """Tell one person one thing. Messages stay minimal: identifiers and codes,
    never more personal data than the reader already has."""
    notification = Notification(
        user_id=user_id, channel="in_app", template=template, params=params or {}
    )
    db.add(notification)
    db.flush()
    enqueue(db, TOPIC_PUSH, {"notification_id": str(notification.id)})
    return notification


def list_for_user(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.channel == "in_app")
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.channel == "in_app",
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def mark_all_read(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC), status="read")
    )
