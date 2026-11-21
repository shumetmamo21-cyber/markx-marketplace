"""Where backup sets are kept (D-094): one interface, two adapters.

- `S3Destination`: a dedicated bucket on any S3-compatible service (Amazon
  S3, Cloudflare R2; MinIO for tests), with its own credentials, never the
  machine's. Everything lives under one prefix. No object is ever made
  public and no link to one is ever made.
- `LocalDestination`: a folder, for a laptop and the tests. It is never
  off-server, and staging and production refuse it (`config.py`).

Every upload is verified before it counts: the size from the destination
must match, and the object is read back in full and its SHA-256 compared
with the bytes that were sent. An S3 upload is atomic (the object appears
only once complete); a multipart upload that fails is aborted, and parts
left by a killed process are aborted by `abort_stale_uploads`. A folder
upload is written beside its target and renamed into place.

Failures are either `DestinationUnavailable` (worth retrying later: a
timeout, an unreachable endpoint, throttling, a provider error) or
`DestinationError` (a setting is wrong: refused credentials, a missing or
public bucket). Neither ever carries a credential.

**The server never deletes a backup (BK-1).** The backup service only adds,
reads and lists; its key is given no delete right at all. Deleting old sets
is retention's job (`retention.py`), run away from the server with its own
key, through `purge`, which removes every version of an object and leaves an
object that is still under an object lock in place.

**Object lock (BK-1).** When a lock is required (always on staging and
production), `check_access` refuses a bucket without S3 Object Lock in
COMPLIANCE mode whose default retention is at least the required number of
days, so every object the server writes is undeletable, by anyone, for that
long. `extend_lock` lengthens one object's lock (COMPLIANCE never allows
shortening), for a blob an old set uploaded that a new set reuses.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol, cast

from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from markx.core.storage import ObjectStorageSettings, make_s3_client

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_COPY_BUFFER = 1024 * 1024
SHA256_METADATA = "markx-sha256"


class DestinationError(Exception):
    """A setting is wrong or the destination is unsafe; retrying will not help."""

    retryable = False

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DestinationUnavailable(DestinationError):
    """The destination did not answer properly now; a later attempt may work."""

    retryable = True


class VerificationFailed(DestinationError):
    """What the destination holds is not what was sent (BK-3). The object is
    then treated as never uploaded: the server cannot delete it, so it is
    never reused, and the next run uploads it again over it."""

    retryable = True

    def __init__(self, reason: str, key: str | None = None) -> None:
        super().__init__(reason)
        self.key = key


class ObjectMissing(DestinationError):
    """The object is not at the destination."""


@dataclass(frozen=True, slots=True)
class RemoteObject:
    key: str
    size: int
    last_modified: datetime
    # The destination's own fingerprint of the stored bytes (the ETag; for a
    # folder, the file's size, change time and inode). It changes whenever
    # the object is written again, whoever writes it (BK-3).
    etag: str | None = None
    # Until when the object is under an object lock, when the destination says.
    locked_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class LockRule:
    """A bucket's object lock, as the provider reports it."""

    mode: str
    days: int


@dataclass(frozen=True, slots=True)
class ObjectVersion:
    key: str
    version_id: str | None
    last_modified: datetime
    is_latest: bool
    delete_marker: bool
    # A delete marker has neither.
    size: int | None = None
    etag: str | None = None


def checked(key: str) -> str:
    if not _KEY.fullmatch(key) or len(key) > 512:
        raise DestinationError("unsafe_key")
    return key


class Destination(Protocol):
    identity: str
    offsite: bool

    # The lock the bucket was found to have by `check_access`, when one is required.
    lock: LockRule | None

    def check_access(self) -> None: ...

    def put_file(self, key: str, path: Path, sha256: str) -> RemoteObject: ...

    def head(self, key: str) -> RemoteObject | None: ...

    def reader(
        self, key: str, version_id: str | None = None
    ) -> AbstractContextManager[IO[bytes]]: ...

    def read_bytes(self, key: str, *, limit: int, version_id: str | None = None) -> bytes: ...

    def list(self, prefix: str) -> Iterator[RemoteObject]: ...

    def delete(self, key: str) -> None: ...

    def purge(self, key: str) -> bool: ...

    def list_versions(self, prefix: str) -> Iterator[ObjectVersion]: ...

    def versions(self, key: str) -> Sequence[ObjectVersion]: ...

    def extend_lock(self, key: str, until: datetime) -> datetime | None: ...

    def abort_stale_uploads(self, older_than: timedelta) -> int: ...


