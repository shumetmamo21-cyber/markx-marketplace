"""Backup trust hardening (D-096): the audit's BK-1, BK-2, BK-3, BK-6, BK-7
and BK-17, proved against a real PostgreSQL 17 and MinIO.

- BK-1: the server's backup key cannot delete anything; the service never
  runs retention; a bucket without a COMPLIANCE object lock is refused where
  one is required; every object of a set is locked, a reused blob's lock is
  lengthened; retention, with its own key, removes every version and leaves
  what a lock still holds.
- BK-3: an upload whose read-back failed, or an object changed at the
  destination since its check, is never reused: the next run uploads it
  again; the index records each blob's encrypted size and SHA-256.
- BK-2: the drill from the destination needs only a read-only key and
  writes nothing to the bucket; the off-server drill's report is entered on
  the server for the watch.
- BK-6: a forged dump that runs a program when restored by a superuser is
  refused when restored, as MarkX restores, by the owner role.
- BK-7: a restore never resets the password of a role that already exists.

Some tests leave a bucket behind that MinIO refuses to remove for a day or
two: its objects are under a COMPLIANCE lock, by design. They are tiny and
hold only generated data; CI's MinIO is discarded after each run.
"""

# The shared fixtures are imported from test_backup_recovery; a test naming one
# as a parameter is not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.backup import crypto
from markx.backup import manifest as manifest_mod
from markx.backup.database import (
    RestoreFailed,
    create_database,
    database_exists,
    drop_database,
)
from markx.backup.database import restore as pg_restore
from markx.backup.destination import DestinationError, S3Destination, VerificationFailed
from markx.backup.drill import run_offsite_drill
from markx.backup.models import BackupRun
from markx.backup.records import Recorder
from markx.backup.restore import list_sets, verify_set
from markx.backup.retention import prune
from markx.backup.runner import run_backup
from markx.core.storage import ObjectStorageSettings, make_s3_client
from tests.conftest import _PG_HOST, _PG_PORT, _PG_SUPERPASS, _PG_SUPERUSER
from tests.storage.conftest import _scratch_buckets
from tests.storage.test_backup_recovery import (  # noqa: F401  (fixtures)
    BOOTSTRAP,
    DATABASE,
    MIGRATOR,
    SUPERUSER,
    Setup,
    _as,
    _destination,
    _listing,
    _marketplace,
    _restore,
    _targets,
    backup_bucket,
    keys,
    restored_db,
    setup,
    tools,
    users,
)


def _restricted(setup: Setup) -> None:
    if not setup.users.restricted:
        pytest.skip("needs the least-privilege MinIO users (infra/backup/minio-least-privilege.sh)")


def _root(minio: ObjectStorageSettings) -> Any:
    return make_s3_client(minio)


def _locked_bucket(minio: ObjectStorageSettings, *, days: int, mode: str = "COMPLIANCE") -> str:
    """A backup bucket with S3 Object Lock and a default retention."""
    name = f"markx-test-backups-lock-{secrets.token_hex(4)}"
    client = _root(minio)
    client.create_bucket(Bucket=name, ObjectLockEnabledForBucket=True)
    client.put_object_lock_configuration(
        Bucket=name,
        ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": mode, "Days": days}},  # type: ignore[typeddict-item]
        },
    )
    client.close()
    _scratch_buckets.append(name)
    return name


def _versioned_bucket(minio: ObjectStorageSettings) -> str:
    name = f"markx-test-backups-ver-{secrets.token_hex(4)}"
    client = _root(minio)
    client.create_bucket(Bucket=name)
    client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    client.close()
    _scratch_buckets.append(name)
    return name


def _on_bucket(setup: Setup, bucket: str, *, lock_min_days: int | None = None) -> Setup:
    """The same setup, writing to another backup bucket."""
    writer = S3Destination(
        replace(_as(setup.minio, setup.users.writer), private_bucket=bucket, public_bucket=bucket),
        prefix="markx/test", offsite=False, identity=f"minio:test/{bucket}/markx/test",
        lock_min_days=lock_min_days,
    )  # fmt: skip
    config = setup.ctx.config
    if lock_min_days is not None:
        config = config.model_copy(
            update={"require_object_lock": True, "object_lock_min_days": lock_min_days}
        )
    return replace(
        setup,
        ctx=replace(setup.ctx, destination=writer, config=config),
        destination=writer,
        reader=_destination(_as(setup.minio, setup.users.reader), bucket),
        retention=_destination(_as(setup.minio, setup.users.retention), bucket),
        bucket=bucket,
    )


