"""The audit's BK-4 and BK-5 (D-105) against a real PostgreSQL 17 and MinIO:

- BK-4: a verified set calls the outside heartbeat; a failed one does not,
  and a heartbeat that fails never fails the backup.
- BK-5: the off-server drill restores with the secrets copy and a staff
  member signs in to the restored copy with their authenticator code; the
  secrets of another server are refused; a copy put in the backup bucket is
  locked and opens from there, even after it was overwritten.

The review notes RN-1, RN-4 and RN-5 are in test_backup_rn.py.
"""

# The shared fixtures are imported from test_backup_recovery; a test naming one
# as a parameter is not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.orm import Session as DbSession

from markx.backup import escrow
from markx.backup.__main__ import main as backup_main
from markx.backup.drill import (
    INJECTED_OTHER_SECRETS,
    SECRETS_SIGN_IN,
    SECRETS_TOTP,
    DrillSecrets,
)
from markx.backup.runner import run_backup
from markx.backup.staff_sign_in import StaffCredentials
from markx.core.config import get_config
from tests.factories import STAFF_PASSWORD, make_staff
from tests.storage.test_backup_recovery import (  # noqa: F401  (fixtures)
    Setup,
    _marketplace,
    _runs,
    backup_bucket,
    keys,
    setup,
    tools,
    users,
)
from tests.storage.test_backup_rn import (
    _environment,
    _key_files,
    _locked,
    _machine,
    _offsite,
    _overwrite,
)
from tests.storage.test_backup_trust import _record
from tests.unit.test_backup_d105 import _Monitor, monitor  # noqa: F401  (fixture)

STAFF_PHONE = "0911000777"


# -- BK-4: the outside heartbeat ------------------------------------------------------------------


def test_a_verified_set_calls_the_outside_heartbeat_and_a_failed_one_does_not(
    setup: Setup, db: DbSession, monitor: tuple[str, type[_Monitor]]
) -> None:
    url, handler = monitor
    config = setup.ctx.config.model_copy(update={"heartbeat_url": SecretStr(url)})
    ctx = replace(setup.ctx, config=config)
    assert run_backup(ctx).status == "succeeded"
    assert len(handler.calls) == 1
    assert _runs(db)[-1].details["heartbeat"] == "sent"
    broken = replace(ctx, config=config.model_copy(update={"pg_dump_command": "false"}))
    assert run_backup(broken).status == "failed"
    assert len(handler.calls) == 1  # no call: the monitor will alert
    handler.status = 500
    later = datetime.now(UTC) + timedelta(minutes=1)
    outcome = run_backup(replace(ctx, clock=lambda: later))
    assert outcome.status == "succeeded"  # the set is good; the monitor alerts if calls stop
    assert _runs(db)[-1].details["heartbeat"] == "failed:http_500"
    assert url not in json.dumps([r.details for r in _runs(db)])


# -- BK-5: the drill with the secrets copy ------------------------------------------------------


def _secrets_copy(setup: Setup, *, encryption_key: str | None = None) -> bytes:
    """This test server's secrets copy (the tests' own development keys)."""
    config = get_config()
    items = {
        "api.env": (f"MARKX_SECRET_KEY={config.secret_key}\n"
                    f"MARKX_ENCRYPTION_KEY={encryption_key or config.encryption_key}\n").encode(),
        "postgres.env": b"POSTGRES_PASSWORD=test-only\nMARKX_DB_MIGRATOR_PASSWORD=test-only\n"
                        b"MARKX_DB_APP_PASSWORD=test-only\nMARKX_DB_READONLY_PASSWORD=test-only\n",
    }  # fmt: skip
    return escrow.make_escrow(items, recipient=setup.keys.recovery.recipient,
                              signing=setup.keys.signing, environment="test",
                              release="test-release", now=datetime.now(UTC))  # fmt: skip


