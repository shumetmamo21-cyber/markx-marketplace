"""The automated recovery drill (D-094; blueprint F.13 "a restore drill every
month", H.7 "a backup restored successfully into a fresh database").

    1. take a real backup set of the source database and stores (the
       rehearsal, on a laptop and in CI), or pick the newest complete set
       already at the destination (`run_offsite_drill`: the monthly drill on
       a separate recovery machine, BK-2);
    2. verify it at the destination, every blob decrypted and hashed;
    3. restore it into a NEW database and new, empty file targets;
    4. compare: the migration version, every table's row count, every file's
       checksum, every database file reference, the private target's privacy
       and the audit log's protection (restore.py);
    5. with failure injection: copy the set into a local folder and prove
       that a changed dump, a cut-short index, a missing manifest, an edited
       manifest, a missing blob and a wrong recovery key are each REFUSED,
       and that a restore refused this way writes nothing. The copy is local,
       so the drill never writes to or deletes from the backup bucket, and a
       read-only key is enough;
    6. remove only what the drill itself created: its database, its file
       targets, its local copies. Never the set (that is a real backup),
       never a source.

**Never on the server (BK-2).** Both refuse to run when MARKX_ENV is staging
or production: the drill needs the recovery key, which must never be on the
server, and it restores into a PostgreSQL that must not be production's.
The monthly drill runs on a separate, throwaway recovery machine (a laptop,
or a free CI runner) with its own PostgreSQL 17 container without network,
the backup bucket's read-only key, and the recovery key
(docs/runbooks/backup-and-restore.md, "The monthly drill").

**With the secrets copy (BK-5, D-105)**, once the restore passed: the copy is
opened with the recovery key, every staff authenticator secret in the
restored database must decrypt with the copied `MARKX_ENCRYPTION_KEY`, a
staff member must sign in to the restored copy with the copied keys, their
password and the code their authenticator app shows (`staff_sign_in.py`),
and the secrets of another server must be refused.

**Older locked copies (RN-1).** Verify and restore use an older locked copy
of any file written again since the set was made; the drill's injection copy
is taken from the same versions, and the report lists what was overwritten.

**A socket path too long (RN-4).** A Unix socket path holds at most 107
bytes on Linux; a longer PGHOST is reported as a FAILED drill with the reason,
and so is any PostgreSQL that cannot be reached, never a traceback.

The rehearsal's file targets are two fresh MinIO buckets when the source is
MinIO (made with MARKX_RESTORE_TARGET_ACCESS_KEY_ID when set), otherwise a
temporary folder; the off-server drill always uses a temporary folder, so it
never needs a new bucket. The rehearsal is recorded in `backup_runs` (kind
`drill`); the off-server drill writes a report, which `record-drill` enters
on the server for the watch.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from cryptography.fernet import Fernet

from markx.backup import manifest as manifest_mod
from markx.backup.config import BackupConfig
from markx.backup.copies import Copies, download_matching
from markx.backup.crypto import RecoveryKey, SignerKey, generate_keys
from markx.backup.database import PgServer, RestoreFailed, database_exists, drop_database
from markx.backup.destination import (
    Destination,
    DestinationError,
    LocalDestination,
)
from markx.backup.escrow import OpenedEscrow, decrypts_with
from markx.backup.records import Recorder, RunRecord
from markx.backup.restore import (
    FileTargets,
    Report,
    SetRefused,
    list_sets,
    read_original_manifest,
    restore_set,
    verify_set,
)
from markx.backup.runner import BackupContext, run_backup
from markx.backup.staff_sign_in import StaffCredentials, sign_in_on_restored
from markx.core.storage import (
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStorageSettings,
    S3ObjectStore,
    make_s3_client,
)

# The faults every drill injects, by the name its report gives each (RN-5:
# `record-drill` checks a report against these). The blob case exists only
# for a set that holds files; the secrets case only with a secrets copy.
INJECTED_DUMP = "one byte of the encrypted dump changed"
INJECTED_INDEX = "the file index cut short"
INJECTED_NO_MANIFEST = "the manifest missing (an unfinished set)"
INJECTED_EDITED_MANIFEST = "the manifest edited"
INJECTED_BLOB = "a file's blob missing"
INJECTED_WRONG_KEY = "a wrong recovery key"
INJECTED_REFUSED_RESTORE = "a restore of an altered set writes nothing"
INJECTED_OTHER_SECRETS = "the secrets of another server"
ALWAYS_INJECTED = (
    INJECTED_DUMP, INJECTED_INDEX, INJECTED_NO_MANIFEST, INJECTED_EDITED_MANIFEST,
    INJECTED_WRONG_KEY, INJECTED_REFUSED_RESTORE,
)  # fmt: skip

# The checks of the secrets step (BK-5), by name.
SECRETS_OPENED = "the secrets copy opens with the recovery key and the server's signature"
SECRETS_TOTP = "every staff authenticator secret decrypts with the copied MARKX_ENCRYPTION_KEY"
SECRETS_SIGN_IN = "a staff member signs in to the restored copy with the copied keys and their code"

# Linux: a Unix socket path is at most 107 bytes (108 with its final NUL).
MAX_SOCKET_PATH = 107


@dataclass(slots=True)
class DrillResult:
    passed: bool
    backup_id: str | None
    restore: Report | None
    injections: list[tuple[str, bool, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    kind: str = "rehearsal"  # or "offsite": on a separate recovery machine
    # BK-5: the checks made with the secrets copy, when one was given.
    secrets: list[tuple[str, bool, str]] = field(default_factory=list)
    # RN-1: files of the set written again since it was made.
    overwritten: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"RECOVERY DRILL of set {self.backup_id}"]
        if self.restore is not None:
            lines.append(self.restore.text())
        for name, ok, detail in self.secrets:
            lines.append(
                f"  {'ok  ' if ok else 'FAIL'}  secrets: {name}{': ' + detail if detail else ''}"
            )
        for name, ok, detail in self.injections:
            lines.append(
                f"  {'ok  ' if ok else 'FAIL'}  injected: {name}{': ' + detail if detail else ''}"
            )
        lines += [f"  WARN  {warning}" for warning in self.warnings]
        lines += [f"  note: {note}" for note in self.notes]
        lines.append("DRILL PASSED" if self.passed else "DRILL FAILED")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "backup_id": self.backup_id,
                "restore": self.restore.as_dict() if self.restore else None,
                "injections": [{"name": n, "refused": ok, "detail": d} for n, ok, d in self.injections],
                "secrets": [{"name": n, "ok": ok, "detail": d} for n, ok, d in self.secrets],
                "overwritten": self.overwritten, "warnings": self.warnings,
                "notes": self.notes, "kind": self.kind, "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None}  # fmt: skip


@dataclass(frozen=True, slots=True)
class DrillSecrets:
    """The opened secrets copy and the staff member who signs in (BK-5)."""

    escrow: OpenedEscrow
    credentials: StaffCredentials


def socket_problem(server: PgServer) -> str | None:
    """Why `server` cannot be reached through its Unix socket, if the path is
    too long for one (RN-4); None when it is fine or not a socket."""
    host = server.host or ""
    if not host.startswith("/"):
        return None
    path = os.path.join(host, f".s.PGSQL.{server.port or '5432'}")
    length = len(os.fsencode(path))
    if length > MAX_SOCKET_PATH:
        return (
            f"the PostgreSQL socket path is {length} bytes, and a Unix socket path can be at "
            f"most {MAX_SOCKET_PATH}: choose a shorter folder (MARKX_RECOVERY_SOCKET_DIR) and "
            "start the recovery PostgreSQL again"
        )
    return None


class DrillRefused(Exception):
    """The drill must not run here."""


def refuse_on_a_server(config: BackupConfig) -> None:
    if config.is_real_environment:
        raise DrillRefused(
            f"a drill never runs on {config.env} (BK-2): run it on a separate recovery machine "
            "(docs/runbooks/backup-and-restore.md, 'The monthly drill')"
        )


# -- the injection copy, in a local folder ------------------------------------------------


def _copy(
    source: Destination, target: Destination, key: str, scratch: Path,
    version_id: str | None = None,
) -> None:  # fmt: skip
    path = scratch / "copy"
    digest = hashlib.sha256()
    with source.reader(key, version_id) as stream, path.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            out.write(chunk)
    target.put_file(key, path, digest.hexdigest())
    path.unlink()


def _replace(target: Destination, key: str, data: bytes, scratch: Path) -> None:
    path = scratch / "replaced"
    path.write_bytes(data)
    target.put_file(key, path, hashlib.sha256(data).hexdigest())
    path.unlink()


def inject_failures(
    destination: Destination, backup_id: str, *, signers: list[SignerKey],
    keys: dict[str, RecoveryKey], manifest: dict[str, Any], scratch: Path,
    server: PgServer, bootstrap_script: Path, psql_command: str, pg_restore_command: str,
    versions: dict[str, str] | None = None,
) -> list[tuple[str, bool, str]]:  # fmt: skip
    """Each case on a fresh LOCAL copy of the set; True means it was refused
    as it must be. Nothing is written to, or deleted from, `destination`.
    The copy is of the versions the set was verified from (`versions`: an
    older locked copy of a file written again since, RN-1)."""
    results: list[tuple[str, bool, str]] = []
    pristine_root, case_root = scratch / "pristine", scratch / "case"
    pristine = LocalDestination(pristine_root, prefix="markx")
    versions = dict(versions or {})
    blob_ids, blobs_version = _blob_ids(destination, manifest, scratch)
    if blobs_version is not None:
        versions[manifest["files"]["blobs_object"]] = blobs_version
    # The set's own pieces, from the signed manifest (a piece hidden or
    # overwritten at the destination is still copied as it was verified).
    set_keys = [manifest_mod.manifest_key(backup_id), manifest["database"]["object"],
                manifest["files"]["index_object"], manifest["files"]["blobs_object"]]  # fmt: skip
    blob_keys = sorted({manifest_mod.blob_key(b) for b in blob_ids})
    for key in set_keys + blob_keys:
        _copy(destination, pristine, key, scratch, versions.get(key))
    copy = LocalDestination(case_root, prefix="markx")

    def fresh() -> None:
        shutil.rmtree(case_root, ignore_errors=True)
        shutil.copytree(pristine_root, case_root)

    def expect_refused(name: str, report: Report, wanted: str) -> None:
        details = "; ".join(d for _, ok, d in report.checks if not ok)
        results.append((name, not report.passed and wanted in details, details[:200]))

    try:
        dump_key = manifest["database"]["object"]
        index_key = manifest["files"]["index_object"]
        manifest_key = manifest_mod.manifest_key(backup_id)

        fresh()
        data = copy.read_bytes(dump_key, limit=2**31)
        flipped = bytearray(data)
        flipped[len(flipped) // 2] ^= 0x01
        _replace(copy, dump_key, bytes(flipped), scratch)
        expect_refused(INJECTED_DUMP,
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "altered_piece")  # fmt: skip

        fresh()
        data = copy.read_bytes(index_key, limit=2**31)
        _replace(copy, index_key, data[: len(data) // 2], scratch)
        expect_refused(INJECTED_INDEX,
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "altered_piece")  # fmt: skip

        fresh()
        copy.delete(manifest_key)
        expect_refused(INJECTED_NO_MANIFEST,
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "no_manifest")  # fmt: skip

        fresh()
        edited = json.loads(copy.read_bytes(manifest_key, limit=2**24))
        edited["database"]["rows"] = int(edited["database"]["rows"]) + 1
        _replace(copy, manifest_key, json.dumps(edited).encode(), scratch)
        expect_refused(INJECTED_EDITED_MANIFEST,
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "signature")  # fmt: skip

        if blob_keys:
            fresh()
            copy.delete(blob_keys[0])
            expect_refused(INJECTED_BLOB,
                           verify_set(destination=copy, backup_id=backup_id, signers=signers,
                                      keys=keys, deep=True), "1 missing")  # fmt: skip

        fresh()
        stranger = generate_keys().recovery
        expect_refused(INJECTED_WRONG_KEY,
                       verify_set(destination=copy, backup_id=backup_id, signers=signers,
                                  keys={stranger.key_id: stranger}, deep=False),
                       "recovery_key_missing")  # fmt: skip

        # A refused restore writes nothing: the dump is altered, so no database appears.
        fresh()
        data = copy.read_bytes(dump_key, limit=2**31)
        _replace(copy, dump_key, data[:-1], scratch)
        target = f"markx_drill_refused_{secrets.token_hex(3)}"
        report = restore_set(
            destination=copy, backup_id=backup_id, signers=signers, keys=keys, server=server,
            target_db=target, confirm=target, files=None, bootstrap_script=bootstrap_script,
            psql_command=psql_command, pg_restore_command=pg_restore_command,
        )  # fmt: skip
        exists = database_exists(server, target)
        if exists:
            drop_database(server, target)
        results.append((INJECTED_REFUSED_RESTORE,
                        not report.passed and not exists, "no database created" if not exists else
                        "A DATABASE WAS CREATED"))  # fmt: skip
    finally:
        shutil.rmtree(case_root, ignore_errors=True)
        shutil.rmtree(pristine_root, ignore_errors=True)
    return results


def _blob_ids(
    destination: Destination, manifest: dict[str, Any], scratch: Path
) -> tuple[list[str], str | None]:
    """The set's blob list as the manifest records it (its SHA-256), and the
    older version it came from when the current one was written again."""
    key = manifest["files"]["blobs_object"]
    copies = Copies(destination)
    path = scratch / "blobs.txt"
    found = download_matching(copies, key, path, sha256=manifest["files"]["blobs_sha256"],
                              size=None)  # fmt: skip
    if found != "ok":
        raise SetRefused(f"{'missing' if found == 'missing' else 'altered'}_piece:blobs.txt")
    data = path.read_bytes()
    path.unlink()
    return [line for line in data.decode("ascii").splitlines() if line], copies.used.get(key)


# -- file targets ---------------------------------------------------------------------------


@dataclass(slots=True)
class DisposableTargets:
    targets: FileTargets
    cleanup: list[Any]


def disposable_file_targets(config: BackupConfig, scratch: Path) -> DisposableTargets:
    forbidden = frozenset(
        n for n in (config.source_private_bucket, config.source_public_bucket,
                    str(config.source_dir.resolve() / "private"),
                    str(config.source_dir.resolve() / "public")) if n
    )  # fmt: skip
    if config.source_provider == "minio" and not config.is_real_environment:
        settings = config.source_settings()
        token = secrets.token_hex(4)
        private_bucket, public_bucket = (
            f"markx-drill-{token}-private",
            f"markx-drill-{token}-public",
        )
        # The source's key only reads (BK-17): a key that may make and remove
        # markx-drill-* buckets is given for that, when there is one.
        key_id = os.environ.get("MARKX_RESTORE_TARGET_ACCESS_KEY_ID") or settings.access_key_id
        secret = (
            os.environ.get("MARKX_RESTORE_TARGET_SECRET_ACCESS_KEY") or settings.secret_access_key
        )
        target = ObjectStorageSettings(
            provider="minio", endpoint_url=settings.endpoint_url, region=settings.region,
            access_key_id=key_id, secret_access_key=secret,
            private_bucket=private_bucket, public_bucket=public_bucket,
        )  # fmt: skip
        client = make_s3_client(target)
        client.create_bucket(Bucket=private_bucket)
        client.create_bucket(Bucket=public_bucket)

        def remove() -> None:
            for bucket in (private_bucket, public_bucket):
                listed = client.list_objects_v2(Bucket=bucket).get("Contents", [])
                for item in listed:
                    client.delete_object(Bucket=bucket, Key=item["Key"])
                client.delete_bucket(Bucket=bucket)
            client.close()

        stores = {
            "private": S3ObjectStore(client, private_bucket, name="private", settings=target),
            "public": S3ObjectStore(client, public_bucket, name="public", settings=target),
        }
        return DisposableTargets(
            FileTargets(stores, f"minio buckets {private_bucket}, {public_bucket}", forbidden),  # type: ignore[arg-type]
            [remove],
        )
    return _folder_targets(scratch, forbidden)


def _folder_targets(scratch: Path, forbidden: frozenset[str]) -> DisposableTargets:
    folder = scratch / "files"
    stores_local = {
        "private": LocalPrivateStorage(folder / "private"),
        "public": LocalPublicStorage(folder / "public"),
    }
    return DisposableTargets(
        FileTargets(stores_local, f"temporary folder {folder}", forbidden),  # type: ignore[arg-type]
        [lambda: shutil.rmtree(folder, ignore_errors=True)],
    )


# -- the drill ---------------------------------------------------------------------------------


def _note_overwrites(result: DrillResult, report: Report) -> None:
    for key in report.facts.get("overwritten", []):
        if key not in result.overwritten:
            result.overwritten.append(key)
    for warning in report.warnings:
        if warning not in result.warnings:
            result.warnings.append(warning)


def _check_secrets(
    result: DrillResult, superuser: PgServer, target_db: str, secrets_: DrillSecrets
) -> None:
    """BK-5, on the restored copy: the copied keys open the staff secrets, a
    staff member signs in with them, and another server's key is refused."""
    escrow = secrets_.escrow
    encryption_key = escrow.value("api.env", "MARKX_ENCRYPTION_KEY")
    secret_key = escrow.value("api.env", "MARKX_SECRET_KEY")
    names = ", ".join(sorted(escrow.items))
    has_keys = bool(encryption_key and secret_key)
    result.secrets.append((SECRETS_OPENED, has_keys,
                           f"{len(escrow.items)} files ({names})" if has_keys
                           else "api.env has no MARKX_SECRET_KEY or MARKX_ENCRYPTION_KEY"))  # fmt: skip
    if not (encryption_key and secret_key):
        return
    app = superuser.as_role("markx_app")
    try:
        with app.connect(target_db) as conn:
            tokens = [bytes(row[0]) for row in conn.execute(
                "select totp_secret_encrypted from staff_members "
                "where totp_secret_encrypted is not null"
            ).fetchall()]  # fmt: skip
    except psycopg.Error as exc:
        result.secrets.append((SECRETS_TOTP, False, f"could not read them ({type(exc).__name__})"))
        return
    opened, total = decrypts_with(encryption_key, tokens)
    result.secrets.append((SECRETS_TOTP, total > 0 and opened == total,
                           f"{opened} of {total} staff secrets"))  # fmt: skip
    signed_in, detail = sign_in_on_restored(
        app_server=app, database=target_db, secret_key=secret_key,
        encryption_key=encryption_key, credentials=secrets_.credentials,
    )  # fmt: skip
    result.secrets.append((SECRETS_SIGN_IN, signed_in, detail))
    stranger, _ = decrypts_with(Fernet.generate_key().decode("ascii"), tokens)
    result.injections.append((INJECTED_OTHER_SECRETS, total > 0 and stranger == 0,
                              f"another server's MARKX_ENCRYPTION_KEY opens {stranger} of "
                              f"{total} staff secrets"))  # fmt: skip


