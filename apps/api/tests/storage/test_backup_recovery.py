"""Backups and disaster recovery against a real PostgreSQL 17 and MinIO (D-094).

Marketplace data is made through the API (sellers' documents, a catalogue
picture rendered by the worker, a buyer's problem photo), so every kind of
stored file the database refers to is in the set. Then the set is taken,
restored into a NEW database and NEW buckets, and compared; and every way a
backup can fail or be tampered with is tried.

PostgreSQL's client tools must be version 17 like the server. Give them as
MARKX_TEST_PG_DUMP, MARKX_TEST_PG_RESTORE and MARKX_TEST_PSQL (CI runs the
server's own image: `docker run --rm -i --network host -e PGHOST -e PGPORT
-e PGUSER -e PGPASSWORD postgres:17 pg_dump`). Without them these tests are
skipped, unless MARKX_TEST_BACKUP_REQUIRED=1 (CI), which fails instead.
Nothing here reaches Amazon or Cloudflare; no customer data is used.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from botocore.exceptions import ConnectionClosedError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.backup import crypto
from markx.backup.config import BackupConfig
from markx.backup.database import PgServer, database_exists, drop_database
from markx.backup.destination import (
    DestinationError,
    DestinationUnavailable,
    LocalDestination,
    S3Destination,
    VerificationFailed,
)
from markx.backup.drill import run_drill
from markx.backup.models import BackupRun
from markx.backup.records import Recorder, RunRecord
from markx.backup.restore import FileTargets, list_sets, restore_set, verify_set
from markx.backup.runner import ADVISORY_LOCK, BackupContext, run_backup
from markx.backup.sources import BucketSource, SourceObject
from markx.core.storage import ObjectStorageSettings, S3ObjectStore, make_s3_client
from markx.ops import service as ops
from markx.ops.models import OpsAlert
from tests.api.test_disputes import Delivered
from tests.bazaar import Bazaar
from tests.conftest import _PG_HOST, _PG_PORT, _PG_SUPERPASS, _PG_SUPERUSER, REPO_ROOT
from tests.storage.conftest import _scratch_buckets
from tests.unit.test_images import phone_jpeg

DATABASE = "markx_test"
BOOTSTRAP = REPO_ROOT / "infra" / "postgres" / "bootstrap.sh"
REQUIRED = os.environ.get("MARKX_TEST_BACKUP_REQUIRED") == "1"


# -- the tools -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Tools:
    pg_dump: str
    pg_restore: str
    psql: str


def _major(command: str) -> int | None:
    try:
        out = subprocess.run([*shlex.split(command), "--version"], capture_output=True, text=True,
                             timeout=300, check=False).stdout  # fmt: skip
    except OSError:
        return None
    match = re.search(r"\) (\d+)", out)
    return int(match.group(1)) if match else None


@pytest.fixture(scope="session")
def tools() -> Tools:
    found = Tools(
        os.environ.get("MARKX_TEST_PG_DUMP", "pg_dump"),
        os.environ.get("MARKX_TEST_PG_RESTORE", "pg_restore"),
        os.environ.get("MARKX_TEST_PSQL", "psql"),
    )
    if _major(found.pg_dump) != 17 or _major(found.pg_restore) != 17:
        message = "PostgreSQL 17 client tools are needed (MARKX_TEST_PG_DUMP and friends)"
        if REQUIRED:
            pytest.fail(message)
        pytest.skip(message)
    return found


MIGRATOR = PgServer(_PG_HOST, _PG_PORT, "markx_migrator", "markx_migrator_dev-only")
SUPERUSER = PgServer(_PG_HOST, _PG_PORT, _PG_SUPERUSER, _PG_SUPERPASS)


@pytest.fixture(scope="session")
def keys() -> crypto.GeneratedKeys:
    return crypto.generate_keys()


def _bucket(minio: ObjectStorageSettings, label: str) -> str:
    import secrets

    name = f"markx-test-{label}-{secrets.token_hex(4)}"
    client = make_s3_client(minio)
    client.create_bucket(Bucket=name)
    client.close()
    _scratch_buckets.append(name)
    return name


@pytest.fixture
def backup_bucket(minio: ObjectStorageSettings) -> str:
    return _bucket(minio, "backups")


def _destination(minio: ObjectStorageSettings, bucket: str, **overrides: Any) -> S3Destination:
    settings = replace(minio, private_bucket=bucket, public_bucket=bucket, **overrides)
    return S3Destination(settings, prefix="markx/test", offsite=False,
                         identity=f"minio:test/{bucket}/markx/test")  # fmt: skip


def _config(
    minio: ObjectStorageSettings, tools: Tools, work: Path, **overrides: Any
) -> BackupConfig:
    settings: dict[str, Any] = {
        "env": "test", "release": "test-release", "database": DATABASE,
        "pg_dump_command": tools.pg_dump, "pg_restore_command": tools.pg_restore,
        "psql_command": tools.psql, "work_dir": work,
        "source_provider": "minio", "source_endpoint_url": minio.endpoint_url,
        "source_private_bucket": minio.private_bucket, "source_public_bucket": minio.public_bucket,
        "source_access_key_id": minio.access_key_id,
        "source_secret_access_key": minio.secret_access_key,
    }  # fmt: skip
    settings.update(overrides)
    return BackupConfig(**settings)


def _ctx(config: BackupConfig, minio: ObjectStorageSettings, destination: Any,
         keys: crypto.GeneratedKeys) -> BackupContext:  # fmt: skip
    return BackupContext(
        config=config, server=MIGRATOR, destination=destination, source=BucketSource(minio),
        recipient=keys.recovery.recipient, signing=keys.signing,
        recorder=Recorder(MIGRATOR, DATABASE),
    )  # fmt: skip


@dataclass
class Setup:
    ctx: BackupContext
    destination: S3Destination
    minio: ObjectStorageSettings
    keys: crypto.GeneratedKeys
    tools: Tools

    @property
    def ring(self) -> dict[str, crypto.RecoveryKey]:
        return {self.keys.recovery.key_id: self.keys.recovery}

    @property
    def signers(self) -> list[crypto.SignerKey]:
        return [self.keys.signing.signer]


@pytest.fixture
def setup(on_minio: ObjectStorageSettings, tools: Tools, keys: crypto.GeneratedKeys,
          backup_bucket: str, tmp_path: Path) -> Setup:  # fmt: skip
    destination = _destination(on_minio, backup_bucket)
    config = _config(on_minio, tools, tmp_path / "work")
    return Setup(_ctx(config, on_minio, destination, keys), destination, on_minio, keys, tools)


@pytest.fixture
def restored_db() -> Iterator[str]:
    name = f"markx_test_restored_{uuid.uuid4().hex[:8]}"
    yield name
    if database_exists(SUPERUSER, name):
        drop_database(SUPERUSER, name)


def _targets(
    minio: ObjectStorageSettings, *, forbidden: frozenset[str] = frozenset()
) -> FileTargets:
    private, public = _bucket(minio, "rp"), _bucket(minio, "rq")
    settings = replace(minio, private_bucket=private, public_bucket=public)
    client = make_s3_client(settings)
    stores = {"private": S3ObjectStore(client, private, name="private", settings=settings),
              "public": S3ObjectStore(client, public, name="public", settings=settings)}  # fmt: skip
    live = frozenset({minio.private_bucket, minio.public_bucket}) | forbidden
    return FileTargets(stores, f"{private}, {public}", live)  # type: ignore[arg-type]


def _restore(s: Setup, backup_id: str, target: str, files: FileTargets | None, **kw: Any) -> Any:
    return restore_set(
        destination=s.destination, backup_id=backup_id, signers=s.signers, keys=s.ring,
        server=SUPERUSER, target_db=target, confirm=kw.pop("confirm", target), files=files,
        bootstrap_script=BOOTSTRAP, psql_command=s.tools.psql,
        pg_restore_command=s.tools.pg_restore, **kw,
    )  # fmt: skip


# -- representative data, made through the API ------------------------------------------------


def _marketplace(db: DbSession) -> Bazaar:
    """Two sellers' eight documents, a rendered catalogue picture (private
    source and two public renditions) and a buyer's problem photo."""
    from markx.worker.runner import run_once

    bazaar = Bazaar(db)
    uploaded = bazaar.staff.post(
        f"/admin/catalog/products/{bazaar.product['id']}/images",
        files={"file": ("photo.jpg", phone_jpeg(), "image/jpeg")},
    )
    assert uploaded.status_code == 202, uploaded.text
    run_once(datetime.now(UTC), jobs=())
    delivered = Delivered(bazaar)
    assert delivered.report().status_code == 200
    photo = delivered.buyer.post(
        f"{delivered.mine}/problem/photos", files={"file": ("p.jpg", phone_jpeg(), "image/jpeg")}
    )
    assert photo.status_code == 201, photo.text
    return bazaar


