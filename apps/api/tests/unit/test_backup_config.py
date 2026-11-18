"""The backup service's settings (D-094): a real server never treats a backup
on its own disk as off-server, never borrows the file stores' key, never
falls back to the machine's credentials, and never runs without the
founder's retention decision."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from markx.backup.config import LOCAL_RETENTION_DAYS, LOCAL_RETENTION_MIN_SETS, BackupConfig


def _real(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "env": "production",
        "release": "abc1234",
        "destination": "r2",
        "destination_endpoint_url": "https://0123456789abcdef.r2.cloudflarestorage.com",
        "destination_bucket": "markx-backups",
        "destination_access_key_id": "test-only-backup-key-id",
        "destination_secret_access_key": "test-only-backup-secret",
        "source_provider": "r2",
        "source_endpoint_url": "https://0123456789abcdef.r2.cloudflarestorage.com",
        "source_private_bucket": "markx-private",
        "source_public_bucket": "markx-public",
        "source_access_key_id": "test-only-read-only-key-id",
        "source_secret_access_key": "test-only-read-only-secret",
        "retention_days": 30,
        "retention_min_sets": 7,
        "public_key_file": "/run/secrets/backup-public.key",
        "signing_key_file": "/run/secrets/backup-signing.key",
    }
    settings.update(overrides)
    return settings


def test_a_complete_real_configuration_is_accepted() -> None:
    config = BackupConfig(**_real())
    assert config.service_problems() == []
    assert config.offsite
    assert config.destination_identity == (
        "r2:0123456789abcdef.r2.cloudflarestorage.com/markx-backups/markx"
    )


@pytest.mark.parametrize("destination", ["local", "minio"])
def test_a_real_server_refuses_a_backup_that_stays_on_it(destination: str) -> None:
    with pytest.raises(ValidationError, match="off-server object storage"):
        BackupConfig(**_real(destination=destination,
                             destination_endpoint_url="http://127.0.0.1:9000"))  # fmt: skip


def test_a_real_server_refuses_plain_http() -> None:
    with pytest.raises(ValidationError, match="must be https"):
        BackupConfig(**_real(destination="s3", destination_region="eu-central-1",
                             destination_endpoint_url="http://s3.example.invalid"))  # fmt: skip


def test_the_backup_bucket_is_never_a_file_bucket() -> None:
    with pytest.raises(ValidationError, match="its own bucket"):
        BackupConfig(**_real(destination_bucket="markx-private"))


def test_no_credentials_means_refusal_not_the_machines_own() -> None:
    with pytest.raises(ValidationError, match="never falls back"):
        BackupConfig(**_real(destination_access_key_id=None, destination_secret_access_key=None))


def test_the_service_needs_its_own_key_and_the_founders_retention() -> None:
    config = BackupConfig(
        **_real(destination_access_key_id="test-only-read-only-key-id", retention_days=None,
                retention_min_sets=None, public_key_file=None, signing_key_file=None,
                release="unknown", source_provider="minio")
    )  # fmt: skip
    problems = " | ".join(config.service_problems())
    assert "its own access key" in problems
    assert "RETENTION_DAYS" in problems
    assert "PUBLIC_KEY_FILE" in problems
    assert "SIGNING_KEY_FILE" in problems
    assert "MARKX_RELEASE" in problems
    assert "SOURCE_PROVIDER must be s3 or r2" in problems


def test_keeping_everything_is_an_explicit_choice() -> None:
    config = BackupConfig(**_real(retention_days=0))
    assert config.service_problems() == []
    assert config.effective_retention_days == 0


def test_a_laptop_gets_safe_provisional_defaults() -> None:
    config = BackupConfig(env="local")
    assert config.destination == "local"
    assert not config.offsite
    assert config.service_problems() == []
    assert (config.effective_retention_days, config.effective_retention_min_sets) == (
        LOCAL_RETENTION_DAYS,
        LOCAL_RETENTION_MIN_SETS,
    )


def test_minio_is_never_called_off_server() -> None:
    config = BackupConfig(env="test", destination="minio",
                          destination_endpoint_url="http://127.0.0.1:9000",
                          destination_bucket="markx-backups", destination_access_key_id="k",
                          destination_secret_access_key="s")  # fmt: skip
    assert not config.offsite


@pytest.mark.parametrize("prefix", ["/abs", "a/../b", "trailing/", "", "spaces are bad"])
def test_an_unsafe_prefix_is_refused(prefix: str) -> None:
    with pytest.raises(ValidationError, match="PREFIX"):
        BackupConfig(env="local", destination_prefix=prefix)


def test_no_secret_in_a_refusal() -> None:
    with pytest.raises(ValidationError) as caught:
        BackupConfig(
            **_real(destination="local", destination_secret_access_key="test-only-TOP-SECRET-VALUE")
        )
    assert "test-only-TOP-SECRET-VALUE" not in str(caught.value)
    config = BackupConfig(**_real())
    assert "test-only-backup-secret" not in repr(config)
    assert "test-only-backup-secret" not in repr(config.destination_settings())
