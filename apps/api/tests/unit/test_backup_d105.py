"""D-105 without a database or MinIO: the secrets copy (BK-5), the outside
heartbeat and the test alert (BK-4), the drill report check (RN-5) and the
socket path check (RN-4). The end-to-end proofs with PostgreSQL and MinIO are
in tests/storage/test_backup_d105.py."""

from __future__ import annotations

import base64
import http.server
import io
import json
import tarfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from markx.backup import __main__ as cli
from markx.backup import crypto, escrow, heartbeat
from markx.backup.config import BackupConfig
from markx.backup.database import PgServer
from markx.backup.drill import (
    ALWAYS_INJECTED,
    INJECTED_BLOB,
    INJECTED_OTHER_SECRETS,
    report_problems,
    socket_problem,
)
from tests.unit.test_backup_commands import REAL

# Test-only values, nobody's secrets.
SECRET_KEY = "test-only-secret-key-for-the-escrow-tests-0123456789"
ENCRYPTION_KEY = Fernet.generate_key().decode()
DB_PASSWORDS = {
    "POSTGRES_PASSWORD": "test-only-superuser-password",
    "MARKX_DB_MIGRATOR_PASSWORD": "test-only-migrator-password",
    "MARKX_DB_APP_PASSWORD": "test-only-app-password",
    "MARKX_DB_READONLY_PASSWORD": "test-only-readonly-password",
}
PRIVATE_KEY_PEM = (
    b"-----BEGIN PRIVATE KEY-----\ntest-only-not-a-real-key\n-----END PRIVATE KEY-----\n"
)


def _settings(folder: Path, *, tls: bool = True) -> tuple[Path, Path]:
    settings, certs = folder / "etc", folder / "tls"
    settings.mkdir()
    certs.mkdir()
    (settings / "api.env").write_text(
        f"MARKX_SECRET_KEY={SECRET_KEY}\nMARKX_ENCRYPTION_KEY='{ENCRYPTION_KEY}'\n"
    )
    (settings / "postgres.env").write_text("".join(f"{k}={v}\n" for k, v in DB_PASSWORDS.items()))
    (settings / "backup.env").write_text("PGPASSWORD=test-only-migrator-password\n")
    if tls:
        (certs / "privkey.pem").write_bytes(PRIVATE_KEY_PEM)
        (certs / "fullchain.pem").write_text("-----BEGIN CERTIFICATE-----\nx\n")
    return settings, certs


@pytest.fixture
def keys() -> crypto.GeneratedKeys:
    return crypto.generate_keys()


def _make(items: dict[str, bytes], keys: crypto.GeneratedKeys) -> bytes:
    return escrow.make_escrow(items, recipient=keys.recovery.recipient, signing=keys.signing,
                              environment="production", release="abc1234",
                              now=datetime.now(UTC))  # fmt: skip


def _ring(keys: crypto.GeneratedKeys) -> dict[str, crypto.RecoveryKey]:
    return {keys.recovery.key_id: keys.recovery}


# -- BK-5: the secrets copy ------------------------------------------------------------------


def test_the_secrets_copy_holds_every_secret_encrypted_and_never_in_plain_form(
    tmp_path: Path, keys: crypto.GeneratedKeys
) -> None:
    settings, certs = _settings(tmp_path)
    items = escrow.collect_from_folders(settings, certs)
    assert sorted(items) == ["api.env", "backup.env", "postgres.env", "tls/fullchain.pem",
                             "tls/privkey.pem"]  # fmt: skip
    data = _make(items, keys)
    envelope = json.loads(data)
    sealed = base64.b64decode(envelope["ciphertext"])
    for secret in (SECRET_KEY, ENCRYPTION_KEY, *DB_PASSWORDS.values(), "test-only-not-a-real-key"):
        assert secret.encode() not in data
        assert secret.encode() not in sealed
        assert base64.b64encode(secret.encode())[:12] not in data
    # Only names and sizes are readable, and the whole envelope is signed.
    assert {i["name"] for i in envelope["items"]} == set(items)
    assert envelope["recipient_key_id"] == keys.recovery.key_id
    opened = escrow.open_escrow(data, keys=_ring(keys), signers=[keys.signing.signer])
    assert opened.items == items
    assert opened.value("api.env", "MARKX_ENCRYPTION_KEY") == ENCRYPTION_KEY
    assert opened.value("api.env", "MARKX_SECRET_KEY") == SECRET_KEY
    assert "test-only" not in repr(opened)


