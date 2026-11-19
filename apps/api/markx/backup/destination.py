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
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol

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
    """What the destination holds is not what was sent."""

    retryable = True


class ObjectMissing(DestinationError):
    """The object is not at the destination."""


@dataclass(frozen=True, slots=True)
class RemoteObject:
    key: str
    size: int
    last_modified: datetime


def checked(key: str) -> str:
    if not _KEY.fullmatch(key) or len(key) > 512:
        raise DestinationError("unsafe_key")
    return key


class Destination(Protocol):
    identity: str
    offsite: bool

    def check_access(self) -> None: ...

    def put_file(self, key: str, path: Path, sha256: str) -> None: ...

    def head(self, key: str) -> RemoteObject | None: ...

    def reader(self, key: str) -> AbstractContextManager[IO[bytes]]: ...

    def read_bytes(self, key: str, *, limit: int) -> bytes: ...

    def list(self, prefix: str) -> Iterator[RemoteObject]: ...

    def delete(self, key: str) -> None: ...

    def abort_stale_uploads(self, older_than: timedelta) -> int: ...


def _hash_stream(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_COPY_BUFFER):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


# -- a folder: a laptop and the tests -------------------------------------------------


class LocalDestination:
    offsite = False

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

    def put_file(self, key: str, path: Path, sha256: str) -> None:
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
        self._verify(key, path.stat().st_size, sha256)

    def _verify(self, key: str, size: int, sha256: str) -> None:
        with self.reader(key) as stream:
            got_sha, got_size = _hash_stream(stream)
        if got_size != size or got_sha != sha256:
            raise VerificationFailed("readback_mismatch")

    def head(self, key: str) -> RemoteObject | None:
        path = self._path(key)
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        return RemoteObject(key, info.st_size, datetime.fromtimestamp(info.st_mtime, UTC))

    @contextmanager
    def reader(self, key: str) -> Iterator[IO[bytes]]:
        try:
            handle = self._path(key).open("rb")
        except FileNotFoundError:
            raise ObjectMissing("missing") from None
        with handle:
            yield handle

    def read_bytes(self, key: str, *, limit: int) -> bytes:
        with self.reader(key) as stream:
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
            yield RemoteObject(key, info.st_size, datetime.fromtimestamp(info.st_mtime, UTC))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

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
    ) -> None:
        self._settings = settings
        self._bucket = settings.private_bucket
        self._prefix = prefix
        self._client = client or make_s3_client(settings)
        self.offsite = offsite
        self.identity = identity
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

    def put_file(self, key: str, path: Path, sha256: str) -> None:
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
            raise VerificationFailed("size_mismatch")
        with self.reader(key) as stream:
            got_sha, got_size = _hash_stream(stream)
        if got_size != size or got_sha != sha256:
            raise VerificationFailed("readback_mismatch")

    def head(self, key: str) -> RemoteObject | None:
        try:
            with _provider():
                response = self._client.head_object(Bucket=self._bucket, Key=self._full(key))
        except ObjectMissing:
            return None
        return RemoteObject(key, int(response["ContentLength"]), response["LastModified"])

    @contextmanager
    def reader(self, key: str) -> Iterator[IO[bytes]]:
        with _provider():
            response = self._client.get_object(Bucket=self._bucket, Key=self._full(key))
        body = response["Body"]
        try:
            with _provider():
                yield body  # type: ignore[misc]
        finally:
            body.close()

    def read_bytes(self, key: str, *, limit: int) -> bytes:
        with self.reader(key) as stream:
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
                    yield RemoteObject(key, int(item["Size"]), item["LastModified"])

    def delete(self, key: str) -> None:
        with _provider():
            self._client.delete_object(Bucket=self._bucket, Key=self._full(key))

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
    )