def _versions(minio: ObjectStorageSettings, bucket: str, prefix: str = "") -> list[dict[str, Any]]:
    client = _root(minio)
    found: list[dict[str, Any]] = []
    for page in client.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        found += page.get("Versions", []) + page.get("DeleteMarkers", [])
    client.close()
    return found


# -- BK-1: the server cannot delete a backup -------------------------------------------------


def test_the_servers_backup_key_can_add_read_and_list_but_never_delete(
    setup: Setup, db: DbSession
) -> None:
    _restricted(setup)
    _marketplace(db)
    assert run_backup(setup.ctx).status == "succeeded"  # an older set retention would want
    later = datetime.now(UTC) + timedelta(minutes=1)
    outcome = run_backup(replace(setup.ctx, clock=lambda: later))
    assert outcome.status == "succeeded", outcome.error_code
    objects = [o.key for o in setup.destination.list("")]
    assert any(k.startswith("objects/") for k in objects)
    assert any(k.endswith("/manifest.json") for k in objects)
    writer = make_s3_client(_as(setup.minio, setup.users.writer))
    for key in objects:
        with pytest.raises(ClientError) as refused:
            writer.delete_object(Bucket=setup.bucket, Key=f"markx/test/{key}")
        assert refused.value.response["Error"]["Code"] == "AccessDenied"
    # A multi-object delete is refused object by object (the answer is 200).
    answer = writer.delete_objects(
        Bucket=setup.bucket, Delete={"Objects": [{"Key": f"markx/test/{objects[0]}"}]}
    )
    assert [e["Code"] for e in answer.get("Errors", [])] == ["AccessDenied"]
    assert not answer.get("Deleted")
    writer.close()
    # Retention needs a delete right the server's key does not have.
    with pytest.raises(DestinationError):
        prune(setup.destination, setup.signers, now=datetime.now(UTC) + timedelta(days=400),
              retention_days=1, min_sets=1, grace=timedelta(hours=48), execute=True)  # fmt: skip
    # Everything is still there, and the recovery machine's key may only read.
    assert sorted(o.key for o in setup.destination.list("")) == sorted(objects)
    reader = make_s3_client(_as(setup.minio, setup.users.reader))
    with pytest.raises(ClientError):
        reader.put_object(Bucket=setup.bucket, Key="markx/test/sets/x", Body=b"x")
    with pytest.raises(ClientError):
        reader.delete_object(Bucket=setup.bucket, Key=f"markx/test/{objects[0]}")
    reader.close()
    assert verify_set(destination=setup.reader, backup_id=str(outcome.backup_id),
                      signers=setup.signers, keys=setup.ring, deep=True).passed  # fmt: skip


def test_a_required_object_lock_is_checked_and_a_bucket_without_one_is_refused(
    setup: Setup,
) -> None:
    writer = _as(setup.minio, setup.users.writer)

    def check(bucket: str, min_days: int) -> S3Destination:
        destination = S3Destination(
            replace(writer, private_bucket=bucket, public_bucket=bucket), prefix="markx/test",
            offsite=False, identity="t", lock_min_days=min_days,
        )  # fmt: skip
        destination.check_access()
        return destination

    with pytest.raises(DestinationError, match="object_lock_missing"):
        check(setup.bucket, 1)  # a plain bucket
    with pytest.raises(DestinationError, match="object_lock_missing"):
        check(_versioned_bucket(setup.minio), 1)  # versioning alone is not a lock
    with pytest.raises(DestinationError, match="object_lock_not_compliance:GOVERNANCE"):
        check(_locked_bucket(setup.minio, days=1, mode="GOVERNANCE"), 1)
    locked = _locked_bucket(setup.minio, days=1)
    with pytest.raises(DestinationError, match="object_lock_too_short:1<30"):
        check(locked, 30)
    assert check(locked, 1).lock is not None
    # Not asked for, nothing is checked (a laptop).
    S3Destination(replace(writer, private_bucket=setup.bucket, public_bucket=setup.bucket),
                  prefix="markx/test", offsite=False, identity="t").check_access()  # fmt: skip


