"""Verifying a backup set and restoring it into isolated targets (D-094).

**Nothing is written to a target until the set has proved itself.** In order:

1. The manifest's signature is checked against the trusted signer keys, it
   must belong to the set asked for, and its status must be `complete`
   (an `incomplete` set is refused unless the operator says
   `--accept-incomplete`, and the report then says INCOMPLETE).
2. The dump and the file index are downloaded; each one's SHA-256 must be
   the one the signed manifest records, then each is decrypted in full once
   without using the output, and the plaintext's SHA-256 must match too.
3. The targets are checked: the database must NOT exist and must not carry
   the backed-up database's own name; file targets must be empty and must
   not be the live buckets; a typed confirmation must repeat the database
   name.

Then the database is restored in one transaction into a NEW database, the
files are written to the target stores (private files only ever to the
private target), every file is read back and compared, and the restored
copy is checked: the migration version, every table's row count against
the counts recorded at the snapshot, no invalid index or unvalidated
constraint, the application role still unable to rewrite the audit log,
every file a row refers to present in the restored stores, and the private
store not readable without credentials. A failed restore drops only the
database it created itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from markx.backup import manifest as manifest_mod
from markx.backup.crypto import (
    DecryptionError,
    RecoveryKey,
    SignerKey,
    decrypt_stream,
)
from markx.backup.database import (
    PgServer,
    RestoreFailed,
    checked_database_name,
    create_database,
    database_exists,
    drop_database,
)
from markx.backup.database import restore as pg_restore
from markx.backup.destination import Destination, DestinationError, ObjectMissing
from markx.backup.references import (
    alembic_revision,
    file_references,
    row_counts,
    schema_problems,
    unclassified_references,
)
from markx.core.storage import (
    LocalObjectStore,
    ObjectStore,
    S3ObjectStore,
    StorageUnavailable,
    StoredFileMissing,
    StoredFileRefused,
    StoreName,
    checked_key,
)

logger = logging.getLogger("markx.backup.restore")
_READ = 1024 * 1024
MAX_INDEX_BYTES = 512 * 1024 * 1024


class SetRefused(Exception):
    """The set, or a target, cannot be trusted or used. Nothing was written."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class Report:
    backup_id: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, ok, detail))
        return ok

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok, _ in self.checks)

    def text(self) -> str:
        lines = [f"backup set {self.backup_id}"]
        for name, ok, detail in self.checks:
            lines.append(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
        lines.append("RESULT: PASSED" if self.passed else "RESULT: FAILED")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"backup_id": self.backup_id, "passed": self.passed, "facts": self.facts,
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in self.checks]}  # fmt: skip


# -- reading the set ----------------------------------------------------------------------


def list_sets(destination: Destination) -> list[str]:
    """Backup ids that have a manifest, newest first (unverified)."""
    ids = set()
    for obj in destination.list("sets/"):
        parts = obj.key.split("/")
        if (
            len(parts) == 3
            and parts[2] == "manifest.json"
            and manifest_mod.BACKUP_ID.fullmatch(parts[1])
        ):
            ids.add(parts[1])
    return sorted(ids, reverse=True)


def read_manifest(
    destination: Destination, backup_id: str, signers: list[SignerKey]
) -> dict[str, Any]:
    try:
        data = destination.read_bytes(
            manifest_mod.manifest_key(backup_id), limit=manifest_mod.MAX_MANIFEST_BYTES
        )
    except ObjectMissing:
        raise SetRefused("no_manifest: the set is unfinished or does not exist") from None
    try:
        return manifest_mod.decode(data, signers, backup_id=backup_id)
    except manifest_mod.ManifestRefused as exc:
        raise SetRefused(exc.reason) from None


