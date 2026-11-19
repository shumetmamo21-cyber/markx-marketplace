"""Readiness reaches the real file stores (D-091), on MinIO only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from markx.core.storage import ObjectStorageSettings
from markx.ops import checks, health
from tests.conftest import ApiClient
from tests.storage.conftest import SwitchStorage


def test_ready_when_both_buckets_answer(client: ApiClient, on_minio: ObjectStorageSettings) -> None:
    health.storage_probe.reset()
    response = client.get("/healthz/ready")
    assert response.status_code == 200
    assert response.json()["storage"] == "up"


def test_not_ready_while_the_store_is_unreachable_and_nothing_is_named(
    client: ApiClient, minio: ObjectStorageSettings, switch: SwitchStorage
) -> None:
    switch.to_unreachable(minio)
    health.storage_probe.reset()
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["storage"] == "down"
    for secret_or_internal in (
        minio.private_bucket,
        minio.public_bucket,
        minio.access_key_id,
        minio.secret_access_key,
        "127.0.0.1:9",
    ):
        assert secret_or_internal not in response.text
    health.storage_probe.reset()


def test_a_missing_bucket_is_an_outage_for_readiness_and_the_watch(
    client: ApiClient, minio: ObjectStorageSettings, switch: SwitchStorage, db: Session
) -> None:
    """S3 answers a HEAD on a missing bucket with a bare 404. Before D-091 the
    watch's storage check raised on it (the job failed) instead of alerting."""
    switch.to(replace(minio, public_bucket=f"{minio.public_bucket}-gone"))
    health.storage_probe.reset()
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["storage"] == "down"
    findings = checks.file_storage(db, datetime.now(UTC))
    assert [f.key for f in findings] == ["storage.unreachable:public"]
    assert findings[0].details["reason"] == "NoSuchBucket"
    health.storage_probe.reset()