def test_a_secrets_copy_opens_only_with_the_recovery_key_and_only_unaltered(
    tmp_path: Path, keys: crypto.GeneratedKeys
) -> None:
    data = _make(escrow.collect_from_folders(*_settings(tmp_path)), keys)
    other = crypto.generate_keys()
    with pytest.raises(escrow.EscrowRefused, match="does_not_decrypt"):
        escrow.open_escrow(data, keys=_ring(other), signers=[keys.signing.signer])
    with pytest.raises(escrow.EscrowRefused, match="signature"):
        escrow.open_escrow(data, keys=_ring(keys), signers=[other.signing.signer])
    envelope = json.loads(data)
    edited = {**envelope, "environment": "staging"}
    with pytest.raises(escrow.EscrowRefused, match="signature"):
        escrow.open_escrow(json.dumps(edited).encode(), keys=_ring(keys),
                           signers=[keys.signing.signer])  # fmt: skip
    # A copy encrypted by anyone with the public key, but not signed by the server.
    forged = crypto.sign_document(
        {**{k: v for k, v in envelope.items() if k not in ("signature", "signer_key_id")}},
        other.signing,
    )
    with pytest.raises(escrow.EscrowRefused, match="signature"):
        escrow.open_escrow(json.dumps(forged).encode(), keys=_ring(keys),
                           signers=[keys.signing.signer])  # fmt: skip
    with pytest.raises(escrow.EscrowRefused):
        escrow.open_escrow(b"not json", keys=_ring(keys), signers=[keys.signing.signer])


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda s: (s / "api.env").unlink(), "api.env is missing"),
        (lambda s: (s / "postgres.env").write_text("POSTGRES_PASSWORD=x\n"),
         "postgres.env has no MARKX_DB_APP_PASSWORD"),
        (lambda s: (s / "api.env").write_text(
            "MARKX_SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET\nMARKX_ENCRYPTION_KEY=x\n"),
         "example value of MARKX_SECRET_KEY"),
        (lambda s: (s / "backup.env").write_text(f"{crypto.RECOVERY_PRIVATE}\nabc\n"),
         "holds a recovery key"),
    ],
)  # fmt: skip
def test_no_copy_is_made_without_the_secrets_a_recovery_needs(
    tmp_path: Path, keys: crypto.GeneratedKeys, change: Any, reason: str
) -> None:
    settings, certs = _settings(tmp_path)
    change(settings)
    with pytest.raises(escrow.EscrowRefused, match=reason):
        _make(escrow.collect_from_folders(settings, certs), keys)


def test_the_tar_stream_from_deploy_sh_holds_known_regular_files_only(
    tmp_path: Path, keys: crypto.GeneratedKeys
) -> None:
    def tar(members: dict[str, bytes], link: str | None = None) -> io.BytesIO:
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if link:
                info = tarfile.TarInfo(link)
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/shadow"
                archive.addfile(info)
        out.seek(0)
        return out

    settings, certs = _settings(tmp_path)
    good = escrow.collect_from_folders(settings, certs)
    assert escrow.collect_from_tar(tar(good)) == good
    with pytest.raises(escrow.EscrowRefused, match="unexpected_file"):
        escrow.collect_from_tar(tar({**good, "../../etc/passwd": b"x"}))
    with pytest.raises(escrow.EscrowRefused, match="not_a_regular_file"):
        escrow.collect_from_tar(tar({}, link="web.env"))
    link = settings / "web.env"
    link.symlink_to("/etc/hostname")
    with pytest.raises(escrow.EscrowRefused, match="not_a_regular_file"):
        escrow.collect_from_folders(settings, certs)


