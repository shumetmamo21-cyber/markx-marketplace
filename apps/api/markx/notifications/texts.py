"""The short texts that leave the server by SMS or Telegram (D-092).

A notification is stored as a template name and parameters. The web app has
its own words for every template (`apps/web/messages/*.json`); a message that
leaves the server needs words here, in both languages.

The rule that matters: **the only parameter an outside text may carry is the
order code.** Never a buyer's or seller's name, phone number, address,
handover code, price or product: an SMS sits unencrypted on a phone and at
the provider, and a Telegram message on Telegram's servers. The person opens
MarkX, signed in, to see the rest. `render` refuses any other placeholder,
and a test checks every text.

Each text fits in at most two SMS segments (Amharic is always UCS-2, 67
units a part), so one alert costs at most two messages. A unit test checks
that too.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from markx.core.codes import is_order_code

# The parameters a text may use. Nothing else is ever filled in.
ALLOWED_PLACEHOLDERS = frozenset({"code"})
MAX_SEGMENTS_PER_TEXT = 2

# template -> {language -> text}. Order alerts only: these are the messages
# worth a paid SMS (D-092). The seller's come first.
ORDER_TEXTS: dict[str, dict[str, str]] = {
    # -- to the shop's order handlers ------------------------------------------------
    "order.placed_for_seller": {
        "en": "MarkX: new order {code}. Accept or decline it in your shop dashboard before "
        "the deadline.",
        "am": "MarkX፦ አዲስ ትዕዛዝ {code}። ጊዜው ሳያልፍ በሱቅዎ ገጽ ይቀበሉ ወይም ይመልሱ።",
    },
    "order.approaching_response_deadline": {
        "en": "MarkX: order {code} is still waiting for your answer and expires soon.",
        "am": "MarkX፦ ትዕዛዝ {code} መልስዎን እየጠበቀ ነው፤ በቅርቡ ጊዜው ያልፋል።",
    },
    "order.expired_unanswered": {
        "en": "MarkX: order {code} expired because it was not answered in time.",
        "am": "MarkX፦ ትዕዛዝ {code} በጊዜው መልስ ስላላገኘ ጊዜው አልፏል።",
    },
    "order.cancelled_by_buyer": {
        "en": "MarkX: the buyer cancelled order {code}.",
        "am": "MarkX፦ ገዢው ትዕዛዝ {code}ን ሰርዘዋል።",
    },
    "order.problem_reported_for_seller": {
        "en": "MarkX: the buyer reported a problem with order {code}. Please answer in your "
        "shop dashboard.",
        "am": "MarkX፦ ገዢው በትዕዛዝ {code} ላይ ችግር አሳውቀዋል። በሱቅዎ ገጽ ይመልሱ።",
    },
    "order.refunded_for_seller": {
        "en": "MarkX decided the problem on order {code}: you refunded the buyer.",
        "am": "MarkX በትዕዛዝ {code} ችግር ላይ ወሰነ፦ ለገዢው ገንዘብ መልሰዋል።",
    },
    "dispute.decided_for_seller": {
        "en": "MarkX decided the problem on order {code}. See your shop dashboard.",
        "am": "MarkX በትዕዛዝ {code} ችግር ላይ ወሰነ። የሱቅዎን ገጽ ይመልከቱ።",
    },
    # -- to the buyer --------------------------------------------------------------------
    "order.seller_confirmed": {
        "en": "MarkX: the shop accepted order {code}.",
        "am": "MarkX፦ ሱቁ ትዕዛዝ {code}ን ተቀብሏል።",
    },
    "order.seller_declined": {
        "en": "MarkX: the shop could not fill order {code}. Open MarkX for other offers.",
        "am": "MarkX፦ ሱቁ ትዕዛዝ {code}ን ማሟላት አልቻለም። ሌሎች ቅናሾችን በMarkX ይመልከቱ።",
    },
    "order.seller_did_not_answer": {
        "en": "MarkX: the shop did not answer order {code} in time. Open MarkX for other offers.",
        "am": "MarkX፦ ሱቁ ለትዕዛዝ {code} በጊዜው አልመለሰም። ሌሎች ቅናሾችን በMarkX ይመልከቱ።",
    },
    "order.ready_for_collection": {
        "en": "MarkX: order {code} is ready to collect at the shop. Bring your handover code "
        "from MarkX.",
        "am": "MarkX፦ ትዕዛዝ {code} በሱቁ ለመውሰድ ዝግጁ ነው። የማስረከቢያ ኮድዎን ከMarkX ይዘው ይምጡ።",
    },
    "order.out_for_delivery": {
        "en": "MarkX: order {code} is on the way.",
        "am": "MarkX፦ ትዕዛዝ {code} በመንገድ ላይ ነው።",
    },
    "order.delivered": {
        "en": "MarkX: order {code} was delivered.",
        "am": "MarkX፦ ትዕዛዝ {code} ደርሷል።",
    },
    "order.completed": {
        "en": "MarkX: order {code} is completed. You can rate your purchase in MarkX.",
        "am": "MarkX፦ ትዕዛዝ {code} ተጠናቋል። ግዢዎን በMarkX መገምገም ይችላሉ።",
    },
    "order.cancelled_not_fulfilled": {
        "en": "MarkX: order {code} was cancelled because the shop did not send it.",
        "am": "MarkX፦ ሱቁ ስላልላከው ትዕዛዝ {code} ተሰርዟል።",
    },
    "order.problem_reported": {
        "en": "MarkX: your problem report on order {code} was received.",
        "am": "MarkX፦ በትዕዛዝ {code} ላይ ያቀረቡት የችግር ሪፖርት ደርሶናል።",
    },
    "order.refunded": {
        "en": "MarkX decided the problem on order {code}: the shop refunded you.",
        "am": "MarkX በትዕዛዝ {code} ችግር ላይ ወሰነ፦ ሱቁ ገንዘብዎን መልሷል።",
    },
    "dispute.decided": {
        "en": "MarkX decided the problem on order {code}. Open MarkX to see the decision.",
        "am": "MarkX በትዕዛዝ {code} ችግር ላይ ወሰነ። ውሳኔውን በMarkX ይመልከቱ።",
    },
}

# What a Telegram message says for a template with no text of its own: the
# person opens MarkX to read it. Telegram costs nothing per message, so every
# notification is pushed; SMS goes only for ORDER_TEXTS.
GENERIC_TEXT: dict[str, str] = {
    "en": "You have a new message from MarkX.",
    "am": "ከMarkX አዲስ መልዕክት አለዎት።",
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class UnsafeText(Exception):
    """A text asked for a parameter that may not leave the server."""


def has_text(template: str) -> bool:
    return template in ORDER_TEXTS


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def render(template: str, params: Mapping[str, Any], language: str) -> str:
    """The outside text for one notification, in the person's language
    (Amharic unless they chose English). Only the order code is filled in."""
    lang = "en" if language == "en" else "am"
    words = ORDER_TEXTS.get(template, GENERIC_TEXT)[lang]
    used = placeholders(words)
    if not used <= ALLOWED_PLACEHOLDERS:
        raise UnsafeText(f"text for {template!r} uses {sorted(used - ALLOWED_PLACEHOLDERS)}")
    code = params.get("order_code")
    if "code" in used:
        if not isinstance(code, str) or not is_order_code(code):
            # Anything but a real order code is never filled into a message
            # that leaves the server.
            raise UnsafeText(f"text for {template!r} needs a plain order code")
        return words.replace("{code}", code)
    return words
