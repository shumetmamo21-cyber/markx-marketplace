"""Choosing the file store by configuration (D-090): what each provider
needs, what a real server refuses, and that switching providers needs no
change anywhere but the environment."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from markx.core import storage
from markx.core.config import Config
from markx.core.storage import (
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStorageSettings,
    S3ObjectStore,
    get_private_storage,
    get_public_storage,
    make_s3_client,
    object_storage_settings,
)
from tests.storage.conftest import SwitchStorage

R2_ENDPOINT = "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
KEY_ID = "test-only-storage-key-id"
SECRET = "test-only-storage-secret-not-real"


def _object_storage(provider: str, **overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "file_storage_provider": provider,
        "storage_access_key_id": KEY_ID,
        "storage_secret_access_key": SECRET,
        "storage_private_bucket": "markx-documents",
        "storage_public_bucket": "markx-pictures",
    }
    if provider == "r2":
        settings["storage_endpoint_url"] = R2_ENDPOINT
    if provider == "minio":
        settings["storage_endpoint_url"] = "http://127.0.0.1:9000"
    if provider == "s3":
        settings["storage_region"] = "eu-central-1"
    settings.update(overrides)
    return settings


def _production(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "env": "production",
        "secret_key": "test-only-not-a-real-secret-at-least-32-characters",
        "encryption_key": "test-only-not-a-real-encryption-key",
        "database_url": "postgresql+psycopg://markx_app:test-only-password@db:5432/markx",
        "migration_database_url": "postgresql+psycopg://markx_migrator:test-only-password@db:5432/markx",
        "cookie_secure": True,
        "public_origin": "https://markx.example",
        "bot_check_provider": "turnstile",
        "turnstile_secret_key": "test-only-turnstile-secret",
        "turnstile_site_key": "test-only-turnstile-site-key",
        "sms_provider": "http",
        "sms_api_url": "https://sms.provider.example/v1/messages",
        "sms_api_key": "test-only-sms-api-key",
        "sms_sender_id": "MarkX",
        "public_media_base_url": "https://media.markx.example",
        **_object_storage("r2"),
    }
    settings.update(overrides)
    return settings


# -- what each provider needs ---------------------------------------------------------


@pytest.mark.parametrize("provider", ["minio", "s3", "r2"])
def test_each_provider_starts_with_its_settings(provider: str) -> None:
    config = Config(**_object_storage(provider))
    settings = object_storage_settings(config)
    assert settings.provider == provider
    assert (settings.private_bucket, settings.public_bucket) == (
        "markx-documents",
        "markx-pictures",
    )


@pytest.mark.parametrize("provider", ["minio", "s3", "r2"])
@pytest.mark.parametrize(
    ("missing", "named"),
    [
        ("storage_private_bucket", "MARKX_STORAGE_PRIVATE_BUCKET"),
        ("storage_public_bucket", "MARKX_STORAGE_PUBLIC_BUCKET"),
        ("storage_access_key_id", "MARKX_STORAGE_ACCESS_KEY_ID"),
        ("storage_secret_access_key", "MARKX_STORAGE_SECRET_ACCESS_KEY"),
    ],
)
def test_a_store_without_its_buckets_or_keys_does_not_start(
    provider: str, missing: str, named: str
) -> None:
    for value in (None, "   "):
        with pytest.raises(ValidationError, match=named):
            Config(**_object_storage(provider, **{missing: value}))


@pytest.mark.parametrize("provider", ["minio", "r2"])
def test_minio_and_r2_need_their_endpoint(provider: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_STORAGE_ENDPOINT_URL must be set"):
        Config(**_object_storage(provider, storage_endpoint_url=None))


def test_s3_needs_its_region() -> None:
    with pytest.raises(ValidationError, match="MARKX_STORAGE_REGION must be set for s3"):
        Config(**_object_storage("s3", storage_region=None))


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com.evil.example",
        "https://r2.cloudflarestorage.com.attacker.example",
        "https://s3.eu-central-1.amazonaws.com",
    ],
)
def test_r2_accepts_only_a_cloudflare_r2_endpoint(endpoint: str) -> None:
    with pytest.raises(ValidationError, match=r"r2\.cloudflarestorage\.com endpoint"):
        Config(**_object_storage("r2", storage_endpoint_url=endpoint))


@pytest.mark.parametrize(
    ("endpoint", "reason"),
    [
        ("ftp://storage.example", "must start with https://"),
        ("https://user:pass@storage.example", "must not carry a user name or password"),
        ("https://storage.example/bucket", "must be the endpoint only"),
        ("https://storage.example?key=x", "must be the endpoint only"),
        ("https://", "must name a host"),
        ("https://storage.example:99999", "not a valid URL"),
    ],
)
def test_the_endpoint_is_a_bare_origin(endpoint: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        Config(**_object_storage("minio", storage_endpoint_url=endpoint))


@pytest.mark.parametrize(
    "bucket", ["ab", "Markx-Docs", "markx_docs", "markx.docs", "-markx", "markx-", "x" * 64]
)
def test_bucket_names_are_plain(bucket: str) -> None:
    with pytest.raises(ValidationError, match="3 to 63 lowercase letters"):
        Config(**_object_storage("minio", storage_private_bucket=bucket))


def test_documents_never_share_a_bucket_with_public_pictures() -> None:
    with pytest.raises(ValidationError, match="two different buckets"):
        Config(**_object_storage("r2", storage_public_bucket="markx-documents"))


def test_the_keys_never_reach_a_log_or_an_error() -> None:
    config = Config(**_object_storage("r2"))
    settings = object_storage_settings(config)
    for text in (repr(config), str(config.model_dump()), repr(settings), str(settings)):
        assert SECRET not in text
        assert KEY_ID not in text
    with pytest.raises(ValidationError) as refused:
        Config(**_object_storage("r2", storage_public_bucket="markx-documents"))
    assert SECRET not in str(refused.value)


# -- what a real server refuses ----------------------------------------------------------


def test_a_real_server_starts_with_r2_or_s3() -> None:
    assert Config(**_production()).file_storage_provider == "r2"
    s3 = Config(**_production(**_object_storage("s3", storage_endpoint_url=None)))
    assert s3.file_storage_provider == "s3"


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("provider", ["local", "minio"])
def test_a_real_server_refuses_its_own_disk_and_minio(env: str, provider: str) -> None:
    with pytest.raises(ValidationError, match="must be real object storage"):
        Config(**_production(env=env, **_object_storage(provider)))


def test_a_real_server_refuses_plain_http_to_its_store() -> None:
    with pytest.raises(ValidationError, match="must be an https:// endpoint"):
        Config(**_production(**_object_storage("s3", storage_endpoint_url="http://s3.example")))


@pytest.mark.parametrize(
    ("media", "reason"),
    [
        ("/api/v1/media", "the picture CDN's https:// address"),
        ("http://media.markx.example", "the picture CDN's https:// address"),
        ("https://markx.example/media", "on its own domain"),
    ],
)
def test_a_real_server_serves_pictures_from_their_own_domain(media: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        Config(**_production(public_media_base_url=media))


def test_a_laptop_may_keep_its_files_on_disk_or_in_minio() -> None:
    assert Config().file_storage_provider == "local"
    assert Config(**_object_storage("minio")).file_storage_provider == "minio"


# -- each provider's connection -----------------------------------------------------------


def _settings(provider: str, **overrides: Any) -> ObjectStorageSettings:
    return object_storage_settings(Config(**_object_storage(provider, **overrides)))


@pytest.mark.parametrize(
    ("provider", "endpoint", "region", "style", "encryption"),
    [
        ("minio", "http://127.0.0.1:9000", "us-east-1", "path", None),
        ("s3", "https://s3.eu-central-1.amazonaws.com", "eu-central-1", "virtual", "AES256"),
        ("r2", R2_ENDPOINT, "auto", "path", None),
    ],
)
def test_each_provider_gets_its_own_endpoint_region_addressing_and_encryption(
    provider: str, endpoint: str, region: str, style: str, encryption: str | None
) -> None:
    settings = _settings(provider)
    client = make_s3_client(settings)
    try:
        assert client.meta.endpoint_url == endpoint
        assert client.meta.region_name == region
        assert client.meta.config.s3 is not None
        assert client.meta.config.s3["addressing_style"] == style
    finally:
        client.close()
    assert settings.encryption == encryption


def test_encryption_can_be_asked_for_or_left_out() -> None:
    assert _settings("r2", storage_server_side_encryption="AES256").encryption == "AES256"
    assert _settings("s3", storage_server_side_encryption="none").encryption is None


def test_only_markx_own_keys_and_endpoint_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever AWS settings the machine has, MarkX uses its own: never the
    founder's other AWS credentials, never another endpoint (AGENTS.md)."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-only-someone-elses-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-only-someone-elses-secret")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://elsewhere.example")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://elsewhere.example")
    for provider in ("s3", "r2", "minio"):
        client = make_s3_client(_settings(provider))
        try:
            credentials = client._request_signer._credentials
            assert credentials is not None
            assert (credentials.access_key, credentials.secret_key) == (KEY_ID, SECRET)
            assert "elsewhere" not in client.meta.endpoint_url
        finally:
            client.close()


def test_switching_providers_is_only_configuration(switch: SwitchStorage) -> None:
    """The same calls reach the local folders, then MinIO, then R2's settings,
    with nothing changed in the code that stores files."""
    assert isinstance(get_private_storage(), LocalPrivateStorage)
    assert isinstance(get_public_storage(), LocalPublicStorage)

    switch.to(_settings("minio"))
    private, public = get_private_storage(), get_public_storage()
    assert isinstance(private, S3ObjectStore)
    assert isinstance(public, S3ObjectStore)
    assert (private.bucket, public.bucket) == ("markx-documents", "markx-pictures")
    assert get_private_storage() is private  # one connection pool, reused

    switch.to(_settings("r2"))
    r2 = get_private_storage()
    assert isinstance(r2, S3ObjectStore)
    assert r2 is not private
    assert r2._client.meta.endpoint_url == R2_ENDPOINT


def test_the_factories_still_refuse_the_disk_on_a_real_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second barrier behind the start-up check."""

    class Real:
        is_real_environment = True
        file_storage_provider = "local"
        storage_dir = "unused"

    monkeypatch.setattr(storage, "get_config", lambda: Real())
    for factory in (get_private_storage, get_public_storage):
        with pytest.raises(RuntimeError, match="development only"):
            factory()
