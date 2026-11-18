"""Regression tests for the independent audit's P0-1 findings (D-084).

SEC-2: the fake bot check is never trusted on a real server.
SEC-3: X-Forwarded-For is believed only from the configured proxies, and the
       rate limits count the address the proxy saw.
SEC-5: security headers on API responses; HSTS only on real servers.
SEC-6: the anti-forgery guard exempts exact paths only, and none today.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from markx.core import botcheck, ratelimit
from markx.core import http as core_http
from markx.core.config import Config, get_config
from markx.core.errors import PermissionDenied
from markx.main import app
from markx.notifications.sms import read_dev_sms_inbox
from tests.conftest import ApiClient, error_code

PHONE = "0911234567"
E164 = "+251911234567"
TRUSTED_PROXY = "192.0.2.1"  # listed in MARKX_TRUSTED_PROXIES by tests/conftest.py
HOUR = timedelta(hours=1)


def _real_config(**changes: Any) -> Config:
    """The running configuration, as a real server would see it. model_copy
    skips validation, so only the fields named here differ."""
    return get_config().model_copy(update={"env": "production", **changes})


def _safe_production_settings(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "env": "production",
        "secret_key": "test-only-not-a-real-secret-at-least-32-characters",
        "encryption_key": "test-only-not-a-real-encryption-key",
        "database_url": "postgresql+psycopg://markx_app:test-only-password@db:5432/markx",
        "migration_database_url": "postgresql+psycopg://markx_migrator:test-only-password@db:5432/markx",
        "cookie_secure": True,
        "public_origin": "https://markx.example",
    }
    settings.update(overrides)
    return settings


def _otp(
    client: ApiClient, phone: str = PHONE, headers: dict[str, str] | None = None, **extra: Any
) -> Any:
    return client.post("/auth/otp/request", json={"phone": phone, **extra}, headers=headers)


# --------------------------------------------------------------------- SEC-2


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_server_refuses_to_start_with_the_fake_bot_check(env: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_BOT_CHECK_PROVIDER"):
        Config(**_safe_production_settings(env=env, bot_check_provider="fake"))


def test_the_fake_bot_check_is_still_allowed_on_a_laptop_and_in_tests() -> None:
    for env in ("local", "test"):
        assert Config(env=env, bot_check_provider="fake").bot_check_provider == "fake"


@pytest.mark.parametrize("token", [None, "", "fake", "anything", "XXXX.DUMMY.TOKEN", "bot"])
def test_on_a_real_server_no_token_passes_the_bot_check(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    monkeypatch.setattr(botcheck, "get_config", _real_config)
    check = botcheck.get_bot_check()
    assert not isinstance(check, botcheck.FakeBotCheck)
    assert check.verify(token, "198.51.100.7") is False


@pytest.mark.parametrize("extra", [{}, {"bot_token": "fake"}, {"bot_token": "anything"}])
def test_on_a_real_server_sign_in_codes_are_refused_without_a_real_check(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]
) -> None:
    monkeypatch.setattr(botcheck, "get_config", _real_config)
    response = _otp(client, **extra)
    assert response.status_code == 403
    assert error_code(response) == "bot_check_failed"
    assert read_dev_sms_inbox(E164) == []


def test_on_a_laptop_the_fake_still_lets_a_person_through(client: ApiClient) -> None:
    assert _otp(client).status_code == 200
    assert len(read_dev_sms_inbox(E164)) == 1


# --------------------------------------------------------------------- SEC-3


def test_behind_a_trusted_proxy_each_visitor_is_counted_separately(client: ApiClient) -> None:
    proxy = ApiClient(ip=TRUSTED_PROXY)
    for i, visitor in enumerate(("198.51.100.7", "198.51.100.8")):
        assert (
            _otp(proxy, f"09112345{i:02d}", headers={"X-Forwarded-For": visitor}).status_code == 200
        )
    assert ratelimit.current("otp:ip:198.51.100.7", HOUR) == 1
    assert ratelimit.current("otp:ip:198.51.100.8", HOUR) == 1
    assert ratelimit.current(f"otp:ip:{TRUSTED_PROXY}", HOUR) == 0


def test_an_untrusted_caller_cannot_choose_its_address(client: ApiClient) -> None:
    # The default test client is 203.0.113.10, which is not a listed proxy.
    for i, spoof in enumerate(("198.51.100.7", "10.0.0.1", "127.0.0.1")):
        response = _otp(client, f"09112345{i:02d}", headers={"X-Forwarded-For": spoof})
        assert response.status_code == 200
    assert ratelimit.current("otp:ip:203.0.113.10", HOUR) == 3
    for spoof in ("198.51.100.7", "10.0.0.1", "127.0.0.1"):
        assert ratelimit.current(f"otp:ip:{spoof}", HOUR) == 0


def test_addresses_a_visitor_prepends_through_the_proxy_are_ignored(
    client: ApiClient, db: Any
) -> None:
    from markx.core import settings_store

    settings_store.set_setting(db, "auth.otp_per_ip_per_hour", 2)
    db.commit()
    proxy = ApiClient(ip=TRUSTED_PROXY)
    # The proxy appends the address it saw (198.51.100.7) to whatever the
    # visitor sent; changing the visitor's part must not open a new bucket.
    codes = [
        _otp(proxy, f"09112345{i:02d}", headers={"X-Forwarded-For": f"10.9.9.{i}, 198.51.100.7"})
        for i in range(3)
    ]
    assert [r.status_code for r in codes] == [200, 200, 429]
    assert ratelimit.current("otp:ip:198.51.100.7", HOUR) == 3


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "not-an-address", "10.0.0.1/8"])
def test_the_trusted_proxy_list_refuses_wildcards_and_mistakes(value: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_TRUSTED_PROXIES"):
        Config(trusted_proxies=value)


def test_the_trusted_proxy_list_takes_addresses_and_networks() -> None:
    config = Config(trusted_proxies=" 10.0.0.5, 172.18.0.0/16 ,::1 ")
    assert config.trusted_proxy_list == ["10.0.0.5", "172.18.0.0/16", "::1"]
    assert Config(trusted_proxies="").trusted_proxy_list == []


# --------------------------------------------------------------------- SEC-5


def test_api_responses_carry_the_security_headers(client: ApiClient) -> None:
    response = client.get("/healthz")
    assert (
        response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    # Not on a laptop or in tests: HSTS would pin plain-HTTP development.
    assert "strict-transport-security" not in response.headers


def test_a_real_server_sends_hsts(client: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_http, "get_config", lambda: _real_config(public_origin="http://testserver")
    )
    response = client.get("/healthz")
    assert response.headers["strict-transport-security"] == "max-age=31536000"


# --------------------------------------------------------------------- SEC-6


def _post(path: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {"type": "http", "method": "POST", "path": path, "headers": raw, "query_string": b""}
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/webhooks/",
        "/api/v1/webhooks/anything",
        "/api/v1/webhooks/../me",
        "/api/v1/telegram/webhook",
        "/api/v1/telegram/webhookx",
        "/api/v1/telegram/webhook/../../me",
    ],
)
def test_no_path_escapes_the_anti_forgery_guard_by_its_prefix(path: str) -> None:
    with pytest.raises(PermissionDenied) as refused:
        core_http.enforce_request_origin(_post(path))
    assert refused.value.code == "csrf_header_missing"


def test_every_exempt_path_is_an_exact_existing_route() -> None:
    routes = {getattr(route, "path", None) for route in app.routes}
    for path in core_http.CSRF_EXEMPT_PATHS:
        assert path in routes, f"{path} is exempt from the anti-forgery guard but is not a route"