def test_in_a_locked_bucket_every_object_is_locked_and_a_reused_blob_stays_locked(
    setup: Setup, db: DbSession
) -> None:
    """And retention, with its own key, leaves a locked set whole."""
    _restricted(setup)
    _marketplace(db)
    locked = _on_bucket(setup, _locked_bucket(setup.minio, days=1), lock_min_days=1)
    first = run_backup(locked.ctx)
    assert first.status == "succeeded", first.error_code
    assert first.manifest["verification"]["object_lock_days"] == 1
    soon = datetime.now(UTC) + timedelta(hours=23)
    for obj in locked.destination.list(""):
        head = locked.destination.head(obj.key)
        assert head is not None
        assert head.locked_until is not None
        assert head.locked_until > soon
    blob = sorted(o.key for o in locked.destination.list("objects/"))[0]
    etag_before = locked.destination.head(blob).etag  # type: ignore[union-attr]

    # A day later (by the backup's clock), every reused blob must be locked
    # for a day from then: its lock is lengthened, its bytes untouched.
    later = datetime.now(UTC) + timedelta(days=1)
    second = run_backup(replace(locked.ctx, clock=lambda: later))
    assert second.status == "succeeded", second.error_code
    assert second.manifest["files"]["new_blobs"] == 0
    head = locked.destination.head(blob)
    assert head is not None
    assert head.locked_until is not None
    assert head.locked_until >= later + timedelta(days=1) - timedelta(minutes=5)
    assert head.etag == etag_before
    # The server's key can lengthen a lock, never shorten it.
    writer = make_s3_client(_as(setup.minio, setup.users.writer))
    with pytest.raises(ClientError):
        writer.put_object_retention(
            Bucket=locked.bucket, Key=f"markx/test/{blob}",
            Retention={"Mode": "COMPLIANCE", "RetainUntilDate": datetime.now(UTC) + timedelta(hours=1)},
        )  # fmt: skip
    writer.close()

    # Retention (its own key) wants the older set gone; the lock holds it whole.
    plan = prune(locked.retention, setup.signers, now=datetime.now(UTC) + timedelta(days=30),
                 retention_days=1, min_sets=1, grace=timedelta(hours=48), execute=True)  # fmt: skip
    assert plan.delete_sets == [str(first.backup_id)]
    assert manifest_mod.manifest_key(str(first.backup_id)) in plan.held
    assert any("object lock" in note for note in plan.notes)
    assert sorted(list_sets(locked.reader)) == sorted([str(first.backup_id), str(second.backup_id)])
    for backup_id in (first.backup_id, second.backup_id):
        assert verify_set(destination=locked.reader, backup_id=str(backup_id),
                          signers=setup.signers, keys=setup.ring, deep=False).passed  # fmt: skip


def test_retention_removes_every_version_and_leaves_no_delete_marker(
    setup: Setup, db: DbSession
) -> None:
    _restricted(setup)
    _marketplace(db)
    versioned = _on_bucket(setup, _versioned_bucket(setup.minio))
    old = run_backup(versioned.ctx)
    later = datetime.now(UTC) + timedelta(minutes=1)
    new = run_backup(replace(versioned.ctx, clock=lambda: later))
    assert (old.status, new.status) == ("succeeded", "succeeded")
    # A blob no set needs, already hidden behind a delete marker by a plain
    # delete (as the old retention left them on a versioned bucket).
    orphan = manifest_mod.blob_key("ab" * 32)
    root = _root(setup.minio)
    root.put_object(Bucket=versioned.bucket, Key=f"markx/test/{orphan}", Body=b"x")
    root.delete_object(Bucket=versioned.bucket, Key=f"markx/test/{orphan}")
    root.close()
    assert len(_versions(setup.minio, versioned.bucket, f"markx/test/{orphan}")) == 2

    plan = prune(versioned.retention, setup.signers, now=datetime.now(UTC) + timedelta(days=30),
                 retention_days=1, min_sets=1, grace=timedelta(hours=48), execute=True)  # fmt: skip
    assert plan.delete_sets == [str(old.backup_id)]
    assert orphan in plan.delete_hidden
    assert plan.held == []
    # Gone in every version: nothing hidden, nothing still paid for.
    assert _versions(setup.minio, versioned.bucket, f"markx/test/sets/{old.backup_id}/") == []
    assert _versions(setup.minio, versioned.bucket, f"markx/test/{orphan}") == []
    # The kept set is whole and restorable.
    assert list_sets(versioned.reader) == [str(new.backup_id)]
    assert verify_set(destination=versioned.reader, backup_id=str(new.backup_id),
                      signers=setup.signers, keys=setup.ring, deep=True).passed  # fmt: skip


