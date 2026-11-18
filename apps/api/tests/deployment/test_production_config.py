"""What a real server (staging or production) refuses to start with (D-091).

One complete, valid production configuration made of test-only values;
then each required setting taken away or made unsafe, one at a time. A
refusal must name the setting and must never repeat a value.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from markx.core.config import Config

# Test-only placeholders. None of them is a credential for anything.
SECRET_VALUES = {
    "secret_key": "test-only-not-a-real-secret-at-least-32-characters",
    # base64 of "test-only-not-a-real-key-32bytes": a well-formed Fernet key.
    "encryption_key": "dGVzdC1vbmx5LW5vdC1hLXJlYWwta2V5LTMyYnl0ZXM=",
    "database_url": "postgresql+psycopg://markx_app:test-only-app-pw-5a1c@postgres:5432/markx",
    "migration_database_url": "postgresql+psycopg://markx_migrator@postgres:5432/markx",
    "turnstile_secret_key": "test-only-turnstile-secret-9f2e",
    "sms_api_key": "test-only-sms-api-key-77ab",
    "storage_access_key_id": "test-only-storage-key-id-31cd",
    "storage_secret_access_key": "test-only-storage-secret-e44f",
}


def production(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "env": "production",
        **SECRET_VALUES,
        "public_origin": "https://markx.example",
        "cookie_secure": True,
        "trusted_proxies": "172.30.10.0/24",
        "bot_check_provider": "turnstile",
        "turnstile_site_key": "test-only-turnstile-site-key",
        "turnstile_allowed_hostnames": "markx.example,www.markx.example",
        "sms_provider": "http",
        "sms_api_url": "https://sms.provider.example/v1/messages",
        "sms_sender_id": "MarkX",
        "file_storage_provider": "r2",
        "storage_endpoint_url": "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com",
        "storage_private_bucket": "markx-documents",
        "storage_public_bucket": "markx-pictures",
        "public_media_base_url": "https://media.markx.example",
        "log_level": "INFO",
    }
    settings.update(overrides)
    return settings


def refusal(**overrides: Any) -> str:
    with pytest.raises(ValidationError) as caught:
        Config(**production(**overrides))
    text = str(caught.value)
    for value in SECRET_VALUES.values():
        assert value not in text, "a refused start-up must never print a value"
    assert "test-only-app-pw" not in text
    return text


@pytest.mark.parametrize("env", ["production", "staging"])
def test_a_complete_real_configuration_starts(env: str) -> None:
    config = Config(**production(env=env))
    assert config.is_real_environment
    assert not config.dev_tools_enabled


def test_the_complete_configuration_is_also_valid_with_amazon_s3() -> None:
    Config(
        **production(
            file_storage_provider="s3", storage_endpoint_url=None, storage_region="eu-central-1"
        )
    )


@pytest.mark.parametrize("env", ["production", "staging"])
@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"secret_key": "short"}, "MARKX_SECRET_KEY"),
        ({"secret_key": "dev-only-secret-key-change-me-0123456789abcdef"}, "MARKX_SECRET_KEY"),
        (
            {"encryption_key": "ZGV2LW9ubHktZW5jcnlwdGlvbi1rZXktMzJieXRlcyE="},
            "MARKX_ENCRYPTION_KEY must not be the development key",
        ),
        ({"encryption_key": "not-a-fernet-key"}, "MARKX_ENCRYPTION_KEY must be a Fernet key"),
        (
            {"database_url": "postgresql+psycopg://markx_app:markx_app_dev-only@postgres/markx"},
            "database passwords must not be the development passwords",
        ),
        ({"cookie_secure": False}, "MARKX_COOKIE_SECURE must be true"),
        ({"public_origin": "http://markx.example"}, "MARKX_PUBLIC_ORIGIN must be an https://"),
        ({"public_origin": "https://markx.example/shop"}, "MARKX_PUBLIC_ORIGIN must be the bare"),
        ({"bot_check_provider": "fake"}, "MARKX_BOT_CHECK_PROVIDER must be a real bot check"),
        ({"sms_provider": "fake"}, "MARKX_SMS_PROVIDER must be a real SMS provider"),
        ({"file_storage_provider": "local"}, "MARKX_FILE_STORAGE_PROVIDER must be real"),
        (
            {"file_storage_provider": "minio", "storage_endpoint_url": "https://minio.example"},
            "not minio",
        ),
        (
            {"public_media_base_url": "/api/v1/media"},
            "MARKX_PUBLIC_MEDIA_BASE_URL must be the picture CDN",
        ),
        (
            {"public_media_base_url": "https://markx.example/media"},
            "MARKX_PUBLIC_MEDIA_BASE_URL must be on its own domain",
        ),
        ({"log_level": "DEBUG"}, "MARKX_LOG_LEVEL must not be DEBUG"),
        ({"turnstile_secret_key": None}, "MARKX_TURNSTILE_SECRET_KEY must be set"),
        ({"turnstile_site_key": ""}, "MARKX_TURNSTILE_SITE_KEY must be set"),
        (
            {"turnstile_allowed_hostnames": "localhost"},
            "is for local testing only",
        ),
        ({"sms_api_key": None}, "MARKX_SMS_API_KEY must be set"),
        ({"sms_api_url": None}, "MARKX_SMS_API_URL must be set"),
        ({"sms_sender_id": None}, "MARKX_SMS_SENDER_ID must be set"),
        ({"storage_private_bucket": None}, "MARKX_STORAGE_PRIVATE_BUCKET must be set"),
        ({"storage_public_bucket": None}, "MARKX_STORAGE_PUBLIC_BUCKET must be set"),
        (
            {"storage_public_bucket": "markx-documents"},
            "the private and the public bucket must be two different buckets",
        ),
        ({"storage_secret_access_key": None}, "MARKX_STORAGE_SECRET_ACCESS_KEY must be set"),
        ({"storage_endpoint_url": None}, "MARKX_STORAGE_ENDPOINT_URL must be set for r2"),
    ],
)
def test_each_unsafe_or_missing_setting_is_refused_by_name(
    env: str, overrides: dict[str, Any], named: str
) -> None:
    assert named in refusal(env=env, **overrides)


@pytest.mark.parametrize("env", ["production", "staging"])
def test_trusted_proxies_must_be_set_on_purpose(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default, loopback only, would make every visitor behind the proxy
    one address: one busy minute would throttle the whole site (D-091)."""
    monkeypatch.delenv("MARKX_TRUSTED_PROXIES", raising=False)
    settings = production(env=env)
    del settings["trusted_proxies"]
    with pytest.raises(ValidationError, match="MARKX_TRUSTED_PROXIES must be set explicitly"):
        Config(**settings)
    # The same value, said on purpose, is accepted (a proxy on the same host).
    Config(**production(env=env, trusted_proxies="127.0.0.1,::1"))


