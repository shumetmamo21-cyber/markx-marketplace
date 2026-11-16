"""SMS behind an adapter (blueprint F.0, F.9).

Release 1 needs a local Ethiopian SMS provider, which is still unresolved
(section O, question 23). Until one is chosen, the only adapter is the fake.
The fake never sends anything: it appends to a file that the dev-only inbox
endpoint reads, so sign-in can be exercised on a laptop and in tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from markx.core.config import get_config


class SmsSender(Protocol):
    def send(self, phone: str, text: str) -> None: ...


class FakeSmsSender:
    def __init__(self, inbox: Path) -> None:
        self._inbox = inbox

    def send(self, phone: str, text: str) -> None:
        self._inbox.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"phone": phone, "text": text, "sent_at": datetime.now(UTC).isoformat()},
            ensure_ascii=False,
        )
        with self._inbox.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def dev_sms_inbox_path() -> Path:
    return get_config().storage_dir / "dev" / "sms-inbox.jsonl"


def read_dev_sms_inbox(phone: str) -> list[dict[str, str]]:
    path = dev_sms_inbox_path()
    if not path.exists():
        return []
    messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [m for m in messages if m["phone"] == phone]


def get_sms_sender() -> SmsSender:
    config = get_config()
    if config.is_real_environment:
        # Refuse to pretend. A real server must have a real provider adapter.
        raise RuntimeError("no real SMS provider adapter exists yet; see section O, question 23")
    return FakeSmsSender(dev_sms_inbox_path())
