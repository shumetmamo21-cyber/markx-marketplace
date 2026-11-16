"""Pushing a notification to a person's Telegram (blueprint D.16, F.9).

The Telegram bot is the first channel. It is not built yet, so the only
adapter is the fake, which appends to a file on a laptop and in tests. On a
real server the factory refuses to hand out the fake, as the SMS factory does:
the worker then retries the message and finally marks it failed, instead of
pretending it was sent.

Messages carry a template name and parameters, never free text, and an
idempotency key. Telegram's own API has no such key, so the real adapter must
remember the keys it has sent (D-034).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from markx.core.config import get_config


class PushSender(Protocol):
    def send(
        self,
        *,
        telegram_id: int,
        template: str,
        params: dict[str, Any],
        language: str,
        idempotency_key: str,
    ) -> None: ...


class FakePushSender:
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
    ) -> None:
        self._outbox.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "telegram_id": telegram_id,
                "template": template,
                "params": params,
                "language": language,
                "idempotency_key": idempotency_key,
                "sent_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        with self._outbox.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def dev_push_outbox_path() -> Path:
    return get_config().storage_dir / "dev" / "push-outbox.jsonl"


def read_dev_push_outbox() -> list[dict[str, Any]]:
    path = dev_push_outbox_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def get_push_sender() -> PushSender:
    config = get_config()
    if config.is_real_environment:
        raise RuntimeError("no Telegram bot adapter exists yet; push messages cannot be sent")
    return FakePushSender(dev_push_outbox_path())