def _drill_set(
    result: DrillResult, destination: Destination, backup_id: str, manifest: dict[str, Any], *,
    config: BackupConfig, superuser: PgServer, keys: dict[str, RecoveryKey],
    signers: list[SignerKey], bootstrap_script: Path, inject: bool, target_db: str,
    scratch: Path, targets: DisposableTargets, secrets_: DrillSecrets | None = None,
) -> None:  # fmt: skip
    """Steps 2 to 5 for one set: deep verify, restore, compare, the secrets
    copy (BK-5), inject."""
    deep = verify_set(destination=destination, backup_id=backup_id, signers=signers, keys=keys,
                      deep=True)  # fmt: skip
    _note_overwrites(result, deep)
    if not deep.passed:
        result.restore = deep
        result.notes.append("the set did not verify at the destination")
        return
    result.restore = restore_set(
        destination=destination, backup_id=backup_id, signers=signers, keys=keys,
        server=superuser, target_db=target_db, confirm=target_db, files=targets.targets,
        bootstrap_script=bootstrap_script, psql_command=config.psql_command,
        pg_restore_command=config.pg_restore_command,
    )  # fmt: skip
    _note_overwrites(result, result.restore)
    if secrets_ is not None and result.restore.passed:
        _check_secrets(result, superuser, target_db, secrets_)
    if inject:
        result.injections = inject_failures(
            destination, backup_id, signers=signers, keys=keys, manifest=manifest,
            scratch=scratch, server=superuser, bootstrap_script=bootstrap_script,
            psql_command=config.psql_command, pg_restore_command=config.pg_restore_command,
            versions=deep.facts.get("older_copies_used"),
        ) + result.injections  # fmt: skip
    result.passed = (
        result.restore.passed
        and all(ok for _, ok, _ in result.injections)
        and (secrets_ is None or (bool(result.secrets) and all(ok for _, ok, _ in result.secrets)))
    )