def _listing(minio: ObjectStorageSettings) -> dict[tuple[str, str], str]:
    client = make_s3_client(minio)
    found = {}
    for store, bucket in (("private", minio.private_bucket), ("public", minio.public_bucket)):
        for item in client.list_objects_v2(Bucket=bucket).get("Contents", []):
            found[(store, item["Key"])] = item["ETag"]
    client.close()
    return found


def _runs(db: DbSession, kind: str = "backup") -> list[BackupRun]:
    db.expire_all()
    return list(db.scalars(select(BackupRun).where(BackupRun.kind == kind)
                           .order_by(BackupRun.started_at)))  # fmt: skip


# -- the whole recovery -----------------------------------------------------------------------


def test_database_and_files_are_backed_up_and_fully_recovered(
    setup: Setup, db: DbSession, restored_db: str
) -> None:
    _marketplace(db)
    before = _listing(setup.minio)
    outcome = run_backup(setup.ctx)
    assert outcome.status == "succeeded", outcome.error_code
    body = outcome.manifest
    files = body["files"]
    # 8 documents, 1 picture source, 1 problem photo; 2 renditions.
    assert files["referenced"] == 12
    assert files["missing_references"] == 0
    assert files["stores"]["private"]["objects"] >= 10
    assert files["stores"]["public"]["objects"] >= 2
    assert body["database"]["row_counts"]["seller_documents"] == 8
    assert body["encryption"]["recipient_key_id"] == setup.keys.recovery.key_id
    assert body["destination"]["offsite"] is False  # MinIO is never called off-server

    # Only ciphertext left the database host: no piece holds a plaintext dump.
    dump = setup.destination.read_bytes(body["database"]["object"], limit=2**30)
    assert dump.startswith(crypto.MAGIC)
    assert b"PGDMP" not in dump

    targets = _targets(setup.minio)
    report = _restore(setup, str(outcome.backup_id), restored_db, targets)
    assert report.passed, report.text()
    assert report.facts["restored_files"]["private"] == files["stores"]["private"]["objects"]

    # Private files only in the private target, public only in the public one,
    # byte for byte the source's.
    source = make_s3_client(setup.minio)
    for (store, key), _etag in before.items():
        original = source.get_object(
            Bucket=setup.minio.private_bucket if store == "private" else setup.minio.public_bucket,
            Key=key,
        )["Body"].read()
        restored = targets.stores[store].get(key)  # type: ignore[index]
        assert hashlib.sha256(restored).digest() == hashlib.sha256(original).digest()
        other = "public" if store == "private" else "private"
        assert not targets.stores[other].exists(key)  # type: ignore[index]
    source.close()
    # The backup changed nothing in the source stores.
    assert _listing(setup.minio) == before

    (run,) = _runs(db)
    assert (run.status, run.verified, run.offsite) == ("succeeded", True, False)
    assert run.object_count == files["object_count"]
    assert run.backup_id == outcome.backup_id