def _download(
    destination: Destination, key: str, path: Path, expected_sha: str, expected_size: int
) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.reader(key) as stream, path.open("wb") as out:
            while chunk := stream.read(_READ):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
    except ObjectMissing:
        raise SetRefused(f"missing_piece:{key.rsplit('/', 1)[-1]}") from None
    if size != expected_size or digest.hexdigest() != expected_sha:
        raise SetRefused(f"altered_piece:{key.rsplit('/', 1)[-1]}")


def _plaintext(path: Path, keys: dict[str, RecoveryKey]) -> Iterator[bytes]:
    with path.open("rb") as handle:
        yield from decrypt_stream(handle, keys)


def _verify_decrypts(
    path: Path, keys: dict[str, RecoveryKey], sha: str, size: int, what: str
) -> None:
    digest = hashlib.sha256()
    total = 0
    try:
        for chunk in _plaintext(path, keys):
            digest.update(chunk)
            total += len(chunk)
    except DecryptionError as exc:
        raise SetRefused(f"{what}_does_not_decrypt: {exc}") from None
    if total != size or digest.hexdigest() != sha:
        raise SetRefused(f"{what}_plaintext_mismatch")


@dataclass(slots=True)
class VerifiedSet:
    manifest: dict[str, Any]
    dump_path: Path
    entries: list[dict[str, Any]]
    workdir: Path


def fetch_and_verify(
    destination: Destination,
    backup_id: str,
    *,
    signers: list[SignerKey],
    keys: dict[str, RecoveryKey],
    workdir: Path,
    accept_incomplete: bool = False,
    report: Report,
) -> VerifiedSet:
    body = read_manifest(destination, backup_id, signers)
    report.check("manifest signed by a trusted key", True, str(body.get("signer_key_id")))
    status = body.get("status")
    if status != manifest_mod.STATUS_COMPLETE:
        if not accept_incomplete:
            raise SetRefused(f"set_status_{status}: refused (--accept-incomplete overrides)")
        report.check("set complete", False, f"status {status}, accepted by the operator")
    else:
        report.check("set complete", True)
    database = body["database"]
    files = body["files"]
    recipient = body["encryption"]["recipient_key_id"]
    if recipient not in keys:
        raise SetRefused(f"recovery_key_missing: the set needs recovery key {recipient}")
    dump_path = workdir / "database.dump.mxb"
    _download(destination, database["object"], dump_path, database["ciphertext_sha256"],
              int(database["ciphertext_bytes"]))  # fmt: skip
    _verify_decrypts(
        dump_path, keys, database["plaintext_sha256"], int(database["plaintext_bytes"]), "dump"
    )
    report.check("database dump intact and decryptable", True,
                 f"{database['plaintext_bytes']} bytes")  # fmt: skip
    index_path = workdir / "files.index.mxb"
    index_head = destination.head(files["index_object"])
    if index_head is None:
        raise SetRefused("missing_piece:files.index.mxb")
    if index_head.size > MAX_INDEX_BYTES:
        raise SetRefused("index_too_large")
    _download(destination, files["index_object"], index_path, files["index_ciphertext_sha256"],
              index_head.size)  # fmt: skip
    try:
        index_plain = b"".join(_plaintext(index_path, keys))
    except DecryptionError as exc:
        raise SetRefused(f"index_does_not_decrypt: {exc}") from None
    if hashlib.sha256(index_plain).hexdigest() != files["index_plaintext_sha256"]:
        raise SetRefused("index_plaintext_mismatch")
    entries = [json.loads(line) for line in index_plain.decode().splitlines() if line]
    if (
        len(entries) != files["object_count"]
        or sum(e["size"] for e in entries) != files["total_bytes"]
    ):
        raise SetRefused("index_does_not_match_manifest")
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if entry["store"] not in ("private", "public"):
            raise SetRefused("index_names_an_unknown_store")
        try:
            checked_key(entry["key"])
            manifest_mod.blob_key(entry["blob"])
        except (StoredFileRefused, ValueError):
            raise SetRefused("index_holds_an_unsafe_key") from None
        if (entry["store"], entry["key"]) in seen:
            raise SetRefused("index_repeats_a_file")
        seen.add((entry["store"], entry["key"]))
    report.check("file index intact", True, f"{len(entries)} files, {files['total_bytes']} bytes")
    return VerifiedSet(body, dump_path, entries, workdir)


