"""Playing Telegram in the tests (D-101), as `test_telegram_linking.py` does
for connecting Telegram: the webhook is called the way Telegram would call
it, with the test-only secret, and the bot's answers are read from the
webhook's reply. Nothing is sent to or received from Telegram, and nothing
here proves that a real bot works.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

from tests.conftest import TEST_BOT_USERNAME, TEST_WEBHOOK_SECRET, ApiClient

SIGN_IN_LINK = re.compile(rf"^https://t\.me/{TEST_BOT_USERNAME}\?start=(si-[A-Za-z0-9_-]{{43}})$")
_update_ids = itertools.count(500_000)


def webhook(update: dict[str, Any]) -> dict[str, Any]:
    caller = ApiClient(send_client_header=False, ip="198.51.100.7")
    response = caller.post(
        "/telegram/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _envelope(telegram_id: int, **message: Any) -> dict[str, Any]:
    return {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 9,
            "date": 1_790_000_000,
            "from": {"id": telegram_id, "is_bot": False, "first_name": "Abebe"},
            "chat": {"id": telegram_id, "type": "private"},
            **message,
        },
    }


def start(browser: ApiClient, language: str = "en") -> str:
    """The browser presses "Sign in with Telegram". Returns the start payload."""
    response = browser.post("/auth/telegram/sign-in", json={"language": language})
    assert response.status_code == 201, response.text
    match = SIGN_IN_LINK.fullmatch(response.json()["link"])
    assert match, response.json()["link"]
    return match.group(1)


def open_link(payload: str, telegram_id: int) -> dict[str, Any]:
    """The person opens the link in Telegram: the bot receives /start."""
    return webhook(_envelope(telegram_id, text=f"/start {payload}"))


def share_phone(
    telegram_id: int,
    phone_number: str,
    *,
    owner: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The person presses "Share my phone number": Telegram sends the contact
    with the sender's own user id (unless `owner` says otherwise)."""
    contact = {
        "phone_number": phone_number,
        "first_name": "Abebe",
        "user_id": telegram_id if owner is None else owner,
    }
    return webhook(_envelope(telegram_id, contact=contact, **extra))


def check(browser: ApiClient) -> Any:
    return browser.post("/auth/telegram/sign-in/check")


def sign_in(browser: ApiClient, telegram_id: int, phone_number: str) -> dict[str, Any]:
    """The whole sign-in, start to session. Returns the check's answer."""
    payload = start(browser)
    open_link(payload, telegram_id)
    share_phone(telegram_id, phone_number)
    response = check(browser)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "signed_in", response.json()
    return dict(response.json())
