"""Turning findings into alerts, and alerts into messages (blueprint F.8,
F.12; D-064).

`watch` (every five minutes) and `reconcile` (once a day) are scheduled
jobs. Each runs its checks, then:

* a finding with no open alert of its key opens one, and queues a message;
* a finding whose alert is open touches it (`last_seen_at`, `occurrences`);
* an open alert of the same source whose key nobody found any more is
  resolved, and queues a "resolved" message.

Messages go through the outbox (`ops.alert`), so a Telegram outage only
delays them, and a rolled-back check never sends one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.notifications.models import Outbox
from markx.ops import checks
from markx.ops.alerts import get_alert_sender
from markx.ops.models import OpsAlert

TOPIC_ALERT = "ops.alert"


def evaluate(
    db: Session, now: datetime, *, source: str, findings: Sequence[checks.Finding]
) -> dict[str, int]:
    """Open, touch and resolve alerts of one source. Returns the counts."""
    open_alerts = {
        alert.key: alert
        for alert in db.scalars(
            select(OpsAlert)
            .where(OpsAlert.source == source, OpsAlert.resolved_at.is_(None))
            .with_for_update()
        )
    }
    seen: set[str] = set()
    opened = touched = resolved = 0
    for finding in findings:
        if finding.key in seen:
            continue
        seen.add(finding.key)
        alert = open_alerts.get(finding.key)
        if alert is None:
            alert = OpsAlert(
                key=finding.key, source=source, severity=finding.severity,
                summary=finding.summary, details=finding.details,
                first_seen_at=now, last_seen_at=now,
            )  # fmt: skip
            db.add(alert)
            db.flush()
            _queue(db, alert, "opened")
            opened += 1
        else:
            escalated = alert.severity == "warning" and finding.severity == "critical"
            alert.summary, alert.details = finding.summary, finding.details
            alert.severity = finding.severity
            alert.last_seen_at = now
            alert.occurrences += 1
            if escalated:
                _queue(db, alert, "opened")
            touched += 1
    for key, alert in open_alerts.items():
        if key not in seen:
            alert.resolved_at = now
            _queue(db, alert, "resolved")
            resolved += 1
    db.flush()
    return {"opened": opened, "touched": touched, "resolved": resolved}


def _queue(db: Session, alert: OpsAlert, state: str) -> None:
    db.add(Outbox(topic=TOPIC_ALERT, payload={"alert_id": str(alert.id), "state": state}))


def watch(db: Session, now: datetime) -> int:
    """The scheduled `ops.watch` job. Returns how many problems are open."""
    findings = checks.run(db, now, checks.WATCH)
    evaluate(db, now, source="watch", findings=findings)
    return len(findings)


def reconcile(db: Session, now: datetime) -> int:
    """The scheduled `ops.reconcile` job (F.12, the daily reconciliation)."""
    findings = checks.run(db, now, checks.RECONCILE)
    evaluate(db, now, source="reconcile", findings=findings)
    return len(findings)


def handle_alert(db: Session, row: Outbox) -> None:
    """The outbox handler for `ops.alert`: send the alert's summary as it
    stands now."""
    payload: dict[str, Any] = row.payload
    alert = db.get(OpsAlert, uuid.UUID(str(payload["alert_id"])))
    if alert is None:
        return
    state = str(payload.get("state", "opened"))
    text = alert.summary if state == "opened" else f"Resolved: {alert.summary}"
    get_alert_sender().send(text=text, severity=alert.severity, state=state, key=alert.key)


def open_alerts(db: Session) -> list[OpsAlert]:
    return list(
        db.scalars(
            select(OpsAlert)
            .where(OpsAlert.resolved_at.is_(None))
            .order_by(OpsAlert.severity, OpsAlert.first_seen_at)
        )
    )


def recent_alerts(db: Session, *, limit: int) -> list[OpsAlert]:
    return list(db.scalars(select(OpsAlert).order_by(OpsAlert.first_seen_at.desc()).limit(limit)))
