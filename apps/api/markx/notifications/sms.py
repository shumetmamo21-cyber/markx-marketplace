"""SMS behind an adapter (blueprint F.0, F.9; D-016, D-089).

Release 1 needs a local Ethiopian SMS provider, which is still unresolved
(section O, question 23). This module is the provider-independent half:

* `SmsSender` is the one interface: `send(phone, text, *, reference)` returns
  an `SmsResult` (the provider's message id, the number of segments, the
  status) or raises `SmsSendError` with a provider-independent error code.
* `FakeSmsSender` never sends anything: it appends to a file the dev-only
  inbox endpoint reads, so sign-in works on a laptop and in tests.
* `HttpSmsSender` is the skeleton of a real adapter, on the standard library
  only: HTTPS to one fixed configured endpoint, a short timeout, no
  redirects, no automatic retries, a bounded response, fail closed. What a
  provider's request and answer look like is not known until one is chosen,
  so that part is a small `SmsWireFormat`; `NeutralJsonWire` is MarkX's own
  placeholder, not any provider's API. Choosing a provider means writing its
  wire format, nothing else here.
* `sms_messages` holds a delivery record per message (`SmsMessage`): never
  the text, never a code, never the whole phone number.

The message text, the API key and the whole phone number are never logged
and never part of an error message.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from http.client import HTTPResponse
from pathlib import Path
from ssl import SSLContext
from typing import Any, Protocol

from sqlalchemy.orm import Session as DbSession

from markx.core.config import get_config
from markx.core.ids import uuid7
from markx.core.phone import InvalidPhoneNumber, mask_phone, normalize_phone
from markx.core.security import keyed_hash
from markx.notifications.models import SmsMessage, SmsPurpose, SmsStatus

logger = logging.getLogger("markx.sms")

# A provider's answer to one message is small; never read an unbounded body.
MAX_RESPONSE_BYTES = 16 * 1024
# A provider message id longer than this, or with control characters, is not one.
MAX_MESSAGE_ID_LENGTH = 128
# Longer messages are refused before anything is sent (cost and abuse).
MAX_SEGMENTS = 6


class SmsErrorCode(StrEnum):
    """Provider-independent reasons a message did not go out."""

    INVALID_PHONE = "invalid_phone"  # not an Ethiopian mobile number
    MESSAGE_TOO_LONG = "message_too_long"  # more than MAX_SEGMENTS
    INVALID_REQUEST = "invalid_request"  # 400, 404, 413, 422: the provider refused it
    AUTH_FAILED = "auth_failed"  # 401, 403: the key or sender is wrong
    RATE_LIMITED = "rate_limited"  # 429
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # 5xx
    UNEXPECTED_STATUS = "unexpected_status"  # any other status
    TIMEOUT = "timeout"  # no answer in time: it may have been sent
    CONNECTION_FAILED = "connection_failed"  # refused, DNS, TLS: nothing was sent
    REDIRECT_REFUSED = "redirect_refused"  # the endpoint tried to send us elsewhere
    MALFORMED_RESPONSE = "malformed_response"  # 2xx but unreadable: it may have been sent
    RESPONSE_TOO_LARGE = "response_too_large"  # 2xx but too big: it may have been sent
    SEND_ERROR = "send_error"  # an error in MarkX's own code around the send


class SmsSendError(Exception):
    """The message did not go out, or may not have. `status` is `failed` when
    nothing was sent and `unknown` when the provider may have taken it. The
    string form carries the code only: never the text, key or number."""

    def __init__(
        self,
        code: SmsErrorCode,
        *,
        status: SmsStatus = SmsStatus.FAILED,
        http_status: int | None = None,
        segments: int = 1,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status = status
        self.http_status = http_status
        self.segments = segments


@dataclass(frozen=True, slots=True)
class SmsResult:
    provider_message_id: str | None
    segments: int
    status: SmsStatus


class SmsSender(Protocol):
    provider: str

    def send(self, phone: str, text: str, *, reference: str) -> SmsResult: ...


# -------------------------------------------------------------------- segments

# The GSM 03.38 default alphabet, and its extension table (two septets each).
_GSM_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = frozenset("^{}\\[~]|€\f")


@dataclass(frozen=True, slots=True)
class SegmentCount:
    encoding: str  # "gsm7" or "ucs2"
    units: int  # septets for GSM-7, UTF-16 code units for UCS-2
    segments: int


def count_segments(text: str) -> SegmentCount:
    """How many SMS segments a text needs. GSM-7 holds 160 septets in one
    segment and 153 per part when split; anything else (Amharic, most
    symbols) is UCS-2: 70 code units in one, 67 per part. A character outside
    the Basic Multilingual Plane (an emoji) takes two UCS-2 units."""
    if all(c in _GSM_BASIC or c in _GSM_EXTENDED for c in text):
        units = sum(2 if c in _GSM_EXTENDED else 1 for c in text)
        single, part = 160, 153
        encoding = "gsm7"
    else:
        units = len(text.encode("utf-16-le")) // 2
        single, part = 70, 67
        encoding = "ucs2"
    segments = 1 if units <= single else -(-units // part)
    return SegmentCount(encoding=encoding, units=units, segments=segments)


# ----------------------------------------------------------------- phone numbers


def to_e164(phone: str) -> str:
    """The number as the sending boundary hands it over: +2519XXXXXXXX or
    +2517XXXXXXXX. Anything that is not an Ethiopian mobile number is refused
    here too, whatever the caller checked before."""
    try:
        return normalize_phone(phone)
    except InvalidPhoneNumber as exc:
        raise SmsSendError(SmsErrorCode.INVALID_PHONE) from exc


def national_format(phone: str) -> str:
    """09XXXXXXXX or 07XXXXXXXX, for a provider that wants the national form."""
    return "0" + to_e164(phone)[4:]


def phone_reference(phone: str) -> bytes:
    """What a delivery record keeps instead of the number: a keyed hash under
    the server secret. The same number always gives the same reference, so
    the resend cooldown and support can find a number's records; a copy of the
    database alone does not reveal the numbers."""
    return keyed_hash("sms-phone", normalize_phone(phone))


def _prepare(phone: str, text: str) -> tuple[str, int]:
    number = to_e164(phone)
    segments = count_segments(text).segments
    if segments > MAX_SEGMENTS:
        raise SmsSendError(SmsErrorCode.MESSAGE_TOO_LONG, segments=segments)
    return number, segments


# --------------------------------------------------------------------- the fake


class FakeSmsSender:
    """For a laptop and the tests only: writes the message to the dev inbox."""

    provider = "fake"

    def __init__(self, inbox: Path) -> None:
        self._inbox = inbox

    def send(self, phone: str, text: str, *, reference: str) -> SmsResult:
        number, segments = _prepare(phone, text)
        self._inbox.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"phone": number, "text": text, "sent_at": datetime.now(UTC).isoformat()},
            ensure_ascii=False,
        )
        with self._inbox.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return SmsResult(
            provider_message_id=f"fake-{reference}", segments=segments, status=SmsStatus.ACCEPTED
        )


def dev_sms_inbox_path() -> Path:
    return get_config().storage_dir / "dev" / "sms-inbox.jsonl"


def read_dev_sms_inbox(phone: str) -> list[dict[str, str]]:
    path = dev_sms_inbox_path()
    if not path.exists():
        return []
    messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [m for m in messages if m["phone"] == phone]


# ---------------------------------------------------------- the HTTPS adapter


@dataclass(frozen=True, slots=True)
class OutgoingSms:
    to: str  # +251…, already checked
    text: str
    sender_id: str
    reference: str


@dataclass(frozen=True, slots=True)
class WireRequest:
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


class SmsWireFormat(Protocol):
    """How one provider's request and answer look. Written when a provider is
    chosen, from its own documentation."""

    def build(self, message: OutgoingSms, api_key: str) -> WireRequest: ...

    def message_id(self, answer: Any) -> str | None:
        """The provider's id from a parsed 2xx JSON answer; None if absent."""
        ...