def verify_blobs(
    destination: Destination, verified: VerifiedSet, keys: dict[str, RecoveryKey], *, deep: bool,
    report: Report,
) -> None:  # fmt: skip
    """Every blob is present; with `deep`, every blob decrypts to its file's
    hash. Counted per distinct blob: equal files share one."""
    missing: set[str] = set()
    damaged: set[str] = set()
    checked_blobs: dict[str, str] = {}
    for entry in verified.entries:
        blob = entry["blob"]
        if blob in checked_blobs:
            if checked_blobs[blob] != entry["sha256"]:
                damaged.add(blob)  # one blob cannot be two different files
            continue
        checked_blobs[blob] = entry["sha256"]
        key = manifest_mod.blob_key(blob)
        if not deep:
            if destination.head(key) is None:
                missing.add(blob)
            continue
        try:
            data = _blob_plaintext(destination, key, keys)
        except ObjectMissing:
            missing.add(blob)
            continue
        except DecryptionError:
            damaged.add(blob)
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
            damaged.add(blob)
    report.check(
        "every file's blob present" + (" and decrypts to its checksum" if deep else ""),
        not missing and not damaged,
        f"{len(checked_blobs)} blobs, {len(missing)} missing, {len(damaged)} damaged",
    )


def _blob_plaintext(destination: Destination, key: str, keys: dict[str, RecoveryKey]) -> bytes:
    with destination.reader(key) as stream:
        return b"".join(decrypt_stream(stream, keys))


# -- targets --------------------------------------------------------------------------------


@dataclass(slots=True)
class FileTargets:
    stores: Mapping[StoreName, ObjectStore]
    description: str
    # The buckets or folders a restore must never write to: the live ones.
    forbidden: frozenset[str] = frozenset()


def _target_names(store: ObjectStore) -> str:
    if isinstance(store, S3ObjectStore):
        return store.bucket
    root = getattr(store, "_root", None)
    return str(root) if root is not None else store.name


def check_targets(
    server: PgServer, target_db: str, confirm: str, files: FileTargets | None,
    manifest: dict[str, Any], report: Report,
) -> None:  # fmt: skip
    checked_database_name(target_db)
    if confirm != target_db:
        raise SetRefused(
            "confirmation_mismatch: --confirm-target must repeat the target database name"
        )
    if target_db == manifest["database"]["name"]:
        raise SetRefused(
            "target_is_the_source_name: restore into a NEW name, then swap names by hand "
            "(docs/runbooks/backup-and-restore.md)"
        )
    if target_db in ("postgres", "template0", "template1"):
        raise SetRefused("target_is_a_system_database")
    if database_exists(server, target_db):
        raise SetRefused("target_database_exists: a restore never overwrites a database")
    report.check("target database is new", True, target_db)
    if files is None:
        return
    private, public = files.stores["private"], files.stores["public"]
    names = {_target_names(private), _target_names(public)}
    if len(names) != 2:
        raise SetRefused("targets_not_separate: private and public files need two targets")
    if names & files.forbidden:
        raise SetRefused("target_is_a_live_store: restore files into new, empty buckets or folders")
    for store in (private, public):
        if _store_has_objects(store):
            raise SetRefused(f"target_not_empty: the {store.name} target already holds files")
    report.check(
        "file targets are separate, empty and not the live stores", True, files.description
    )


def _store_has_objects(store: ObjectStore) -> bool:
    if isinstance(store, S3ObjectStore):
        response = store._client.list_objects_v2(Bucket=store.bucket, MaxKeys=1)
        return bool(response.get("KeyCount", 0))
    root = getattr(store, "_root", None)
    if isinstance(root, Path):
        return root.exists() and any(p.is_file() for p in root.rglob("*"))
    return False


