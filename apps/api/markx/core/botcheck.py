"""The bot check that runs before any SMS is sent (blueprint D.2, H.3).

Outside services sit behind adapters with a fake for tests (blueprint F.0).
The production adapter (Cloudflare Turnstile is the blueprint's candidate) is
not built yet; see docs/DEVELOPMENT_STATUS.md.

The fake accepts every token, including none, so it must never answer on a
real server (SEC-2, D-084). Two barriers stop that: the configuration refuses
to load on staging or production with `bot_check_provider = "fake"`
(`markx/core/config.py`), and `get_bot_check` itself refuses to hand the fake
out there, so a sign-in on a misconfigured server is refused, never waved
through.
"""

from __future__ import annotations

import logging
from typing import Protocol

from markx.core.config import get_config

logger = logging.getLogger("markx.botcheck")


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


def get_bot_check() -> BotCheck:
    config = get_config()
    if config.is_real_environment:
        # Only the fake exists today, and it is never trusted on a real server.
        logger.error("no real bot-check adapter is configured; sign-in codes are refused")
        return RefusingBotCheck()
    return FakeBotCheck()
