"""pg_dump and pg_restore for backups and restores (D-094).

**No secret on a command line.** The connection travels in the PG*
environment variables of the child process only (PGPASSWORD, or a
PGPASSFILE), never as an argument, so it never shows in `ps`, in a log or
in an error. The child gets no MARKX_* or AWS_* variable at all.

**Consistency.** The backup opens a REPEATABLE READ transaction, exports its
snapshot, and runs `pg_dump --snapshot` on it: the dump, the row counts and
the file references are all read from the same instant.

**A dump is accepted only when** pg_dump exited 0, wrote something that
begins like a custom-format archive, and `pg_restore --list` read its table
of contents and found every table the snapshot holds, alembic_version's
data among them. The plaintext is streamed: to the encryption, which writes
only ciphertext to disk, and to `pg_restore --list`. It is never written to
disk in the clear.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import psycopg

from markx.backup.crypto import Encryptor, RecipientKey, StreamDigest

_READ = 1024 * 1024
_SAFE_DB = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_FORWARDED_PREFIXES = ("MARKX_", "AWS_")


class DumpFailed(Exception):
    """The dump cannot be trusted; `reason` names why, without any secret."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RestoreFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def checked_database_name(name: str) -> str:
    if not _SAFE_DB.fullmatch(name):
        raise ValueError(f"unsafe database name: {name!r}")
    return name


@dataclass(frozen=True, slots=True)
class PgServer:
    """How to reach one PostgreSQL server. `password` may be None when a
    PGPASSFILE (or ~/.pgpass) holds it."""

    host: str | None
    port: str | None
    user: str | None
    password: str | None

    @classmethod
    def from_environment(cls) -> PgServer:
        return cls(
            host=os.environ.get("PGHOST"),
            port=os.environ.get("PGPORT"),
            user=os.environ.get("PGUSER"),
            password=os.environ.get("PGPASSWORD"),
        )

    def __repr__(self) -> str:
        return f"PgServer(host={self.host!r}, port={self.port!r}, user={self.user!r}, password=***)"

    def child_environment(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(_FORWARDED_PREFIXES)}
        for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
            env.pop(name, None)
        for name, value in (
            ("PGHOST", self.host), ("PGPORT", self.port), ("PGUSER", self.user),
            ("PGPASSWORD", self.password),
        ):  # fmt: skip
            if value:
                env[name] = value
        return env

    def connect(self, dbname: str, **kwargs: Any) -> psycopg.Connection[Any]:
        params: dict[str, Any] = {"dbname": checked_database_name(dbname)}
        for name, value in (
            ("host", self.host), ("port", self.port), ("user", self.user),
            ("password", self.password),
        ):  # fmt: skip
            if value:
                params[name] = value
        return psycopg.connect(**params, **kwargs)


@dataclass(frozen=True, slots=True)
class DumpResult:
    digest: StreamDigest
    tables_in_archive: int
    pg_dump_version: str


def _command(command: str) -> list[str]:
    return shlex.split(command)


def tool_version(command: str, server: PgServer) -> str:
    result = subprocess.run(  # noqa: S603  (operator-configured command, argv list)
        [*_command(command), "--version"],
        capture_output=True, text=True, timeout=120, env=server.child_environment(), check=False,
    )  # fmt: skip
    return result.stdout.strip()[:200] or "unknown"


