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

from markx.backup import manifest as manifest_mod
from markx.backup.config import BackupConfig
from markx.backup.crypto import RecoveryKey, SignerKey, generate_keys
from markx.backup.database import PgServer, database_exists, drop_database
from markx.backup.destination import (
    Destination,
    DestinationError,
    LocalDestination,
)
from markx.backup.records import Recorder, RunRecord
from markx.backup.restore import (
    FileTargets,
    Report,
    SetRefused,
    list_sets,
    read_manifest,
    restore_set,
    verify_set,
)
from markx.backup.runner import BackupContext, run_backup
from markx.core.storage import (
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStorageSettings,
    S3ObjectStore,
    make_s3_client,
)


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

    def text(self) -> str:
        lines = [f"RECOVERY DRILL of set {self.backup_id}"]
        if self.restore is not None:
            lines.append(self.restore.text())
        for name, ok, detail in self.injections:
            lines.append(
                f"  {'ok  ' if ok else 'FAIL'}  injected: {name}{': ' + detail if detail else ''}"
            )
        lines += [f"  note: {note}" for note in self.notes]
        lines.append("DRILL PASSED" if self.passed else "DRILL FAILED")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "backup_id": self.backup_id,
                "restore": self.restore.as_dict() if self.restore else None,
                "injections": [{"name": n, "refused": ok, "detail": d} for n, ok, d in self.injections],
                "notes": self.notes, "kind": self.kind, "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None}  # fmt: skip


class DrillRefused(Exception):
    """The drill must not run here."""


def refuse_on_a_server(config: BackupConfig) -> None:
    if config.is_real_environment:
        raise DrillRefused(
            f"a drill never runs on {config.env} (BK-2): run it on a separate recovery machine "
            "(docs/runbooks/backup-and-restore.md, 'The monthly drill')"
        )


# -- the injection copy, in a local folder ------------------------------------------------


