"""Writing to the audit log. Every staff action passes through here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from markx.audit.models import AuditLog
from markx.core.logging import request_id_var


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is performing an action, for the audit log and status events."""

    type: str  # "staff", "user" or "system"
    user_id: uuid.UUID | None
    ip: str | None = None

    @classmethod
    def system(cls) -> Actor:
        return cls(type="system", user_id=None)


def record_by(
    db: Session,
    actor: Actor,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    *,
    before: Any | None = None,
    after: Any | None = None,
) -> AuditLog:
    return record(
        db,
        actor_type=actor.type,
        actor_user_id=actor.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        ip=actor.ip,
    )


def record(
    db: Session,
    *,
    actor_type: str,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    before: Any | None = None,
    after: Any | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Add an audit row to the current transaction.

    It commits or rolls back together with the change it describes, so the
    trail can never claim something that did not happen.
    """
    request_id = request_id_var.get()
    entry = AuditLog(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before=before,
        after=after,
        ip=ip,
        request_id=None if request_id == "-" else request_id,
    )
    db.add(entry)
    return entry
