"""What was ordered, as the seller bot shows it (F-26, decided by the founder; D-104).

The seller's own Telegram messages about an order (the new-order alert, the
reminder before it expires, every other seller order message, and the
`/orders` inbox) name the products: the store's own public listings, as the
order line copied them when the buyer ordered (`order_items.title_en` and
`title_am`). Product names only: never the buyer's name, phone number,
address or handover code, never a price, a quantity or a variant.

One rule for every message, here:

* the name in the reader's language (the other language when that one is
  empty);
* control characters and line breaks become spaces, runs of spaces one
  space: a name is always one line of plain text (Telegram is sent no
  formatting mode, so nothing in a name is read as markup);
* each name at most `NAME_LIMIT` characters, cut at a word where one is near
  the end, with "…";
* the same product twice (two variants) named once;
* at most `NAMES_SHOWN` names, then "and N more".
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.orders.models import OrderItem, SellerOrder
from markx.telegram_bot.texts import lang_of, say

# PROVISIONAL (P-104-1, D-104): the longest product name a message shows. A
# phone screen shows about 35 to 40 characters a line.
#   The engineer's guess; THE FOUNDER MUST CONFIRM OR CHANGE IT BEFORE MARKX
#   GOES LIVE.
NAME_LIMIT = 40
# PROVISIONAL (P-104-2): names shown for one order; the rest are counted.
NAMES_SHOWN = 3
# The longest text this module can make: the names, their separators and
# "and N more". `notifications.texts` refuses anything longer.
MAX_TEXT = NAMES_SHOWN * (NAME_LIMIT + 2) + 40

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_SPACES = re.compile(r"\s+")


def clean(name: str) -> str:
    """One line of plain text."""
    return _SPACES.sub(" ", _CONTROL.sub(" ", name)).strip()


def shorten(name: str, limit: int = NAME_LIMIT) -> str:
    if len(name) <= limit:
        return name
    cut = name[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit * 2 // 3:  # a word ends near the limit: cut there
        cut = cut[:space]
    return cut.rstrip(" ,;:-–—(") + "…"


def describe(names: Iterable[str], language: str | None) -> str:
    """The product names of one order, ready for a message ("" for none)."""
    shown: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = clean(raw)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        shown.append(shorten(name))
    if not shown:
        return ""
    separator = ", " if lang_of(language) == "en" else "፣ "
    text = separator.join(shown[:NAMES_SHOWN])
    if len(shown) > NAMES_SHOWN:
        text = say("products_more", language, names=text, more=len(shown) - NAMES_SHOWN)
    return text


def for_seller_orders(
    db: Session, seller_order_ids: Iterable[uuid.UUID], language: str | None
) -> dict[uuid.UUID, str]:
    """`describe` for each seller order, from its own order lines."""
    ids = list(seller_order_ids)
    if not ids:
        return {}
    english = lang_of(language) == "en"
    names: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    for seller_order_id, title_en, title_am in db.execute(
        select(OrderItem.seller_order_id, OrderItem.title_en, OrderItem.title_am)
        .where(OrderItem.seller_order_id.in_(ids))
        .order_by(OrderItem.seller_order_id, OrderItem.id)
    ):
        first, other = (title_en, title_am) if english else (title_am, title_en)
        names[seller_order_id].append(first if clean(first) else other)
    return {i: describe(found, language) for i, found in names.items()}


def for_notification(
    db: Session, seller_id: uuid.UUID, seller_order_id: uuid.UUID, language: str | None
) -> str:
    """The names for a seller order message, only if that order is that store's."""
    owner = db.scalar(select(SellerOrder.seller_id).where(SellerOrder.id == seller_order_id))
    if owner != seller_id:
        return ""
    return for_seller_orders(db, [seller_order_id], language)[seller_order_id]
