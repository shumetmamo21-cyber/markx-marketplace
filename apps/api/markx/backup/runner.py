"""One backup set, from start to a verified, signed manifest (D-094).

The order is what makes a set recoverable:

1. **Lock.** A PostgreSQL advisory lock on the source database (and a file
   lock in the working folder): two backups never run at once, whichever
   machine starts them. A second one records `skipped` and leaves.
2. **Snapshot.** One REPEATABLE READ transaction exports its snapshot.
   pg_dump dumps exactly that snapshot, and the same transaction reads the
   row count of every table and every file the rows refer to.
3. **Files, after the snapshot.** Files are written before the row that
   names them commits, and no MarkX feature deletes or rewrites a file
   (D-062, D-090). So every file the snapshot refers to already exists when
   the listing starts after it. A referenced file that is NOT found makes
   the set `incomplete`, which a restore refuses by default and the watch
   reports. Unreferenced files are backed up too.
4. **Upload and verify** each piece: the destination's size, then a full
   read-back compared with the SHA-256 of what was sent.
5. **Manifest last.** Signed; its arrival at the destination is the moment
   the set exists. Anything before it is an unfinished set that no restore
   will use and retention removes after its grace period.

Unchanged files are not read again: the last run's catalog (kept in the
working folder) maps each file's fingerprint (size and ETag, or size, mtime
and inode) to its blob. Equal files share one blob. A run that was
interrupted leaves its blobs behind for the next run to reuse.

**A blob is reused only when it is provably the one that passed its check
(BK-3).** The blob ledger (kept in the working folder) records, for each
blob whose upload was read back in full and matched, its encrypted size,
the SHA-256 of its encrypted bytes, and the destination's own fingerprint of
the stored object (its ETag) right after that check. A later run reuses the
blob only when the destination still lists it with that size and that ETag;
anything else (an upload whose check failed, an object written again since,
a blob the ledger does not know) is uploaded again, over it. A blob whose
check fails is removed from the ledger at once, so it is never reused even
by the same run. Every index entry records its blob's encrypted size and
SHA-256, and a set is `complete` only when every blob in it passed.

**Nothing here deletes anything at the destination (BK-1).** The server's
key cannot. On a failure the last good set stays, and the failed attempt's
working folder (the encrypted pieces, the tool output, a report) is kept
under `failed/` for investigation. With an object lock, a blob that a new
set reuses has its lock lengthened, so that every object of the newest set
is locked for at least `MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from markx.backup import heartbeat
from markx.backup import manifest as manifest_mod
from markx.backup.config import BackupConfig
from markx.backup.copies import Copies
from markx.backup.crypto import (
    FORMAT_NAME,
    Encryptor,
    RecipientKey,
    SigningKey,
    blob_id,
)
from markx.backup.database import DumpFailed, PgServer, dump
from markx.backup.destination import (
    Destination,
    DestinationError,
    DestinationUnavailable,
    RemoteObject,
    VerificationFailed,
)
from markx.backup.records import Recorder, RunRecord
from markx.backup.references import (
    FileReference,
    alembic_revision,
    database_identity,
    file_references,
    row_counts,
    unclassified_references,
)
from markx.backup.sources import (
    STORES,
    Skipped,
    Source,
    SourceCorrupt,
    SourceMissing,
    SourceObject,
)
from markx.core.storage import sniff_image_type

logger = logging.getLogger("markx.backup")

# 'markxbkp' as a number: the one advisory lock every backup takes.
ADVISORY_LOCK = 0x6D61726B78626B70
_READ = 1024 * 1024


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class BackupContext:
    config: BackupConfig
    server: PgServer
    destination: Destination
    source: Source
    recipient: RecipientKey
    signing: SigningKey
    recorder: Recorder
    clock: Callable[[], datetime] = utcnow


@dataclass(slots=True)
class BackupOutcome:
    status: str  # succeeded, incomplete, failed, skipped
    backup_id: str | None = None
    error_code: str | None = None
    retryable: bool = False
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileEntry:
    store: str
    key: str
    size: int
    sha256: str
    content_type: str | None
    blob: str
    fingerprint: str
    # The blob as stored: its encrypted size and the SHA-256 of its encrypted bytes (BK-3).
    ciphertext_bytes: int
    ciphertext_sha256: str

    def public(self) -> dict[str, Any]:
        return {"store": self.store, "key": self.key, "size": self.size, "sha256": self.sha256,
                "content_type": self.content_type, "blob": self.blob,
                "ciphertext_bytes": self.ciphertext_bytes,
                "ciphertext_sha256": self.ciphertext_sha256}  # fmt: skip


@dataclass(slots=True)
class LedgerEntry:
    """A blob whose upload was read back in full and matched (BK-3)."""

    bytes: int
    sha256: str
    # The destination's fingerprint of the object right after that check.
    etag: str
    locked_until: str | None = None


@dataclass(slots=True)
class FilesResult:
    entries: list[FileEntry]
    new_blobs: int
    reused_blobs: int
    missing_references: list[FileReference]
    skipped: dict[str, int]
    # Blobs proved this run: read back now, or unchanged since they were.
    proved: set[str] = field(default_factory=set)
    # RN-1: blobs this service checked whose stored bytes someone changed since
    # (another size or fingerprint than right after the check).
    overwritten: list[str] = field(default_factory=list)


# -- locks ------------------------------------------------------------------------------


@contextmanager
def _file_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(path, "a+")  # noqa: SIM115
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def backup_lock(server: PgServer, database: str, work_dir: Path) -> Iterator[bool]:
    """True while this process holds both locks; False when another backup does."""
    with _file_lock(work_dir / ".lock") as local:
        if not local:
            yield False
            return
        with server.connect(database, autocommit=True, connect_timeout=15) as conn:
            row = conn.execute("select pg_try_advisory_lock(%s)", (ADVISORY_LOCK,)).fetchone()
            if not (row and row[0]):
                yield False
                return
            try:
                yield True
            finally:
                conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK,))


# -- the file catalog (unchanged files are not read again) --------------------------------


def _load_catalog(path: Path) -> dict[tuple[str, str], FileEntry]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    catalog: dict[tuple[str, str], FileEntry] = {}
    for row in rows:
        try:
            entry = FileEntry(**row)
        except TypeError:
            continue
        catalog[(entry.store, entry.key)] = entry
    return catalog


def _catalog_path(ctx: BackupContext, work_dir: Path) -> Path:
    """One catalog per key pair: after a key rotation no blob encrypted to the
    old key is ever reused for a new set."""
    return work_dir / f"file-catalog-{ctx.recipient.key_id}-{ctx.signing.key_id}.json"


def _save_catalog(path: Path, entries: list[FileEntry]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps([vars_(e) for e in entries]), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def vars_(entry: FileEntry | LedgerEntry) -> dict[str, Any]:
    return {slot: getattr(entry, slot) for slot in entry.__slots__}


def _ledger_path(ctx: BackupContext, work_dir: Path) -> Path:
    return work_dir / f"blob-ledger-{ctx.recipient.key_id}-{ctx.signing.key_id}.json"


def _load_ledger(path: Path) -> dict[str, LedgerEntry]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    ledger: dict[str, LedgerEntry] = {}
    if not isinstance(rows, dict):
        return ledger
    for blob, row in rows.items():
        try:
            ledger[str(blob)] = LedgerEntry(**row)
        except TypeError:
            continue
    return ledger


def _save_ledger(path: Path, ledger: dict[str, LedgerEntry]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({b: vars_(e) for b, e in sorted(ledger.items())}), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _reusable(blob: str, remote: dict[str, RemoteObject], ledger: dict[str, LedgerEntry]) -> bool:
    """The destination still holds exactly the object that passed its check:
    the same size and the same fingerprint (ETag) as right after it."""
    obj, record = remote.get(blob), ledger.get(blob)
    return (
        obj is not None
        and record is not None
        and obj.size == record.bytes
        and obj.etag is not None
        and obj.etag == record.etag
    )


# -- the pieces ---------------------------------------------------------------------------


def _encrypt_source(
    ctx: BackupContext, item: SourceObject, scratch: Path
) -> tuple[Path, Any, str | None]:
    """Encrypt one stored object; refuse it if its bytes are not the ones the
    store lists (another size, or another MD5 than its ETag states)."""
    out_path = scratch / "blob.partial"
    md5 = hashlib.md5(usedforsecurity=False)
    with open(out_path, "wb") as out, ctx.source.open(item) as stream:
        encryptor = Encryptor(ctx.recipient, out)
        head = b""
        while chunk := stream.read(_READ):
            if len(head) < 16:
                head += chunk[: 16 - len(head)]
            md5.update(chunk)
            encryptor.write(chunk)
        digest = encryptor.finish()
    if digest.plaintext_bytes != item.size or (
        item.expected_md5 is not None and md5.hexdigest() != item.expected_md5
    ):
        out_path.unlink(missing_ok=True)
        raise SourceCorrupt(item.key)
    return out_path, digest, sniff_image_type(head)


def _keep_locked(ctx: BackupContext, blob: str, record: LedgerEntry, now: datetime) -> None:
    """With an object lock, a reused blob must stay locked as long as a new
    object would: lengthen its lock when it would end too soon (BK-1)."""
    lock = ctx.destination.lock
    if lock is None:
        return
    needed = now + timedelta(days=ctx.config.object_lock_min_days)
    if record.locked_until is not None and datetime.fromisoformat(record.locked_until) >= needed:
        return
    # Whole seconds, rounded up: providers keep a lock date to the second or
    # millisecond. The bucket's own period, so a blob is lengthened again only
    # once that period minus the minimum has passed.
    target = now + timedelta(days=max(lock.days, ctx.config.object_lock_min_days))
    target = target.replace(microsecond=0) + timedelta(seconds=1)
    until = ctx.destination.extend_lock(manifest_mod.blob_key(blob), target)
    if until is None or until < needed - timedelta(seconds=1):
        raise VerificationFailed("object_not_locked", manifest_mod.blob_key(blob))
    record.locked_until = until.isoformat()


def backup_files(
    ctx: BackupContext, refs: list[FileReference], work_dir: Path, scratch: Path
) -> FilesResult:
    catalog = _load_catalog(_catalog_path(ctx, work_dir))
    ledger_path = _ledger_path(ctx, work_dir)
    ledger = _load_ledger(ledger_path)
    remote: dict[str, RemoteObject] = {
        obj.key.rsplit("/", 1)[-1]: obj for obj in ctx.destination.list("objects/")
    }
    # RN-1: a blob this service read back and recorded, now with other bytes:
    # written again by someone else (the server never rewrites a checked blob).
    changed = sorted(
        manifest_mod.blob_key(blob) for blob, record in ledger.items()
        if blob in remote and (remote[blob].size != record.bytes or remote[blob].etag != record.etag)
    )  # fmt: skip
    now = ctx.clock()
    entries: list[FileEntry] = []
    skipped: dict[str, int] = {}
    proved: set[str] = set()
    new = reused = 0

    def reuse(blob: str) -> LedgerEntry | None:
        if not _reusable(blob, remote, ledger):
            return None
        record = ledger[blob]
        if blob not in proved:
            _keep_locked(ctx, blob, record, now)
            proved.add(blob)
        return record

    try:
        for store in STORES:
            for item in ctx.source.list(store):
                if isinstance(item, Skipped):
                    skipped[item.reason] = skipped.get(item.reason, 0) + 1
                    continue
                cached = catalog.get((item.store, item.key))
                if cached and cached.fingerprint == item.fingerprint:
                    record = reuse(cached.blob)
                    if record is not None:
                        cached.ciphertext_bytes, cached.ciphertext_sha256 = (
                            record.bytes, record.sha256,
                        )  # fmt: skip
                        entries.append(cached)
                        reused += 1
                        continue
                try:
                    path, digest, content_type = _encrypt_source(ctx, item, scratch)
                except SourceMissing:
                    # Listed, then gone. If a row needs it, it is reported below.
                    skipped["vanished"] = skipped.get("vanished", 0) + 1
                    continue
                except SourceCorrupt:
                    # Not backed up as if it were good. If a row needs it, the set
                    # is incomplete, and the count says why.
                    logger.error(
                        "a stored file does not match its checksum", extra={"store": item.store}
                    )
                    skipped["corrupt"] = skipped.get("corrupt", 0) + 1
                    continue
                blob = blob_id(ctx.signing, ctx.recipient, digest.plaintext_sha256)
                record = reuse(blob)
                if record is not None and record.bytes == digest.ciphertext_bytes:
                    reused += 1
                else:
                    record = _upload_blob(ctx, blob, path, digest, remote, ledger)
                    proved.add(blob)
                    new += 1
                path.unlink(missing_ok=True)
                entries.append(
                    FileEntry(item.store, item.key, digest.plaintext_bytes,
                              digest.plaintext_sha256, content_type, blob, item.fingerprint,
                              record.bytes, record.sha256)
                )  # fmt: skip
    finally:
        # Even an interrupted run keeps what it proved, for the next run.
        _save_ledger(ledger_path, ledger)
    present = {(e.store, e.key) for e in entries}
    missing = [ref for ref in refs if (ref.store, ref.key) not in present]
    return FilesResult(entries, new, reused, missing, skipped, proved, changed)


def _upload_blob(
    ctx: BackupContext, blob: str, path: Path, digest: Any, remote: dict[str, RemoteObject],
    ledger: dict[str, LedgerEntry],
) -> LedgerEntry:  # fmt: skip
    """Upload one blob (over whatever the destination holds under its name)
    and record it only once its read-back matched."""
    ledger.pop(blob, None)
    remote.pop(blob, None)
    try:
        stored = ctx.destination.put_file(
            manifest_mod.blob_key(blob), path, digest.ciphertext_sha256
        )
    except VerificationFailed:
        # Never reused: not in the ledger, so the next run uploads it again.
        logger.error("a blob did not read back as sent; it will be uploaded again")
        raise
    if stored.etag is None:
        raise VerificationFailed("no_fingerprint", manifest_mod.blob_key(blob))
    record = LedgerEntry(digest.ciphertext_bytes, digest.ciphertext_sha256, stored.etag,
                         stored.locked_until.isoformat() if stored.locked_until else None)  # fmt: skip
    ledger[blob] = record
    remote[blob] = stored
    return record


def _encrypt_bytes_to(ctx: BackupContext, data: bytes, path: Path) -> Any:
    with open(path, "wb") as out:
        encryptor = Encryptor(ctx.recipient, out)
        encryptor.write(data)
        return encryptor.finish()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ):
            digest.update(chunk)
    return digest.hexdigest()


# -- one backup -------------------------------------------------------------------------


def run_backup(ctx: BackupContext) -> BackupOutcome:
    config = ctx.config
    work = config.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = ctx.clock()
    backup_id = manifest_mod.new_backup_id(started, secrets.token_hex(4))
    record = RunRecord(
        kind="backup", environment=config.env, destination=ctx.destination.identity,
        offsite=ctx.destination.offsite, started_at=started, backup_id=backup_id,
    )  # fmt: skip
    with backup_lock(ctx.server, config.database, work) as held:
        if not held:
            record.status, record.finished_at = "skipped", ctx.clock()
            record.details = {"reason": "another backup is running"}
            ctx.recorder.start(record)
            ctx.recorder.finish(record)
            logger.warning("backup skipped: another backup is running")
            return BackupOutcome("skipped", backup_id, "already_running")
        ctx.recorder.abandon_running("backup", started)
        ctx.recorder.start(record)
        set_dir = work / "incoming" / backup_id
        set_dir.mkdir(parents=True, mode=0o700)
        try:
            outcome = _make_set(ctx, backup_id, started, set_dir, work, record)
        except (DestinationError, DumpFailed, SourceMissing, OSError, Exception) as exc:
            outcome = _failed(ctx, exc, backup_id, set_dir, work, record)
        return outcome


def _error_code(exc: BaseException) -> tuple[str, bool]:
    if isinstance(exc, DestinationError):
        return f"destination:{exc.reason}", exc.retryable
    if isinstance(exc, DumpFailed):
        return f"database:{exc.reason}", True
    if isinstance(exc, SourceMissing):
        return "source:vanished", True
    if isinstance(exc, OSError):
        return f"local:{type(exc).__name__}", True
    return f"unexpected:{type(exc).__name__}", False


def _failed(
    ctx: BackupContext, exc: BaseException, backup_id: str, set_dir: Path, work: Path,
    record: RunRecord,
) -> BackupOutcome:  # fmt: skip
    code, retryable = _error_code(exc)
    logger.error(
        "BACKUP FAILED; the previous good backup is kept",
        extra={"backup_id": backup_id, "error_code": code},
    )
    evidence = work / "failed" / backup_id
    try:
        evidence.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if set_dir.exists():
            os.replace(set_dir, evidence)
        else:
            evidence.mkdir(mode=0o700)
        (evidence / "report.json").write_text(
            json.dumps({"backup_id": backup_id, "error_code": code, "retryable": retryable,
                        "failed_at": ctx.clock().isoformat(),
                        # On this server only, beside the evidence; never sent anywhere.
                        # Codes, SQL and paths, never a credential (the connection
                        # is never an argument).
                        "traceback": traceback.format_exception(exc)[-12:]}, indent=2),
            encoding="utf-8",
        )  # fmt: skip
        _keep_newest(work / "failed", ctx.config.failed_evidence_keep)
    except OSError:
        logger.exception("could not keep the failed backup's evidence")
    record.status, record.finished_at = "failed", ctx.clock()
    record.error_code, record.error_summary = code, f"{type(exc).__name__}"
    ctx.recorder.finish(record)
    return BackupOutcome("failed", backup_id, code, retryable)


def _keep_newest(folder: Path, keep: int) -> None:
    if not folder.is_dir():
        return
    entries = sorted(
        (p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()), reverse=True
    )
    for old in entries[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def _make_set(
    ctx: BackupContext, backup_id: str, started: datetime, set_dir: Path, work: Path,
    record: RunRecord,
) -> BackupOutcome:  # fmt: skip
    config = ctx.config
    destination = ctx.destination
    destination.check_access()
    destination.abort_stale_uploads(timedelta(hours=24))
    prefix = manifest_mod.set_prefix(backup_id)

    # 1-2. The snapshot: dump, row counts and references from one instant.
    dump_path = set_dir / "database.dump.mxb"
    with ctx.server.connect(config.database, connect_timeout=15) as snap:
        snap.execute("set transaction isolation level repeatable read, read only")
        row = snap.execute("select pg_export_snapshot(), now()").fetchone()
        assert row is not None
        snapshot, snapshot_at = str(row[0]), row[1]
        identity = database_identity(snap)
        revision = alembic_revision(snap)
        counts = row_counts(snap)
        refs = file_references(snap)
        unclassified = unclassified_references(snap)
        with open(dump_path, "wb") as out:
            dumped = dump(
                server=ctx.server, database=config.database, snapshot=snapshot,
                recipient=ctx.recipient, out=out, evidence_dir=set_dir,
                expected_tables=counts.keys(), pg_dump_command=config.pg_dump_command,
                pg_restore_command=config.pg_restore_command,
            )  # fmt: skip
        snap.rollback()
    destination.put_file(f"{prefix}/database.dump.mxb", dump_path, dumped.digest.ciphertext_sha256)

    # 3. Files, after the snapshot.
    scratch = Path(tempfile.mkdtemp(prefix="blob-", dir=set_dir))
    files = backup_files(ctx, refs, work, scratch)
    shutil.rmtree(scratch, ignore_errors=True)
    index = "\n".join(json.dumps(e.public(), sort_keys=True) for e in files.entries).encode()
    index_path = set_dir / "files.index.mxb"
    index_digest = _encrypt_bytes_to(ctx, index, index_path)
    destination.put_file(f"{prefix}/files.index.mxb", index_path, index_digest.ciphertext_sha256)
    blobs = sorted({e.blob for e in files.entries})
    blobs_path = set_dir / "blobs.txt"
    blobs_path.write_text("".join(f"{b}\n" for b in blobs), encoding="ascii")
    blobs_sha = _sha256_file(blobs_path)
    destination.put_file(f"{prefix}/blobs.txt", blobs_path, blobs_sha)

    # 4. The manifest, last. Complete only when every file is there and every
    # blob of the set passed its check (BK-3).
    unproved = sorted(set(blobs) - files.proved)
    if unproved:
        raise VerificationFailed(f"blobs_not_verified:{len(unproved)}")
    complete = not files.missing_references and unclassified == 0
    by_store = {
        store: {"objects": sum(1 for e in files.entries if e.store == store),
                "bytes": sum(e.size for e in files.entries if e.store == store)}
        for store in STORES
    }  # fmt: skip
    finished = ctx.clock()
    body: dict[str, Any] = {
        "backup_id": backup_id,
        "status": manifest_mod.STATUS_COMPLETE if complete else manifest_mod.STATUS_INCOMPLETE,
        "created_at": started.isoformat(),
        "completed_at": finished.isoformat(),
        "environment": config.env,
        "application": {"release": config.release, "alembic_revision": revision},
        "database": {
            "name": identity.name,
            "server_version": identity.server_version,
            "system_identifier": identity.system_identifier,
            "snapshot_at": snapshot_at.isoformat(),
            "format": "pg_dump custom (compressed)",
            "pg_dump_version": dumped.pg_dump_version,
            "object": f"{prefix}/database.dump.mxb",
            "plaintext_bytes": dumped.digest.plaintext_bytes,
            "plaintext_sha256": dumped.digest.plaintext_sha256,
            "ciphertext_bytes": dumped.digest.ciphertext_bytes,
            "ciphertext_sha256": dumped.digest.ciphertext_sha256,
            "tables": len(counts),
            "rows": sum(counts.values()),
            "row_counts": counts,
        },
        "files": {
            "index_object": f"{prefix}/files.index.mxb",
            "index_ciphertext_sha256": index_digest.ciphertext_sha256,
            "index_plaintext_sha256": index_digest.plaintext_sha256,
            "blobs_object": f"{prefix}/blobs.txt",
            "blobs_sha256": blobs_sha,
            "blob_count": len(blobs),
            "object_count": len(files.entries),
            "total_bytes": sum(e.size for e in files.entries),
            "stores": by_store,
            "referenced": len(refs),
            "missing_references": len(files.missing_references),
            "missing_by_kind": _by_kind(files.missing_references),
            "unclassified_references": unclassified,
            "new_blobs": files.new_blobs,
            "reused_blobs": files.reused_blobs,
            "verified_blobs": len(files.proved & set(blobs)),
            "skipped": files.skipped,
        },
        "encryption": {
            "format": FORMAT_NAME,
            "recipient_key_id": ctx.recipient.key_id,
            "signing_key_id": ctx.signing.key_id,
        },
        "destination": {"identity": destination.identity, "offsite": destination.offsite},
        "verification": {
            "database_dump": "pg_restore_list_ok",
            "uploads": "read_back_sha256_ok",
            # Every blob: read back now, or the same size and ETag as when it was.
            "blobs": "read_back_or_unchanged_since_read_back",
            "object_lock_days": destination.lock.days if destination.lock else None,
            "references": "complete" if complete else "missing",
        },
    }
    manifest_bytes = manifest_mod.encode(body, ctx.signing)
    manifest_path = set_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    destination.put_file(
        manifest_mod.manifest_key(backup_id), manifest_path, _sha256_file(manifest_path)
    )

    # RN-1: has anything at the destination been written again since?
    overwritten, overwrite_check = _overwrites(destination, files.overwritten)
    # BK-4: the outside heartbeat, after a verified set only.
    beat = _heartbeat(config) if complete else "not_sent:incomplete"

    # Recorded, and the local copy kept (only the last few, only verified ones).
    status = "succeeded" if complete else "incomplete"
    record.status, record.finished_at = status, finished
    record.verified = complete
    record.database_bytes = dumped.digest.ciphertext_bytes
    record.object_count, record.object_bytes = len(files.entries), body["files"]["total_bytes"]
    record.new_objects = files.new_blobs
    record.details = {
        "release": config.release, "alembic_revision": revision, "tables": len(counts),
        "rows": sum(counts.values()), "referenced": len(refs),
        "missing_references": len(files.missing_references), "skipped": files.skipped,
        "recipient_key_id": ctx.recipient.key_id,
        "overwritten": {"count": len(overwritten), "keys": overwritten[:20]},
        "overwrite_check": overwrite_check, "heartbeat": beat,
    }  # fmt: skip
    if not complete:
        record.error_code = (
            "missing_references" if files.missing_references else "unclassified_references"
        )
    ctx.recorder.finish(record)
    _save_catalog(_catalog_path(ctx, work), files.entries)
    (set_dir / "remote-verified").write_text(finished.isoformat(), encoding="ascii")
    local_sets = work / "sets"
    local_sets.mkdir(exist_ok=True, mode=0o700)
    os.replace(set_dir, local_sets / backup_id)
    _prune_local_sets(local_sets, config.local_keep_sets)
    if complete:
        write_status(work, backup_id, finished, destination.offsite)
    logger.info(
        "backup %s", status,
        extra={"backup_id": backup_id, "objects": len(files.entries),
               "new_blobs": files.new_blobs, "database_bytes": dumped.digest.ciphertext_bytes},
    )  # fmt: skip
    return BackupOutcome(status, backup_id, record.error_code, False, body)


def _heartbeat(config: BackupConfig) -> str:
    """BK-4: the outside heartbeat; nothing it does can fail a good set."""
    try:
        return heartbeat.ping(config.heartbeat, timeout=config.heartbeat_timeout_seconds)
    except Exception as exc:
        logger.error("the outside heartbeat failed", extra={"error_code": type(exc).__name__})
        return f"failed:{type(exc).__name__}"


def _overwrites(destination: Destination, changed_blobs: list[str]) -> tuple[list[str], str]:
    """Objects at the destination written again since they were made (RN-1):
    every piece of every set is written exactly once, so any of them with a
    second, different version (or hidden by a delete marker) was written by
    someone else; and every blob whose bytes changed since this service
    checked it. Returns them, and "ok" or why the versions could not be read
    (the server's key needs s3:ListBucketVersions)."""
    copies = Copies(destination)
    copies.scan("sets/")
    found = sorted(copies.overwritten | set(changed_blobs))
    if found:
        logger.error(
            "BACKUP FILES WERE WRITTEN AGAIN at the destination; the older locked copies are "
            "kept (docs/runbooks/backup-and-restore.md, 'A backup file was overwritten')",
            extra={"count": len(found)},
        )
    return found, ("ok" if not copies.notes else f"unavailable: {copies.notes[0]}")


def _by_kind(refs: list[FileReference]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ref in refs:
        counts[ref.kind] = counts.get(ref.kind, 0) + 1
    return counts


def _prune_local_sets(folder: Path, keep: int) -> None:
    """Local copies are a convenience, never the backup: only copies whose
    remote set was verified are ever removed, newest `keep` kept."""
    verified = sorted(
        (p for p in folder.iterdir() if p.is_dir() and (p / "remote-verified").exists()),
        reverse=True,
    )
    for old in verified[keep:]:
        shutil.rmtree(old, ignore_errors=True)


# -- the status file the container's health check reads ----------------------------------


def write_status(work: Path, backup_id: str, at: datetime, offsite: bool) -> None:
    path = work / "status.json"
    tmp = path.with_name("status.json.tmp")
    tmp.write_text(
        json.dumps({"last_verified_backup_id": backup_id, "last_verified_at": at.isoformat(),
                    "offsite": offsite}),
        encoding="utf-8",
    )  # fmt: skip
    os.replace(tmp, path)


def health(config: BackupConfig, now: datetime) -> tuple[bool, str]:
    """Healthy: a verified set newer than `max_age_hours`, and off-server on a real server."""
    try:
        status = json.loads((config.work_dir / "status.json").read_text(encoding="utf-8"))
        at = datetime.fromisoformat(status["last_verified_at"])
    except (FileNotFoundError, ValueError, KeyError):
        return False, "no verified backup yet"
    if config.is_real_environment and not status.get("offsite"):
        return False, "the last verified backup is not off-server"
    age = now - at
    if age > timedelta(hours=config.max_age_hours):
        return False, f"the last verified backup is {age.total_seconds() / 3600:.1f} hours old"
    return True, f"last verified backup {status['last_verified_backup_id']}"


# -- the scheduled service ---------------------------------------------------------------


@dataclass(slots=True)
class Attempts:
    outcomes: list[BackupOutcome] = field(default_factory=list)


def run_with_retries(
    run: Callable[[], BackupOutcome], *, attempts: int, delay_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Attempts:  # fmt: skip
    """Retry a failed backup when retrying may help, waiting longer each time.
    Each attempt is its own recorded run with its own final status."""
    result = Attempts()
    for attempt in range(1, attempts + 1):
        outcome = run()
        result.outcomes.append(outcome)
        if outcome.status != "failed" or not outcome.retryable or attempt == attempts:
            break
        sleep(delay_seconds * attempt)
    return result


def seconds_until(hour: int, now: datetime) -> float:
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


__all__ = [
    "BackupContext",
    "BackupOutcome",
    "DestinationUnavailable",
    "health",
    "run_backup",
    "run_with_retries",
    "seconds_until",
]