# -- BK-3: a damaged upload is never reused --------------------------------------------------


def test_a_blob_whose_upload_failed_its_check_is_uploaded_again_by_the_next_run(
    setup: Setup, db: DbSession, monkeypatch: pytest.MonkeyPatch, restored_db: str
) -> None:
    """The audit's regression test: an upload arrives damaged, its read-back
    fails, the server cannot delete it; the next run must not reuse it."""
    _marketplace(db)
    real_put = setup.destination.put_file
    damaged: dict[str, bytes] = {}

    def arrives_damaged(key: str, path: Path, sha256: str) -> Any:
        if key.startswith("objects/") and not damaged:
            data = bytearray(path.read_bytes())
            data[len(data) // 2] ^= 0x01  # one byte changed on the way
            bad = path.with_name("damaged")
            bad.write_bytes(bytes(data))
            damaged[key] = bytes(data)
            return real_put(key, bad, sha256)  # what was SENT has this hash
        return real_put(key, path, sha256)

    monkeypatch.setattr(setup.destination, "put_file", arrives_damaged)
    failed = run_backup(setup.ctx)
    assert (failed.status, failed.error_code) == ("failed", "destination:readback_mismatch")
    ((key, bad),) = damaged.items()
    # The damaged object is still at the destination: nothing may delete it.
    assert setup.destination.read_bytes(key, limit=2**30) == bad
    monkeypatch.setattr(setup.destination, "put_file", real_put)

    again = run_backup(setup.ctx)
    assert again.status == "succeeded", again.error_code
    assert again.manifest["files"]["new_blobs"] >= 1
    assert again.manifest["files"]["verified_blobs"] == again.manifest["files"]["blob_count"]
    assert setup.destination.read_bytes(key, limit=2**30) != bad
    backup_id = str(again.backup_id)
    assert verify_set(destination=setup.reader, backup_id=backup_id, signers=setup.signers,
                      keys=setup.ring, deep=True).passed  # fmt: skip
    report = _restore(setup, backup_id, restored_db, _targets(setup.minio))
    assert report.passed, report.text()


def test_a_blob_changed_at_the_destination_since_its_check_is_uploaded_again(
    setup: Setup, db: DbSession
) -> None:
    """Same size, other bytes (and so another ETag): never reused by name."""
    _marketplace(db)
    first = run_backup(setup.ctx)
    assert first.status == "succeeded"
    blob = sorted(o.key for o in setup.destination.list("objects/"))[0]
    data = bytearray(setup.destination.read_bytes(blob, limit=2**30))
    data[-1] ^= 0x01
    root = _root(setup.minio)
    root.put_object(Bucket=setup.bucket, Key=f"markx/test/{blob}", Body=bytes(data))
    root.close()

    second = run_backup(setup.ctx)
    assert second.status == "succeeded"
    assert second.manifest["files"]["new_blobs"] == 1  # that blob, and only that one
    assert setup.destination.read_bytes(blob, limit=2**30) != bytes(data)
    deep = verify_set(destination=setup.reader, backup_id=str(second.backup_id),
                      signers=setup.signers, keys=setup.ring, deep=True)  # fmt: skip
    assert deep.passed, deep.text()
    # The first set's blob was mended too: it decrypts to the same file.
    deep_first = verify_set(destination=setup.reader, backup_id=str(first.backup_id),
                            signers=setup.signers, keys=setup.ring, deep=True)  # fmt: skip
    assert deep_first.passed, deep_first.text()
    assert "uploaded again since and intact" in deep_first.text()


def test_the_index_records_each_blobs_encrypted_size_and_hash(setup: Setup, db: DbSession) -> None:
    _marketplace(db)
    outcome = run_backup(setup.ctx)
    files = outcome.manifest["files"]
    data = setup.reader.read_bytes(files["index_object"], limit=2**30)
    index = b"".join(crypto.decrypt_stream(io.BytesIO(data), setup.ring))
    entries = [json.loads(line) for line in index.decode().splitlines() if line]
    assert entries
    for entry in entries:
        stored = setup.reader.read_bytes(manifest_mod.blob_key(entry["blob"]), limit=2**30)
        assert entry["ciphertext_bytes"] == len(stored)
        assert entry["ciphertext_sha256"] == hashlib.sha256(stored).hexdigest()
    # A blob cut short is caught by the ordinary verify, without decrypting.
    victim = manifest_mod.blob_key(entries[0]["blob"])
    stored = setup.reader.read_bytes(victim, limit=2**30)
    root = _root(setup.minio)
    root.put_object(Bucket=setup.bucket, Key=f"markx/test/{victim}", Body=stored[:-1])
    root.close()
    shallow = verify_set(destination=setup.reader, backup_id=str(outcome.backup_id),
                         signers=setup.signers, keys=setup.ring, deep=False)  # fmt: skip
    assert not shallow.passed
    assert "1 damaged" in shallow.text()


def test_a_set_is_complete_only_when_every_blob_in_it_passed(
    setup: Setup, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from markx.backup import runner

    _marketplace(db)
    real = runner.backup_files

    def forgets_one(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        result.proved.discard(sorted(result.proved)[0])
        return result

    monkeypatch.setattr(runner, "backup_files", forgets_one)
    outcome = run_backup(setup.ctx)
    assert (outcome.status, outcome.error_code) == (
        "failed", "destination:blobs_not_verified:1",
    )  # fmt: skip
    assert list_sets(setup.reader) == []


def test_verification_failure_names_the_object(tmp_path: Path) -> None:
    from markx.backup.destination import LocalDestination

    path = tmp_path / "piece"
    path.write_bytes(b"ciphertext")
    local = LocalDestination(tmp_path / "dest", prefix="markx")
    with pytest.raises(VerificationFailed) as caught:
        local.put_file("objects/ab/x", path, "0" * 64)
    assert caught.value.key == "objects/ab/x"


# -- BK-2: the drill away from the server ------------------------------------------------------


def test_the_off_server_drill_needs_only_a_read_only_key_and_writes_nothing(
    setup: Setup, db: DbSession, tmp_path: Path
) -> None:
    _marketplace(db)
    made = run_backup(setup.ctx)
    assert made.status == "succeeded"
    before = sorted((o.key, o.etag) for o in setup.reader.list(""))
    config = setup.ctx.config.model_copy(update={"env": "local"})
    result = run_offsite_drill(config, setup.reader, superuser=SUPERUSER, keys=setup.ring,
                               signers=setup.signers, bootstrap_script=BOOTSTRAP)  # fmt: skip
    assert result.passed, result.text()
    assert result.backup_id == made.backup_id
    assert len(result.injections) == 7
    assert all(ok for _, ok, _ in result.injections)
    assert result.restore is not None
    assert result.restore.facts["restored_files"]["private"] >= 10
    assert sorted((o.key, o.etag) for o in setup.reader.list("")) == before
    with psycopg.connect(host=_PG_HOST, port=_PG_PORT, user=_PG_SUPERUSER, password=_PG_SUPERPASS,
                         dbname="postgres") as conn:  # fmt: skip
        left = conn.execute(
            "select count(*) from pg_database where datname like 'markx_drill%'"
        ).fetchone()
    assert left == (0,)

    # Its report, entered on the server, is what the watch reads.
    report = tmp_path / "drill.json"
    report.write_text(json.dumps(result.as_dict(), default=str))
    assert _record(setup, report) == 0
    db.expire_all()
    (drill,) = db.scalars(select(BackupRun).where(BackupRun.kind == "drill")).all()
    assert (drill.status, drill.verified, drill.backup_id) == ("succeeded", True, made.backup_id)
    assert drill.details["offsite_report"] is True


def _record(setup: Setup, report: Path) -> int:
    """`record-drill` as the server runs it: the server's own settings."""
    from markx.backup.__main__ import main

    signer = report.with_name("signer-public.key")
    if not signer.exists():
        crypto.write_key_file(signer, crypto.encode_signer(setup.keys.signing.signer), secret=False)
    env = {
        "MARKX_ENV": "test", "MARKX_BACKUP_DATABASE": DATABASE,
        "MARKX_BACKUP_DESTINATION": "minio",
        "MARKX_BACKUP_DESTINATION_ENDPOINT_URL": str(setup.minio.endpoint_url),
        "MARKX_BACKUP_DESTINATION_BUCKET": setup.bucket,
        "MARKX_BACKUP_DESTINATION_PREFIX": "markx/test",
        "MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID": setup.users.writer.access_key,
        "MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY": setup.users.writer.secret_key,
        "PGHOST": MIGRATOR.host or "", "PGPORT": MIGRATOR.port or "",
        "PGUSER": MIGRATOR.user or "", "PGPASSWORD": MIGRATOR.password or "",
    }  # fmt: skip
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return main(["record-drill", "--report", str(report), "--signer", str(signer)])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_record_drill_refuses_a_report_it_cannot_tie_to_a_real_set(
    setup: Setup, db: DbSession, tmp_path: Path
) -> None:
    report = tmp_path / "drill.json"
    now = datetime.now(UTC).isoformat()
    base = {"passed": True, "backup_id": "20261101T000000Z-00000000", "kind": "offsite",
            "started_at": now, "finished_at": now, "restore": None, "injections": []}  # fmt: skip
    report.write_text(json.dumps(base))
    assert _record(setup, report) == 2  # no such set
    report.write_text(json.dumps({**base, "kind": "rehearsal"}))
    assert _record(setup, report) == 2  # not an off-server drill
    report.write_text("not json")
    assert _record(setup, report) == 2
    db.expire_all()
    assert db.scalars(select(BackupRun).where(BackupRun.kind == "drill")).all() == []


# -- BK-6: a forged dump cannot run programs where it is restored ------------------------------


def _forged_set(setup: Setup, name: str) -> str:
    """What a compromised server could sign: a database whose restore calls
    a function that runs a program (`COPY ... TO PROGRAM`, here the harmless
    `true`) for every row loaded, through a CHECK constraint. The function is
    harmless while the source is made, then its body is replaced, so making
    the source runs nothing."""
    create_database(SUPERUSER, name, bootstrap_script=BOOTSTRAP, psql_command=setup.tools.psql)
    with MIGRATOR.connect(name, autocommit=True) as conn:
        conn.execute("create function public.f(int) returns boolean volatile language plpgsql "
                     "as $$ begin return true; end $$")  # fmt: skip
        conn.execute("create table planted (x int check (public.f(x)))")
        conn.execute("insert into planted values (1)")
        conn.execute("create or replace function public.f(int) returns boolean volatile "
                     "language plpgsql as $$ begin execute 'copy (select 1) to program ''true''';"
                     " return true; end $$")  # fmt: skip
    config = setup.ctx.config.model_copy(update={"database": name})
    outcome = run_backup(replace(setup.ctx, config=config, recorder=Recorder(MIGRATOR, name)))
    assert outcome.status == "succeeded", outcome.error_code
    return str(outcome.backup_id)


def test_a_forged_dump_cannot_run_a_program_on_the_recovery_machine(
    setup: Setup, restored_db: str, tmp_path: Path
) -> None:
    source = f"markx_test_forged_{uuid.uuid4().hex[:6]}"
    contrast = f"markx_test_contrast_{uuid.uuid4().hex[:6]}"
    try:
        backup_id = _forged_set(setup, source)
        # As MarkX restores (the owner role): the program is refused, the
        # restore fails, and the half-made database is gone.
        report = _restore(setup, backup_id, restored_db, None)
        assert not report.passed
        assert "pg_restore_exit_1" in report.text()
        assert not database_exists(SUPERUSER, restored_db)

        # Why it matters: the same archive, restored by a SUPERUSER, runs it.
        from markx.backup.restore import Report as RestoreReport
        from markx.backup.restore import _plaintext, fetch_and_verify

        verified = fetch_and_verify(setup.reader, backup_id, signers=setup.signers,
                                    keys=setup.ring, workdir=tmp_path,
                                    report=RestoreReport(backup_id))  # fmt: skip
        owner_evidence, super_evidence = tmp_path / "owner", tmp_path / "super"
        owner_evidence.mkdir()
        super_evidence.mkdir()
        create_database(SUPERUSER, contrast, bootstrap_script=BOOTSTRAP,
                        psql_command=setup.tools.psql)  # fmt: skip
        with pytest.raises(RestoreFailed):
            pg_restore(server=SUPERUSER.as_role("markx_migrator"), target=contrast,
                       plaintext=_plaintext(verified.dump_path, setup.ring),
                       pg_restore_command=setup.tools.pg_restore,
                       evidence_dir=owner_evidence)  # fmt: skip
        refusal = (owner_evidence / "pg_restore.stderr").read_text()
        assert "permission denied" in refusal
        assert "program" in refusal
        drop_database(SUPERUSER, contrast)
        create_database(SUPERUSER, contrast, bootstrap_script=BOOTSTRAP,
                        psql_command=setup.tools.psql)  # fmt: skip
        pg_restore(server=SUPERUSER, target=contrast,
                   plaintext=_plaintext(verified.dump_path, setup.ring),
                   pg_restore_command=setup.tools.pg_restore, evidence_dir=super_evidence)  # fmt: skip
    finally:
        for name in (source, contrast):
            if database_exists(SUPERUSER, name):
                drop_database(SUPERUSER, name)


def test_the_restored_copy_is_owned_by_the_owner_role_with_the_sources_exact_grants(
    setup: Setup, db: DbSession, restored_db: str
) -> None:
    """Restored as the owner, every table keeps exactly its source grants:
    bootstrap's default grants must not widen them (the audit log and the
    other history tables would lose their protection)."""
    _marketplace(db)
    outcome = run_backup(setup.ctx)
    report = _restore(setup, str(outcome.backup_id), restored_db, None)
    assert report.passed, report.text()
    assert "as the owner role (not a superuser)" in report.text()

    def grants(name: str) -> dict[str, tuple[str, str]]:
        with SUPERUSER.connect(name) as conn:
            rows = conn.execute(
                "select c.relname, pg_get_userbyid(c.relowner), coalesce(c.relacl::text, '') "
                "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = 'public' and c.relkind in ('r', 'S', 'v')"
            ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    restored, source = grants(restored_db), grants(DATABASE)
    assert restored == source
    assert {owner for owner, _ in restored.values()} == {"markx_migrator"}
    assert "markx_app=ar/" in restored["audit_log"][1]  # read and add, never change


# -- BK-7: a restore never resets a password ----------------------------------------------------


def test_a_restore_never_resets_the_password_of_an_existing_role(
    setup: Setup, db: DbSession, restored_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_backup(setup.ctx)
    # As the old runbook said to: the passwords given to a restore. Roles
    # are shared by the whole server, so bootstrap.sh would reset them.
    monkeypatch.setenv("MARKX_DB_APP_PASSWORD", "test-only-would-lock-the-app-out")
    report = _restore(setup, str(outcome.backup_id), restored_db, None)
    assert not report.passed
    assert "roles_exist_passwords_given" in report.text()
    assert not database_exists(SUPERUSER, restored_db)
    # The application still logs in with its own password.
    with psycopg.connect(host=_PG_HOST, port=_PG_PORT, user="markx_app",
                         password="markx_app_dev-only", dbname=DATABASE) as conn:  # fmt: skip
        assert conn.execute("select 1").fetchone() == (1,)
    monkeypatch.delenv("MARKX_DB_APP_PASSWORD")
    again = _restore(setup, str(outcome.backup_id), restored_db, None)
    assert again.passed, again.text()