def dump(
    *,
    server: PgServer,
    database: str,
    snapshot: str,
    recipient: RecipientKey,
    out: IO[bytes],
    evidence_dir: Path,
    expected_tables: Iterable[str],
    pg_dump_command: str,
    pg_restore_command: str,
) -> DumpResult:
    """Dump `database` at `snapshot`, encrypted to `recipient`, into `out`."""
    env = server.child_environment()
    stderr_path = evidence_dir / "pg_dump.stderr"
    toc_path = evidence_dir / "pg_restore-list.txt"
    list_stderr_path = evidence_dir / "pg_restore-list.stderr"
    encryptor = Encryptor(recipient, out)
    with (
        stderr_path.open("wb") as dump_err,
        toc_path.open("wb") as toc,
        list_stderr_path.open("wb") as list_err,
    ):
        dumper = subprocess.Popen(  # noqa: S603
            [*_command(pg_dump_command), "--format=custom", "--compress=6", "--no-password",
             f"--snapshot={snapshot}", f"--dbname={checked_database_name(database)}"],
            stdout=subprocess.PIPE, stderr=dump_err, env=env,
        )  # fmt: skip
        lister = subprocess.Popen(  # noqa: S603
            [*_command(pg_restore_command), "--list"],
            stdin=subprocess.PIPE, stdout=toc, stderr=list_err, env=env,
        )  # fmt: skip
        assert dumper.stdout is not None
        assert lister.stdin is not None
        first = b""
        lister_open = True
        try:
            while chunk := dumper.stdout.read(_READ):
                if not first:
                    first = chunk[:5]
                encryptor.write(chunk)
                if lister_open:
                    try:
                        lister.stdin.write(chunk)
                    except BrokenPipeError:
                        lister_open = False  # it read the table of contents and left
        finally:
            dumper.stdout.close()
            dump_rc = dumper.wait()
            with contextlib.suppress(BrokenPipeError):
                lister.stdin.close()
            list_rc = lister.wait()
    digest = encryptor.finish()
    if dump_rc != 0:
        raise DumpFailed(f"pg_dump_exit_{dump_rc}")
    if digest.plaintext_bytes == 0:
        raise DumpFailed("empty_dump")
    if first != b"PGDMP":
        raise DumpFailed("not_a_custom_archive")
    if list_rc != 0:
        raise DumpFailed(f"pg_restore_list_exit_{list_rc}")
    toc_text = toc_path.read_text(encoding="utf-8", errors="replace")
    in_archive = set(re.findall(r"\bTABLE public (\S+) ", toc_text))
    expected = set(expected_tables)
    missing = sorted(expected - in_archive)
    if missing:
        raise DumpFailed(f"tables_missing_from_archive:{len(missing)}")
    if "alembic_version" in expected and not re.search(
        r"\bTABLE DATA public alembic_version ", toc_text
    ):
        raise DumpFailed("alembic_version_data_missing")
    return DumpResult(digest, len(in_archive), tool_version(pg_dump_command, server))


def database_exists(server: PgServer, name: str) -> bool:
    with server.connect("postgres", autocommit=True) as conn:
        row = conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
    return row is not None


def create_database(
    server: PgServer, name: str, *, bootstrap_script: Path, psql_command: str
) -> None:
    """A new database with the three MarkX roles, exactly as bootstrap.sh makes it.
    Role passwords are never reset here unless the MARKX_DB_*_PASSWORD
    variables are given (D-091)."""
    env = server.child_environment()
    env["PSQL"] = psql_command
    for name_ in (
        "MARKX_DB_MIGRATOR_PASSWORD",
        "MARKX_DB_APP_PASSWORD",
        "MARKX_DB_READONLY_PASSWORD",
    ):
        if name_ in os.environ:
            env[name_] = os.environ[name_]
    result = subprocess.run(  # noqa: S603
        [str(bootstrap_script), checked_database_name(name)],
        env=env, capture_output=True, timeout=300, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise RestoreFailed("bootstrap_failed")


def drop_database(server: PgServer, name: str) -> None:
    """Drop ONE database by name. Only ever called on a database this process
    itself created moments before (a failed restore, a drill)."""
    with server.connect("postgres", autocommit=True) as conn:
        conn.execute(
            psycopg.sql.SQL("drop database if exists {} with (force)").format(
                psycopg.sql.Identifier(checked_database_name(name))
            )
        )


def restore(
    *,
    server: PgServer,
    target: str,
    plaintext: Iterable[bytes],
    pg_restore_command: str,
    evidence_dir: Path,
) -> None:
    """Feed a decrypted archive to `pg_restore --single-transaction`: either all
    of it is restored, or nothing is. A decryption error mid-way kills
    pg_restore before it can commit."""
    stderr_path = evidence_dir / "pg_restore.stderr"
    with stderr_path.open("wb") as err:
        proc = subprocess.Popen(  # noqa: S603
            [*_command(pg_restore_command), "--exit-on-error", "--single-transaction",
             "--no-password", f"--dbname={checked_database_name(target)}"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
            env=server.child_environment(),
        )  # fmt: skip
        assert proc.stdin is not None
        try:
            for chunk in plaintext:
                proc.stdin.write(chunk)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        rc = proc.wait()
    if rc != 0:
        raise RestoreFailed(f"pg_restore_exit_{rc}")