def _cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, keys: crypto.GeneratedKeys) -> Path:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    crypto.write_key_file(key_dir / "backup-public.key",
                          crypto.encode_recipient(keys.recovery.recipient), secret=False)  # fmt: skip
    crypto.write_key_file(key_dir / "signing.key", crypto.encode_signing(keys.signing), secret=True)
    crypto.write_key_file(key_dir / "recovery.key", crypto.encode_recovery(keys.recovery),
                          secret=True)  # fmt: skip
    crypto.write_key_file(key_dir / "signer.key", crypto.encode_signer(keys.signing.signer),
                          secret=False)  # fmt: skip
    monkeypatch.setenv("MARKX_ENV", "local")
    monkeypatch.setenv("MARKX_BACKUP_PUBLIC_KEY_FILE", str(key_dir / "backup-public.key"))
    monkeypatch.setenv("MARKX_BACKUP_SIGNING_KEY_FILE", str(key_dir / "signing.key"))
    monkeypatch.setenv("MARKX_BACKUP_WORK_DIR", str(tmp_path / "work"))
    return key_dir


def test_the_commands_make_and_open_a_copy_and_print_no_secret(
    tmp_path: Path, keys: crypto.GeneratedKeys, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    key_dir = _cli_env(monkeypatch, tmp_path, keys)
    settings, certs = _settings(tmp_path)
    out = tmp_path / "copies"
    assert cli.main(["escrow-secrets", "--from-dir", str(settings), "--tls-dir", str(certs),
                     "--out-dir", str(out)]) == 0  # fmt: skip
    printed = capsys.readouterr().out
    (made,) = list(out.iterdir())
    assert escrow.ESCROW_NAME.fullmatch(made.name)
    assert made.stat().st_mode & 0o777 == 0o600
    assert "api.env" in printed
    assert "tls/privkey.pem" in printed
    for secret in (SECRET_KEY, ENCRYPTION_KEY, *DB_PASSWORDS.values()):
        assert secret not in printed
        assert secret.encode() not in made.read_bytes()
    common = [
        "--recovery-key",
        str(key_dir / "recovery.key"),
        "--signer",
        str(key_dir / "signer.key"),
    ]
    assert cli.main(["open-secrets", "--file", str(made), *common, "--check"]) == 0
    checked = capsys.readouterr().out
    assert "signature and contents verified" in checked
    assert SECRET_KEY not in checked
    target = tmp_path / "restored-secrets"
    assert cli.main(["open-secrets", "--file", str(made), *common, "--out", str(target)]) == 0
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / "api.env").read_text() == (settings / "api.env").read_text()
    assert (target / "tls" / "privkey.pem").read_bytes() == PRIVATE_KEY_PEM
    assert all(p.stat().st_mode & 0o077 == 0 for p in target.rglob("*"))
    # Never over a folder that holds anything.
    assert cli.main(["open-secrets", "--file", str(made), *common, "--out", str(target)]) != 0


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_secrets_copy_is_never_opened_on_a_server(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: str
) -> None:
    for name, value in REAL.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MARKX_ENV", env)
    argv = ["open-secrets", "--from-destination", "--recovery-key", "r", "--signer", "s", "--check"]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert f"never runs on {env}" in capsys.readouterr().err


def test_another_servers_key_opens_none_of_the_staff_secrets() -> None:
    key = Fernet.generate_key().decode()
    tokens = [Fernet(key.encode()).encrypt(b"JBSWY3DPEHPK3PXP") for _ in range(3)]
    assert escrow.decrypts_with(key, tokens) == (3, 3)
    assert escrow.decrypts_with(Fernet.generate_key().decode(), tokens) == (0, 3)
    assert escrow.decrypts_with("not a key", tokens) == (0, 3)


# -- BK-4: the outside heartbeat ---------------------------------------------------------------


class _Monitor(http.server.BaseHTTPRequestHandler):
    calls: list[str] = []  # noqa: RUF012
    status = 200

    def do_GET(self) -> None:
        type(self).calls.append(self.path)
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *_: Any) -> None:
        return


@pytest.fixture
def monitor() -> Iterator[tuple[str, type[_Monitor]]]:
    """A stand-in for the outside monitor, on this machine only."""
    handler = type("Monitor", (_Monitor,), {"calls": [], "status": 200})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/ping/test-only-token", handler
    finally:
        server.shutdown()
        server.server_close()


def test_the_heartbeat_calls_the_monitor_and_never_shows_its_address(
    monitor: tuple[str, type[_Monitor]], caplog: pytest.LogCaptureFixture
) -> None:
    url, handler = monitor
    assert heartbeat.ping(url, timeout=5) == "sent"
    assert handler.calls == ["/ping/test-only-token"]
    handler.status = 500
    assert heartbeat.ping(url, timeout=5) == "failed:http_500"
    assert heartbeat.ping(None, timeout=5) == "off"
    assert "test-only-token" not in caplog.text
    assert heartbeat.ping("http://127.0.0.1:9/x", timeout=2).startswith("failed:")