def test_the_off_server_drill_restores_with_the_secrets_copy_and_staff_sign_in_with_their_code(
    setup: Setup, db: DbSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = make_staff(db, STAFF_PHONE)  # its authenticator secret, encrypted in the database
    _marketplace(db)
    assert run_backup(setup.ctx).status == "succeeded"
    copy = tmp_path / "secrets.json"
    copy.write_bytes(_secrets_copy(setup))
    recovery, signer, _, _ = _key_files(setup, tmp_path / "keys")
    report = tmp_path / "drill.json"
    machine = _machine(setup, setup.users.reader, MARKX_DRILL_STAFF_PASSWORD=STAFF_PASSWORD,
                       MARKX_DRILL_STAFF_TOTP_SECRET=secret)  # fmt: skip
    with _environment(machine):
        code = backup_main(["drill", "--from-destination", "--recovery-key", str(recovery),
                            "--signer", str(signer), "--secrets", str(copy),
                            "--staff-phone", STAFF_PHONE, "--report", str(report)])  # fmt: skip
    said = capsys.readouterr().out
    assert code == 0, said
    assert "DRILL PASSED" in said
    data = json.loads(report.read_text())
    assert {r["name"]: r["ok"] for r in data["secrets"]} == {
        "the secrets copy opens with the recovery key and the server's signature": True,
        SECRETS_TOTP: True,
        SECRETS_SIGN_IN: True,
    }
    assert "signed in as staff (super_admin)" in said
    other = next(i for i in data["injections"] if i["name"] == INJECTED_OTHER_SECRETS)
    assert other["refused"] is True
    for value in (STAFF_PASSWORD, secret, get_config().encryption_key):
        assert value not in said
        assert value not in report.read_text()
    # The server accepts the report, secrets step included (RN-5 knows it).
    assert _record(setup, report) == 0
    row = _runs(db, "drill")[-1]
    assert (row.status, row.details["secrets_checked"]) == ("succeeded", True)


def test_the_secrets_of_another_server_fail_the_drill(setup: Setup, db: DbSession) -> None:
    secret = make_staff(db, STAFF_PHONE)
    assert run_backup(setup.ctx).status == "succeeded"
    wrong = Fernet.generate_key().decode()
    opened = escrow.open_escrow(_secrets_copy(setup, encryption_key=wrong), keys=setup.ring,
                                signers=setup.signers)  # fmt: skip
    staff = StaffCredentials(STAFF_PHONE, STAFF_PASSWORD, lambda: pyotp.TOTP(secret).now())
    result = _offsite(setup, secrets_=DrillSecrets(opened, staff))
    assert not result.passed
    checks = {name: (ok, detail) for name, ok, detail in result.secrets}
    assert checks[SECRETS_TOTP] == (False, "0 of 1 staff secrets")
    assert checks[SECRETS_SIGN_IN][0] is False
    assert "DRILL FAILED" in result.text()


def test_a_secrets_copy_in_the_backup_bucket_is_locked_and_opens_from_there(
    setup: Setup, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = _locked(setup)
    recovery, signer, public, signing = _key_files(s, tmp_path / "keys")
    settings = tmp_path / "etc"
    settings.mkdir()
    for name, data in escrow.open_escrow(_secrets_copy(s), keys=s.ring,
                                         signers=s.signers).items.items():  # fmt: skip
        (settings / name).write_bytes(data)
    server = _machine(s, s.users.writer, MARKX_BACKUP_PUBLIC_KEY_FILE=str(public),
                      MARKX_BACKUP_SIGNING_KEY_FILE=str(signing),
                      MARKX_BACKUP_REQUIRE_OBJECT_LOCK="1", MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS="1",
                      MARKX_BACKUP_WORK_DIR=str(tmp_path / "work"))  # fmt: skip
    with _environment(server):
        assert backup_main(["escrow-secrets", "--from-dir", str(settings), "--upload"]) == 0
    said = capsys.readouterr().out
    assert "uploaded to" in said
    (listed,) = list(s.reader.list("escrow/"))
    assert listed.key.startswith("escrow/markx-secrets-")
    head = s.reader.head(listed.key)
    assert head is not None
    assert head.locked_until is not None
    _overwrite(s, listed.key, b"garbage over the secrets copy")
    with _environment(_machine(s, s.users.reader)):
        code = backup_main(["open-secrets", "--from-destination", "--recovery-key", str(recovery),
                            "--signer", str(signer), "--check"])  # fmt: skip
    said = capsys.readouterr().out
    assert code == 0, said
    assert "signature and contents verified" in said
    assert "api.env" in said
