"""Cloudflare Turnstile, verified on the server (D-085).

Cloudflare is never called: every test stands in for Siteverify, either as a
function or as a real HTTP server on 127.0.0.1, so timeouts, refusals and
broken answers are exercised through the same code a real server runs.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import ValidationError

from markx.core import botcheck
from markx.core.botcheck import (
    SIGN_IN_ACTION,
    SITEVERIFY_URL,
    TurnstileBotCheck,
    urllib_transport,
)
from markx.core.config import Config, get_config
from markx.notifications.sms import read_dev_sms_inbox
from tests.conftest import ApiClient, error_code

# Clearly fake values; no real key exists in this repository.
SECRET = "0x4-test-only-not-a-real-turnstile-secret"
SITE_KEY = "0x4-test-only-not-a-real-turnstile-site-key"
TOKEN = "test-only-token.abc123"
HOST = "markx.example"
E164 = "+251911234567"


def _ok(**changes: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "success": True,
        "challenge_ts": "2026-11-18T03:00:00.000Z",
        "hostname": HOST,
        "error-codes": [],
        "action": SIGN_IN_ACTION,
        "cdata": "",
    }
    answer.update(changes)
    return answer


class Cloudflare:
    """Stands in for Siteverify and records what it was sent."""

    def __init__(self, *answers: Any, status: int = 200) -> None:
        self.answers = list(answers)
        self.status = status
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, fields: dict[str, str], timeout: float) -> tuple[int, bytes]:
        self.calls.append((url, dict(fields), timeout))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        body = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return self.status, body


def _check(cloudflare: Any, **kwargs: Any) -> TurnstileBotCheck:
    return TurnstileBotCheck(
        secret_key=SECRET,
        allowed_hostnames=[HOST],
        timeout_seconds=kwargs.pop("timeout_seconds", 5.0),
        transport=cloudflare,
        **kwargs,
    )


# ------------------------------------------------------------- a real "yes"


def test_a_solved_token_passes_and_cloudflare_is_asked_properly() -> None:
    cloudflare = Cloudflare(_ok())
    assert _check(cloudflare).verify(TOKEN, "198.51.100.7") is True
    [(url, fields, timeout)] = cloudflare.calls
    assert url == SITEVERIFY_URL == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert fields == {"secret": SECRET, "response": TOKEN, "remoteip": "198.51.100.7"}
    assert timeout == 5.0


def test_without_an_address_none_is_sent() -> None:
    cloudflare = Cloudflare(_ok())
    assert _check(cloudflare).verify(TOKEN, None) is True
    assert "remoteip" not in cloudflare.calls[0][1]


def test_the_hostname_is_compared_without_case() -> None:
    assert _check(Cloudflare(_ok(hostname="MarkX.Example"))).verify(TOKEN, None) is True


# ------------------------------------------------- tokens that are refused


@pytest.mark.parametrize("token", [None, "", "   "])
def test_a_missing_token_is_refused_without_asking_cloudflare(token: str | None) -> None:
    cloudflare = Cloudflare(_ok())
    assert _check(cloudflare).verify(token, None) is False
    assert cloudflare.calls == []


@pytest.mark.parametrize("token", ["x" * 2049, "token-with-ünïcode", "token\nwith-newline"])
def test_a_malformed_token_is_refused_without_asking_cloudflare(token: str) -> None:
    cloudflare = Cloudflare(_ok())
    assert _check(cloudflare).verify(token, None) is False
    assert cloudflare.calls == []


@pytest.mark.parametrize(
    "codes",
    [
        ["invalid-input-response"],  # forged or garbage token
        ["timeout-or-duplicate"],  # expired, or already used once
        ["missing-input-response"],
        ["invalid-input-secret"],  # our secret is wrong: refuse, never pass
        ["internal-error"],
        ["bad-request"],
        [],
    ],
)
def test_cloudflare_saying_no_is_a_no(codes: list[str]) -> None:
    answer = {"success": False, "error-codes": codes}
    assert _check(Cloudflare(answer)).verify(TOKEN, None) is False


def test_a_reused_token_is_refused_the_second_time() -> None:
    # Cloudflare redeems a token once; the second ask says "timeout-or-duplicate".
    cloudflare = Cloudflare(_ok(), {"success": False, "error-codes": ["timeout-or-duplicate"]})
    check = _check(cloudflare)
    assert check.verify(TOKEN, None) is True
    assert check.verify(TOKEN, None) is False
    assert len(cloudflare.calls) == 2


@pytest.mark.parametrize("success", ["true", 1, None, "yes"])
def test_only_a_literal_true_counts_as_success(success: Any) -> None:
    assert _check(Cloudflare(_ok(success=success))).verify(TOKEN, None) is False


@pytest.mark.parametrize("hostname", ["evil.example", "markx.example.evil.example", "", None, 7])
def test_a_token_solved_on_another_site_is_refused(hostname: Any) -> None:
    assert _check(Cloudflare(_ok(hostname=hostname))).verify(TOKEN, None) is False


@pytest.mark.parametrize("action", ["checkout", "", None, "SIGN_IN"])
def test_a_token_solved_for_another_action_is_refused(action: Any) -> None:
    assert _check(Cloudflare(_ok(action=action))).verify(TOKEN, None) is False


def test_an_answer_without_hostname_or_action_is_refused() -> None:
    assert _check(Cloudflare({"success": True})).verify(TOKEN, None) is False


# ------------------------------------------- Cloudflare unwell: fail closed


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("timed out"),
        ConnectionRefusedError(),
        OSError("network unreachable"),
        urllib.error.URLError("name resolution failed"),
        RuntimeError("anything else"),
    ],
)
def test_an_unreachable_cloudflare_refuses(failure: BaseException) -> None:
    assert _check(Cloudflare(failure)).verify(TOKEN, None) is False


@pytest.mark.parametrize("status", [400, 403, 429, 500, 502, 503])
def test_an_error_status_refuses_even_with_a_success_body(status: int) -> None:
    assert _check(Cloudflare(_ok(), status=status)).verify(TOKEN, None) is False


@pytest.mark.parametrize(
    "body", [b"", b"<html>bad gateway</html>", b"[true]", b'"success"', b"\xff\xfe", b"null"]
)
def test_a_broken_answer_refuses(body: bytes) -> None:
    assert _check(Cloudflare(body)).verify(TOKEN, None) is False


def test_an_oversized_answer_refuses() -> None:
    huge = json.dumps(_ok(cdata="x" * (botcheck.MAX_RESPONSE_BYTES + 10))).encode()
    assert _check(Cloudflare(huge)).verify(TOKEN, None) is False


# ----------------------------------------------- the secret stays secret


def test_neither_the_secret_nor_the_token_is_ever_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for cloudflare in (
        Cloudflare({"success": False, "error-codes": ["timeout-or-duplicate"]}),
        Cloudflare(TimeoutError("timed out")),
        Cloudflare(_ok(hostname="evil.example")),
        Cloudflare(b"not json"),
    ):
        _check(cloudflare).verify(TOKEN, "198.51.100.7")
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "bot check refused" in logged
    assert "timeout-or-duplicate" in logged  # the reason is useful and kept
    for private in (SECRET, TOKEN, "198.51.100.7"):
        assert private not in logged


def test_the_secret_is_not_in_reprs_or_validation_errors() -> None:
    check = _check(Cloudflare(_ok()))
    assert SECRET not in repr(check)
    config = Config(bot_check_provider="turnstile", turnstile_secret_key=SECRET,
                    turnstile_site_key=SITE_KEY)  # fmt: skip
    assert SECRET not in repr(config)
    assert SECRET not in str(config.model_dump())
    with pytest.raises(ValidationError) as refused:
        Config(bot_check_provider="turnstile", turnstile_secret_key=SECRET)
    assert SECRET not in str(refused.value)


# ------------------------------------------------------- configuration


def test_turnstile_needs_both_keys() -> None:
    with pytest.raises(ValidationError, match="MARKX_TURNSTILE_SECRET_KEY must be set"):
        Config(bot_check_provider="turnstile", turnstile_site_key=SITE_KEY)
    with pytest.raises(ValidationError, match="MARKX_TURNSTILE_SITE_KEY must be set"):
        Config(bot_check_provider="turnstile", turnstile_secret_key=SECRET)


def test_the_allowed_hostname_defaults_to_the_public_origin() -> None:
    config = Config(public_origin="https://www.MarkX.example", bot_check_provider="turnstile",
                    turnstile_secret_key=SECRET, turnstile_site_key=SITE_KEY)  # fmt: skip
    assert config.turnstile_hostnames == ["www.markx.example"]
    config = Config(turnstile_allowed_hostnames="markx.example, www.markx.example")
    assert config.turnstile_hostnames == ["markx.example", "www.markx.example"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("markx.et", "markx.et"),
        ("MarkX.et, www.markx.et", "markx.et,www.markx.et"),
        (" localhost ", "localhost"),
        ("staging.markx.et,markx.et,www.markx.et", "staging.markx.et,markx.et,www.markx.et"),
        ("xn--mgbh0fb.et", "xn--mgbh0fb.et"),
        ("", ""),
    ],
)
def test_bare_hostnames_are_accepted(value: str, expected: str) -> None:
    assert Config(turnstile_allowed_hostnames=value).turnstile_allowed_hostnames == expected


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("https://markx.et", "includes a protocol"),
        ("http://localhost:3000", "includes a protocol"),
        ("markx.et/sign-in", "includes a path"),
        ("markx.et/", "includes a path"),
        ("markx.et?x=1", "includes a path"),
        ("markx.et:443", "includes a port"),
        ("localhost:3000", "includes a port"),
        ("*.markx.et", "is a wildcard"),
        ("*", "is a wildcard"),
        ("127.0.0.1", "is an IP address"),
        ("[::1]", "is an IP address"),
        ("markx.et.", "ends with a dot"),
        ("markx.et,,www.markx.et", "is empty"),
        ("markx.et,", "is empty"),
        ("mark x.et", "contains a space"),
        ("-markx.et", "is not a valid hostname"),
        ("markx_et", "is not a valid hostname"),
        ("ማርክ.et", "is not a valid hostname"),
        ("a" * 64 + ".et", "is not a valid hostname"),
    ],
)
def test_malformed_hostnames_are_refused_with_the_reason(value: str, reason: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_TURNSTILE_ALLOWED_HOSTNAMES") as refused:
        Config(turnstile_allowed_hostnames=value)
    assert reason in str(refused.value)


def test_every_bad_entry_is_named_at_once() -> None:
    with pytest.raises(ValidationError) as refused:
        Config(turnstile_allowed_hostnames="https://markx.et, markx.et, *.markx.et")
    message = str(refused.value)
    assert "'https://markx.et' includes a protocol" in message
    assert "'*.markx.et' is a wildcard" in message
    assert "'markx.et' " not in message.replace("'https://markx.et'", "")


@pytest.mark.parametrize("hostnames", ["localhost", "markx.et,localhost", "app.localhost"])
def test_a_real_server_refuses_a_localhost_widget(hostnames: str) -> None:
    with pytest.raises(ValidationError, match="is for local testing only"):
        Config(**_production(turnstile_allowed_hostnames=hostnames))


def test_a_laptop_may_use_a_localhost_widget() -> None:
    config = Config(bot_check_provider="turnstile", turnstile_secret_key=SECRET,
                    turnstile_site_key=SITE_KEY, turnstile_allowed_hostnames="localhost")  # fmt: skip
    assert config.turnstile_hostnames == ["localhost"]


def test_a_bad_hostname_stops_the_start_with_a_clear_message(tmp_path: Path) -> None:
    """What a person sees when the API starts with a mistake in its settings,
    and that the secret is not part of it."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("MARKX_")}
    env.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        MARKX_ENV="local",
        MARKX_BOT_CHECK_PROVIDER="turnstile",
        MARKX_TURNSTILE_SITE_KEY=SITE_KEY,
        MARKX_TURNSTILE_SECRET_KEY=SECRET,
        MARKX_TURNSTILE_ALLOWED_HOSTNAMES="https://markx.et",
    )
    started = subprocess.run(
        [sys.executable, "-c", "from markx.core.config import get_config; get_config()"],
        cwd=tmp_path,  # no .env file here
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert started.returncode != 0
    assert "MARKX_TURNSTILE_ALLOWED_HOSTNAMES" in started.stderr
    assert "'https://markx.et' includes a protocol" in started.stderr
    assert SECRET not in started.stderr + started.stdout


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
        "turnstile_secret_key": SECRET,
        "turnstile_site_key": SITE_KEY,
        # A real server also needs a real SMS sender (D-089).
        "sms_provider": "http",
        "sms_api_url": "https://sms.provider.example/v1/messages",
        "sms_api_key": "test-only-sms-api-key",
        "sms_sender_id": "MarkX",
    }
    settings.update(overrides)
    return settings