def test_the_heartbeat_address_is_checked_and_https_on_a_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert BackupConfig(heartbeat_url="http://127.0.0.1:8/x").heartbeat == "http://127.0.0.1:8/x"
    with pytest.raises(ValidationError, match="no user name or password"):
        BackupConfig(heartbeat_url="https://user:pw@hc.example.invalid/x")
    with pytest.raises(ValidationError, match="plain http"):
        BackupConfig(heartbeat_url="ftp://hc.example.invalid/x")
    real = {k.removeprefix("MARKX_BACKUP_").lower(): v for k, v in REAL.items()
            if k.startswith("MARKX_BACKUP_")}  # fmt: skip
    with pytest.raises(ValidationError, match="must be https"):
        BackupConfig(env="production", release="r", heartbeat_url="http://hc.example.invalid/x",
                     **real)  # fmt: skip
    ok = BackupConfig(env="production", release="r",
                      heartbeat_url="https://hc.example.invalid/x", **real)  # fmt: skip
    assert "hc.example.invalid" not in repr(ok)


def test_the_heartbeat_command_says_whether_it_is_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    monitor: tuple[str, type[_Monitor]],
) -> None:  # fmt: skip
    monkeypatch.setenv("MARKX_ENV", "local")
    assert cli.main(["heartbeat"]) == 0
    assert "OFF" in capsys.readouterr().out
    assert cli.main(["heartbeat", "--send"]) == cli.EXIT_FAILED
    url, handler = monitor
    monkeypatch.setenv("MARKX_BACKUP_HEARTBEAT_URL", url)
    assert cli.main(["heartbeat", "--send"]) == 0
    said = capsys.readouterr().out
    assert "on, after each verified set, to 127.0.0.1" in said
    assert "test-only-token" not in said
    assert handler.calls == ["/ping/test-only-token"]


# -- BK-4: the test alert and the alerts that do not need the database --------------------------