def _hash_stream(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_COPY_BUFFER):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


# -- a folder: a laptop and the tests -------------------------------------------------


def _local_etag(info: os.stat_result) -> str:
    return f"{info.st_size}-{info.st_mtime_ns}-{info.st_ino}"


class LocalDestination:
    offsite = False
    lock: LockRule | None = None  # a folder has no object lock

    def __init__(self, root: Path, *, prefix: str) -> None:
        self._root = root.resolve()
        self._prefix = prefix
        self.identity = f"local:{self._root}/{prefix}"

    def _path(self, key: str) -> Path:
        path = self._root / self._prefix / checked(key)
        # Nothing on the way may be a link out of the folder.
        resolved = path.resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise DestinationError("unsafe_key")
        for parent in [path, *path.parents]:
            if parent == self._root:
                break
            if parent.is_symlink():
                raise DestinationError("symlink_in_destination")
        return path

    def check_access(self) -> None:
        try:
            (self._root / self._prefix).mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise DestinationUnavailable(f"folder_unwritable:{type(exc).__name__}") from None

    def put_file(self, key: str, path: Path, sha256: str) -> RemoteObject:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = target.with_name(target.name + ".partial")
        try:
            with path.open("rb") as source, open(partial, "wb") as out:
                shutil.copyfileobj(source, out, _COPY_BUFFER)
                out.flush()
                os.fsync(out.fileno())
            partial.chmod(0o600)
            os.replace(partial, target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise DestinationUnavailable(f"write_failed:{type(exc).__name__}") from None
        return self._verify(key, path.stat().st_size, sha256)

    def _verify(self, key: str, size: int, sha256: str) -> RemoteObject:
        before = self.head(key)
        with self.reader(key) as stream:
            got_sha, got_size = _hash_stream(stream)
        if before is None or got_size != size or got_sha != sha256:
            raise VerificationFailed("readback_mismatch", key)
        return before

    def head(self, key: str) -> RemoteObject | None:
        path = self._path(key)
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        return RemoteObject(key, info.st_size, datetime.fromtimestamp(info.st_mtime, UTC),
                            _local_etag(info))  # fmt: skip

    @contextmanager
    def reader(self, key: str, version_id: str | None = None) -> Iterator[IO[bytes]]:
        if version_id is not None:
            raise ObjectMissing("missing")  # a folder keeps one version of each file
        try:
            handle = self._path(key).open("rb")
        except FileNotFoundError:
            raise ObjectMissing("missing") from None
        with handle:
            yield handle

    def read_bytes(self, key: str, *, limit: int, version_id: str | None = None) -> bytes:
        with self.reader(key, version_id) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise DestinationError("object_too_large")
        return data

    def list(self, prefix: str) -> Iterator[RemoteObject]:
        base = self._root / self._prefix
        start = base / prefix if prefix else base
        if not start.exists():
            return
        for path in sorted(start.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.name.endswith(".partial"):
                continue
            key = path.relative_to(base).as_posix()
            info = path.stat()
            yield RemoteObject(key, info.st_size, datetime.fromtimestamp(info.st_mtime, UTC),
                               _local_etag(info))  # fmt: skip

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def purge(self, key: str) -> bool:
        self.delete(key)
        return True

    def list_versions(self, prefix: str) -> Iterator[ObjectVersion]:
        for obj in self.list(prefix):
            yield ObjectVersion(obj.key, None, obj.last_modified, True, False, obj.size, obj.etag)

    def versions(self, key: str) -> Sequence[ObjectVersion]:
        """A folder keeps only the current file: there is never an older copy."""
        obj = self.head(key)
        if obj is None:
            return []
        return [ObjectVersion(key, None, obj.last_modified, True, False, obj.size, obj.etag)]

    def extend_lock(self, key: str, until: datetime) -> datetime | None:
        return None

    def abort_stale_uploads(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        removed = 0
        base = self._root / self._prefix
        if not base.exists():
            return 0
        for path in base.rglob("*.partial"):
            if not path.is_symlink() and datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


# -- an S3-compatible bucket -------------------------------------------------------------

_UNAVAILABLE_CODES = frozenset(
    {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "503", "500",
     "Throttling", "ThrottlingException", "RequestTimeTooSkewed"}
)  # fmt: skip


def _translate(exc: Exception) -> DestinationError:
    """A provider failure as one of ours, with the provider's code only."""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", "unknown"))
        if code in ("NoSuchKey", "404", "NotFound"):
            return ObjectMissing("missing")
        if code in _UNAVAILABLE_CODES:
            return DestinationUnavailable(f"provider:{code}")
        return DestinationError(f"provider:{code}")
    if isinstance(exc, ConnectTimeoutError | ReadTimeoutError):
        return DestinationUnavailable("timeout")
    if isinstance(exc, EndpointConnectionError):
        return DestinationUnavailable("unreachable")
    if isinstance(exc, S3UploadFailedError):
        return DestinationUnavailable("upload_failed")
    if isinstance(exc, BotoCoreError):
        return DestinationUnavailable(type(exc).__name__)
    raise exc


@contextmanager
def _provider() -> Iterator[None]:
    try:
        yield
    except (ClientError, BotoCoreError, S3UploadFailedError) as exc:
        raise _translate(exc) from None


# A version that cannot be removed because an object lock still holds it.
# AWS answers AccessDenied, MinIO InvalidRequest (verified with MinIO only).
_LOCKED_CODES = frozenset({"AccessDenied", "InvalidRequest", "ObjectLocked"})


class S3Destination:
    offsite: bool

    def __init__(
        self,
        settings: ObjectStorageSettings,
        *,
        prefix: str,
        offsite: bool,
        identity: str,
        client: S3Client | None = None,
        multipart_threshold: int = 64 * 1024 * 1024,
        lock_min_days: int | None = None,
    ) -> None:
        self._settings = settings
        self._bucket = settings.private_bucket
        self._prefix = prefix
        self._client = client or make_s3_client(settings)
        self.offsite = offsite
        self.identity = identity
        # When set, the bucket must have an object lock this long (BK-1).
        self._lock_min_days = lock_min_days
        self.lock: LockRule | None = None
        self._transfer = TransferConfig(
            multipart_threshold=multipart_threshold,
            multipart_chunksize=max(multipart_threshold, 5 * 1024 * 1024),
            use_threads=False,
        )

    def _full(self, key: str) -> str:
        return f"{self._prefix}/{checked(key)}"

    def check_access(self) -> None:
        """The bucket answers with our keys, and NOT without them."""
        with _provider():
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in ("404", "NoSuchBucket", "NotFound"):
                    raise DestinationError("provider:NoSuchBucket") from None
                raise
        if self._anonymous_can_list():
            raise DestinationError("bucket_is_public")
        if self._lock_min_days is not None:
            self.lock = self._checked_lock(self._lock_min_days)

    def lock_rule(self) -> LockRule | None:
        """The bucket's default object lock, or None when it has none."""
        try:
            with _provider():
                config = self._client.get_object_lock_configuration(Bucket=self._bucket)
        except DestinationError as exc:
            if exc.reason in (
                "provider:ObjectLockConfigurationNotFoundError",
                "provider:ObjectLockConfigurationNotFound",
            ):
                return None
            raise
        lock = config.get("ObjectLockConfiguration", {})
        if lock.get("ObjectLockEnabled") != "Enabled":
            return None
        default = lock.get("Rule", {}).get("DefaultRetention", {})
        days = int(default.get("Days") or 0) + 365 * int(default.get("Years") or 0)
        if not default.get("Mode") or days <= 0:
            return None
        return LockRule(str(default["Mode"]), days)

    def _checked_lock(self, min_days: int) -> LockRule:
        """Refuse a bucket whose objects anyone could delete (BK-1). COMPLIANCE
        only: a GOVERNANCE lock can be lifted by a key with the bypass right.
        PROVISIONAL (D-096): requiring a lock, its mode and its minimum period
        are for the founder to confirm with F-16. Whether Cloudflare R2's own
        "bucket locks" answer this S3 call, and how, is NOT VERIFIED: if they
        do not, an R2 bucket is refused here. Test it once F-16 is decided."""
        rule = self.lock_rule()
        if rule is None:
            raise DestinationError("object_lock_missing")
        if rule.mode != "COMPLIANCE":
            raise DestinationError(f"object_lock_not_compliance:{rule.mode}")
        if rule.days < min_days:
            raise DestinationError(f"object_lock_too_short:{rule.days}<{min_days}")
        return rule

    def _anonymous_can_list(self) -> bool:
        anonymous = make_s3_client(self._settings, unsigned=True)
        try:
            anonymous.list_objects_v2(Bucket=self._bucket, Prefix=self._prefix + "/", MaxKeys=1)
        except (ClientError, BotoCoreError):
            return False
        finally:
            anonymous.close()
        return True

    def anonymous_can_read(self, key: str) -> bool:
        anonymous = make_s3_client(self._settings, unsigned=True)
        try:
            anonymous.head_object(Bucket=self._bucket, Key=self._full(key))
        except (ClientError, BotoCoreError):
            return False
        finally:
            anonymous.close()
        return True

    def put_file(self, key: str, path: Path, sha256: str) -> RemoteObject:
        extra: dict[str, object] = {
            "ContentType": "application/octet-stream",
            "CacheControl": "no-store",
            "Metadata": {SHA256_METADATA: sha256},
        }
        if self._settings.encryption is not None:
            extra["ServerSideEncryption"] = self._settings.encryption
        with _provider():
            # Multipart uploads that fail are aborted by the transfer manager.
            self._client.upload_file(
                str(path), self._bucket, self._full(key), ExtraArgs=extra, Config=self._transfer
            )
        size = path.stat().st_size
        remote = self.head(key)
        if remote is None or remote.size != size:
            raise VerificationFailed("size_mismatch", key)
        with self.reader(key) as stream:
            got_sha, got_size = _hash_stream(stream)
        if got_size != size or got_sha != sha256:
            raise VerificationFailed("readback_mismatch", key)
        if self.lock is not None and remote.locked_until is None:
            # The bucket's default lock did not reach this object.
            raise VerificationFailed("object_not_locked", key)
        return remote

    def head(self, key: str) -> RemoteObject | None:
        try:
            with _provider():
                response = self._client.head_object(Bucket=self._bucket, Key=self._full(key))
        except ObjectMissing:
            return None
        return RemoteObject(key, int(response["ContentLength"]), response["LastModified"],
                            response.get("ETag"), response.get("ObjectLockRetainUntilDate"))  # fmt: skip

    @contextmanager
    def reader(self, key: str, version_id: str | None = None) -> Iterator[IO[bytes]]:
        """The object's current bytes, or one older version's (RN-1): a
        version kept by the bucket's versioning and object lock after the
        object was written again."""
        args: dict[str, str] = {"Bucket": self._bucket, "Key": self._full(key)}
        if version_id is not None:
            args["VersionId"] = version_id
        with _provider():
            response = self._client.get_object(**args)  # type: ignore[arg-type]
        body = response["Body"]
        try:
            with _provider():
                yield body  # type: ignore[misc]
        finally:
            body.close()

    def read_bytes(self, key: str, *, limit: int, version_id: str | None = None) -> bytes:
        with self.reader(key, version_id) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise DestinationError("object_too_large")
        return data

    def list(self, prefix: str) -> Iterator[RemoteObject]:
        full_prefix = f"{self._prefix}/{prefix}"
        paginator = self._client.get_paginator("list_objects_v2")
        with _provider():
            for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for item in page.get("Contents", []):
                    key = item["Key"][len(self._prefix) + 1 :]
                    yield RemoteObject(key, int(item["Size"]), item["LastModified"],
                                       item.get("ETag"))  # fmt: skip

    def delete(self, key: str) -> None:
        """A plain delete. On a versioned bucket it only hides the object
        behind a delete marker; retention uses `purge` instead."""
        with _provider():
            self._client.delete_object(Bucket=self._bucket, Key=self._full(key))

    def list_versions(self, prefix: str) -> Iterator[ObjectVersion]:
        """Every version and delete marker under `prefix` (an unversioned
        bucket reports one version per object, id "null")."""
        full_prefix = f"{self._prefix}/{prefix}"
        paginator = self._client.get_paginator("list_object_versions")
        with _provider():
            for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for item, marker in [(v, False) for v in page.get("Versions", [])] + [
                    (m, True) for m in page.get("DeleteMarkers", [])
                ]:
                    size = cast("int | None", item.get("Size"))
                    yield ObjectVersion(item["Key"][len(self._prefix) + 1 :],
                                        item.get("VersionId"), item["LastModified"],
                                        bool(item.get("IsLatest")), marker,
                                        int(size) if size is not None else None,
                                        cast("str | None", item.get("ETag")))  # fmt: skip

    def versions(self, key: str) -> Sequence[ObjectVersion]:
        """Every stored version of exactly this object, newest first, without
        delete markers (RN-1). An unversioned bucket reports one, id "null"."""
        found = [v for v in self.list_versions(key) if v.key == key and not v.delete_marker]
        return sorted(found, key=lambda v: (v.is_latest, v.last_modified), reverse=True)

    def purge(self, key: str) -> bool:
        """Remove EVERY version of one object and its delete markers, so that
        retention really frees the space on a versioned bucket. False when an
        object lock still holds a version: that version stays, and a later
        run removes it once the lock has passed. Retention only."""
        full = self._full(key)
        held = False
        versions = [v for v in self.list_versions(key) if v.key == key]
        if not versions:
            return True
        for version in versions:
            try:
                if version.version_id:
                    self._client.delete_object(
                        Bucket=self._bucket, Key=full, VersionId=version.version_id
                    )
                else:
                    self._client.delete_object(Bucket=self._bucket, Key=full)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in _LOCKED_CODES and self._version_locked(full, version.version_id):
                    held = True
                    continue
                raise _translate(exc) from None
            except BotoCoreError as exc:
                raise _translate(exc) from None
        return not held

    def _version_locked(self, full: str, version_id: str | None) -> bool:
        """Whether a refusal was the lock's, not a missing right of the key."""
        args: dict[str, str] = {"Bucket": self._bucket, "Key": full}
        if version_id:
            args["VersionId"] = version_id
        try:
            retention = self._client.get_object_retention(**args)  # type: ignore[arg-type]
        except (ClientError, BotoCoreError):
            return False
        until = retention.get("Retention", {}).get("RetainUntilDate")
        return until is not None and until > datetime.now(UTC)

    def extend_lock(self, key: str, until: datetime) -> datetime | None:
        """Lengthen this object's COMPLIANCE lock to `until` (never shortens:
        the provider refuses that). Returns the new date."""
        with _provider():
            self._client.put_object_retention(
                Bucket=self._bucket, Key=self._full(key),
                Retention={"Mode": "COMPLIANCE", "RetainUntilDate": until},
            )  # fmt: skip
        head = self.head(key)
        return head.locked_until if head else None

    def abort_stale_uploads(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        aborted = 0
        with _provider():
            response = self._client.list_multipart_uploads(
                Bucket=self._bucket, Prefix=self._prefix + "/"
            )
            for upload in response.get("Uploads", []):
                if upload["Initiated"] < cutoff:
                    self._client.abort_multipart_upload(
                        Bucket=self._bucket, Key=upload["Key"], UploadId=upload["UploadId"]
                    )
                    aborted += 1
        return aborted

    def close(self) -> None:
        self._client.close()


def make_destination(config: object) -> Destination:
    """The destination a `BackupConfig` names."""
    from markx.backup.config import BackupConfig

    assert isinstance(config, BackupConfig)
    if config.destination == "local":
        return LocalDestination(config.destination_dir, prefix=config.destination_prefix)
    return S3Destination(
        config.destination_settings(),
        prefix=config.destination_prefix,
        offsite=config.offsite,
        identity=config.destination_identity,
        lock_min_days=config.object_lock_min_days if config.object_lock_required else None,
    )