def _cleanup(
    result: DrillResult, superuser: PgServer, target_db: str, targets: DisposableTargets | None,
    scratch: Path,
) -> None:  # fmt: skip
    result.finished_at = datetime.now(UTC)
    try:
        if database_exists(superuser, target_db):
            drop_database(superuser, target_db)
            result.notes.append(f"drill database {target_db} dropped")
    except (psycopg.Error, RestoreFailed) as exc:
        if result.passed:
            result.passed = False
        result.notes.append(
            f"the drill database could not be checked or removed ({type(exc).__name__})"
        )
    if targets is not None:
        for step in targets.cleanup:
            step()
        result.notes.append(f"drill file targets removed ({targets.targets.description})")
    shutil.rmtree(scratch, ignore_errors=True)


def newest_complete_set(destination: Destination, signers: list[SignerKey]) -> str | None:
    """The newest set whose ORIGINAL manifest verifies and says complete (an
    overwritten manifest does not hide a set, RN-1)."""
    for backup_id in list_sets(destination):
        try:
            body = read_original_manifest(destination, backup_id, signers)
        except SetRefused:
            continue
        if body.get("status") == manifest_mod.STATUS_COMPLETE:
            return backup_id
    return None


def run_offsite_drill(
    config: BackupConfig, destination: Destination, *, superuser: PgServer,
    keys: dict[str, RecoveryKey], signers: list[SignerKey], bootstrap_script: Path,
    inject: bool = True, backup_id: str | None = None, secrets_: DrillSecrets | None = None,
) -> DrillResult:  # fmt: skip
    """The monthly drill on a separate recovery machine (BK-2): no backup is
    taken and nothing is written to the bucket, so the bucket's read-only
    key, the recovery key and the signer PUBLIC key are all it needs. The
    newest complete set (or `backup_id`) is verified in full, restored into
    a NEW database on `superuser`'s server (a throwaway container) and a
    temporary folder, compared, put through the injected failures and, with
    `secrets_`, the secrets step (BK-5)."""
    refuse_on_a_server(config)
    started = datetime.now(UTC)
    result = DrillResult(False, None, None, started_at=started, kind="offsite")
    problem = socket_problem(superuser)
    if problem is not None:
        result.finished_at = datetime.now(UTC)
        result.notes.append(problem)
        return result
    scratch = Path(tempfile.mkdtemp(prefix="markx-drill-"))
    target_db = f"markx_drill_{started.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(2)}"
    targets: DisposableTargets | None = None
    try:
        chosen = backup_id or newest_complete_set(destination, signers)
        result.backup_id = chosen
        if chosen is None:
            result.notes.append("no complete set signed by a trusted key at the destination")
            return result
        try:
            manifest = read_original_manifest(destination, chosen, signers)
        except SetRefused as exc:
            result.notes.append(f"the set was refused: {exc.reason}")
            return result
        targets = _folder_targets(scratch, frozenset())
        _drill_set(result, destination, chosen, manifest, config=config, superuser=superuser,
                   keys=keys, signers=signers, bootstrap_script=bootstrap_script, inject=inject,
                   target_db=target_db, scratch=scratch, targets=targets,
                   secrets_=secrets_)  # fmt: skip
        result.notes.append(f"set made at {manifest.get('created_at')}, off-server drill")
        return result
    except DestinationError as exc:
        result.passed = False
        result.notes.append(f"the destination failed: {exc.reason}")
        return result
    except (psycopg.Error, RestoreFailed, SetRefused) as exc:
        result.passed = False
        reason = getattr(exc, "reason", None) or type(exc).__name__
        result.notes.append(f"the recovery PostgreSQL could not be used: {reason}")
        return result
    finally:
        _cleanup(result, superuser, target_db, targets, scratch)


