"""MinIO for the object storage tests (D-090).

The tests talk to a real MinIO server, never to Amazon or Cloudflare. CI
starts one beside PostgreSQL (`.github/workflows/ci.yml`) and sets
MARKX_TEST_MINIO_REQUIRED=1, so a missing server fails the run instead of
skipping it. On a laptop:

    docker run -d --name markx-minio -p 127.0.0.1:9000:9000 \\
      -e MINIO_ROOT_USER=markx-dev-only -e MINIO_ROOT_PASSWORD=markx-minio-dev-only-password \\
      bitnamilegacy/minio:2025.7.23-debian-12-r5

Each run makes its own buckets, with a random suffix, and removes them at
the end. Every object written is a generated picture: no real document.
"""

from __future__ import annotations

import os
import secrets
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError

from markx.core.config import get_config
from markx.core.storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    make_s3_client,
    reset_cached_stores,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

ENDPOINT = os.environ.get("MARKX_TEST_MINIO_ENDPOINT", "http://127.0.0.1:9000")
ACCESS_KEY = os.environ.get("MARKX_TEST_MINIO_ACCESS_KEY", "markx-dev-only")
SECRET_KEY = os.environ.get("MARKX_TEST_MINIO_SECRET_KEY", "markx-minio-dev-only-password")
REQUIRED = os.environ.get("MARKX_TEST_MINIO_REQUIRED") == "1"
_RUN = secrets.token_hex(4)


def _minio_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/minio/health/live", timeout=2) as answer:  # noqa: S310
            return bool(answer.status == 200)
    except OSError:
        return False


@pytest.fixture(scope="session")
def minio() -> Iterator[ObjectStorageSettings]:
    """Settings for this run's two buckets on the MinIO server."""
    if not _minio_is_up():
        if REQUIRED:
            pytest.fail(f"MinIO is required (MARKX_TEST_MINIO_REQUIRED=1) but {ENDPOINT} is down")
        pytest.skip(f"no MinIO at {ENDPOINT} (docs/SETUP.md, 'Object storage on a laptop')")
    settings = ObjectStorageSettings(
        provider="minio",
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        private_bucket=f"markx-test-files-{_RUN}-private",
        public_bucket=f"markx-test-files-{_RUN}-public",
    )
    client = make_s3_client(settings)
    buckets = [settings.private_bucket, settings.public_bucket]
    for bucket in buckets:
        client.create_bucket(Bucket=bucket)
    try:
        yield settings
    finally:
        for bucket in (*buckets, *_scratch_buckets):
            empty_and_remove(client, bucket)
        client.close()


_scratch_buckets: list[str] = []


def empty_and_remove(client: S3Client, bucket: str) -> None:
    """Remove a bucket this run made, with the generated pictures in it."""
    try:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                client.delete_object(Bucket=bucket, Key=item["Key"])
        client.delete_bucket(Bucket=bucket)
    except ClientError:
        pass


@pytest.fixture
def scratch_bucket(minio: ObjectStorageSettings) -> Iterator[str]:
    """A bucket of its own, for a test that changes a bucket's policy."""
    name = f"markx-test-{_RUN}-{secrets.token_hex(3)}"
    client = make_s3_client(minio)
    client.create_bucket(Bucket=name)
    _scratch_buckets.append(name)
    try:
        yield name
    finally:
        client.close()


@pytest.fixture
def stores(minio: ObjectStorageSettings) -> Iterator[tuple[S3ObjectStore, S3ObjectStore]]:
    """This run's private and public stores, on their own connection."""
    client = make_s3_client(minio)
    private = S3ObjectStore(client, minio.private_bucket, name="private", settings=minio)
    public = S3ObjectStore(client, minio.public_bucket, name="public", settings=minio)
    try:
        yield private, public
    finally:
        client.close()


def storage_environment(settings: ObjectStorageSettings) -> dict[str, str]:
    return {
        "MARKX_FILE_STORAGE_PROVIDER": settings.provider,
        "MARKX_STORAGE_ENDPOINT_URL": settings.endpoint_url or "",
        "MARKX_STORAGE_REGION": settings.region,
        "MARKX_STORAGE_ACCESS_KEY_ID": settings.access_key_id,
        "MARKX_STORAGE_SECRET_ACCESS_KEY": settings.secret_access_key,
        "MARKX_STORAGE_PRIVATE_BUCKET": settings.private_bucket,
        "MARKX_STORAGE_PUBLIC_BUCKET": settings.public_bucket,
        "MARKX_STORAGE_CONNECT_TIMEOUT_SECONDS": str(settings.connect_timeout),
        "MARKX_STORAGE_READ_TIMEOUT_SECONDS": str(settings.read_timeout),
    }


class SwitchStorage:
    """Points the running API and worker at a store through their own
    configuration, as an operator would with environment variables."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def to(self, settings: ObjectStorageSettings) -> None:
        for name, value in storage_environment(settings).items():
            self._monkeypatch.setenv(name, value)
        get_config.cache_clear()
        reset_cached_stores()

    def to_unreachable(self, settings: ObjectStorageSettings) -> None:
        """A MinIO that is not there: a closed port on this machine."""
        self.to(replace(settings, endpoint_url="http://127.0.0.1:9", connect_timeout=1.0))


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch) -> Iterator[SwitchStorage]:
    yield SwitchStorage(monkeypatch)
    monkeypatch.undo()
    get_config.cache_clear()
    reset_cached_stores()


@pytest.fixture
def on_minio(minio: ObjectStorageSettings, switch: SwitchStorage) -> ObjectStorageSettings:
    """The API and the worker keep their files in this run's MinIO buckets."""
    switch.to(minio)
    return minio
