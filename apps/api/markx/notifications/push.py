"""Pushing a notification to a person's Telegram (blueprint D.16, F.9; D-034, D-092).

Provider-independent, like SMS (D-089):

* `PushSender` is the one interface: `send(*, telegram_id, template, params,
  language, idempotency_key, reply_markup=None) -> PushResult`, or `PushSendError` with a
  provider-independent code and a status (`failed`: certainly not sent;
  `unknown`: it may have been).
* `FakePushSender` never sends anything: it appends to a file on a laptop and
  in tests.
* `BotApiPushSender` is the adapter for Telegram's Bot API (`sendMessage`),
  on the standard library only: HTTPS to Telegram's fixed address, no
  redirects, a short timeout, a bounded answer, one attempt per call. **It
  has only ever been run against stand-ins: no bot exists and nothing has
  been sent to Telegram.** It renders the text from `texts.py`: the order
  code at most, never a name, phone number or address.
* `get_push_sender()` returns None when no provider is configured (always on a
  real server until the founder connects a bot). The worker then records the
  delivery as `unavailable` and goes on; it never raises (D-092). Before
  D-092 it raised, so every message for a person with a linked Telegram was
  retried eight times and then given up as a failed outbox row.

Telegram's API has no idempotency key. `idempotency_key` is the outbox row's
id: the fake records it, and the delivery record (`notification_deliveries`)
is what remembers whether an attempt began, so the worker can tell an
interrupted attempt from a fresh one (D-092).

The bot token is part of the Bot API's address, so the address is never
logged and never part of an error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from markx.core.config import get_config
from markx.notifications import texts
from markx.notifications.sms import (
    MAX_MESSAGE_ID_LENGTH,
    MAX_RESPONSE_BYTES,
    RedirectRefused,
    Transport,
    UrllibTransport,
)

logger = logging.getLogger("markx.push")

TELEGRAM_API = "https://api.telegram.org"


class PushStatus(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PushErrorCode(StrEnum):
    """Provider-independent reasons a push did not go out."""

    INVALID_REQUEST = "invalid_request"  # 400: chat not found, bad text
    RECIPIENT_BLOCKED = "recipient_blocked"  # 403: the person blocked the bot
    AUTH_FAILED = "auth_failed"  # 401, 404: the token is wrong
    RATE_LIMITED = "rate_limited"  # 429
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # 5xx
    UNEXPECTED_STATUS = "unexpected_status"
    TIMEOUT = "timeout"  # no answer in time: it may have been sent
    CONNECTION_FAILED = "connection_failed"  # refused, DNS, TLS: nothing was sent
    REDIRECT_REFUSED = "redirect_refused"
    MALFORMED_RESPONSE = "malformed_response"  # 2xx but unreadable: it may have been sent
    UNSAFE_TEXT = "unsafe_text"  # the text would carry more than the order code


# Worth another attempt: nothing went out and the cause may pass.
RETRYABLE_PUSH_ERRORS = frozenset(
    {
        PushErrorCode.RATE_LIMITED,
        PushErrorCode.PROVIDER_UNAVAILABLE,
        PushErrorCode.CONNECTION_FAILED,
        PushErrorCode.TIMEOUT,
        PushErrorCode.MALFORMED_RESPONSE,
    }
)


class PushSendError(Exception):
    """The push did not go out, or may not have. The string form is the code
    only: never the text, the token or the Telegram id."""

    def __init__(
        self,
        code: PushErrorCode,
        *,
        status: PushStatus = PushStatus.FAILED,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status = status
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class PushResult:
    provider_message_id: str | None
    status: PushStatus = PushStatus.ACCEPTED


class PushSender(Protocol):
    def send(
        self,
        *,
        telegram_id: int,
        template: str,
        params: dict[str, Any],
        language: str,
        idempotency_key: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> PushResult | None: ...


class FakePushSender:
    """For a laptop and the tests only: writes the message to a file."""

    provider = "fake"

    def __init__(self, outbox: Path) -> None:
        self._outbox = outbox

    def send(
        self,
        *,
        telegram_id: int,
        template: str,
        params: dict[str, Any],
        language: str,
        idempotency_key: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> PushResult:
        self._outbox.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "telegram_id": telegram_id,
            "template": template,
            "params": params,
            "language": language,
            "idempotency_key": idempotency_key,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        if reply_markup is not None:
            record["reply_markup"] = reply_markup
        # The words a real bot would send (D-102), so a test can read them;
        # None where the real adapter would refuse the text.
        try:
            record["text"] = texts.render_telegram(template, params, language)
        except texts.UnsafeText:
            record["text"] = None
        line = json.dumps(record, ensure_ascii=False)
        with self._outbox.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return PushResult(provider_message_id=f"fake-{idempotency_key}")


def dev_push_outbox_path() -> Path:
    return get_config().storage_dir / "dev" / "push-outbox.jsonl"


def read_dev_push_outbox() -> list[dict[str, Any]]:
    path = dev_push_outbox_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _status_error(status: int) -> PushErrorCode:
    if status == 400:
        return PushErrorCode.INVALID_REQUEST
    if status == 403:
        return PushErrorCode.RECIPIENT_BLOCKED
    if status in (401, 404):
        return PushErrorCode.AUTH_FAILED
    if status == 429:
        return PushErrorCode.RATE_LIMITED
    if 500 <= status < 600:
        return PushErrorCode.PROVIDER_UNAVAILABLE
    return PushErrorCode.UNEXPECTED_STATUS


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError)


class BotApiPushSender:
    """Telegram's Bot API `sendMessage` (D-092). Never run against Telegram:
    the founder has not created a bot. `transport` is for the tests."""

    provider = "telegram_bot_api"

    def __init__(
        self,
        *,
        bot_token: str,
        timeout_seconds: float,
        transport: Transport | None = None,
        api_base: str = TELEGRAM_API,
    ) -> None:
        if not bot_token.strip():
            raise ValueError("a Telegram bot token is required")
        if not api_base.startswith("https://"):
            raise ValueError("the Telegram API is reached over HTTPS only")
        self._url = f"{api_base}/bot{bot_token}/sendMessage"
        self._timeout = timeout_seconds
        self._transport: Transport = transport or UrllibTransport()

    def __repr__(self) -> str:  # never show the token
        return "BotApiPushSender()"

    def send(
        self,
        *,
        telegram_id: int,
        template: str,
        params: dict[str, Any],
        language: str,
        idempotency_key: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> PushResult:
        try:
            text = texts.render_telegram(template, params, language)
        except texts.UnsafeText as exc:
            raise self._fail(PushErrorCode.UNSAFE_TEXT, idempotency_key) from exc
        message: dict[str, Any] = {
            "chat_id": telegram_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            # Buttons (D-102): Accept and Decline on a new order, a link to
            # the order page. Their data names an order id, never more.
            message["reply_markup"] = reply_markup
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MarkX-Push/1",
        }
        try:
            status, raw = self._transport(self._url, headers, body, self._timeout)
        except RedirectRefused as exc:
            raise self._fail(PushErrorCode.REDIRECT_REFUSED, idempotency_key) from exc
        except Exception as exc:  # timeout, refused, DNS, TLS
            if _is_timeout(exc):
                raise self._fail(
                    PushErrorCode.TIMEOUT, idempotency_key, status=PushStatus.UNKNOWN
                ) from exc
            raise self._fail(PushErrorCode.CONNECTION_FAILED, idempotency_key) from exc
        if not 200 <= status < 300:
            raise self._fail(_status_error(status), idempotency_key, http_status=status)
        message_id: str | None = None
        if len(raw) <= MAX_RESPONSE_BYTES:
            try:
                answer: Any = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                answer = None
            if isinstance(answer, dict) and answer.get("ok") is True:
                result = answer.get("result")
                if isinstance(result, dict) and isinstance(result.get("message_id"), int):
                    message_id = str(result["message_id"])
        if message_id is None or len(message_id) > MAX_MESSAGE_ID_LENGTH:
            # Telegram said yes in some form but the answer cannot be read:
            # the message may have gone out.
            raise self._fail(
                PushErrorCode.MALFORMED_RESPONSE, idempotency_key, status=PushStatus.UNKNOWN
            )
        return PushResult(provider_message_id=message_id)

    def _fail(
        self,
        code: PushErrorCode,
        reference: str,
        *,
        status: PushStatus = PushStatus.FAILED,
        http_status: int | None = None,
    ) -> PushSendError:
        # The code, the status and our own reference only: never the address
        # (it holds the token), the text or the Telegram id.
        logger.warning(
            "push not sent",
            extra={
                "push_provider": self.provider,
                "push_error": code.value,
                "push_status": status.value,
                "push_http_status": http_status,
                "push_reference": reference,
            },
        )
        return PushSendError(code, status=status, http_status=http_status)


def get_push_sender() -> PushSender | None:
    """The configured push sender, or None when there is none (D-092). Never
    raises for a missing provider: the caller records the delivery as
    `unavailable` instead."""
    config = get_config()
    provider = config.push_provider
    if provider == "bot_api":
        # The configuration has already refused to load without the token.
        assert config.telegram_bot_token is not None
        return BotApiPushSender(
            bot_token=config.telegram_bot_token,
            timeout_seconds=config.telegram_push_timeout_seconds,
        )
    if provider == "fake":
        if config.is_real_environment:
            # A second barrier: the configuration already refuses the fake there.
            return None
        return FakePushSender(dev_push_outbox_path())
    return None
