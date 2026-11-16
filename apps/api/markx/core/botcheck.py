"""The bot check that runs before any SMS is sent (blueprint D.2, H.3).

Outside services sit behind adapters with a fake for tests (blueprint F.0).
The production adapter (Cloudflare Turnstile is the blueprint's candidate) is
not built yet; see docs/DEVELOPMENT_STATUS.md.
"""

from __future__ import annotations

from typing import Protocol


class BotCheck(Protocol):
    def verify(self, token: str | None, ip: str | None) -> bool: ...


class FakeBotCheck:
    """Accepts everything except the literal token "bot", so tests can
    exercise the refusal path."""

    def verify(self, token: str | None, ip: str | None) -> bool:
        return token != "bot"


def get_bot_check() -> BotCheck:
    return FakeBotCheck()