class NeutralJsonWire:
    """MarkX's own placeholder shape, NOT any provider's API (D-089): a JSON
    POST of `to`, `from`, `text` and `reference` with the key as a bearer
    token, answered by a JSON object carrying `message_id`. It exists so the
    adapter can be built and tested before a provider is chosen; a gateway
    that speaks exactly this could use it, but no known provider does."""

    def build(self, message: OutgoingSms, api_key: str) -> WireRequest:
        body = json.dumps(
            {
                "to": message.to,
                "from": message.sender_id,
                "text": message.text,
                "reference": message.reference,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return WireRequest(
            body=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    def message_id(self, answer: Any) -> str | None:
        if not isinstance(answer, dict):
            return None
        value = answer.get("message_id")
        return value if isinstance(value, str) else None


# (url, headers, body, timeout) -> (HTTP status, at most MAX_RESPONSE_BYTES + 1 bytes)
Transport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]


class RedirectRefused(urllib.error.URLError):
    pass


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A fixed endpoint never sends us elsewhere; following a redirect would
    hand the key and the message to another address."""

    def http_error_302(self, req: Any, fp: Any, code: int, msg: str, headers: Any) -> None:
        fp.close()  # the socket is released before refusing
        raise RedirectRefused("redirect refused")

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class UrllibTransport:
    """POST over HTTPS with the standard library. Errors are raised to the
    caller. `context` and `use_env_proxy` exist for the tests' local server."""

    def __init__(self, *, context: SSLContext | None = None, use_env_proxy: bool = True) -> None:
        handlers: list[urllib.request.BaseHandler] = [
            _NoRedirects(),
            urllib.request.HTTPSHandler(context=context),
        ]
        if not use_env_proxy:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise ValueError("SMS is sent over HTTPS only")
        request = urllib.request.Request(  # noqa: S310  (https:// checked above)
            url, data=body, method="POST", headers=dict(headers)
        )
        try:
            response: HTTPResponse = self._opener.open(request, timeout=timeout)
            with response:
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:  # a 4xx or 5xx answer
            if 300 <= exc.code < 400:
                raise RedirectRefused("redirect refused") from exc
            with exc:
                return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)


def _status_error(status: int) -> SmsErrorCode:
    if status in (400, 404, 405, 409, 413, 415, 422):
        return SmsErrorCode.INVALID_REQUEST
    if status in (401, 403):
        return SmsErrorCode.AUTH_FAILED
    if status == 429:
        return SmsErrorCode.RATE_LIMITED
    if 500 <= status < 600:
        return SmsErrorCode.PROVIDER_UNAVAILABLE
    return SmsErrorCode.UNEXPECTED_STATUS


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)


