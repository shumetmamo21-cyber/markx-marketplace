"""The bot's buttons (D-102).

A button's data names one action and one seller order id, at most 37 bytes
(Telegram allows 64). It is never trusted: the server checks the person, the
store, the role and the order again when the button is pressed, exactly as the
website does (`markx.telegram_bot.service`).

Links open MarkX itself. The buyer's "order placed" message opens the secure
tracking link made for it (D.14, C-10: no sign-in, never the handover code);
later updates, and every seller message, open the order page, which needs the
person to be signed in, so the link alone shows nothing.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from markx.core.config import get_config
from markx.telegram_bot.texts import DECLINE_REASONS, lang_of, say

# o: open one order, a: accept, d: decline (choose a reason), dr: decline with
# reason n, r: packed and ready, x: on its way; inbox and checkin take no id.
CALLBACK = re.compile(
    r"(?P<verb>o|a|d|r|x):(?P<id>[0-9a-f]{32})"
    r"|dr:(?P<reason>[0-9]):(?P<rid>[0-9a-f]{32})"
    r"|(?P<word>inbox|checkin)"
)
MAX_CALLBACK_BYTES = 64

# The tracking link as the API issues it (`orders.issue_tracking_link`).
_TRACKING_PATH = re.compile(
    r"/api/v1/track/([0-9a-f-]{36})(\?expires=[0-9]{1,12}&signature=[A-Za-z0-9_-]{43})"
)

# Seller templates whose message carries Accept and Decline (S-07).
ANSWER_TEMPLATES = frozenset({"order.placed_for_seller", "order.approaching_response_deadline"})


def _button(key: str, language: str, data: str) -> dict[str, str]:
    assert len(data.encode()) <= MAX_CALLBACK_BYTES
    return {"text": say(key, language), "callback_data": data}


def _link(key: str, language: str, path: str) -> dict[str, str]:
    origin = get_config().public_origin.rstrip("/")
    return {"text": say(key, language), "url": f"{origin}/{lang_of(language)}/{path}"}


def markup(rows: list[list[dict[str, str]]]) -> dict[str, Any] | None:
    rows = [row for row in rows if row]
    return {"inline_keyboard": rows} if rows else None


def inbox_button(language: str) -> dict[str, str]:
    return _button("btn_inbox", language, "inbox")


def checkin_button(language: str) -> dict[str, str]:
    return _button("btn_checkin", language, "checkin")


def seller_order_link(
    language: str, seller_id: uuid.UUID, seller_order_id: uuid.UUID
) -> dict[str, str]:
    return _link("btn_open", language, f"seller/{seller_id}/orders/{seller_order_id}")


def open_order(language: str, seller_order_id: uuid.UUID, label: str) -> dict[str, str]:
    return {"text": label, "callback_data": f"o:{seller_order_id.hex}"}


def answer_row(language: str, seller_order_id: uuid.UUID) -> list[dict[str, str]]:
    return [
        _button("btn_accept", language, f"a:{seller_order_id.hex}"),
        _button("btn_decline", language, f"d:{seller_order_id.hex}"),
    ]


def ready_row(language: str, seller_order_id: uuid.UUID) -> list[dict[str, str]]:
    return [_button("btn_ready", language, f"r:{seller_order_id.hex}")]


def sent_row(language: str, seller_order_id: uuid.UUID) -> list[dict[str, str]]:
    return [_button("btn_sent", language, f"x:{seller_order_id.hex}")]


def reason_rows(language: str, seller_order_id: uuid.UUID) -> list[list[dict[str, str]]]:
    return [
        [_button(key, language, f"dr:{n}:{seller_order_id.hex}")]
        for n, key in enumerate(DECLINE_REASONS)
    ] + [[_button("btn_back", language, f"o:{seller_order_id.hex}")]]


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def for_notification(template: str, params: dict[str, Any], language: str) -> dict[str, Any] | None:
    """The buttons under a pushed notification, or None."""
    seller_id, seller_order_id = (
        _uuid(params.get("seller_id")),
        _uuid(params.get("seller_order_id")),
    )
    if seller_id is not None and seller_order_id is not None:
        rows = []
        if template in ANSWER_TEMPLATES:
            rows.append(answer_row(language, seller_order_id))
        rows.append(
            [inbox_button(language), seller_order_link(language, seller_id, seller_order_id)]
        )
        return markup(rows)
    if template == "seller.weekly_report":
        return markup([[checkin_button(language)]])
    order_id = _uuid(params.get("order_id"))
    tracking = _TRACKING_PATH.fullmatch(str(params.get("tracking_path") or ""))
    if order_id is not None and tracking is not None and tracking.group(1) == str(order_id):
        # The order placed (C-10): the buyer's secure tracking link, which opens
        # without signing in and never shows the handover code (D.14). It was
        # made for this message; it expires on its own (`TRACKING_LINK_SECONDS`).
        return markup(
            [[_link("btn_open", language, f"track/{tracking.group(1)}{tracking.group(2)}")]]
        )
    if order_id is not None and template.startswith(("order.", "dispute.")):
        # The buyer's order page (C-10); it asks them to sign in.
        return markup([[_link("btn_open", language, f"orders/{order_id}")]])
    return None