def run_drill(
    ctx: BackupContext, *, superuser: PgServer, keys: dict[str, RecoveryKey],
    signers: list[SignerKey], bootstrap_script: Path, inject: bool, record: bool = True,
) -> DrillResult:  # fmt: skip
    """The rehearsal, on a laptop and in CI: a backup is taken first."""
    config = ctx.config
    refuse_on_a_server(config)
    problem = socket_problem(superuser)
    if problem is not None:
        return DrillResult(False, None, None, notes=[problem], finished_at=datetime.now(UTC))
    started = datetime.now(UTC)
    recorder = Recorder(superuser if record else None, config.database)
    run = RunRecord(kind="drill", environment=config.env, destination=ctx.destination.identity,
                    offsite=ctx.destination.offsite, started_at=started)  # fmt: skip
    recorder.start(run)
    result = DrillResult(False, None, None)
    scratch = Path(tempfile.mkdtemp(prefix="markx-drill-"))
    target_db = f"markx_drill_{started.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(2)}"
    disposable: DisposableTargets | None = None
    try:
        outcome = run_backup(ctx)
        result.backup_id = run.backup_id = outcome.backup_id
        if outcome.status != "succeeded":
            result.notes.append(
                f"the backup did not succeed: {outcome.status} {outcome.error_code}"
            )
            return result
        disposable = disposable_file_targets(config, scratch)
        _drill_set(result, ctx.destination, str(outcome.backup_id), outcome.manifest,
                   config=config, superuser=superuser, keys=keys, signers=signers,
                   bootstrap_script=bootstrap_script, inject=inject, target_db=target_db,
                   scratch=scratch, targets=disposable)  # fmt: skip
        return result
    finally:
        _cleanup(result, superuser, target_db, disposable, scratch)
        run.status = "succeeded" if result.passed else "failed"
        run.finished_at = datetime.now(UTC)
        run.verified = result.passed
        if not result.passed:
            failed = [n for n, ok, _ in (result.restore.checks if result.restore else []) if not ok]
            failed += [f"injected:{n}" for n, ok, _ in result.injections if not ok]
            run.error_code = "drill_failed"
            run.error_summary = ", ".join(failed)[:500] or "; ".join(result.notes)[:500]
        run.details = {
            "seconds": result.restore.facts.get("seconds") if result.restore else None,
            "injections": len(result.injections),
            "restored_files": result.restore.facts.get("restored_files")
            if result.restore
            else None,
        }
        recorder.finish(run)