# -- the restore -----------------------------------------------------------------------------


def _restore_files(
    destination: Destination, verified: VerifiedSet, keys: dict[str, RecoveryKey],
    files: FileTargets, report: Report,
) -> set[tuple[str, str]]:  # fmt: skip
    restored: set[tuple[str, str]] = set()
    failures: dict[str, int] = {}
    for entry in verified.entries:
        store = files.stores[entry["store"]]
        try:
            data = _blob_plaintext(destination, manifest_mod.blob_key(entry["blob"]), keys)
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise DecryptionError("checksum")
            content_type = entry.get("content_type")
            if content_type is None:
                raise StoredFileRefused("unknown type")
            store.put(entry["key"], data, content_type)
            if hashlib.sha256(store.get(entry["key"])).hexdigest() != entry["sha256"]:
                raise DecryptionError("read back")
        except ObjectMissing:
            failures["blob_missing"] = failures.get("blob_missing", 0) + 1
            continue
        except DecryptionError:
            failures["blob_damaged"] = failures.get("blob_damaged", 0) + 1
            continue
        except StoredFileRefused:
            failures["refused_by_store"] = failures.get("refused_by_store", 0) + 1
            continue
        restored.add((entry["store"], entry["key"]))
    counts = {s: sum(1 for st, _ in restored if st == s) for s in ("private", "public")}
    report.facts["restored_files"] = counts
    report.check(
        "every file restored, read back and matched its checksum",
        not failures,
        f"{len(restored)} of {len(verified.entries)} ({counts['private']} private, "
        f"{counts['public']} public)" + (f"; problems {failures}" if failures else ""),
    )
    return restored


def _verify_database(
    server: PgServer, target: str, manifest: dict[str, Any], restored_files: set[tuple[str, str]] | None,
    files: FileTargets | None, report: Report,
) -> None:  # fmt: skip
    database = manifest["database"]
    with server.connect(target, autocommit=True) as conn:
        revision = alembic_revision(conn)
        report.check(
            "migration version",
            revision == manifest["application"]["alembic_revision"],
            str(revision),
        )
        counts = row_counts(conn)
        expected: dict[str, int] = database["row_counts"]
        differing = sorted(
            t for t in set(expected) | set(counts) if expected.get(t) != counts.get(t)
        )
        report.check(
            "every table's row count equals the snapshot's",
            not differing,
            f"{len(counts)} tables, {sum(counts.values())} rows"
            + (f"; differing: {', '.join(differing[:10])}" if differing else ""),
        )
        problems = schema_problems(conn)
        report.check("indexes valid and constraints validated", not problems, "; ".join(problems))
        report.check("audit log still protected from the application role", _audit_protected(conn))
        refs = file_references(conn)
        unclassified = unclassified_references(conn)
        report.check("no unclassified file references", unclassified == 0, str(unclassified))
    if restored_files is None or files is None:
        return
    unresolved = [r for r in refs if (r.store, r.key) not in restored_files]
    report.check(
        "every file the database refers to resolves to a restored file",
        not unresolved,
        f"{len(refs)} references" + (f", {len(unresolved)} unresolved" if unresolved else ""),
    )
    absent = 0
    for ref in refs[:50]:  # spot check through the store itself
        try:
            files.stores[ref.store].head(ref.key)
        except StoredFileMissing:
            absent += 1
    report.check("referenced files readable through the target stores", absent == 0,
                 f"{min(len(refs), 50)} checked")  # fmt: skip


def _audit_protected(conn: psycopg.Connection[Any]) -> bool:
    try:
        with conn.transaction():
            conn.execute("set local role markx_app")
            conn.execute("update audit_log set action = action")
            raise _Rollback
    except _Rollback:
        return False
    except psycopg.Error:
        return True


class _Rollback(Exception):
    pass


