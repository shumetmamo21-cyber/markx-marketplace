"""Reading the stored files for a backup (D-094). Read-only by construction.

A source offers `list()` and `open()`, nothing else: there is no way for the
backup to write, change or delete a stored file. Two stores, always kept
apart: `private` (documents, picture sources, problem photos) and `public`
(rendered pictures).

The folder source never follows a symbolic link and never leaves its folder;
a link is reported as `skipped_symlink`, not read. Keys are checked against
the storage key pattern, so nothing outside the stores can be named.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from markx.backup.destination import DestinationUnavailable, _translate
from markx.core.storage import (
    ObjectStorageSettings,
    StoredFileRefused,
    StoreName,
    checked_key,
    make_s3_client,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


STORES: tuple[StoreName, StoreName] = ("private", "public")


class SourceMissing(LookupError):
    """A listed object vanished, or a referenced one is not in the store."""


class SourceCorrupt(ValueError):
    """The bytes read are not the bytes the store says it holds."""


@dataclass(frozen=True, slots=True)
class SourceObject:
    store: StoreName
    key: str
    size: int
    # Changes whenever the bytes do: the ETag in a bucket, mtime+size+inode in a folder.
    fingerprint: str
    last_modified: datetime
    # The MD5 the provider states for the bytes (a single-part, unencrypted
    # object's ETag), so a backup can tell a damaged object from a good one.
    expected_md5: str | None = None


@dataclass(frozen=True, slots=True)
class Skipped:
    store: StoreName
    reason: str  # skipped_symlink, unsafe_key, not_a_file


class Source(Protocol):
    def list(self, store: StoreName) -> Iterator[SourceObject | Skipped]: ...

    def open(self, item: SourceObject) -> AbstractContextManager[IO[bytes]]: ...


class FolderSource:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def list(self, store: StoreName) -> Iterator[SourceObject | Skipped]:
        base = self._root / store
        if not base.is_dir() or base.is_symlink():
            return
        for directory, dirnames, filenames in os.walk(base, followlinks=False):
            for name in list(dirnames):
                if os.path.islink(os.path.join(directory, name)):
                    dirnames.remove(name)
                    yield Skipped(store, "skipped_symlink")
            for name in sorted(filenames):
                path = Path(directory) / name
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    yield Skipped(store, "skipped_symlink")
                    continue
                if not stat.S_ISREG(info.st_mode):
                    yield Skipped(store, "not_a_file")
                    continue
                key = path.relative_to(base).as_posix()
                try:
                    checked_key(key)
                except StoredFileRefused:
                    yield Skipped(store, "unsafe_key")
                    continue
                yield SourceObject(
                    store=store, key=key, size=info.st_size,
                    fingerprint=f"{info.st_size}:{info.st_mtime_ns}:{info.st_ino}",
                    last_modified=datetime.fromtimestamp(info.st_mtime, UTC),
                )  # fmt: skip

    @contextmanager
    def open(self, item: SourceObject) -> Iterator[IO[bytes]]:
        path = self._root / item.store / checked_key(item.key)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise SourceMissing(item.key) from None
        except OSError as exc:  # ELOOP: the file became a link since it was listed
            raise SourceMissing(f"unreadable:{type(exc).__name__}") from None
        with os.fdopen(fd, "rb") as handle:
            yield handle


class BucketSource:
    def __init__(self, settings: ObjectStorageSettings, client: S3Client | None = None) -> None:
        self._client = client or make_s3_client(settings)
        self._buckets: dict[StoreName, str] = {
            "private": settings.private_bucket,
            "public": settings.public_bucket,
        }

    def list(self, store: StoreName) -> Iterator[SourceObject | Skipped]:
        paginator = self._client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self._buckets[store]):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    try:
                        checked_key(key)
                    except StoredFileRefused:
                        yield Skipped(store, "unsafe_key")
                        continue
                    etag = str(item.get("ETag", "")).strip('"')
                    md5 = (
                        etag
                        if len(etag) == 32 and all(c in "0123456789abcdef" for c in etag)
                        else None
                    )
                    yield SourceObject(
                        store=store, key=key, size=int(item["Size"]),
                        fingerprint=f"{item['Size']}:{etag}",
                        last_modified=item["LastModified"], expected_md5=md5,
                    )  # fmt: skip
        except (ClientError, BotoCoreError) as exc:
            error = _translate(exc)
            raise DestinationUnavailable(f"source:{error.reason}") from None

    @contextmanager
    def open(self, item: SourceObject) -> Iterator[IO[bytes]]:
        try:
            response = self._client.get_object(Bucket=self._buckets[item.store], Key=item.key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404", "NotFound"):
                raise SourceMissing(item.key) from None
            raise DestinationUnavailable(f"source:provider:{code}") from None
        except BotoCoreError as exc:
            raise DestinationUnavailable(f"source:{type(exc).__name__}") from None
        body = response["Body"]
        try:
            yield body  # type: ignore[misc]
        finally:
            body.close()


def make_source(config: object) -> Source:
    from markx.backup.config import BackupConfig

    assert isinstance(config, BackupConfig)
    if config.source_provider == "local":
        return FolderSource(config.source_dir)
    return BucketSource(config.source_settings())