# -- checking a drill's report before it counts (RN-5) --------------------------------------

# The checks every passed off-server restore makes (restore.py), by name or the
# start of their name. A report missing any of them did not restore the set.
_REQUIRED_RESTORE_CHECKS = (
    "manifest signed by a trusted key",
    "set complete",
    "database dump intact and decryptable",
    "file index intact",
    "every file's blob present",
    "target database is new",
    "database restored in one transaction, as the owner role (not a superuser)",
    "every file restored, read back and matched its checksum",
    "migration version",
    "every table's row count equals the snapshot's",
    "indexes valid and constraints validated",
    "audit log",
    "no unclassified file references",
    "every file the database refers to resolves to a restored file",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(items: Any) -> list[dict[str, Any]]:
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def report_problems(report: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Why an off-server drill's report does not show a PASSED drill of the
    set `manifest` describes (RN-5). Its own `passed` field is not believed:
    every check must be there and have passed, every injected fault must have
    been refused, the secrets step must have passed when it ran, and what it
    restored must be what the signed manifest says the set holds. Empty: the
    drill passed."""
    found = _content_problems(report, manifest)
    claimed = report.get("passed") is True
    if claimed and found:
        found.insert(0, "the report says PASSED, but its contents do not show a passed drill")
    if not claimed and not found:
        found.append("the report says FAILED")
    return found


def _content_problems(report: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    found: list[str] = []
    restore = report.get("restore")
    if not isinstance(restore, dict):
        return ["the report holds no restore"]
    if restore.get("backup_id") != report.get("backup_id"):
        found.append("the restore is of another set than the report names")
    checks = _rows(restore.get("checks"))
    names = [str(c.get("name", "")) for c in checks]
    for required in _REQUIRED_RESTORE_CHECKS:
        if not any(name.startswith(required) for name in names):
            found.append(f"no check '{required}'")
    failed = [str(c.get("name")) for c in checks if c.get("ok") is not True]
    if failed:
        found.append(f"failed checks: {', '.join(failed)[:200]}")
    injections = _rows(report.get("injections"))
    injected = {str(i.get("name")) for i in injections}
    wanted = set(ALWAYS_INJECTED)
    if int(manifest.get("files", {}).get("blob_count") or 0) > 0:
        wanted.add(INJECTED_BLOB)
    missing = sorted(wanted - injected)
    if missing:
        found.append(f"injected faults not tried: {', '.join(missing)}")
    known = {*ALWAYS_INJECTED, INJECTED_BLOB, INJECTED_OTHER_SECRETS}
    if injected - known:
        found.append("the report names injected faults no drill makes")
    not_refused = [str(i.get("name")) for i in injections if i.get("refused") is not True]
    if not_refused:
        found.append(f"injected faults NOT refused: {', '.join(not_refused)}")
    secret_rows = _rows(report.get("secrets"))
    if [r for r in secret_rows if r.get("ok") is not True]:
        found.append("the secrets step failed")
    if secret_rows and INJECTED_OTHER_SECRETS not in injected:
        found.append(f"injected fault not tried: {INJECTED_OTHER_SECRETS}")
    # What was restored is what the signed manifest says the set holds.
    facts = _dict(restore.get("facts"))
    source = _dict(facts.get("source"))
    if source.get("created_at") != manifest.get("created_at"):
        found.append("the restored set's time is not the set's")
    if source.get("database") != manifest.get("database", {}).get("name"):
        found.append("the restored database is not the set's")
    restored = _dict(facts.get("restored_files"))
    total = sum(v for v in restored.values() if isinstance(v, int) and not isinstance(v, bool))
    if total != int(manifest.get("files", {}).get("object_count") or 0):
        found.append(
            f"{total} files restored, the set holds {manifest.get('files', {}).get('object_count')}"
        )
    rows = f"{manifest.get('database', {}).get('rows')} rows"
    counted = next((c for c in checks if str(c.get("name")).startswith(
        "every table's row count equals the snapshot's")), None)  # fmt: skip
    if counted is None or rows not in str(counted.get("detail", "")):
        found.append("the restored row count is not the set's")
    return found
