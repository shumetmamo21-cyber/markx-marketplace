"""The automated recovery drill (D-094; blueprint F.13 "a restore drill every
month", H.7 "a backup restored successfully into a fresh database").

    1. take a real backup set of the source database and stores;
    2. verify it at the destination, every blob decrypted and hashed;
    3. restore it into a NEW database and new, empty file targets;
    4. compare: the migration version, every table's row count, every file's
       checksum, every database file reference, the private target's privacy
       and the audit log's protection (restore.py);
    5. with failure injection: copy the set under a separate drill prefix and
       prove that a changed dump, a cut-short index, a missing manifest, an
       edited manifest, a missing blob and a wrong recovery key are each
       REFUSED, and that a restore refused this way writes nothing;
    6. remove only what the drill itself created: its database, its file
       targets, its injection copies. Never the set it made (that is a real
       backup), never a source.

On a laptop and in CI the file targets are two fresh MinIO buckets when the
source is MinIO, otherwise a temporary folder. On a server, files are
restored into a temporary folder: the drill never needs a new paid bucket.
The result is recorded in `backup_runs` (kind `drill`) for the watch.
"""

from __future__ import annotations

import json
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
    LocalDestination,
    S3Destination,
)
from markx.backup.records import Recorder, RunRecord
from markx.backup.restore import FileTargets, Report, restore_set, verify_set
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
                "notes": self.notes}  # fmt: skip


# -- the injection copy ------------------------------------------------------------------


def _sibling(destination: Destination, prefix: str) -> Destination:
    """The same destination under another prefix: where injections happen."""
    if isinstance(destination, LocalDestination):
        return LocalDestination(destination._root, prefix=prefix)
    assert isinstance(destination, S3Destination)
    return S3Destination(
        destination._settings, prefix=prefix, offsite=destination.offsite,
        identity=f"{destination.identity}-drill", client=destination._client,
    )  # fmt: skip


def _copy(source: Destination, target: Destination, key: str, scratch: Path) -> None:
    path = scratch / "copy"
    import hashlib

    digest = hashlib.sha256()
    with source.reader(key) as stream, path.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            out.write(chunk)
    target.put_file(key, path, digest.hexdigest())
    path.unlink()


def _replace(target: Destination, key: str, data: bytes, scratch: Path) -> None:
    import hashlib

    path = scratch / "replaced"
    path.write_bytes(data)
    target.put_file(key, path, hashlib.sha256(data).hexdigest())
    path.unlink()


def _clear(target: Destination) -> None:
    for obj in list(target.list("")):
        target.delete(obj.key)


def inject_failures(
    destination: Destination, backup_id: str, *, signers: list[SignerKey],
    keys: dict[str, RecoveryKey], manifest: dict[str, Any], scratch: Path,
    server: PgServer, bootstrap_script: Path, psql_command: str, pg_restore_command: str,
) -> list[tuple[str, bool, str]]:  # fmt: skip
    """Each case on a fresh copy of the set; True means it was refused as it must be."""
    results: list[tuple[str, bool, str]] = []
    prefix = getattr(destination, "_prefix", "markx")
    copy = _sibling(destination, f"{prefix}-drill-{secrets.token_hex(4)}")
    set_keys = [o.key for o in destination.list(f"{manifest_mod.set_prefix(backup_id)}/")]
    blob_keys = sorted({manifest_mod.blob_key(b) for b in _blob_ids(destination, manifest)})

    def fresh() -> None:
        _clear(copy)
        for key in set_keys + blob_keys:
            _copy(destination, copy, key, scratch)

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
        _clear(copy)
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
        target = ObjectStorageSettings(
            provider="minio", endpoint_url=settings.endpoint_url, region=settings.region,
            access_key_id=settings.access_key_id, secret_access_key=settings.secret_access_key,
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


def run_drill(
    ctx: BackupContext, *, superuser: PgServer, keys: dict[str, RecoveryKey],
    signers: list[SignerKey], bootstrap_script: Path, inject: bool, record: bool = True,
) -> DrillResult:  # fmt: skip
    config = ctx.config
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
        deep = verify_set(destination=ctx.destination, backup_id=str(outcome.backup_id),
                          signers=signers, keys=keys, deep=True)  # fmt: skip
        if not deep.passed:
            result.restore = deep
            result.notes.append("the set did not verify at the destination")
            return result
        disposable = disposable_file_targets(config, scratch)
        result.restore = restore_set(
            destination=ctx.destination, backup_id=str(outcome.backup_id), signers=signers,
            keys=keys, server=superuser, target_db=target_db, confirm=target_db,
            files=disposable.targets, bootstrap_script=bootstrap_script,
            psql_command=config.psql_command, pg_restore_command=config.pg_restore_command,
        )  # fmt: skip
        if inject:
            result.injections = inject_failures(
                ctx.destination, str(outcome.backup_id), signers=signers, keys=keys,
                manifest=outcome.manifest, scratch=scratch, server=superuser,
                bootstrap_script=bootstrap_script, psql_command=config.psql_command,
                pg_restore_command=config.pg_restore_command,
            )  # fmt: skip
        result.passed = result.restore.passed and all(ok for _, ok, _ in result.injections)
        return result
    finally:
        if database_exists(superuser, target_db):
            drop_database(superuser, target_db)
            result.notes.append(f"drill database {target_db} dropped")
        if disposable is not None:
            for step in disposable.cleanup:
                step()
            result.notes.append(f"drill file targets removed ({disposable.targets.description})")
        shutil.rmtree(scratch, ignore_errors=True)
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
