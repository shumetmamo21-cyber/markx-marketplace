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

**A restore runs as an ordinary owner role, never as the superuser (BK-6).**
A dump is executable content: a forged set could carry SQL that, run by a
superuser, executes shell commands on the database host (`COPY ... TO
PROGRAM`). The superuser only creates the empty database and the MarkX roles
(bootstrap.sh, our own SQL) and drops a database this process made; the
archive is fed to pg_restore logged in as `markx_migrator`, the schema owner,
and the restored copy is checked as `markx_migrator` and `markx_app`. A
`SET ROLE` would not do: the archive could simply `RESET ROLE`.

**A restore never resets a role's password (BK-7).** Roles are shared by
the whole PostgreSQL server. When the MarkX roles already exist there, the
restore leaves their passwords alone, and it refuses to run at all if
MARKX_DB_*_PASSWORD values are given, because bootstrap.sh would otherwise
reset them (on a production server that would lock the running app out).
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

MARKX_ROLES = ("markx_migrator", "markx_app", "markx_readonly")
# The variables bootstrap.sh resets a role's password from (D-091).
ROLE_PASSWORD_VARIABLES = (
    "MARKX_DB_MIGRATOR_PASSWORD",
    "MARKX_DB_APP_PASSWORD",
    "MARKX_DB_READONLY_PASSWORD",
)
# The passwords bootstrap.sh gives a role when none is given: a laptop's, CI's
# and a throwaway recovery container's. Not secrets (docs/SETUP.md).
_DEV_PASSWORDS = {
    "markx_migrator": "markx_migrator_dev-only",
    "markx_app": "markx_app_dev-only",
}
# Log in as these roles for a restore, without ever setting their password.
_LOGIN_VARIABLES = {
    "markx_migrator": ("MARKX_RESTORE_OWNER_PASSWORD", "MARKX_DB_MIGRATOR_PASSWORD"),
    "markx_app": ("MARKX_RESTORE_APP_PASSWORD", "MARKX_DB_APP_PASSWORD"),
}


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

    def as_role(self, role: str) -> PgServer:
        """The same server, logged in as one of the MarkX roles (BK-6). The
        password comes from MARKX_RESTORE_OWNER_PASSWORD (markx_migrator) or
        MARKX_RESTORE_APP_PASSWORD (markx_app), else the one bootstrap.sh gave
        it on this machine, else bootstrap.sh's default."""
        password = next(
            (os.environ[v] for v in _LOGIN_VARIABLES[role] if os.environ.get(v)),
            _DEV_PASSWORDS[role],
        )
        return PgServer(self.host, self.port, role, password)

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


def existing_markx_roles(server: PgServer) -> list[str]:
    with server.connect("postgres", autocommit=True) as conn:
        rows = conn.execute(
            "select rolname from pg_roles where rolname = any(%s) order by rolname",
            (list(MARKX_ROLES),),
        ).fetchall()
    return [str(r[0]) for r in rows]


def create_database(
    server: PgServer, name: str, *, bootstrap_script: Path, psql_command: str
) -> None:
    """A new database with the three MarkX roles, exactly as bootstrap.sh makes it.
    Roles that already exist keep their passwords: none is ever reset here
    (BK-7). New roles take the MARKX_DB_*_PASSWORD values when given (a
    throwaway recovery server that should not use the defaults)."""
    given = [v for v in ROLE_PASSWORD_VARIABLES if os.environ.get(v)]
    existing = existing_markx_roles(server)
    if given and existing:
        raise RestoreFailed(
            "roles_exist_passwords_given: the MarkX roles already exist on this PostgreSQL "
            "server and a restore never resets their passwords; unset "
            + ", ".join(given)
            + " (log in with MARKX_RESTORE_OWNER_PASSWORD instead), or restore on a "
            "throwaway recovery server"
        )
    env = server.child_environment()
    env["PSQL"] = psql_command
    if not existing:
        for variable in given:
            env[variable] = os.environ[variable]
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
