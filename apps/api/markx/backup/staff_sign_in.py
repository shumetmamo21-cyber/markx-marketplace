"""The drill's last step with the secrets copy (BK-5, D-105): a staff member
signs in to the RESTORED copy, with the COPIED keys, using their password
and the code their authenticator app shows.

The real API is started as a separate process on this recovery machine,
listening on 127.0.0.1 only, against the restored database (logged in as
`markx_app`), with `MARKX_SECRET_KEY` and `MARKX_ENCRYPTION_KEY` from the
copy and nothing else from the server. The sign-in goes through the same
route a browser uses (`POST /api/v1/auth/staff/sign-in`). If the copied
encryption key is not the one the staff secrets were encrypted with, the
code cannot be checked and the sign-in is refused: that is what this proves.

The keys, the password and the code travel to the child process in its
environment only, never as an argument, a log line or a file. The API runs
with `MARKX_ENV=local`: fakes for SMS and the bot check, no Telegram, no
storage provider, so it contacts nothing. It is stopped at once afterwards.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from markx.backup.database import PgServer

START_TIMEOUT_SECONDS = 90
_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "VIRTUAL_ENV")


@dataclass(frozen=True, slots=True)
class StaffCredentials:
    phone: str
    password: str
    # Asked for at the moment of the sign-in, not before: an authenticator
    # code changes every 30 seconds and a restore takes longer.
    code: Callable[[], str]

    def __repr__(self) -> str:
        return "StaffCredentials(phone=***, password=***, code=***)"


def database_url(server: PgServer, database: str) -> str:
    user = urllib.parse.quote(server.user or "markx_app", safe="")
    password = urllib.parse.quote(server.password or "", safe="")
    host = server.host or "127.0.0.1"
    port = server.port or "5432"
    if host.startswith("/"):  # a Unix socket folder (the recovery container)
        query = urllib.parse.urlencode({"host": host, "port": port})
        return f"postgresql+psycopg://{user}:{password}@/{database}?{query}"
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _post(url: str, body: dict[str, str]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(  # noqa: S310  (127.0.0.1, our own child)
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-MarkX-Client": "recovery-drill"},
    )  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def _alive(base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/api/v1/healthz/live", timeout=2) as answer:  # noqa: S310
            return bool(answer.status == 200)
    except OSError:
        return False


def sign_in_on_restored(
    *, app_server: PgServer, database: str, secret_key: str, encryption_key: str,
    credentials: StaffCredentials,
) -> tuple[bool, str]:  # fmt: skip
    """(signed in as staff, what happened in words, without any secret)."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    storage = tempfile.mkdtemp(prefix="markx-drill-api-")
    env = {k: v for k, v in os.environ.items() if k in _KEEP}
    env.update({
        "MARKX_ENV": "local", "MARKX_LOG_LEVEL": "WARNING", "MARKX_PUBLIC_ORIGIN": base,
        "MARKX_DATABASE_URL": database_url(app_server, database),
        "MARKX_MIGRATION_DATABASE_URL": database_url(app_server, database),
        "MARKX_SECRET_KEY": secret_key, "MARKX_ENCRYPTION_KEY": encryption_key,
        "MARKX_SMS_PROVIDER": "fake", "MARKX_STORAGE_DIR": storage,
    })  # fmt: skip
    child = subprocess.Popen(  # noqa: S603  (our own interpreter, fixed arguments)
        [sys.executable, "-m", "uvicorn", "markx.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning", "--no-access-log"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not _alive(base):
            if child.poll() is not None or time.monotonic() > deadline:
                return False, "the API did not start against the restored copy"
            time.sleep(0.5)
        try:
            code = credentials.code()
        except (EOFError, KeyboardInterrupt, OSError):
            return False, "no authenticator code was given"
        status, answer = _post(
            f"{base}/api/v1/auth/staff/sign-in",
            {"phone": credentials.phone, "password": credentials.password, "totp_code": code},
        )  # fmt: skip
        me = answer.get("me") if isinstance(answer, dict) else None
        if status == 200 and isinstance(me, dict) and me.get("session_kind") == "staff":
            staff = me.get("staff")
            role = staff.get("role") if isinstance(staff, dict) else None
            return True, f"signed in as staff ({role}) through POST /api/v1/auth/staff/sign-in"
        error = answer.get("error") if isinstance(answer, dict) else None
        error_code = error.get("code") if isinstance(error, dict) else None
        return False, f"the sign-in was refused (HTTP {status}, {error_code or 'no error code'})"
    finally:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=20)
        if child.stderr is not None:
            child.stderr.close()
        with contextlib.suppress(OSError):
            import shutil

            shutil.rmtree(storage, ignore_errors=True)