class HttpSmsSender:
    """The provider-independent HTTPS adapter (D-089). One attempt per
    message: a login code is never sent twice by MarkX on its own."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        sender_id: str,
        timeout_seconds: float,
        provider: str = "http",
        wire: SmsWireFormat | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("the SMS endpoint must be an https:// URL")
        if not api_key:
            raise ValueError("an SMS API key is required")
        if not sender_id:
            raise ValueError("an SMS sender id is required")
        self.provider = provider
        self._endpoint = endpoint
        self._key = api_key
        self._sender_id = sender_id
        self._timeout = timeout_seconds
        self._wire: SmsWireFormat = wire or NeutralJsonWire()
        self._transport: Transport = transport or UrllibTransport()

    def __repr__(self) -> str:  # never show the key
        return f"HttpSmsSender(provider={self.provider!r}, sender_id={self._sender_id!r})"

    def send(self, phone: str, text: str, *, reference: str) -> SmsResult:
        number, segments = _prepare(phone, text)
        request = self._wire.build(
            OutgoingSms(to=number, text=text, sender_id=self._sender_id, reference=reference),
            self._key,
        )
        headers = {"Accept": "application/json", "User-Agent": "MarkX-SMS/1", **request.headers}
        try:
            status, raw = self._transport(self._endpoint, headers, request.body, self._timeout)
        except RedirectRefused as exc:
            raise self._fail(SmsErrorCode.REDIRECT_REFUSED, segments, reference) from exc
        except Exception as exc:  # timeout, refused, DNS, TLS: fail closed
            if _is_timeout(exc):
                raise self._fail(
                    SmsErrorCode.TIMEOUT, segments, reference, status=SmsStatus.UNKNOWN
                ) from exc
            raise self._fail(SmsErrorCode.CONNECTION_FAILED, segments, reference) from exc
        if not 200 <= status < 300:
            raise self._fail(_status_error(status), segments, reference, http_status=status)
        # From here the provider said yes in some form: if the answer cannot be
        # read, the message may still have gone out.
        if len(raw) > MAX_RESPONSE_BYTES:
            raise self._fail(
                SmsErrorCode.RESPONSE_TOO_LARGE, segments, reference, status=SmsStatus.UNKNOWN
            )
        try:
            answer: Any = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            answer = None
        message_id = self._wire.message_id(answer) if answer is not None else None
        if (
            not message_id
            or len(message_id) > MAX_MESSAGE_ID_LENGTH
            or not message_id.isprintable()
        ):
            raise self._fail(
                SmsErrorCode.MALFORMED_RESPONSE, segments, reference, status=SmsStatus.UNKNOWN
            )
        return SmsResult(
            provider_message_id=message_id, segments=segments, status=SmsStatus.ACCEPTED
        )

    def _fail(
        self,
        code: SmsErrorCode,
        segments: int,
        reference: str,
        *,
        status: SmsStatus = SmsStatus.FAILED,
        http_status: int | None = None,
    ) -> SmsSendError:
        # The code, the status and our own reference only: never the text,
        # the key, the number or the provider's body (it may echo the text).
        logger.warning(
            "SMS not sent",
            extra={
                "sms_provider": self.provider,
                "sms_error": code.value,
                "sms_status": status.value,
                "sms_http_status": http_status,
                "sms_reference": reference,
            },
        )
        return SmsSendError(code, status=status, http_status=http_status, segments=segments)


def get_sms_sender() -> SmsSender:
    config = get_config()
    if config.sms_provider == "http":
        # The configuration has already refused to load without these.
        assert config.sms_api_url is not None
        assert config.sms_api_key is not None
        assert config.sms_sender_id is not None
        return HttpSmsSender(
            endpoint=config.sms_api_url,
            api_key=config.sms_api_key.get_secret_value(),
            sender_id=config.sms_sender_id,
            timeout_seconds=config.sms_timeout_seconds,
        )
    if config.is_real_environment:
        # A second barrier: the configuration already refuses the fake there.
        raise RuntimeError("the fake SMS sender is refused on staging and production")
    return FakeSmsSender(dev_sms_inbox_path())


# ------------------------------------------------------------ delivery records


def record_message(
    db: DbSession,
    *,
    purpose: SmsPurpose,
    phone: str,
    text: str,
    provider: str,
    now: datetime,
    otp_challenge_id: uuid.UUID | None = None,
    notification_id: uuid.UUID | None = None,
) -> SmsMessage:
    """Add a `pending` delivery record to the session (the caller commits).
    The text is only measured, never stored."""
    row = SmsMessage(
        id=uuid7(),
        purpose=purpose.value,
        phone_ref=phone_reference(phone),
        otp_challenge_id=otp_challenge_id,
        notification_id=notification_id,
        provider=provider,
        status=SmsStatus.PENDING.value,
        segments=count_segments(text).segments,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


def send_recorded(
    db: DbSession, record: SmsMessage, sender: SmsSender, *, phone: str, text: str
) -> SmsResult:
    """Send one message whose `pending` record is already committed, then
    store the outcome and commit it. Raises SmsSendError when it did not go
    out (the record then says `failed` or `unknown` and why)."""
    reference = str(record.id)
    try:
        result = sender.send(phone, text, reference=reference)
    except SmsSendError as exc:
        _finish(db, record, status=exc.status, error_code=exc.code.value, segments=exc.segments)
        raise
    except Exception as exc:
        # An adapter bug must not leave the record pending or leak the text.
        logger.exception(
            "the SMS adapter raised", extra={"sms_reference": reference, "phone": mask_phone(phone)}
        )
        _finish(db, record, status=SmsStatus.UNKNOWN, error_code=SmsErrorCode.SEND_ERROR.value)
        raise SmsSendError(SmsErrorCode.SEND_ERROR, status=SmsStatus.UNKNOWN) from exc
    _finish(
        db,
        record,
        status=result.status,
        provider_message_id=result.provider_message_id,
        segments=result.segments,
    )
    return result


def _finish(
    db: DbSession,
    record: SmsMessage,
    *,
    status: SmsStatus,
    error_code: str | None = None,
    provider_message_id: str | None = None,
    segments: int | None = None,
) -> None:
    now = datetime.now(UTC)
    record.status = status.value
    record.error_code = error_code
    record.provider_message_id = provider_message_id
    if segments is not None:
        record.segments = max(1, segments)
    record.completed_at = now
    record.updated_at = now
    db.commit()