def check_private(files: FileTargets, report: Report) -> None:
    private = files.stores["private"]
    if isinstance(private, S3ObjectStore):
        sample = private._client.list_objects_v2(Bucket=private.bucket, MaxKeys=1).get(
            "Contents", []
        )
        if not sample:
            report.check("private target not readable without credentials", True, "empty")
            return
        try:
            readable = private.readable_without_credentials(sample[0]["Key"])
        except StorageUnavailable:
            readable = True
        report.check("private target not readable without credentials", not readable)
    elif isinstance(private, LocalObjectStore):
        root = private._root
        loose = [p for p in root.rglob("*") if p.is_file() and p.stat().st_mode & 0o077]
        report.check("private target files readable by their owner only", not loose,
                     f"{len(loose)} too open" if loose else "")  # fmt: skip


def restore_set(
    *,
    destination: Destination,
    backup_id: str,
    signers: list[SignerKey],
    keys: dict[str, RecoveryKey],
    server: PgServer,
    target_db: str,
    confirm: str,
    files: FileTargets | None,
    bootstrap_script: Path,
    psql_command: str,
    pg_restore_command: str,
    accept_incomplete: bool = False,
    workdir: Path | None = None,
) -> Report:
    report = Report(backup_id)
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="markx-restore-", dir=workdir))
    os.chmod(scratch, 0o700)
    created = False
    try:
        verified = fetch_and_verify(
            destination, backup_id, signers=signers, keys=keys, workdir=scratch,
            accept_incomplete=accept_incomplete, report=report,
        )  # fmt: skip
        verify_blobs(destination, verified, keys, deep=False, report=report)
        if not report.passed and not accept_incomplete:
            raise SetRefused("blobs_missing")
        check_targets(server, target_db, confirm, files, verified.manifest, report)
        create_database(
            server, target_db, bootstrap_script=bootstrap_script, psql_command=psql_command
        )
        created = True
        pg_restore(
            server=server, target=target_db, plaintext=_plaintext(verified.dump_path, keys),
            pg_restore_command=pg_restore_command, evidence_dir=scratch,
        )  # fmt: skip
        report.check("database restored in one transaction", True, target_db)
        restored = None
        if files is not None:
            restored = _restore_files(destination, verified, keys, files, report)
            check_private(files, report)
        _verify_database(server, target_db, verified.manifest, restored, files, report)
        report.facts["seconds"] = round(time.monotonic() - started, 1)
        report.facts["source"] = {
            "created_at": verified.manifest["created_at"],
            "release": verified.manifest["application"]["release"],
            "database": verified.manifest["database"]["name"],
        }
        return report
    except SetRefused as exc:
        report.check("set and targets accepted", False, exc.reason)
        return report
    except (RestoreFailed, DestinationError, DecryptionError) as exc:
        reason = getattr(exc, "reason", None) or type(exc).__name__
        report.check("restore", False, str(reason))
        if created:
            drop_database(server, target_db)
            report.check("the half-restored database was removed", True, target_db)
        return report
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify_set(
    *, destination: Destination, backup_id: str, signers: list[SignerKey],
    keys: dict[str, RecoveryKey], deep: bool, workdir: Path | None = None,
) -> Report:  # fmt: skip
    """Everything short of writing anywhere: signature, hashes, decryption,
    every blob (and with `deep`, every blob decrypted and hashed)."""
    report = Report(backup_id)
    scratch = Path(tempfile.mkdtemp(prefix="markx-verify-", dir=workdir))
    try:
        verified = fetch_and_verify(
            destination, backup_id, signers=signers, keys=keys, workdir=scratch, report=report
        )
        verify_blobs(destination, verified, keys, deep=deep, report=report)
        report.facts["manifest"] = {
            k: verified.manifest[k] for k in ("created_at", "status", "environment", "application")
        }
    except SetRefused as exc:
        report.check("set accepted", False, exc.reason)
    except DestinationError as exc:
        report.check("destination readable", False, exc.reason)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return report
