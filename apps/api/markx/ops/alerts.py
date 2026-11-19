"""Where alerts go (blueprint F.12: "alerts go to a private Telegram group the
founder watches"; D-064).

* `TelegramAlertSender` posts the alert's one-line summary to the group, with
  the bot's token, when both `MARKX_TELEGRAM_BOT_TOKEN` and
  `MARKX_ALERT_TELEGRAM_CHAT_ID` are set. Nothing else leaves the server: no
  name, phone number or address is ever in a summary.
* `LogAlertSender` writes the alert to the log at CRITICAL (or INFO when it
  resolves). It is the fallback on a server without Telegram configured, so
  an alert is never silently dropped.
* On a laptop and in tests the alert is also appended to a file, so a
  person or a test can read what would have been sent.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from markx.core.config import get_config

logger = logging.getLogger("markx.ops.alerts")
TELEGRAM_TIMEOUT_SECONDS = 10


class AlertSender(Protocol):
    def send(self, *, text: str, severity: str, state: str, key: str) -> None: ...


class LogAlertSender:
    def send(self, *, text: str, severity: str, state: str, key: str) -> None:
        level = logging.CRITICAL if state == "opened" else logging.INFO
        logger.log(level, "ops alert %s", state, extra={"alert_key": key, "severity": severity,
                                                         "summary": text})  # fmt: skip


class FileAlertSender(LogAlertSender):
    """The laptop and test channel: the log, plus a file to read back."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def send(self, *, text: str, severity: str, state: str, key: str) -> None:
        super().send(text=text, severity=severity, state=state, key=key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"key": key, "severity": severity, "state": state, "text": text,
             "sent_at": datetime.now(UTC).isoformat()},
            ensure_ascii=False,
        )  # fmt: skip
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class TelegramAlertSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, *, text: str, severity: str, state: str, key: str) -> None:
        mark = {"opened": "ALERT", "resolved": "RESOLVED"}.get(state, state.upper())
        body = urllib.parse.urlencode(
            {"chat_id": self._chat_id, "text": f"[MarkX {mark} · {severity}] {text}",
             "disable_web_page_preview": "true"}
        ).encode()  # fmt: skip
        request = urllib.request.Request(self._url, data=body, method="POST")  # noqa: S310
        # An error raises, so the outbox retries the message (F.8).
        with urllib.request.urlopen(request, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"Telegram answered {response.status}")


def dev_alerts_path() -> Path:
    return get_config().storage_dir / "dev" / "alerts.jsonl"


def read_dev_alerts() -> list[dict[str, Any]]:
    path = dev_alerts_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def get_alert_sender() -> AlertSender:
    config = get_config()
    if config.telegram_bot_token and config.alert_telegram_chat_id:
        return TelegramAlertSender(config.telegram_bot_token, config.alert_telegram_chat_id)
    if config.dev_tools_enabled:
        return FileAlertSender(dev_alerts_path())
    return LogAlertSender()
