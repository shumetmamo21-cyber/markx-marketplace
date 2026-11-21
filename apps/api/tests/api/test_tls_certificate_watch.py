"""The site's certificate can never expire silently (D-103; audit of
19 November 2026, section 13: "certificates will silently expire").

Renewal runs on the host (`deploy.sh certificate renew`, on a timer). The
worker's watch does not trust it: it reads the date the proxy's certificate
really expires and alerts before it does, through the same alert channel as
every other operations alert (the founder's Telegram group, or the log).
The certificates here are made on the spot; nothing is contacted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.core.config import get_config
from markx.notifications.models import Outbox
from markx.ops import checks
from markx.ops import service as ops
from markx.ops.models import OpsAlert

NOW = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)


def _certificate(path: Path, expires: datetime, *, chain: bool = True) -> Path:
    """fullchain.pem as a certificate tool writes it: the site's own
    certificate first, then (here) a second one standing in for the chain."""
    blocks = []
    for name, not_after in (
        ("markx.example.invalid", expires),
        ("chain", NOW + timedelta(days=900)),
    ):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(min(NOW, not_after) - timedelta(days=60))
            .not_valid_after(not_after)
            .sign(key, hashes.SHA256())
        )
        blocks.append(cert.public_bytes(serialization.Encoding.PEM))
        if not chain:
            break
    path.write_bytes(b"".join(blocks))
    return path


@pytest.fixture
def certificate_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The watch configured as the production Compose file configures the
    worker (MARKX_TLS_CERTIFICATE_FILE), with the default warning time."""
    path = tmp_path / "fullchain.pem"
    config = get_config().model_copy(update={"tls_certificate_file": path})
    monkeypatch.setattr(checks, "get_config", lambda: config)
    return path


def _findings() -> list[checks.Finding]:
    return checks.tls_certificate(None, NOW)  # type: ignore[arg-type]


def test_nothing_is_checked_where_no_certificate_is_configured() -> None:
    assert get_config().tls_certificate_file is None  # a laptop and the tests
    assert _findings() == []
    assert checks.tls_certificate in checks.WATCH


def test_a_certificate_with_time_left_raises_nothing(certificate_file: Path) -> None:
    _certificate(certificate_file, NOW + timedelta(days=60))
    assert _findings() == []
    # One day more than the warning time: still quiet.
    _certificate(certificate_file, NOW + timedelta(days=22))
    assert _findings() == []


def test_three_weeks_before_expiry_it_warns_and_names_the_date(certificate_file: Path) -> None:
    _certificate(certificate_file, NOW + timedelta(days=20, hours=1))
    (finding,) = _findings()
    assert finding.key == "tls.certificate_expiring"
    assert finding.severity == "warning"
    assert "2026-12-11" in finding.summary
    assert "20 day(s) left" in finding.summary
    assert finding.details == {"expires_at": "2026-12-11T10:00:00+00:00", "days_left": 20}


def test_the_last_week_is_critical_and_an_expired_certificate_says_so(
    certificate_file: Path,
) -> None:
    _certificate(certificate_file, NOW + timedelta(days=6))
    (finding,) = _findings()
    assert (finding.key, finding.severity) == ("tls.certificate_expiring", "critical")
    _certificate(certificate_file, NOW - timedelta(hours=1))
    (finding,) = _findings()
    assert finding.severity == "critical"
    assert "EXPIRED" in finding.summary
    assert finding.details["days_left"] == -1


def test_the_site_certificate_is_the_first_of_the_chain(certificate_file: Path) -> None:
    """The chain's other certificates live longer; only the first counts."""
    _certificate(certificate_file, NOW + timedelta(days=3))
    assert [f.severity for f in _findings()] == ["critical"]


def test_a_missing_or_broken_certificate_is_critical(certificate_file: Path) -> None:
    (finding,) = _findings()  # not there at all
    assert (finding.key, finding.severity) == ("tls.certificate_unreadable", "critical")
    assert finding.details == {"reason": "FileNotFoundError"}
    certificate_file.write_text("not a certificate")
    (finding,) = _findings()
    assert finding.key == "tls.certificate_unreadable"
    assert finding.details == {"reason": "ValueError"}


def test_the_watch_alerts_once_escalates_and_reports_the_renewal(
    certificate_file: Path, db: DbSession
) -> None:
    """Through the scheduled watch: one alert when the warning time starts,
    sent again only when it turns critical, and resolved once a renewed
    certificate is in place (the file replaced, as the install step does)."""

    def tls_alerts(now: datetime) -> tuple[list[OpsAlert], list[str]]:
        ops.watch(db, now)
        db.commit()
        db.expire_all()
        alerts = list(
            db.scalars(select(OpsAlert).where(OpsAlert.key.like("tls.%")).order_by(OpsAlert.id))
        )
        states = [
            row.payload["state"]
            for row in db.scalars(
                select(Outbox).where(Outbox.topic == ops.TOPIC_ALERT).order_by(Outbox.id)
            )
            if row.payload["alert_id"] in {str(a.id) for a in alerts}
        ]
        return alerts, states

    _certificate(certificate_file, NOW + timedelta(days=15))
    alerts, states = tls_alerts(NOW)
    assert [(a.severity, a.resolved_at) for a in alerts] == [("warning", None)]
    assert states == ["opened"]

    alerts, states = tls_alerts(NOW + timedelta(minutes=5))
    assert states == ["opened"], "no second message while nothing changed"

    alerts, states = tls_alerts(NOW + timedelta(days=9))
    assert [a.severity for a in alerts] == ["critical"]
    assert states == ["opened", "opened"], "told again when it became critical"

    _certificate(certificate_file, NOW + timedelta(days=90))
    later = NOW + timedelta(days=9, minutes=5)
    alerts, states = tls_alerts(later)
    assert [a.resolved_at for a in alerts] == [later]
    assert states == ["opened", "opened", "resolved"]