def test_the_test_alert_reaches_the_telegram_group_or_says_nobody_was_told(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from markx.core.config import get_config
    from markx.ops import alerts, notify

    sent: list[str] = []

    class Answer:
        status = 200

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(request: Any, timeout: float) -> Answer:
        sent.append(request.data.decode())
        return Answer()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    off = get_config().model_copy(update={"alert_telegram_chat_id": None})
    monkeypatch.setattr(alerts, "get_config", lambda: off)
    monkeypatch.setattr(notify, "get_config", lambda: off)
    assert notify.main(["test"]) == notify.EXIT_NOT_DELIVERED
    assert "NOT DELIVERED TO ANY PERSON" in capsys.readouterr().out
    assert sent == []
    on = off.model_copy(update={"alert_telegram_chat_id": "-1001"})
    monkeypatch.setattr(alerts, "get_config", lambda: on)
    monkeypatch.setattr(notify, "get_config", lambda: on)
    assert notify.main(["test"]) == 0
    assert "delivered to the staff Telegram alert group" in capsys.readouterr().out
    assert "TEST+ALERT" in sent[-1]
    assert "chat_id=-1001" in sent[-1]
    assert notify.main(["send", "--key", "container.worker", "--text",
                        "The worker container has been unhealthy for 15 minutes."]) == 0  # fmt: skip
    assert "unhealthy+for+15+minutes" in sent[-1]
    assert "ALERT" in sent[-1]
    assert notify.main(["send", "--key", "container.worker", "--state", "resolved",
                        "--text", "The worker container is running again."]) == 0  # fmt: skip
    assert "RESOLVED" in sent[-1]
    assert "Resolved%3A" in sent[-1]

    def refused(request: Any, timeout: float) -> Answer:
        raise OSError("network unreachable")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", refused)
    assert notify.main(["test"]) == notify.EXIT_NOT_DELIVERED
    assert "NOT DELIVERED" in capsys.readouterr().out


# -- RN-5: a drill report counts only when its contents show a passed drill ---------------------


def _manifest() -> dict[str, Any]:
    return {"created_at": "2026-11-20T23:00:00+00:00",
            "database": {"name": "markx", "rows": 120},
            "files": {"object_count": 4, "blob_count": 4}}  # fmt: skip


def _passing_report() -> dict[str, Any]:
    names = [
        "manifest signed by a trusted key",
        "set complete",
        "database dump intact and decryptable",
        "file index intact",
        "every file's blob present with its recorded size",
        "target database is new",
        "database restored in one transaction, as the owner role (not a superuser)",
        "every file restored, read back and matched its checksum",
        "migration version",
        "every table's row count equals the snapshot's",
        "indexes valid and constraints validated",
        "audit log still protected from the application role",
        "no unclassified file references",
        "every file the database refers to resolves to a restored file",
    ]
    checks = [{"name": n, "ok": True, "detail": ""} for n in names]
    checks[9]["detail"] = "40 tables, 120 rows"
    return {
        "passed": True, "backup_id": "20261120T230000Z-0123abcd", "kind": "offsite",
        "restore": {"backup_id": "20261120T230000Z-0123abcd", "passed": True, "checks": checks,
                    "facts": {"source": {"created_at": "2026-11-20T23:00:00+00:00",
                                         "database": "markx"},
                              "restored_files": {"private": 3, "public": 1}}},
        "injections": [{"name": n, "refused": True, "detail": ""}
                       for n in (*ALWAYS_INJECTED, INJECTED_BLOB)],
    }  # fmt: skip


def test_a_full_drill_report_passes() -> None:
    assert report_problems(_passing_report(), _manifest()) == []


@pytest.mark.parametrize(
    ("tamper", "says"),
    [
        (lambda r: r["restore"]["checks"][3].update(ok=False), "failed checks"),
        (lambda r: r["restore"].update(checks=[]), "no check"),
        (lambda r: r.update(restore=None), "no restore"),
        (lambda r: r.update(injections=[]), "injected faults not tried"),
        (lambda r: r["injections"][0].update(refused=False), "NOT refused"),
        (lambda r: r["restore"]["facts"]["restored_files"].update(public=0), "3 files restored"),
        (lambda r: r["restore"]["checks"][9].update(detail="40 tables, 12 rows"), "row count"),
        (lambda r: r["restore"]["facts"]["source"].update(created_at="2026-01-01T00:00:00+00:00"),
         "time is not the set's"),
        (lambda r: r["restore"].update(backup_id="20261101T000000Z-00000000"), "another set"),
        (lambda r: r.update(secrets=[{"name": "x", "ok": False}],
                            injections=[*r["injections"],
                                        {"name": INJECTED_OTHER_SECRETS, "refused": True}]),
         "secrets step failed"),
        (lambda r: r.update(secrets=[{"name": "x", "ok": True}]), INJECTED_OTHER_SECRETS),
    ],
)  # fmt: skip
def test_a_report_that_says_passed_without_showing_it_is_not_a_pass(tamper: Any, says: str) -> None:
    report = _passing_report()
    tamper(report)
    problems = report_problems(report, _manifest())
    assert problems, "a tampered report must not count as a passed drill"
    assert problems[0].startswith("the report says PASSED, but")
    assert any(says in p for p in problems), problems


def test_a_set_without_files_needs_no_blob_fault_and_a_failed_report_stays_failed() -> None:
    manifest = {**_manifest(), "files": {"object_count": 0, "blob_count": 0}}
    report = _passing_report()
    report["injections"] = [i for i in report["injections"] if i["name"] != INJECTED_BLOB]
    report["restore"]["facts"]["restored_files"] = {"private": 0, "public": 0}
    assert report_problems(report, manifest) == []
    report["passed"] = False
    assert report_problems(report, manifest) == ["the report says FAILED"]


# -- RN-4: a socket path too long for Linux -------------------------------------------------------


def test_a_socket_path_longer_than_107_bytes_is_named_as_the_problem() -> None:
    assert socket_problem(PgServer("127.0.0.1", "5432", "postgres", None)) is None
    assert socket_problem(PgServer("/tmp/markx-recovery-socket/run", "5432", "p", None)) is None  # noqa: S108
    folder = "/tmp/" + "x" * 90  # noqa: S108  (only measured)
    problem = socket_problem(PgServer(folder, "5432", "postgres", None))
    assert problem is not None
    assert "at most 107" in problem
    assert "MARKX_RECOVERY_SOCKET_DIR" in problem
