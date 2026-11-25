"""The bot check that runs before any SMS is sent (blueprint D.2, H.3).

Outside services sit behind adapters with a fake for tests (blueprint F.0).

* `TurnstileBotCheck` asks Cloudflare Turnstile's Siteverify API whether the
  token the sign-in page sent was really solved, on our site, for sign-in,
  and not used before (D-085). Anything short of a clear "yes" is a "no":
  a missing, malformed, invalid, expired or reused token, a wrong hostname
  or action, a timeout, an unreachable or confused Cloudflare. No code is
  sent then, rather than one sent to a robot.
* `FakeBotCheck` is for a laptop and the tests only. It accepts every token,
  so it must never answer on a real server (SEC-2, D-084): the configuration
  refuses to load on staging or production with it, and `get_bot_check`
  refuses to hand it out there.
* `RefusingBotCheck` refuses everyone; a real server without a configured
  real check gets it, as a second barrier.

The secret key is read from MARKX_TURNSTILE_SECRET_KEY, sent only to
Cloudflare, and never logged. Tokens are never logged either.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from markx.core.config import get_config

logger = logging.getLogger("markx.botcheck")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# The action the sign-in widget declares; a token solved for anything else
# is refused.
SIGN_IN_ACTION = "sign_in"
# The action the guest checkout's widget declares (C-07, D-108): a token solved
# for signing in is not one for placing a guest order, and the other way round.
GUEST_CHECKOUT_ACTION = "guest_checkout"
# Turnstile tokens are at most 2048 characters; anything longer is not one.
MAX_TOKEN_LENGTH = 2048
# Cloudflare's answer is a few hundred bytes; never read an unbounded body.
MAX_RESPONSE_BYTES = 64 * 1024

# (url, form fields, timeout in seconds) -> (HTTP status, body bytes)
Transport = Callable[[str, dict[str, str], float], tuple[int, bytes]]


class BotCheck(Protocol):
    def verify(self, token: str | None, ip: str | None) -> bool: ...


class FakeBotCheck:
    """For a laptop and the tests only. Accepts everything except the literal
    token "bot", so tests can exercise the refusal path."""

    def verify(self, token: str | None, ip: str | None) -> bool:
        return token != "bot"  # noqa: S105  (a test sentinel, not a credential)


class RefusingBotCheck:
    """Refuses every caller. Handed out when no real check is available on a
    real server: no SMS is sent rather than one sent to a robot."""

    def verify(self, token: str | None, ip: str | None) -> bool:
        return False


def urllib_transport(url: str, fields: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """POST the fields form-encoded; return the status and at most
    MAX_RESPONSE_BYTES of the body. Errors are raised to the caller."""
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(  # noqa: S310  (a fixed https:// URL)
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:  # a 4xx or 5xx answer
        return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)


class TurnstileBotCheck:
    """Server-side verification with Cloudflare Turnstile (D-085)."""

    def __init__(
        self,
        *,
        secret_key: str,
        allowed_hostnames: Sequence[str],
        timeout_seconds: float,
        action: str = SIGN_IN_ACTION,
        transport: Transport = urllib_transport,
        url: str = SITEVERIFY_URL,
    ) -> None:
        if not secret_key:
            raise ValueError("a Turnstile secret key is required")
        if not allowed_hostnames:
            raise ValueError("at least one allowed hostname is required")
        self._secret = secret_key
        self._hostnames = frozenset(h.lower() for h in allowed_hostnames)
        self._timeout = timeout_seconds
        self._action = action
        self._transport = transport
        self._url = url

    def __repr__(self) -> str:  # never show the secret
        return f"TurnstileBotCheck(hostnames={sorted(self._hostnames)}, action={self._action!r})"

    def verify(self, token: str | None, ip: str | None) -> bool:
        if not token or not token.strip():
            self._refuse("missing-token")
            return False
        if len(token) > MAX_TOKEN_LENGTH or not token.isascii() or not token.isprintable():
            self._refuse("malformed-token")
            return False
        fields = {"secret": self._secret, "response": token}
        if ip:
            fields["remoteip"] = ip
        try:
            status, raw = self._transport(self._url, fields, self._timeout)
        except Exception as exc:  # timeout, DNS, refused, TLS: fail closed
            self._refuse("unreachable", detail=type(exc).__name__)
            return False
        if status != 200:
            self._refuse("http-status", detail=str(status))
            return False
        if len(raw) > MAX_RESPONSE_BYTES:
            self._refuse("response-too-large")
            return False
        try:
            answer: Any = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            self._refuse("response-not-json")
            return False
        if not isinstance(answer, dict):
            self._refuse("response-not-an-object")
            return False
        if answer.get("success") is not True:
            codes = answer.get("error-codes")
            listed = codes if isinstance(codes, list) else []
            # "timeout-or-duplicate" is Cloudflare's answer for an expired or
            # already-used token; "invalid-input-response" for a forged one.
            self._refuse("not-successful", detail=",".join(str(c)[:40] for c in listed[:5]))
            return False
        hostname = answer.get("hostname")
        if not isinstance(hostname, str) or hostname.lower() not in self._hostnames:
            self._refuse("wrong-hostname", detail=str(hostname)[:80])
            return False
        if answer.get("action") != self._action:
            self._refuse("wrong-action", detail=str(answer.get("action"))[:40])
            return False
        return True

    @staticmethod
    def _refuse(reason: str, detail: str = "") -> None:
        # Reasons and Cloudflare's error codes only: never the token, the
        # secret or the caller's address.
        logger.warning(
            "bot check refused", extra={"botcheck_reason": reason, "botcheck_detail": detail}
        )


def get_bot_check(action: str = SIGN_IN_ACTION) -> BotCheck:
    """The bot check for one action: signing in (the default) or placing a
    guest order (`GUEST_CHECKOUT_ACTION`, D-108)."""
    config = get_config()
    if config.bot_check_provider == "turnstile":
        # The configuration has already refused to load without these.
        assert config.turnstile_secret_key is not None
        return TurnstileBotCheck(
            secret_key=config.turnstile_secret_key.get_secret_value(),
            allowed_hostnames=config.turnstile_hostnames,
            timeout_seconds=config.turnstile_timeout_seconds,
            action=action,
            transport=urllib_transport,  # looked up per call, so tests can stand in
        )
    if config.is_real_environment:
        logger.error("no real bot-check adapter is configured; sign-in codes are refused")
        return RefusingBotCheck()
    return FakeBotCheck()
