"""Writing to the audit log. Every staff action passes through here."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from markx.audit.models import AuditLog
from markx.core.logging import request_id_var


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