def test_a_second_backup_moves_only_new_files(setup: Setup, db: DbSession) -> None:
    bazaar = _marketplace(db)
    first = run_backup(setup.ctx)
    assert first.status == "succeeded"
    again = run_backup(setup.ctx)
    assert again.status == "succeeded"
    assert again.manifest["files"]["new_blobs"] == 0
    assert again.manifest["files"]["reused_blobs"] == again.manifest["files"]["object_count"]

    from markx.worker.runner import run_once

    uploaded = bazaar.staff.post(
        f"/admin/catalog/products/{bazaar.product['id']}/images",
        files={"file": ("photo2.jpg", phone_jpeg(orientation=1), "image/jpeg")},
    )
    assert uploaded.status_code == 202
    run_once(datetime.now(UTC), jobs=())
    third = run_backup(setup.ctx)
    assert third.status == "succeeded"
    # One new source and its two renditions; nothing else is transferred.
    assert third.manifest["files"]["new_blobs"] == 3
    assert list_sets(setup.destination)[:3] == sorted(
        [str(first.backup_id), str(again.backup_id), str(third.backup_id)], reverse=True
    )


# -- incomplete sets ---------------------------------------------------------------------------


def test_a_missing_referenced_file_makes_the_set_incomplete_and_unrestorable(
    setup: Setup, db: DbSession, restored_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from markx.sellers.models import SellerDocument

    _marketplace(db)
    lost = db.scalars(select(SellerDocument.file_key).limit(1)).one()
    client = make_s3_client(setup.minio)
    client.delete_object(Bucket=setup.minio.private_bucket, Key=lost)  # the loss under test
    client.close()

    outcome = run_backup(setup.ctx)
    assert outcome.status == "incomplete"
    assert outcome.manifest["files"]["missing_by_kind"] == {"seller_document": 1}
    (run,) = _runs(db)
    assert (run.status, run.verified, run.error_code) == ("incomplete", False, "missing_references")

    report = _restore(setup, str(outcome.backup_id), restored_db, None)
    assert not report.passed
    assert "set_status_incomplete" in report.text()
    assert not database_exists(SUPERUSER, restored_db)

    # The watch raises it (on a server; here switched on by hand).
    _watch_on(monkeypatch)
    ops.watch(db, datetime.now(UTC))
    db.commit()
    keys = {a.key for a in db.scalars(select(OpsAlert).where(OpsAlert.resolved_at.is_(None)))}
    assert {"backup.incomplete", "backup.stale"} <= keys


def test_a_database_not_yet_migrated_backs_up_and_restores_as_empty(
    setup: Setup, restored_db: str
) -> None:
    """deploy.sh takes a set before the first migration, of an empty database."""
    from markx.backup.database import create_database

    empty = f"markx_test_empty_{uuid.uuid4().hex[:6]}"
    create_database(SUPERUSER, empty, bootstrap_script=BOOTSTRAP, psql_command=setup.tools.psql)
    try:
        config = setup.ctx.config.model_copy(update={"database": empty})
        ctx = replace(setup.ctx, config=config, recorder=Recorder(MIGRATOR, empty))
        outcome = run_backup(ctx)  # its record cannot be written: no table yet
        assert outcome.status == "succeeded", outcome.error_code
        assert outcome.manifest["database"]["tables"] == 0
        assert outcome.manifest["application"]["alembic_revision"] is None
        report = _restore(setup, str(outcome.backup_id), restored_db, None)
        assert report.passed, report.text()
    finally:
        drop_database(SUPERUSER, empty)


def test_a_damaged_source_file_is_never_backed_up_as_good(
    setup: Setup, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store states an MD5 (the ETag) that the bytes read do not have."""
    from markx.sellers.models import SellerDocument

    _marketplace(db)
    damaged = db.scalars(select(SellerDocument.file_key).limit(1)).one()
    real_list = setup.ctx.source.list

    def as_listed(store: Any) -> Iterator[Any]:
        for item in real_list(store):
            if isinstance(item, SourceObject) and item.key == damaged:
                item = replace(item, expected_md5="0" * 32)
            yield item

    monkeypatch.setattr(setup.ctx.source, "list", as_listed)
    outcome = run_backup(setup.ctx)
    assert outcome.status == "incomplete"
    assert outcome.manifest["files"]["skipped"] == {"corrupt": 1}
    assert outcome.manifest["files"]["missing_by_kind"] == {"seller_document": 1}


def test_after_a_key_rotation_no_blob_of_the_old_key_is_reused(setup: Setup, db: DbSession) -> None:
    _marketplace(db)
    old = run_backup(setup.ctx)
    assert old.status == "succeeded"
    new_keys = crypto.generate_keys()
    rotated = replace(setup.ctx, recipient=new_keys.recovery.recipient)
    new = run_backup(rotated)
    assert new.status == "succeeded"
    files = new.manifest["files"]
    assert files["new_blobs"] == files["blob_count"]  # every file encrypted again
    assert new.manifest["encryption"]["recipient_key_id"] == new_keys.recovery.key_id
    ring = {new_keys.recovery.key_id: new_keys.recovery}
    assert verify_set(destination=setup.destination, backup_id=str(new.backup_id),
                      signers=setup.signers, keys=ring, deep=True).passed  # fmt: skip
    # The old set still needs, and opens with, the old key only.
    assert not verify_set(destination=setup.destination, backup_id=str(old.backup_id),
                          signers=setup.signers, keys=ring, deep=False).passed  # fmt: skip
    both = {**ring, **setup.ring}
    assert verify_set(destination=setup.destination, backup_id=str(old.backup_id),
                      signers=setup.signers, keys=both, deep=True).passed  # fmt: skip


def _watch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from markx.core.config import get_config
    from markx.ops import checks

    config = get_config().model_copy(update={"backup_monitoring": "on"})
    monkeypatch.setattr(checks, "get_config", lambda: config)


# -- failures ------------------------------------------------------------------------------------


def test_a_failed_dump_keeps_the_last_good_set_and_its_evidence(
    setup: Setup, db: DbSession, tmp_path: Path
) -> None:
    good = run_backup(setup.ctx)
    assert good.status == "succeeded"
    broken = replace(
        setup.ctx, config=setup.ctx.config.model_copy(update={"pg_dump_command": "false"})
    )
    failed = run_backup(broken)
    assert (failed.status, failed.error_code) == ("failed", "database:pg_dump_exit_1")
    assert failed.retryable
    # The last good set is untouched and still the newest complete one.
    assert list_sets(setup.destination) == [str(good.backup_id)]
    assert verify_set(destination=setup.destination, backup_id=str(good.backup_id),
                      signers=setup.signers, keys=setup.ring, deep=True).passed  # fmt: skip
    evidence = setup.ctx.config.work_dir.resolve() / "failed" / str(failed.backup_id)
    report = json.loads((evidence / "report.json").read_text())
    assert report["error_code"] == "database:pg_dump_exit_1"
    assert (evidence / "pg_dump.stderr").exists()
    runs = _runs(db)
    assert [(r.status, r.error_code) for r in runs] == [
        ("succeeded", None), ("failed", "database:pg_dump_exit_1"),
    ]  # fmt: skip


def test_an_empty_or_foreign_dump_is_rejected(setup: Setup, db: DbSession) -> None:
    empty = replace(
        setup.ctx, config=setup.ctx.config.model_copy(update={"pg_dump_command": "true"})
    )
    assert run_backup(empty).error_code == "database:empty_dump"
    fake = replace(setup.ctx, config=setup.ctx.config.model_copy(
        update={"pg_dump_command": "echo not-a-dump"}))  # fmt: skip
    assert run_backup(fake).error_code == "database:not_a_custom_archive"
    assert list_sets(setup.destination) == []


def test_an_unreachable_destination_fails_clearly_and_is_retryable(
    setup: Setup, db: DbSession
) -> None:
    dead = _destination(setup.minio, "markx-nowhere", endpoint_url="http://127.0.0.1:9",
                        connect_timeout=1.0)  # fmt: skip
    outcome = run_backup(replace(setup.ctx, destination=dead))
    assert outcome.status == "failed"
    assert outcome.error_code == "destination:unreachable"
    assert outcome.retryable
    assert _runs(db)[-1].error_code == "destination:unreachable"


def test_an_interrupted_backup_leaves_no_set_and_the_next_one_resumes(
    setup: Setup, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _marketplace(db)
    real_put = setup.destination.put_file

    def cut_off(key: str, path: Path, sha256: str) -> None:
        if key.endswith("files.index.mxb"):
            raise DestinationUnavailable("timeout")  # the line dropped mid-backup
        real_put(key, path, sha256)

    monkeypatch.setattr(setup.destination, "put_file", cut_off)
    interrupted = run_backup(setup.ctx)
    assert (interrupted.status, interrupted.error_code) == ("failed", "destination:timeout")
    # Its blobs and dump reached the bucket, but without a manifest it is no set.
    assert list(setup.destination.list("objects/"))
    assert list_sets(setup.destination) == []
    monkeypatch.setattr(setup.destination, "put_file", real_put)

    resumed = run_backup(setup.ctx)
    assert resumed.status == "succeeded"
    assert resumed.manifest["files"]["new_blobs"] == 0  # everything reused


def test_two_backups_never_run_at_once(setup: Setup, db: DbSession) -> None:
    with psycopg.connect(host=_PG_HOST, port=_PG_PORT, user="markx_migrator",
                         password="markx_migrator_dev-only", dbname=DATABASE,
                         autocommit=True) as other:  # fmt: skip
        other.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK,))
        outcome = run_backup(setup.ctx)
        other.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK,))
    assert (outcome.status, outcome.error_code) == ("skipped", "already_running")
    work = setup.ctx.config.work_dir.resolve()
    with open(work / ".lock", "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        assert run_backup(setup.ctx).status == "skipped"
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert [r.status for r in _runs(db)] == ["skipped", "skipped"]
    assert run_backup(setup.ctx).status == "succeeded"


def test_a_run_left_running_by_a_dead_process_is_marked_abandoned(
    setup: Setup, db: DbSession
) -> None:
    Recorder(MIGRATOR, DATABASE).start(
        RunRecord(kind="backup", environment="test", destination="x", offsite=False,
                  started_at=datetime.now(UTC) - timedelta(hours=3))
    )  # fmt: skip
    assert run_backup(setup.ctx).status == "succeeded"
    assert [(r.status, r.error_code) for r in _runs(db)] == [
        ("abandoned", "process_died"), ("succeeded", None),
    ]  # fmt: skip


# -- the destination ------------------------------------------------------------------------------


def test_a_public_backup_bucket_is_refused(
    minio: ObjectStorageSettings, scratch_bucket: str
) -> None:
    client = make_s3_client(minio)
    client.put_bucket_policy(Bucket=scratch_bucket, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]},
                       "Action": ["s3:ListBucket"], "Resource": [f"arn:aws:s3:::{scratch_bucket}"]}],
    }))  # fmt: skip
    client.close()
    with pytest.raises(DestinationError, match="bucket_is_public"):
        _destination(minio, scratch_bucket).check_access()


def test_a_missing_backup_bucket_is_a_settings_error(minio: ObjectStorageSettings) -> None:
    with pytest.raises(DestinationError) as caught:
        _destination(minio, "markx-test-no-such-bucket").check_access()
    assert not caught.value.retryable


def test_an_upload_that_does_not_read_back_is_refused(
    minio: ObjectStorageSettings, backup_bucket: str, tmp_path: Path
) -> None:
    path = tmp_path / "piece"
    path.write_bytes(b"ciphertext")
    destination = _destination(minio, backup_bucket)
    with pytest.raises(VerificationFailed):
        destination.put_file("sets/x/piece", path, "0" * 64)
    local = LocalDestination(tmp_path / "dest", prefix="markx")
    with pytest.raises(VerificationFailed):
        local.put_file("sets/x/piece", path, "0" * 64)


def test_a_failed_multipart_upload_is_aborted(
    minio: ObjectStorageSettings, backup_bucket: str, tmp_path: Path
) -> None:
    settings = replace(minio, private_bucket=backup_bucket, public_bucket=backup_bucket)
    destination = S3Destination(settings, prefix="markx/test", offsite=False, identity="t",
                                multipart_threshold=5 * 1024 * 1024)  # fmt: skip
    parts = {"n": 0}

    def fail_second_part(**kwargs: Any) -> None:
        parts["n"] += 1
        if parts["n"] >= 2:  # the line drops after the first part, and stays down
            raise ConnectionClosedError(endpoint_url="http://127.0.0.1:9000")

    destination._client.meta.events.register("before-send.s3.UploadPart", fail_second_part)
    path = tmp_path / "big"
    path.write_bytes(os.urandom(12 * 1024 * 1024))
    with pytest.raises(DestinationError):
        destination.put_file("sets/x/big", path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert destination.head("sets/x/big") is None
    open_uploads = destination._client.list_multipart_uploads(Bucket=backup_bucket)
    assert open_uploads.get("Uploads", []) == []


def test_the_local_destination_refuses_escapes_and_links(tmp_path: Path) -> None:
    local = LocalDestination(tmp_path / "dest", prefix="markx")
    local.check_access()
    for key in ("../outside", "/etc/passwd", "a/../../b", "sets/../../x"):
        with pytest.raises(DestinationError):
            local.head(key)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "dest" / "markx" / "sets")
    with pytest.raises(DestinationError):
        local.head("sets/x")


# -- restore safeguards -----------------------------------------------------------------------------


def test_a_restore_never_overwrites_and_never_touches_the_live_stores(
    setup: Setup, db: DbSession, restored_db: str
) -> None:
    outcome = run_backup(setup.ctx)
    backup_id = str(outcome.backup_id)

    def refused(target: str, files: FileTargets | None, **kw: Any) -> str:
        report = _restore(setup, backup_id, target, files, **kw)
        assert not report.passed
        return report.text()

    with psycopg.connect(host=_PG_HOST, port=_PG_PORT, user=_PG_SUPERUSER, password=_PG_SUPERPASS,
                         dbname="postgres", autocommit=True) as conn:  # fmt: skip
        conn.execute(f"create database {restored_db}")
    assert "target_database_exists" in refused(restored_db, None)
    drop_database(SUPERUSER, restored_db)
    assert "target_is_a_system_database" in refused("postgres", None)
    assert "target_is_the_source_name" in refused(DATABASE, None)
    assert "confirmation_mismatch" in refused(restored_db, None, confirm="markx")
    assert not database_exists(SUPERUSER, restored_db)

    live = FileTargets(
        {
            "private": S3ObjectStore(
                make_s3_client(setup.minio),
                setup.minio.private_bucket,
                name="private",
                settings=setup.minio,
            ),
            "public": S3ObjectStore(
                make_s3_client(setup.minio),
                setup.minio.public_bucket,
                name="public",
                settings=setup.minio,
            ),
        },
        "the live buckets",
        frozenset({setup.minio.private_bucket, setup.minio.public_bucket}),
    )  # type: ignore[arg-type]
    assert "target_is_a_live_store" in refused(restored_db, live)

    used = _targets(setup.minio)
    used.stores["private"].put("leftover.png", _PNG, "image/png")  # type: ignore[index]
    assert "target_not_empty" in refused(restored_db, used)
    assert not database_exists(SUPERUSER, restored_db)


_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2d5b2f40000000049454e44ae426082"
)


def test_tampering_at_the_destination_is_refused_before_anything_is_written(
    setup: Setup, db: DbSession, restored_db: str
) -> None:
    _marketplace(db)
    outcome = run_backup(setup.ctx)
    backup_id = str(outcome.backup_id)
    dump_key = outcome.manifest["database"]["object"]
    original = setup.destination.read_bytes(dump_key, limit=2**30)
    # Someone with the bucket's keys replaces the dump with one of their own,
    # encrypted to the (public) recipient key: the signed hash catches it.
    forged = crypto.encrypt_bytes(setup.keys.recovery.recipient, b"PGDMP forged")
    tmp = setup.ctx.config.work_dir / "forged"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(forged)
    setup.destination.put_file(dump_key, tmp, hashlib.sha256(forged).hexdigest())
    report = _restore(setup, backup_id, restored_db, None)
    assert not report.passed
    assert "altered_piece:database.dump.mxb" in report.text()
    assert not database_exists(SUPERUSER, restored_db)
    tmp.write_bytes(original)
    setup.destination.put_file(dump_key, tmp, hashlib.sha256(original).hexdigest())

    # A blob damaged in place: the deep verification names it, and a restore
    # reports the file as damaged instead of writing it.
    blob = sorted(setup.destination.list("objects/"), key=lambda o: o.key)[0]
    data = bytearray(setup.destination.read_bytes(blob.key, limit=2**30))
    data[-1] ^= 0x01
    tmp.write_bytes(bytes(data))
    setup.destination.put_file(blob.key, tmp, hashlib.sha256(bytes(data)).hexdigest())
    deep = verify_set(destination=setup.destination, backup_id=backup_id, signers=setup.signers,
                      keys=setup.ring, deep=True)  # fmt: skip
    assert not deep.passed
    assert "1 damaged" in deep.text()
    report = _restore(setup, backup_id, restored_db, _targets(setup.minio))
    assert not report.passed
    assert "blob_damaged" in report.text()


def test_the_wrong_recovery_key_restores_nothing(
    setup: Setup, db: DbSession, restored_db: str
) -> None:
    outcome = run_backup(setup.ctx)
    stranger = crypto.generate_keys().recovery
    report = restore_set(
        destination=setup.destination, backup_id=str(outcome.backup_id), signers=setup.signers,
        keys={stranger.key_id: stranger}, server=SUPERUSER, target_db=restored_db,
        confirm=restored_db, files=None, bootstrap_script=BOOTSTRAP,
        psql_command=setup.tools.psql, pg_restore_command=setup.tools.pg_restore,
    )  # fmt: skip
    assert not report.passed
    assert "recovery_key_missing" in report.text()
    assert not database_exists(SUPERUSER, restored_db)


# -- the drill --------------------------------------------------------------------------------------


def test_the_recovery_drill_restores_compares_injects_failures_and_cleans_up(
    setup: Setup, db: DbSession
) -> None:
    _marketplace(db)
    before = _listing(setup.minio)
    result = run_drill(setup.ctx, superuser=SUPERUSER, keys=setup.ring, signers=setup.signers,
                       bootstrap_script=BOOTSTRAP, inject=True)  # fmt: skip
    assert result.passed, result.text()
    assert result.restore is not None
    assert result.restore.facts["restored_files"]["public"] >= 2
    injected = {name for name, ok, _ in result.injections if ok}
    assert len(injected) == len(result.injections) == 7
    # Only the drill's own things were removed: the set it made is a real backup.
    assert list_sets(setup.destination) == [str(result.backup_id)]
    assert _listing(setup.minio) == before
    with psycopg.connect(host=_PG_HOST, port=_PG_PORT, user=_PG_SUPERUSER, password=_PG_SUPERPASS,
                         dbname="postgres") as conn:  # fmt: skip
        left = conn.execute(
            "select count(*) from pg_database where datname like 'markx_drill%'"
        ).fetchone()
    assert left == (0,)
    client = make_s3_client(setup.minio)
    assert not [b for b in client.list_buckets()["Buckets"] if b["Name"].startswith("markx-drill-")]
    client.close()
    (drill,) = _runs(db, "drill")
    assert (drill.status, drill.verified) == ("succeeded", True)
    assert drill.details["injections"] == 7


def test_a_drill_that_cannot_restore_is_recorded_failed(setup: Setup, db: DbSession) -> None:
    broken = replace(
        setup.ctx, config=setup.ctx.config.model_copy(update={"pg_dump_command": "false"})
    )
    result = run_drill(broken, superuser=SUPERUSER, keys=setup.ring, signers=setup.signers,
                       bootstrap_script=BOOTSTRAP, inject=False)  # fmt: skip
    assert not result.passed
    (drill,) = _runs(db, "drill")
    assert (drill.status, drill.error_code) == ("failed", "drill_failed")
