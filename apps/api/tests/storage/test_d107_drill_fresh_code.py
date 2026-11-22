"""D-107: the off-server drill's stand-in authenticator never replays a code.

CI's off-server drill failed once on pull request #15 (CI run on 9869524):
every restore check passed, then the staff sign-in to the restored copy was
refused (HTTP 401, staff_credentials_invalid). The demo data signs its staff
member in with a code, so the database remembers that 30-second step
(`totp_last_step`, the replay guard); the backup made seconds later carries
it; the drill's stand-in then took the code of the same step, which the API
rightly refuses as a replay. Whether it failed depended on where the
30-second boundary fell. This reproduces it: a sign-in, a backup and the
drill inside one step.
"""

# ruff: noqa: F811

from __future__ import annotations

import time
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffMember
from markx.backup.__main__ import fresh_code
from markx.backup.__main__ import main as backup_main
from markx.backup.runner import run_backup
from tests.conftest import ApiClient
from tests.factories import STAFF_PASSWORD, make_staff
from tests.storage.test_backup_d105 import _secrets_copy
from tests.storage.test_backup_recovery import (  # noqa: F401  (fixtures)
    Setup,
    _marketplace,
    backup_bucket,
    keys,
    setup,
    tools,
    users,
)
from tests.storage.test_backup_rn import _environment, _key_files, _machine

STAFF_PHONE = "0911000778"


def test_the_stand_in_code_is_from_a_step_after_the_call() -> None:
    totp = pyotp.TOTP(pyotp.random_base32())
    now = [1_800_000_007.0]  # 7 seconds into a 30-second step
    waited: list[float] = []

    def sleep(seconds: float) -> None:
        waited.append(seconds)
        now[0] += seconds

    code = fresh_code(totp, clock=lambda: now[0], sleep=sleep)
    assert waited == [24.0]  # to one second into the next step
    assert code == totp.at(1_800_000_031)


def test_a_drill_right_after_a_sign_in_still_signs_the_staff_member_in(
    setup: Setup, db: DbSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Start early in a step, so the sign-in, the backup and the drill's own
    # sign-in all fall inside it, as in the failed CI run.
    time.sleep(30 - (time.time() % 30) + 0.5)
    secret = make_staff(db, STAFF_PHONE)
    signed_in = ApiClient().post(
        "/auth/staff/sign-in",
        json={
            "phone": STAFF_PHONE,
            "password": STAFF_PASSWORD,
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )  # as the demo data does: the database now remembers this step
    assert signed_in.status_code == 200, signed_in.text
    db.expire_all()
    assert db.scalar(select(StaffMember.totp_last_step)) is not None
    _marketplace(db)
    assert run_backup(setup.ctx).status == "succeeded"
    copy = tmp_path / "secrets.json"
    copy.write_bytes(_secrets_copy(setup))
    recovery, signer, _, _ = _key_files(setup, tmp_path / "keys")
    machine = _machine(setup, setup.users.reader, MARKX_DRILL_STAFF_PASSWORD=STAFF_PASSWORD,
                       MARKX_DRILL_STAFF_TOTP_SECRET=secret)  # fmt: skip
    with _environment(machine):
        code = backup_main(["drill", "--from-destination", "--recovery-key", str(recovery),
                            "--signer", str(signer), "--secrets", str(copy),
                            "--staff-phone", STAFF_PHONE])  # fmt: skip
    said = capsys.readouterr().out
    assert code == 0, said
    assert "signed in as staff (super_admin)" in said