def test_a_real_server_starts_with_turnstile_configured() -> None:
    config = Config(**_production())
    assert isinstance(_real_check(config), TurnstileBotCheck)


@pytest.mark.parametrize(
    "keys",
    [
        # Cloudflare's published dummy keys: they pass or fail everyone.
        {"turnstile_secret_key": "1x0000000000000000000000000000000AA"},
        {"turnstile_secret_key": "2x0000000000000000000000000000000AA"},
        {"turnstile_site_key": "1x00000000000000000000AA"},
        {"turnstile_site_key": "3x00000000000000000000FF"},
    ],
)
def test_a_real_server_refuses_cloudflare_test_keys(keys: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="not Cloudflare's test keys"):
        Config(**_production(**keys))


def test_test_keys_are_allowed_on_a_laptop() -> None:
    config = Config(bot_check_provider="turnstile", turnstile_secret_key="1x0000000000000000000000000000000AA",
                    turnstile_site_key="1x00000000000000000000AA")  # fmt: skip
    assert config.bot_check_provider == "turnstile"


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_server_still_refuses_the_fake(env: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_BOT_CHECK_PROVIDER"):
        Config(**_production(env=env, bot_check_provider="fake"))


def _real_check(config: Config) -> Any:
    original = botcheck.get_config
    botcheck.get_config = lambda: config  # type: ignore[assignment]
    try:
        return botcheck.get_bot_check()
    finally:
        botcheck.get_config = original  # type: ignore[assignment]


# --------------------------- the real HTTP code, against a local stand-in


@pytest.fixture
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)


