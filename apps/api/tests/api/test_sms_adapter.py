"""The provider-independent SMS adapter (D-089).

No provider is contacted by any test. The adapter is driven by a stand-in
transport and by a real HTTPS server on 127.0.0.1 with a throwaway
certificate made for the test, so TLS, timeouts, refusals and redirects are
real. The configuration's start-up checks are tested here too.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
import urllib.error
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import ValidationError

from markx.core.config import Config
from markx.notifications import sms
from markx.notifications.sms import (
    MAX_RESPONSE_BYTES,
    FakeSmsSender,
    HttpSmsSender,
    NeutralJsonWire,
    SmsErrorCode,
    SmsSendError,
    SmsStatus,
    UrllibTransport,
    count_segments,
    national_format,
    to_e164,
)

API_KEY = "test-only-sms-api-key-0123456789"
OTP = "482913"
TEXT = f"MarkX code: {OTP}. It expires in 5 minutes. Never share it."
PHONE = "0911234567"
E164 = "+251911234567"
ENDPOINT = "https://sms.provider.example/v1/messages"


class StandIn:
    """Records every call; answers with a status and body, or raises."""

    def __init__(self, answer: tuple[int, bytes] | BaseException) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        self.calls.append((url, dict(headers), body, timeout))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _ok(message_id: str = "msg-123") -> tuple[int, bytes]:
    return 200, json.dumps({"message_id": message_id}).encode()


def _sender(transport: Any, **overrides: Any) -> HttpSmsSender:
    settings: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "api_key": API_KEY,
        "sender_id": "MarkX",
        "timeout_seconds": 8.0,
        "transport": transport,
    }
    settings.update(overrides)
    return HttpSmsSender(**settings)


# ------------------------------------------------------------- segments


@pytest.mark.parametrize(
    ("text", "encoding", "segments"),
    [
        ("", "gsm7", 1),
        ("a" * 160, "gsm7", 1),
        ("a" * 161, "gsm7", 2),
        ("a" * 306, "gsm7", 2),
        ("a" * 307, "gsm7", 3),
        ("€" * 80, "gsm7", 1),  # an extension character takes two septets
        ("€" * 81, "gsm7", 2),
        ("ሀ" * 70, "ucs2", 1),
        ("ሀ" * 71, "ucs2", 2),
        ("ሀ" * 134, "ucs2", 2),
        ("ሀ" * 135, "ucs2", 3),
        ("a" * 69 + "ሀ", "ucs2", 1),  # one Amharic letter makes the whole text UCS-2
        ("😀" * 35, "ucs2", 1),  # outside the BMP: two units each
        ("😀" * 36, "ucs2", 2),
    ],
)
def test_segments_are_counted_by_encoding(text: str, encoding: str, segments: int) -> None:
    counted = count_segments(text)
    assert (counted.encoding, counted.segments) == (encoding, segments)


def test_both_login_code_texts_fit_one_segment() -> None:
    from markx.accounts.service import _otp_text

    assert count_segments(_otp_text("123456", "en")).segments == 1
    amharic = count_segments(_otp_text("123456", "am"))
    assert (amharic.encoding, amharic.segments) == ("ucs2", 1)


# --------------------------------------------------------- phone numbers


@pytest.mark.parametrize("form", ["0911234567", "911234567", "+251911234567", "00251911234567"])
def test_the_sending_boundary_hands_over_one_form(form: str) -> None:
    assert to_e164(form) == E164
    assert national_format(form) == "0911234567"
    assert national_format("+251711234567") == "0711234567"


@pytest.mark.parametrize("phone", ["+14155550100", "0811234567", "", "+2519112345678"])
def test_a_number_that_is_not_ethiopian_is_refused_before_sending(phone: str) -> None:
    stand_in = StandIn(_ok())
    with pytest.raises(SmsSendError) as excinfo:
        _sender(stand_in).send(phone, TEXT, reference="r1")
    assert excinfo.value.code is SmsErrorCode.INVALID_PHONE
    assert excinfo.value.status is SmsStatus.FAILED
    assert stand_in.calls == []


# ------------------------------------------------------- the stand-in


def test_a_message_the_provider_accepts() -> None:
    stand_in = StandIn(_ok("abc-42"))
    result = _sender(stand_in, timeout_seconds=3.5).send("0911 23 45 67", TEXT, reference="r-1")
    assert result == sms.SmsResult(
        provider_message_id="abc-42", segments=1, status=SmsStatus.ACCEPTED
    )
    (url, headers, body, timeout) = stand_in.calls[0]
    assert url == ENDPOINT
    assert timeout == 3.5
    assert headers["Authorization"] == f"Bearer {API_KEY}"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body) == {"to": E164, "from": "MarkX", "text": TEXT, "reference": "r-1"}


def test_amharic_is_sent_as_utf8_and_counted_as_unicode() -> None:
    stand_in = StandIn(_ok())
    text = f"የMarkX ኮድ፦ {OTP}። " * 4  # 76 UCS-2 units
    result = _sender(stand_in).send(PHONE, text, reference="r")
    assert result.segments == 2
    body = stand_in.calls[0][2]
    assert "ኮድ".encode() in body
    assert json.loads(body.decode("utf-8"))["text"] == text


def test_a_message_longer_than_six_segments_is_refused_before_sending() -> None:
    stand_in = StandIn(_ok())
    with pytest.raises(SmsSendError) as excinfo:
        _sender(stand_in).send(PHONE, "ሀ" * (67 * 6 + 1), reference="r")
    assert excinfo.value.code is SmsErrorCode.MESSAGE_TOO_LONG
    assert excinfo.value.segments == 7
    assert stand_in.calls == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, SmsErrorCode.INVALID_REQUEST),
        (401, SmsErrorCode.AUTH_FAILED),
        (403, SmsErrorCode.AUTH_FAILED),
        (404, SmsErrorCode.INVALID_REQUEST),
        (422, SmsErrorCode.INVALID_REQUEST),
        (429, SmsErrorCode.RATE_LIMITED),
        (500, SmsErrorCode.PROVIDER_UNAVAILABLE),
        (502, SmsErrorCode.PROVIDER_UNAVAILABLE),
        (503, SmsErrorCode.PROVIDER_UNAVAILABLE),
        (504, SmsErrorCode.PROVIDER_UNAVAILABLE),
        (302, SmsErrorCode.UNEXPECTED_STATUS),
        (418, SmsErrorCode.UNEXPECTED_STATUS),
    ],
)
def test_error_statuses_map_to_provider_independent_codes(status: int, code: SmsErrorCode) -> None:
    stand_in = StandIn((status, b'{"error": "nope"}'))
    with pytest.raises(SmsSendError) as excinfo:
        _sender(stand_in).send(PHONE, TEXT, reference="r")
    assert excinfo.value.code is code
    assert excinfo.value.status is SmsStatus.FAILED
    assert excinfo.value.http_status == status
    # Never retried: a login code goes out at most once.
    assert len(stand_in.calls) == 1


@pytest.mark.parametrize(
    ("answer", "code", "status"),
    [
        (TimeoutError("timed out"), SmsErrorCode.TIMEOUT, SmsStatus.UNKNOWN),
        # How urllib reports a connect timeout.
        (urllib.error.URLError(TimeoutError("timed out")), SmsErrorCode.TIMEOUT, SmsStatus.UNKNOWN),
        (ConnectionRefusedError(111, "refused"), SmsErrorCode.CONNECTION_FAILED, SmsStatus.FAILED),
        (OSError("name not known"), SmsErrorCode.CONNECTION_FAILED, SmsStatus.FAILED),
        (ssl.SSLError("bad certificate"), SmsErrorCode.CONNECTION_FAILED, SmsStatus.FAILED),
        ((200, b"not json"), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        ((200, b"[1, 2]"), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        ((200, b"{}"), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        ((200, b'{"message_id": ""}'), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        ((200, b'{"message_id": 7}'), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        ((200, b'{"message_id": "a\\nb"}'), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        (
            (200, json.dumps({"message_id": "x" * 129}).encode()),
            SmsErrorCode.MALFORMED_RESPONSE,
            SmsStatus.UNKNOWN,
        ),
        ((200, b"\xff\xfe"), SmsErrorCode.MALFORMED_RESPONSE, SmsStatus.UNKNOWN),
        (
            (200, b" " * (MAX_RESPONSE_BYTES + 1)),
            SmsErrorCode.RESPONSE_TOO_LARGE,
            SmsStatus.UNKNOWN,
        ),
    ],
)
def test_failures_fail_closed_and_say_whether_it_may_have_gone_out(
    answer: Any, code: SmsErrorCode, status: SmsStatus
) -> None:
    stand_in = StandIn(answer)
    with pytest.raises(SmsSendError) as excinfo:
        _sender(stand_in).send(PHONE, TEXT, reference="r")
    assert (excinfo.value.code, excinfo.value.status) == (code, status)
    assert len(stand_in.calls) == 1


def test_secrets_codes_and_numbers_never_reach_the_log_or_the_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # The provider's body echoes everything back, as some do on errors.
    echo = json.dumps({"error": TEXT, "key": API_KEY, "to": E164}).encode()
    for answer in [(401, echo), (500, echo), (200, echo), TimeoutError(TEXT + API_KEY)]:
        sender = _sender(StandIn(answer))
        with pytest.raises(SmsSendError) as excinfo:
            sender.send(PHONE, TEXT, reference="ref-9")
        for shown in (str(excinfo.value), repr(excinfo.value), repr(sender)):
            assert OTP not in shown
            assert API_KEY not in shown
            assert E164 not in shown
    assert caplog.records, "a failure is logged"
    for record in caplog.records:
        logged = json.dumps(record.__dict__, default=str) + record.getMessage()
        assert OTP not in logged
        assert API_KEY not in logged
        assert "911234567" not in logged  # in no form of the number
    assert any(getattr(r, "sms_reference", None) == "ref-9" for r in caplog.records)


def test_the_adapter_refuses_an_endpoint_that_is_not_https() -> None:
    with pytest.raises(ValueError, match="https"):
        _sender(StandIn(_ok()), endpoint="http://sms.provider.example/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        UrllibTransport()("http://127.0.0.1:1/", {}, b"", 1.0)


def test_the_wire_format_is_the_only_provider_specific_part() -> None:
    class Other:
        def build(self, message: sms.OutgoingSms, api_key: str) -> sms.WireRequest:
            return sms.WireRequest(body=f"{message.to}|{message.text}".encode(),
                                   headers={"X-Api-Key": api_key})  # fmt: skip

        def message_id(self, answer: Any) -> str | None:
            return str(answer["id"]) if isinstance(answer, dict) and "id" in answer else None

    stand_in = StandIn((201, b'{"id": 99}'))
    result = _sender(stand_in, wire=Other()).send(PHONE, "hi", reference="r")
    assert result.provider_message_id == "99"
    assert stand_in.calls[0][1]["X-Api-Key"] == API_KEY
    assert "Authorization" not in stand_in.calls[0][1]
    assert isinstance(
        NeutralJsonWire().build(sms.OutgoingSms(E164, "t", "S", "r"), "k").body, bytes
    )


def test_the_fake_returns_a_result_and_still_fills_the_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox.jsonl"
    result = FakeSmsSender(inbox).send(PHONE, TEXT, reference="abc")
    assert result == sms.SmsResult("fake-abc", 1, SmsStatus.ACCEPTED)
    line = json.loads(inbox.read_text(encoding="utf-8"))
    assert (line["phone"], line["text"]) == (E164, TEXT)


# ---------------------------------------------------- a real HTTPS server


class _Provider(BaseHTTPRequestHandler):
    behaviour: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        _Provider.behaviour.setdefault("received", []).append(
            (dict(self.headers.items()), self.rfile.read(length))
        )
        time.sleep(_Provider.behaviour.get("delay", 0))
        if "location" in _Provider.behaviour:
            self.send_response(307)
            self.send_header("Location", _Provider.behaviour["location"])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = _Provider.behaviour.get("body", json.dumps({"message_id": "srv-1"}).encode())
        self.send_response(_Provider.behaviour.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # The client stops reading a huge body, as it should.
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # keep the test output clean
        pass


def _throwaway_certificate(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
def provider(tmp_path: Path) -> Iterator[tuple[str, ssl.SSLContext]]:
    """A local HTTPS server and a client context that trusts only its
    throwaway certificate."""
    cert_path, key_path = _throwaway_certificate(tmp_path)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    _Provider.behaviour = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert_path))
    yield f"https://127.0.0.1:{server.server_address[1]}/v1/messages", client_context
    server.shutdown()
    server.server_close()


def _over_https(url: str, context: ssl.SSLContext | None, timeout: float = 3.0) -> HttpSmsSender:
    transport = UrllibTransport(context=context, use_env_proxy=False)
    return _sender(transport, endpoint=url, timeout_seconds=timeout)


def test_over_https_a_message_is_accepted(provider: tuple[str, ssl.SSLContext]) -> None:
    url, context = provider
    result = _over_https(url, context).send(PHONE, "የMarkX ኮድ፦ 123456", reference="r-7")
    assert result.provider_message_id == "srv-1"
    ((headers, body),) = _Provider.behaviour["received"]
    assert headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(body.decode("utf-8"))["text"] == "የMarkX ኮድ፦ 123456"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, SmsErrorCode.INVALID_REQUEST),
        (401, SmsErrorCode.AUTH_FAILED),
        (403, SmsErrorCode.AUTH_FAILED),
        (429, SmsErrorCode.RATE_LIMITED),
        (500, SmsErrorCode.PROVIDER_UNAVAILABLE),
        (503, SmsErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_over_https_error_statuses(
    provider: tuple[str, ssl.SSLContext], status: int, code: SmsErrorCode
) -> None:
    url, context = provider
    _Provider.behaviour.update(status=status, body=b'{"error": "x"}')
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, context).send(PHONE, TEXT, reference="r")
    assert (excinfo.value.code, excinfo.value.http_status) == (code, status)
    assert len(_Provider.behaviour["received"]) == 1  # no retry


def test_over_https_a_slow_provider_times_out(provider: tuple[str, ssl.SSLContext]) -> None:
    url, context = provider
    _Provider.behaviour["delay"] = 1.5
    started = time.monotonic()
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, context, timeout=0.3).send(PHONE, TEXT, reference="r")
    assert time.monotonic() - started < 1.4
    assert (excinfo.value.code, excinfo.value.status) == (SmsErrorCode.TIMEOUT, SmsStatus.UNKNOWN)


def test_over_https_an_oversized_answer_is_not_read_in_full(
    provider: tuple[str, ssl.SSLContext],
) -> None:
    url, context = provider
    _Provider.behaviour["body"] = b'{"message_id": "' + b"x" * (4 * MAX_RESPONSE_BYTES) + b'"}'
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, context).send(PHONE, TEXT, reference="r")
    assert excinfo.value.code is SmsErrorCode.RESPONSE_TOO_LARGE


def test_over_https_a_malformed_answer(provider: tuple[str, ssl.SSLContext]) -> None:
    url, context = provider
    _Provider.behaviour["body"] = b"<html>gateway</html>"
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, context).send(PHONE, TEXT, reference="r")
    assert excinfo.value.code is SmsErrorCode.MALFORMED_RESPONSE


def test_over_https_a_redirect_is_refused_and_not_followed(
    provider: tuple[str, ssl.SSLContext],
) -> None:
    url, context = provider
    _Provider.behaviour["location"] = url.replace("/v1/messages", "/elsewhere")
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, context).send(PHONE, TEXT, reference="r")
    assert excinfo.value.code is SmsErrorCode.REDIRECT_REFUSED
    assert len(_Provider.behaviour["received"]) == 1  # the key went nowhere else


def test_over_https_an_untrusted_certificate_is_refused(
    provider: tuple[str, ssl.SSLContext],
) -> None:
    url, _ = provider
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(url, ssl.create_default_context()).send(PHONE, TEXT, reference="r")
    assert excinfo.value.code is SmsErrorCode.CONNECTION_FAILED
    assert "received" not in _Provider.behaviour


def test_over_https_a_refused_connection() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The port is closed again: the connection is refused.
    with pytest.raises(SmsSendError) as excinfo:
        _over_https(f"https://127.0.0.1:{port}/v1/messages", None).send(PHONE, TEXT, reference="r")
    assert (excinfo.value.code, excinfo.value.status) == (
        SmsErrorCode.CONNECTION_FAILED,
        SmsStatus.FAILED,
    )


# ------------------------------------------------------- configuration


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
        "sms_api_url": ENDPOINT,
        "sms_api_key": API_KEY,
        "sms_sender_id": "MarkX",
    }
    settings.update(overrides)
    return settings


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_server_refuses_to_start_with_the_fake_sms_sender(env: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_SMS_PROVIDER must be a real SMS provider"):
        Config(**_production(env=env, sms_provider="fake"))


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize(
    ("missing", "named"),
    [
        ("sms_api_url", "MARKX_SMS_API_URL"),
        ("sms_api_key", "MARKX_SMS_API_KEY"),
        ("sms_sender_id", "MARKX_SMS_SENDER_ID"),
    ],
)
def test_a_real_server_refuses_to_start_without_the_providers_settings(
    env: str, missing: str, named: str
) -> None:
    with pytest.raises(ValidationError, match=named):
        Config(**_production(env=env, **{missing: None}))
    with pytest.raises(ValidationError, match=named):
        Config(**_production(env=env, **{missing: "  "}))


def test_a_real_server_starts_with_a_complete_sms_configuration() -> None:
    config = Config(**_production())
    assert config.sms_provider == "http"
    assert config.sms_timeout_seconds == 8.0
    assert API_KEY not in repr(config)
    assert API_KEY not in str(config.model_dump())


def test_the_fake_is_still_allowed_on_a_laptop_and_in_tests() -> None:
    for env in ("local", "test"):
        assert Config(env=env).sms_provider == "fake"


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("http://sms.example/send", "https://"),
        ("ftp://sms.example/send", "https://"),
        ("https:///send", "host"),
        ("https://user:pass@sms.example/send", "user name or password"),
        ("https://sms.example/send?key=abc", "query"),
        ("https://sms.example/send#x", "query or fragment"),
        ("https://sms.example:99999/send", "not a valid URL"),
        ("not a url", "https://"),
    ],
)
def test_the_endpoint_must_be_a_fixed_https_url(url: str, problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        Config(sms_api_url=url)


@pytest.mark.parametrize("sender", ["MarkX", "MARKX2026", "8811", "+251911234567"])
def test_valid_sender_ids(sender: str) -> None:
    assert Config(sms_sender_id=sender).sms_sender_id == sender


@pytest.mark.parametrize("sender", ["Mark X", "MarkXMarketplace", "ማርክኤክስ", "1234567890123456"])
def test_invalid_sender_ids(sender: str) -> None:
    with pytest.raises(ValidationError, match="MARKX_SMS_SENDER_ID"):
        Config(sms_sender_id=sender)


@pytest.mark.parametrize("timeout", [0, -1, 31])
def test_the_timeout_is_short_and_positive(timeout: float) -> None:
    with pytest.raises(ValidationError):
        Config(sms_timeout_seconds=timeout)


def test_a_missing_key_error_never_shows_the_other_values() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Config(sms_provider="http", sms_api_key=API_KEY, sms_sender_id="MarkX")
    assert "MARKX_SMS_API_URL must be set" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_the_factory_builds_the_https_adapter_from_the_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config(sms_provider="http", sms_api_url=ENDPOINT, sms_api_key=API_KEY,
                    sms_sender_id="MarkX", sms_timeout_seconds=4)  # fmt: skip
    monkeypatch.setattr(sms, "get_config", lambda: config)
    sender = sms.get_sms_sender()
    assert isinstance(sender, HttpSmsSender)
    assert API_KEY not in repr(sender)


def test_the_factory_refuses_the_fake_on_a_real_server_as_a_second_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from markx.core.config import get_config

    config = get_config().model_copy(update={"env": "production"})
    monkeypatch.setattr(sms, "get_config", lambda: config)
    with pytest.raises(RuntimeError, match="fake SMS sender is refused"):
        sms.get_sms_sender()