def _copy(source: Destination, target: Destination, key: str, scratch: Path) -> None:
    path = scratch / "copy"
    digest = hashlib.sha256()
    with source.reader(key) as stream, path.open("wb") as out:
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
) -> list[tuple[str, bool, str]]:  # fmt: skip
    """Each case on a fresh LOCAL copy of the set; True means it was refused
    as it must be. Nothing is written to, or deleted from, `destination`."""
    results: list[tuple[str, bool, str]] = []
    pristine_root, case_root = scratch / "pristine", scratch / "case"
    pristine = LocalDestination(pristine_root, prefix="markx")
    set_keys = [o.key for o in destination.list(f"{manifest_mod.set_prefix(backup_id)}/")]
    blob_keys = sorted({manifest_mod.blob_key(b) for b in _blob_ids(destination, manifest)})
    for key in set_keys + blob_keys:
        _copy(destination, pristine, key, scratch)
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
        expect_refused("one byte of the encrypted dump changed",
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "altered_piece")  # fmt: skip

        fresh()
        data = copy.read_bytes(index_key, limit=2**31)
        _replace(copy, index_key, data[: len(data) // 2], scratch)
        expect_refused("the file index cut short",
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "altered_piece")  # fmt: skip

        fresh()
        copy.delete(manifest_key)
        expect_refused("the manifest missing (an unfinished set)",
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "no_manifest")  # fmt: skip

        fresh()
        edited = json.loads(copy.read_bytes(manifest_key, limit=2**24))
        edited["database"]["rows"] = int(edited["database"]["rows"]) + 1
        _replace(copy, manifest_key, json.dumps(edited).encode(), scratch)
        expect_refused("the manifest edited",
                       verify_set(destination=copy, backup_id=backup_id, signers=signers, keys=keys,
                                  deep=False), "signature")  # fmt: skip

        if blob_keys:
            fresh()
            copy.delete(blob_keys[0])
            expect_refused("a file's blob missing",
                           verify_set(destination=copy, backup_id=backup_id, signers=signers,
                                      keys=keys, deep=True), "1 missing")  # fmt: skip

        fresh()
        stranger = generate_keys().recovery
        expect_refused("a wrong recovery key",
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
        results.append(("a restore of an altered set writes nothing",
                        not report.passed and not exists, "no database created" if not exists else
                        "A DATABASE WAS CREATED"))  # fmt: skip
    finally:
        shutil.rmtree(case_root, ignore_errors=True)
        shutil.rmtree(pristine_root, ignore_errors=True)
    return results


def _blob_ids(destination: Destination, manifest: dict[str, Any]) -> list[str]:
    data = destination.read_bytes(manifest["files"]["blobs_object"], limit=256 * 1024 * 1024)
    return [line for line in data.decode("ascii").splitlines() if line]


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


def _drill_set(
    result: DrillResult, destination: Destination, backup_id: str, manifest: dict[str, Any], *,
    config: BackupConfig, superuser: PgServer, keys: dict[str, RecoveryKey],
    signers: list[SignerKey], bootstrap_script: Path, inject: bool, target_db: str,
    scratch: Path, targets: DisposableTargets,
) -> None:  # fmt: skip
    """Steps 2 to 5 for one set: deep verify, restore, compare, inject."""
    deep = verify_set(destination=destination, backup_id=backup_id, signers=signers, keys=keys,
                      deep=True)  # fmt: skip
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
    if inject:
        result.injections = inject_failures(
            destination, backup_id, signers=signers, keys=keys, manifest=manifest,
            scratch=scratch, server=superuser, bootstrap_script=bootstrap_script,
            psql_command=config.psql_command, pg_restore_command=config.pg_restore_command,
        )  # fmt: skip
    result.passed = result.restore.passed and all(ok for _, ok, _ in result.injections)


def _cleanup(
    result: DrillResult, superuser: PgServer, target_db: str, targets: DisposableTargets | None,
    scratch: Path,
) -> None:  # fmt: skip
    result.finished_at = datetime.now(UTC)
    if database_exists(superuser, target_db):
        drop_database(superuser, target_db)
        result.notes.append(f"drill database {target_db} dropped")
    if targets is not None:
        for step in targets.cleanup:
            step()
        result.notes.append(f"drill file targets removed ({targets.targets.description})")
    shutil.rmtree(scratch, ignore_errors=True)


def newest_complete_set(destination: Destination, signers: list[SignerKey]) -> str | None:
    """The newest set whose manifest verifies and says complete."""
    for backup_id in list_sets(destination):
        try:
            body = read_manifest(destination, backup_id, signers)
        except SetRefused:
            continue
        if body.get("status") == manifest_mod.STATUS_COMPLETE:
            return backup_id
    return None


def run_offsite_drill(
    config: BackupConfig, destination: Destination, *, superuser: PgServer,
    keys: dict[str, RecoveryKey], signers: list[SignerKey], bootstrap_script: Path,
    inject: bool = True, backup_id: str | None = None,
) -> DrillResult:  # fmt: skip
    """The monthly drill on a separate recovery machine (BK-2): no backup is
    taken and nothing is written to the bucket, so the bucket's read-only
    key, the recovery key and the signer PUBLIC key are all it needs. The
    newest complete set (or `backup_id`) is verified in full, restored into
    a NEW database on `superuser`'s server (a throwaway container) and a
    temporary folder, compared, and put through the injected failures."""
    refuse_on_a_server(config)
    started = datetime.now(UTC)
    result = DrillResult(False, None, None, started_at=started, kind="offsite")
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
            manifest = read_manifest(destination, chosen, signers)
        except SetRefused as exc:
            result.notes.append(f"the set was refused: {exc.reason}")
            return result
        targets = _folder_targets(scratch, frozenset())
        _drill_set(result, destination, chosen, manifest, config=config, superuser=superuser,
                   keys=keys, signers=signers, bootstrap_script=bootstrap_script, inject=inject,
                   target_db=target_db, scratch=scratch, targets=targets)  # fmt: skip
        result.notes.append(f"set made at {manifest.get('created_at')}, off-server drill")
        return result
    except DestinationError as exc:
        result.notes.append(f"the destination failed: {exc.reason}")
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