class _Siteverify(BaseHTTPRequestHandler):
    behaviour: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        _Siteverify.behaviour["received"] = urllib.parse.parse_qs(self.rfile.read(length).decode())
        _Siteverify.behaviour["content_type"] = self.headers.get("Content-Type")
        time.sleep(_Siteverify.behaviour.get("delay", 0))
        body = json.dumps(_Siteverify.behaviour.get("answer", _ok())).encode()
        self.send_response(_Siteverify.behaviour.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def siteverify(no_proxy: None) -> Iterator[str]:
    _Siteverify.behaviour = {}
    server = HTTPServer(("127.0.0.1", 0), _Siteverify)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/turnstile/v0/siteverify"
    server.shutdown()
    server.server_close()


def _over_http(url: str, timeout: float = 2.0) -> TurnstileBotCheck:
    return TurnstileBotCheck(secret_key=SECRET, allowed_hostnames=[HOST], timeout_seconds=timeout,
                             transport=urllib_transport, url=url)  # fmt: skip


def test_over_http_a_solved_token_passes_and_is_sent_form_encoded(siteverify: str) -> None:
    assert _over_http(siteverify).verify(TOKEN, "198.51.100.7") is True
    assert _Siteverify.behaviour["content_type"] == "application/x-www-form-urlencoded"
    assert _Siteverify.behaviour["received"] == {
        "secret": [SECRET],
        "response": [TOKEN],
        "remoteip": ["198.51.100.7"],
    }


def test_over_http_a_slow_cloudflare_times_out_and_refuses(siteverify: str) -> None:
    _Siteverify.behaviour["delay"] = 1.0
    started = time.monotonic()
    assert _over_http(siteverify, timeout=0.2).verify(TOKEN, None) is False
    assert time.monotonic() - started < 0.9


@pytest.mark.parametrize("status", [500, 503, 429])
def test_over_http_an_error_status_refuses(siteverify: str, status: int) -> None:
    _Siteverify.behaviour["status"] = status
    assert _over_http(siteverify).verify(TOKEN, None) is False


def test_over_http_a_cloudflare_no_refuses(siteverify: str) -> None:
    _Siteverify.behaviour["answer"] = {"success": False, "error-codes": ["invalid-input-response"]}
    assert _over_http(siteverify).verify(TOKEN, None) is False


def test_over_http_nobody_listening_refuses(no_proxy: None) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The port is closed again: the connection is refused.
    assert _over_http(f"http://127.0.0.1:{port}/siteverify").verify(TOKEN, None) is False


# ----------------------------------------- the sign-in route, end to end


@pytest.fixture
def turnstile_on(monkeypatch: pytest.MonkeyPatch) -> Cloudflare:
    config = get_config().model_copy(
        update={"bot_check_provider": "turnstile", "turnstile_secret_key": Config(
            turnstile_secret_key=SECRET).turnstile_secret_key, "turnstile_site_key": SITE_KEY,
            "turnstile_allowed_hostnames": "testserver"}
    )  # fmt: skip
    cloudflare = Cloudflare(_ok(hostname="testserver"))
    monkeypatch.setattr(botcheck, "get_config", lambda: config)
    monkeypatch.setattr(botcheck, "urllib_transport", cloudflare)
    return cloudflare


def _ask(client: ApiClient, **extra: Any) -> Any:
    return client.post("/auth/otp/request", json={"phone": "0911234567", **extra})


def test_sign_in_with_a_solved_token_sends_the_code(
    client: ApiClient, turnstile_on: Cloudflare
) -> None:
    assert _ask(client, bot_token=TOKEN).status_code == 200
    assert len(read_dev_sms_inbox(E164)) == 1
    assert turnstile_on.calls[0][1]["response"] == TOKEN
    assert turnstile_on.calls[0][1]["remoteip"] == "203.0.113.10"


@pytest.mark.parametrize(
    ("extra", "answer"),
    [
        ({}, None),  # no token at all
        ({"bot_token": ""}, None),
        ({"bot_token": TOKEN}, {"success": False, "error-codes": ["invalid-input-response"]}),
        ({"bot_token": TOKEN}, {"success": False, "error-codes": ["timeout-or-duplicate"]}),
        ({"bot_token": TOKEN}, TimeoutError("timed out")),
    ],
)
def test_sign_in_without_a_valid_token_sends_nothing(
    client: ApiClient, turnstile_on: Cloudflare, extra: dict[str, str], answer: Any
) -> None:
    if answer is not None:
        turnstile_on.answers = [answer]
    response = _ask(client, **extra)
    assert response.status_code == 403
    assert error_code(response) == "bot_check_failed"
    assert read_dev_sms_inbox(E164) == []
