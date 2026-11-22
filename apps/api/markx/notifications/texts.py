"""The short texts that leave the server by SMS or Telegram (D-092).

A notification is stored as a template name and parameters. The web app has
its own words for every template (`apps/web/messages/*.json`); a message that
leaves the server needs words here, in both languages.

The rule that matters: **the only parameter an SMS may carry is the order
code.** (Telegram: also the weekly message's figures, and on a store's own
order messages the product names, F-26; see `render_telegram`.) Never a buyer's or seller's name, phone number, address,
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
from datetime import date
from typing import Any

from markx.core.codes import is_order_code
from markx.core.ethiopian import amharic_date

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

# Telegram only (D-102). Telegram costs nothing per message, so these never
# make a template SMS-worthy: SMS still uses ORDER_TEXTS alone. Where both
# exist, Telegram uses its own: a seller's new order and its reminder carry
# Accept and Decline buttons, which an SMS cannot.
TELEGRAM_TEXTS: dict[str, dict[str, str]] = {
    # -- to the shop's order handlers ------------------------------------------------
    "order.placed_for_seller": {
        "en": "MarkX: new order {code}. Tap Accept or Decline below before the deadline. "
        "/orders shows every order waiting for you.",
        "am": "MarkX፦ አዲስ ትዕዛዝ {code}። ጊዜው ሳያልፍ ከታች «ተቀበል» ወይም «አትቀበል»ን ይጫኑ። "
        "እርስዎን የሚጠብቁ ትዕዛዞችን ሁሉ /orders ያሳያል።",
    },
    "order.approaching_response_deadline": {
        "en": "MarkX: order {code} is still waiting for your answer and expires in a few "
        "minutes. Tap Accept or Decline below.",
        "am": "MarkX፦ ትዕዛዝ {code} መልስዎን እየጠበቀ ነው፤ በጥቂት ደቂቃዎች ውስጥ ጊዜው ያልፋል። "
        "ከታች «ተቀበል» ወይም «አትቀበል»ን ይጫኑ።",
    },
    "order.completed_for_seller": {
        "en": "MarkX: order {code} is completed.",
        "am": "MarkX፦ ትዕዛዝ {code} ተጠናቋል።",
    },
    "order.cancelled_not_fulfilled_for_seller": {
        "en": "MarkX: order {code} was cancelled because it was not sent in time.",
        "am": "MarkX፦ ትዕዛዝ {code} በጊዜው ስላልተላከ ተሰርዟል።",
    },
    "order.problem_buyer_added": {
        "en": "MarkX: the buyer added to the problem report on order {code}.",
        "am": "MarkX፦ ገዢው በትዕዛዝ {code} የችግር ሪፖርት ላይ ተጨማሪ ጽፈዋል።",
    },
    # The weekly message (S-26): counts only, never money, names or products.
    "seller.weekly_report": {
        "en": "MarkX weekly report, week from {week}: {received} orders received, "
        "{confirmed} accepted, {completed} completed. {to_confirm} of your prices need "
        "checking: send /checkin if they are all still right.",
        "am": "የMarkX ሳምንታዊ ሪፖርት፣ ከ{week} ጀምሮ ያለው ሳምንት፦ {received} ትዕዛዞች ደርሰዋል፣ "
        "{confirmed} ተቀብለዋል፣ {completed} ተጠናቀዋል። {to_confirm} ዋጋዎችዎ መረጋገጥ አለባቸው፤ "
        "ሁሉም አሁንም ትክክል ከሆኑ /checkin ይላኩ።",
    },
    # -- to the buyer (C-10) -------------------------------------------------------------
    "order.placed": {
        "en": "MarkX: your order {code} was sent to the shop. You will hear here as soon as "
        "it answers.",
        "am": "MarkX፦ ትዕዛዝዎ {code} ወደ ሱቁ ተልኳል። ሱቁ እንደመለሰ እዚህ ይነገርዎታል።",
    },
    "order.next_best_offer": {
        "en": "MarkX: another shop has what you ordered in {code}. Open MarkX to see the offer.",
        "am": "MarkX፦ በ{code} ያዘዙትን ሌላ ሱቅ አለው። ቅናሹን በMarkX ይመልከቱ።",
    },
    "order.ready": {
        "en": "MarkX: order {code} is packed and ready. It will be on its way soon.",
        "am": "MarkX፦ ትዕዛዝ {code} ታሽጎ ዝግጁ ነው። በቅርቡ ይላካል።",
    },
    "order.delivery_failed": {
        "en": "MarkX: the delivery of order {code} did not succeed. Open MarkX to see what "
        "happens next.",
        "am": "MarkX፦ የትዕዛዝ {code} ማድረስ አልተሳካም። ቀጥሎ የሚሆነውን በMarkX ይመልከቱ።",
    },
    "order.returned": {
        "en": "MarkX: order {code} went back to the shop.",
        "am": "MarkX፦ ትዕዛዝ {code} ወደ ሱቁ ተመልሷል።",
    },
    "order.payment_recorded": {
        "en": "MarkX: the shop recorded your payment for order {code}.",
        "am": "MarkX፦ ሱቁ ለትዕዛዝ {code} ክፍያዎን መዝግቧል።",
    },
    "order.handover_code_reissued": {
        "en": "MarkX: you have a new handover code for order {code}. Open MarkX to see it.",
        "am": "MarkX፦ ለትዕዛዝ {code} አዲስ የማስረከቢያ ኮድ አለዎት። በMarkX ይመልከቱት።",
    },
    "order.problem_seller_replied": {
        "en": "MarkX: the shop answered your problem report on order {code}.",
        "am": "MarkX፦ ሱቁ በትዕዛዝ {code} ላይ ላቀረቡት የችግር ሪፖርት መልስ ሰጥቷል።",
    },
}

# The placeholders a Telegram text may use, each with the one parameter it
# is filled from (D-102). Besides the order code: the weekly message's week
# and counts, which must be plain whole numbers.
TELEGRAM_PLACEHOLDERS: dict[str, str] = {
    "code": "order_code",
    "week": "week_start",
    "received": "orders_received",
    "confirmed": "orders_confirmed",
    "completed": "completed",
    "to_confirm": "prices_to_confirm",
}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_COUNT = 1_000_000

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


# F-26 (decided by the founder; D-104): a seller order message in Telegram
# names the products ordered, on a line of its own under the words. Only for
# the store's own messages (`notifications.delivery` adds `product_names`
# only for a store's member allowed to handle that order), only the names
# `telegram_bot.products` makes (one short line of plain text), and never in
# an SMS: `render` above takes the order code alone.
PRODUCTS_PARAM = "product_names"
PRODUCTS_LINE: dict[str, str] = {
    "en": "Products: {products}",
    "am": "ምርቶች፦ {products}",
}
MAX_PRODUCTS_TEXT = 200
_NOT_ONE_PLAIN_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _week_text(day: str, lang: str) -> str:
    """The week's first day as words (C-05, D-106): in Amharic the Ethiopian
    date with the Gregorian one in brackets, "7 ኅዳር 2019 (2026-11-16)"; in
    English the date as it came. A date that does not exist is refused."""
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise UnsafeText("the week needs a real date") from None
    return f"{amharic_date(parsed)} ({day})" if lang == "am" else day


def render_telegram(template: str, params: Mapping[str, Any], language: str) -> str:
    """The Telegram text for one notification (D-102): Telegram's own words
    where they exist, else the SMS words, else the generic line. Only the
    order code, the week and whole-number counts are ever filled in; a store's
    order message also gets its product names on a line of their own (F-26)."""
    lang = "en" if language == "en" else "am"
    words = (TELEGRAM_TEXTS.get(template) or ORDER_TEXTS.get(template) or GENERIC_TEXT)[lang]
    used = placeholders(words)
    if not used <= set(TELEGRAM_PLACEHOLDERS):
        raise UnsafeText(f"text for {template!r} uses {sorted(used - set(TELEGRAM_PLACEHOLDERS))}")
    for name in sorted(used):
        value = params.get(TELEGRAM_PLACEHOLDERS[name])
        if name == "code":
            if not isinstance(value, str) or not is_order_code(value):
                raise UnsafeText(f"text for {template!r} needs a plain order code")
            filled = value
        elif name == "week":
            if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
                raise UnsafeText(f"text for {template!r} needs a plain date")
            filled = _week_text(value, lang)
        else:
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_COUNT:
                raise UnsafeText(f"text for {template!r} needs a whole number for {name!r}")
            filled = str(value)
        words = words.replace("{" + name + "}", filled)
    names = params.get(PRODUCTS_PARAM)
    if names is not None:
        if not template.startswith("order.") or not params.get("seller_order_id"):
            raise UnsafeText(
                f"product names are only for a store's order messages, not {template!r}"
            )
        if (
            not isinstance(names, str)
            or not names.strip()
            or len(names) > MAX_PRODUCTS_TEXT
            or _NOT_ONE_PLAIN_LINE.search(names)
        ):
            raise UnsafeText(f"text for {template!r} needs one short line of product names")
        # Filled last and alone, so nothing in a name is read as a placeholder.
        words += "\n" + PRODUCTS_LINE[lang].replace("{products}", names)
    return words