def test_trusted_proxies_set_through_the_environment_counts_as_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKX_TRUSTED_PROXIES", "172.30.10.0/24")
    settings = production()
    del settings["trusted_proxies"]
    assert Config(**settings).trusted_proxy_list == ["172.30.10.0/24"]


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "not-an-address"])
def test_trusted_proxies_never_trusts_everyone(value: str) -> None:
    assert "MARKX_TRUSTED_PROXIES" in refusal(trusted_proxies=value)


def test_every_problem_is_listed_at_once_with_development_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server started with nothing but MARKX_ENV=production is refused
    with the whole list, so the operator fixes it in one go."""
    monkeypatch.delenv("MARKX_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("MARKX_TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError) as caught:
        Config(env="production")
    text = str(caught.value)
    for named in (
        "MARKX_SECRET_KEY",
        "MARKX_ENCRYPTION_KEY",
        "database passwords",
        "MARKX_COOKIE_SECURE",
        "MARKX_PUBLIC_ORIGIN",
        "MARKX_TRUSTED_PROXIES",
        "MARKX_BOT_CHECK_PROVIDER",
        "MARKX_SMS_PROVIDER",
        "MARKX_FILE_STORAGE_PROVIDER",
        "MARKX_PUBLIC_MEDIA_BASE_URL",
    ):
        assert named in text
    assert "input_value" not in text


def test_a_refused_start_up_never_prints_the_raw_configuration() -> None:
    """Before D-091 pydantic printed part of the input, a password included."""
    text = refusal(sms_provider="fake")
    assert "input_value" not in text
    assert "postgres:5432" not in text


@pytest.mark.parametrize("level", ["verbose", "", "TRACE"])
def test_an_unknown_log_level_is_refused_everywhere(level: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_LOG_LEVEL must be one of"):
        Config(log_level=level)


def test_a_log_level_is_accepted_in_any_case() -> None:
    assert Config(log_level="warning").log_level == "WARNING"


def test_a_laptop_keeps_its_development_defaults() -> None:
    """The rules above are for real servers only: a laptop starts as before."""
    config = Config(env="local")
    assert config.bot_check_provider == "fake"
    assert config.sms_provider == "fake"
    assert config.startup_warnings() == []


def test_a_real_server_without_an_alert_destination_says_so_at_start_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARKX_TELEGRAM_BOT_TOKEN", raising=False)
    warnings = Config(**production()).startup_warnings()
    about_alerts = [w for w in warnings if "MARKX_ALERT_TELEGRAM_CHAT_ID" in w]
    assert len(about_alerts) == 1
    # D-092: nor does it have a Telegram push provider, and it says that too.
    assert len(warnings) == 2
    configured = Config(
        **production(
            telegram_bot_token="123456:TEST-ONLY-bot-token-not-a-real-secret",
            alert_telegram_chat_id="-1000000000000",
            telegram_push_provider="bot_api",
        )
    )
    assert configured.startup_warnings() == []


def test_a_real_server_without_a_push_provider_starts_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-092: no bot exists yet, so a real server must start without one, use
    no push provider at all, and say so in words at start-up."""
    monkeypatch.delenv("MARKX_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MARKX_TELEGRAM_PUSH_PROVIDER", raising=False)
    config = Config(**production())
    assert config.push_provider == "none"
    assert any("no Telegram push provider" in w for w in config.startup_warnings())
    assert Config(env="local").push_provider == "fake"


def test_a_real_server_refuses_the_fake_push_sender_and_bot_api_needs_its_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARKX_TELEGRAM_BOT_TOKEN", raising=False)
    assert "MARKX_TELEGRAM_PUSH_PROVIDER" in refusal(telegram_push_provider="fake")
    with pytest.raises(ValidationError, match="MARKX_TELEGRAM_BOT_TOKEN"):
        Config(**production(telegram_push_provider="bot_api"))
