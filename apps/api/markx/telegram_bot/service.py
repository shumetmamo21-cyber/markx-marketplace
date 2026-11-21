"""The seller bot (blueprint S-07, S-24, D.16; D-102).

Telegram calls the webhook (`/telegram/webhook`, authenticated by its secret,
D-093) with a person's command or button press. This module answers it.

**The website's rules, checked again at every press.** Nothing in a button or
a command is trusted. Each time:

1. The sender must be the Telegram account *connected* to an active MarkX
   account now (`users.telegram_id`); a disconnected, remembered one is not
   enough (D-101). Telegram proves the sender; the webhook secret proves
   Telegram.
2. The store must pass `deps.seller_membership`, the same function every
   `/seller/{seller_id}/...` route of the website uses: an active member of a
   store that is not closed, whose role holds the capability
   (`handle_orders` for orders, `manage_offers` for price, stock and the
   check-in, any member to list offers).
3. The change goes through the same service function as the website's button
   (`orders.seller_respond`, `mark_ready`, `seller_dispatch`,
   `offers.update_offer`, `set_stock`, `confirm_offers`), which locks the row
   and checks the order's state, deadline and the store's status itself.

**Never twice, never lost.** The update id is stored in the same transaction
as the change (`telegram_updates`), so a press Telegram delivers again (after
a restart, a timeout or a lost answer) changes nothing a second time. The
repeated delivery is answered with the *current* state of what was pressed
(`replay=True`), so the person still sees the outcome even if the first
answer never reached Telegram. Messages MarkX starts itself (alerts) go
through the outbox and the delivery records (D-092).

Answers are a single Bot API method returned in the webhook's own response
(`sendMessage`, or `editMessageText` for a button under a message), so MarkX
makes no call to Telegram here. Handover codes are never typed into the bot:
the seller enters them on the website (D-044).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from markx.accounts.deps import seller_membership
from markx.accounts.models import User, UserStatus
from markx.accounts.permissions import SellerCapability, seller_can
from markx.audit.service import Actor
from markx.core import ratelimit
from markx.core.errors import AppError, RateLimited
from markx.core.security import keyed_hash
from markx.delivery.models import DeliveryMode, Shipment
from markx.offers import selectors as offer_selectors
from markx.offers import service as offers
from markx.offers.models import Offer
from markx.offers.service import MAX_PRICE_SANTIM, MAX_STOCK
from markx.orders import service as orders
from markx.orders.models import Order, OrderItem, SellerOrder, SellerOrderStatus
from markx.sellers.models import Seller, SellerMember, SellerStatus
from markx.telegram_bot import keyboards as kb
from markx.telegram_bot import products
from markx.telegram_bot.texts import DECLINE_REASONS, error_text, say

logger = logging.getLogger("markx.telegram_bot")

# PROVISIONAL (P-102-1, D-102): presses and commands one Telegram account may
# send in an hour. A busy shop answers a few dozen orders a day; past this the
# bot stays silent for the rest of the hour, as for link attempts (D-093).
#   The engineer's guess; THE FOUNDER MUST CONFIRM OR CHANGE IT BEFORE MARKX
#   GOES LIVE.
ACTIONS_PER_TELEGRAM_ACCOUNT_PER_HOUR = 120
# PROVISIONAL (P-102-3): orders shown in one inbox message; the rest are on
# the website.
INBOX_LIMIT = 10
# PROVISIONAL (P-102-4): listings shown by /offers.
OFFERS_LIMIT = 20

# The seller orders with a next step the bot can take or explain.
INBOX_STATUSES = (
    SellerOrderStatus.PLACED,
    SellerOrderStatus.CONFIRMED,
    SellerOrderStatus.PAID,
    SellerOrderStatus.READY,
    SellerOrderStatus.DELIVERY_FAILED,
)
_COMMAND = re.compile(r"/([a-z]{2,16})(?:@[A-Za-z0-9_]{5,32})?(?:[ \t]+(.{1,200}))?[ \t]*")
COMMANDS = frozenset({"help", "orders", "offers", "price", "stock", "checkin"})
_REF = r"([0-9A-Fa-f]{6})"
_PRICE_ARGS = re.compile(_REF + r"[ \t]+([0-9]{1,9})(?:\.([0-9]{1,2}))?")
_STOCK_ARGS = re.compile(_REF + r"[ \t]+([0-9]{1,9})")
_MAX_TELEGRAM_ID = 2**52


@dataclass(frozen=True, slots=True)
class Press:
    """Who is asking, where to answer, and (for a button) which message."""

    user: User | None
    sender_id: int
    chat_id: int
    message_id: int | None = None

    @property
    def language(self) -> str:
        return self.user.language if self.user is not None else "am"


def _now() -> datetime:
    return datetime.now(UTC)


def _int(value: Any, upper: int = _MAX_TELEGRAM_ID) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= upper:
        return value
    return None


def _reply(press: Press, text: str, markup: dict[str, Any] | None = None) -> dict[str, Any]:
    if press.message_id is not None:
        answer: dict[str, Any] = {
            "method": "editMessageText",
            "chat_id": press.chat_id,
            "message_id": press.message_id,
            "text": text,
        }
    else:
        answer = {"method": "sendMessage", "chat_id": press.chat_id, "text": text}
    if markup is not None:
        answer["reply_markup"] = markup
    return answer


def _person(db: Session, sender_id: int) -> User | None:
    """The active MarkX account this Telegram account is connected to now."""
    user = db.scalar(select(User).where(User.telegram_id == sender_id))
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    return user


def _throttled(sender_id: int) -> bool:
    ref = keyed_hash("telegram-ref", str(sender_id)).hex()[:32]
    try:
        ratelimit.hit(
            f"telegram:bot:tg:{ref}", ACTIONS_PER_TELEGRAM_ACCOUNT_PER_HOUR, timedelta(hours=1)
        )
    except RateLimited:
        return True
    return False


def _stores(db: Session, user: User, capability: SellerCapability | None) -> list[Seller]:
    """Stores where `seller_membership` would let this person use
    `capability`. Only to choose what to list: every change asks
    `seller_membership` itself again."""
    rows = db.execute(
        select(SellerMember.role, Seller)
        .join(Seller, Seller.id == SellerMember.seller_id)
        .where(
            SellerMember.user_id == user.id,
            SellerMember.is_active,
            Seller.status != SellerStatus.CLOSED,
        )
        .order_by(Seller.id)
    ).all()
    return [seller for role, seller in rows if capability is None or seller_can(role, capability)]


# -- one update ---------------------------------------------------------------------------


def handle(db: Session, update: dict[str, Any], *, replay: bool) -> dict[str, Any] | None:
    """The answer to a bot command or a button press, or None when the
    update is not one (the caller then answers nothing). `replay`: Telegram
    sent this update before and it was handled; answer, change nothing."""
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        return _callback(db, callback, replay=replay)
    message = update.get("message")
    if isinstance(message, dict):
        return _message(db, message, replay=replay)
    return None


def _sender_and_chat(message: Any, sender: Any) -> tuple[int, int] | None:
    if not isinstance(message, dict) or not isinstance(sender, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    if sender.get("is_bot") is not False:
        return None
    sender_id, chat_id = _int(sender.get("id")), _int(chat.get("id"))
    if sender_id is None or chat_id is None or sender_id != chat_id:
        return None
    return sender_id, chat_id


def _message(db: Session, message: dict[str, Any], *, replay: bool) -> dict[str, Any] | None:
    text = message.get("text")
    if not isinstance(text, str) or len(text) > 300:
        return None
    match = _COMMAND.fullmatch(text)
    if match is None:
        return None
    command, args = match.group(1), (match.group(2) or "").strip()
    who = _sender_and_chat(message, message.get("from"))
    if who is None:
        return None
    sender_id, chat_id = who
    if command == "start":
        # `/start` with no link (a link is the caller's): the commands, for a
        # connected person.
        if args:
            return None
        command = "help"
    user = _person(db, sender_id)
    if user is None:
        if command not in COMMANDS:
            return None  # an unknown command from a stranger: ignored (D-093)
        from markx.accounts.telegram_link import REPLIES

        # Not connected (or the account is blocked): how to connect, in both
        # languages, naming no account.
        return {"method": "sendMessage", "chat_id": chat_id, "text": REPLIES["help"]}
    if not replay and _throttled(sender_id):
        return None
    press = Press(user=user, sender_id=sender_id, chat_id=chat_id)
    if command == "orders":
        return _inbox(db, press)
    if command == "offers":
        return _offers(db, press)
    if command == "price":
        return _price(db, press, args, replay=replay)
    if command == "stock":
        return _stock(db, press, args, replay=replay)
    if command == "checkin":
        return _checkin(db, press, replay=replay)
    return _reply(press, say("help", press.language))


def _callback(db: Session, callback: dict[str, Any], *, replay: bool) -> dict[str, Any] | None:
    message = callback.get("message")
    who = _sender_and_chat(message, callback.get("from"))
    data = callback.get("data")
    if who is None or not isinstance(data, str) or len(data.encode()) > kb.MAX_CALLBACK_BYTES:
        return None
    assert isinstance(message, dict)
    message_id = _int(message.get("message_id"), 2**31 - 1)
    sender_id, chat_id = who
    match = kb.CALLBACK.fullmatch(data)
    if match is None:
        return None
    user = _person(db, sender_id)
    if user is None:
        from markx.accounts.telegram_link import REPLIES

        return {"method": "sendMessage", "chat_id": chat_id, "text": REPLIES["help"]}
    if not replay and _throttled(sender_id):
        return None
    press = Press(user=user, sender_id=sender_id, chat_id=chat_id, message_id=message_id)
    if match.group("word") == "inbox":
        return _inbox(db, press)
    if match.group("word") == "checkin":
        return _checkin(db, press, replay=replay)
    if match.group("rid") is not None:
        reason = int(match.group("reason"))
        if reason >= len(DECLINE_REASONS):
            return None
        return _order_action(
            db, press, "dr", uuid.UUID(match.group("rid")), reason=reason, replay=replay
        )
    return _order_action(
        db, press, match.group("verb"), uuid.UUID(match.group("id")), replay=replay
    )


# -- orders (S-07) ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OrderView:
    seller_order: SellerOrder
    code: str
    items: int
    collection: bool
    products: str  # the product names (F-26, D-104); "" if none


def _views(db: Session, seller_orders: list[SellerOrder], language: str | None) -> list[_OrderView]:
    ids = [s.id for s in seller_orders]
    if not ids:
        return []
    codes = dict(
        db.execute(
            select(SellerOrder.id, Order.code)
            .join(Order, Order.id == SellerOrder.order_id)
            .where(SellerOrder.id.in_(ids))
        ).all()
    )
    items = dict(
        db.execute(
            select(OrderItem.seller_order_id, func.sum(OrderItem.quantity))
            .where(OrderItem.seller_order_id.in_(ids))
            .group_by(OrderItem.seller_order_id)
        ).all()
    )
    modes = dict(
        db.execute(
            select(Shipment.seller_order_id, Shipment.mode).where(Shipment.seller_order_id.in_(ids))
        ).all()
    )
    names = products.for_seller_orders(db, ids, language)
    return [
        _OrderView(
            seller_order=s,
            code=codes[s.id],
            items=int(items.get(s.id) or 0),
            collection=modes.get(s.id) == DeliveryMode.SHOP_COLLECTION,
            products=names.get(s.id, ""),
        )
        for s in seller_orders
    ]


def _state(view: _OrderView, language: str, now: datetime) -> str:
    status = view.seller_order.status
    if status == SellerOrderStatus.READY and view.collection:
        return say("state_ready_collection", language)
    words = say(f"state_{status}", language)
    if status == SellerOrderStatus.PLACED and view.seller_order.response_deadline > now:
        minutes = max(1, int((view.seller_order.response_deadline - now).total_seconds() // 60))
        words += ", " + say("minutes_left", language, minutes=minutes)
    return words


def _line(view: _OrderView, language: str, now: datetime) -> str:
    line = say(
        "order_line", language, code=view.code, state=_state(view, language, now), items=view.items
    )
    if view.products:
        line += "\n" + say("order_products", language, products=view.products)
    return line


def _next_steps(view: _OrderView, language: str, now: datetime) -> list[list[dict[str, str]]]:
    """The buttons the order's state allows; the service checks again."""
    seller_order = view.seller_order
    status = seller_order.status
    if status == SellerOrderStatus.PLACED and seller_order.response_deadline > now:
        return [kb.answer_row(language, seller_order.id)]
    if status in (SellerOrderStatus.CONFIRMED, SellerOrderStatus.PAID):
        return [kb.ready_row(language, seller_order.id)]
    if (
        status in (SellerOrderStatus.READY, SellerOrderStatus.DELIVERY_FAILED)
        and not view.collection
    ):
        return [kb.sent_row(language, seller_order.id)]
    return []


def _card(
    db: Session, press: Press, seller_order: SellerOrder, headline: str | None = None
) -> dict[str, Any]:
    language, now = press.language, _now()
    (view,) = _views(db, [seller_order], language)
    lines = [headline] if headline else []
    lines.append(_line(view, language, now))
    status = seller_order.status
    if (status == SellerOrderStatus.READY and view.collection) or (
        status == SellerOrderStatus.OUT_FOR_DELIVERY
    ):
        lines.append(say("handover_on_web", language))
    rows = _next_steps(view, language, now)
    rows.append(
        [
            kb.inbox_button(language),
            kb.seller_order_link(language, seller_order.seller_id, seller_order.id),
        ]
    )
    return _reply(press, "\n".join(lines), kb.markup(rows))


def _inbox(db: Session, press: Press) -> dict[str, Any]:
    assert press.user is not None
    language, now = press.language, _now()
    stores = _stores(db, press.user, SellerCapability.HANDLE_ORDERS)
    if not stores:
        return _reply(press, say("not_a_seller", language))
    query = select(SellerOrder).where(
        SellerOrder.seller_id.in_([s.id for s in stores]),
        SellerOrder.status.in_(INBOX_STATUSES),
    )
    waiting = list(
        db.scalars(
            query.order_by(SellerOrder.response_deadline, SellerOrder.id).limit(INBOX_LIMIT + 1)
        )
    )
    if not waiting:
        return _reply(press, say("inbox_empty", language))
    shown = _views(db, waiting[:INBOX_LIMIT], language)
    lines = [say("inbox_title", language)] + ["• " + _line(v, language, now) for v in shown]
    if len(waiting) > INBOX_LIMIT:
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        lines.append(say("inbox_more", language, more=int(total) - INBOX_LIMIT))
    rows = [[kb.open_order(language, v.seller_order.id, f"{v.code} ›")] for v in shown]
    rows.append([kb.inbox_button(language)])
    return _reply(press, "\n".join(lines), kb.markup(rows))


_DONE = {"a": "done_accepted", "dr": "done_declined", "r": "done_ready", "x": "done_sent"}


def _order_action(
    db: Session,
    press: Press,
    verb: str,
    seller_order_id: uuid.UUID,
    *,
    reason: int | None = None,
    replay: bool,
) -> dict[str, Any]:
    assert press.user is not None
    language = press.language
    back = kb.markup([[kb.inbox_button(language)]])
    seller_order = db.get(SellerOrder, seller_order_id)
    if seller_order is None:
        return _reply(press, error_text("order_not_found", language), back)
    try:
        # Exactly the website's check for `/seller/{seller_id}/orders/...`.
        member, seller = seller_membership(
            db, press.user.id, seller_order.seller_id, SellerCapability.HANDLE_ORDERS
        )
    except AppError as exc:
        logger.info("telegram bot action refused", extra={"outcome": exc.code})
        return _reply(press, error_text(exc.code, language), back)
    code = db.scalar(select(Order.code).where(Order.id == seller_order.order_id)) or ""
    if verb == "d" and not replay:
        return _reply(
            press,
            say("choose_reason", language, code=code),
            kb.markup(kb.reason_rows(language, seller_order.id)),
        )
    headline: str | None = None
    if verb in _DONE and not replay:
        try:
            with db.begin_nested():
                if verb == "a":
                    orders.seller_respond(db, seller, member, seller_order.id, accept=True)
                elif verb == "dr":
                    assert reason is not None
                    orders.seller_respond(
                        db, seller, member, seller_order.id, accept=False,
                        reason=say(DECLINE_REASONS[reason], language),
                    )  # fmt: skip
                elif verb == "r":
                    orders.mark_ready(db, seller, member, seller_order.id)
                else:
                    orders.seller_dispatch(db, seller, member, seller_order.id)
        except AppError as exc:
            logger.info("telegram bot action refused", extra={"outcome": exc.code})
            headline = error_text(exc.code, language, code)
        else:
            logger.info("telegram bot action", extra={"outcome": verb})
            headline = say(_DONE[verb], language, code=code)
    db.refresh(seller_order)
    return _card(db, press, seller_order, headline)


# -- listings (S-24, S-08) ----------------------------------------------------------------


def offer_ref(offer_id: uuid.UUID) -> str:
    """A listing's short reference in the bot: the last six hex digits of
    its id (random in a UUIDv7)."""
    return offer_id.hex[-6:].upper()


def _birr(santim: int) -> str:
    birr, cents = divmod(santim, 100)
    return f"{birr:,}" + (f".{cents:02d}" if cents else "")


def _offers(db: Session, press: Press) -> dict[str, Any]:
    assert press.user is not None
    language = press.language
    stores = _stores(db, press.user, None)  # the website lists offers for any member
    if not stores:
        return _reply(press, say("not_a_seller", language))
    rows: list[dict[str, Any]] = []
    for store in stores:
        left = OFFERS_LIMIT - len(rows)
        if left <= 0:
            break
        rows += offer_selectors.seller_offers(
            db, store.id, language, status=None, after=None, limit=left
        )
    if not rows:
        return _reply(press, say("offers_empty", language))
    lines = [say("offers_title", language)]
    for row in rows:
        flag = ""
        if row["status"] == "paused":
            flag = say("flag_paused", language)
        elif row["needs_confirmation"]:
            flag = say("flag_stale", language)
        name = " ".join(filter(None, [row["product_name"], row["variant_label"]]))
        lines.append(
            say(
                "offer_line",
                language,
                ref=offer_ref(row["id"]),
                name=name,
                price=_birr(row["price_santim"]),
                available=row["available"],
                flag=flag,
            )
        )
    can_check_in = bool(_stores(db, press.user, SellerCapability.MANAGE_OFFERS))
    markup = kb.markup([[kb.checkin_button(language)]]) if can_check_in else None
    return _reply(press, "\n".join(lines), markup)


def _find_offer(db: Session, press: Press, ref: str) -> tuple[Offer, Seller, Actor] | str:
    """The listing with this reference in a store where this person may
    manage offers, checked as the website checks it; or the reply's key."""
    assert press.user is not None
    stores = _stores(db, press.user, None)
    found = list(
        db.scalars(
            select(Offer).where(
                Offer.seller_id.in_([s.id for s in stores]),
                func.right(func.replace(cast(Offer.id, Text), "-", ""), 6) == ref.lower(),
            )
        )
    )
    if len(found) != 1:
        return "offer_unknown"
    offer = found[0]
    try:
        # Exactly the website's check for `PATCH /seller/{seller_id}/offers/...`.
        _, seller = seller_membership(
            db, press.user.id, offer.seller_id, SellerCapability.MANAGE_OFFERS
        )
    except AppError as exc:
        return "err_" + (exc.code if f"err_{exc.code}" in _ERR_KEYS else "permission_denied")
    return offer, seller, Actor(type="user", user_id=press.user.id)


_ERR_KEYS = frozenset({"err_permission_denied", "err_seller_closed"})


def _offer_summary(db: Session, press: Press, offer: Offer) -> dict[str, Any]:
    return offer_selectors.seller_offer_detail(db, offer.seller_id, offer.id, press.language)


def _price(db: Session, press: Press, args: str, *, replay: bool) -> dict[str, Any]:
    language = press.language
    match = _PRICE_ARGS.fullmatch(args)
    if match is None:
        return _reply(press, say("usage_price", language))
    found = _find_offer(db, press, match.group(1))
    if isinstance(found, str):
        return _reply(press, say(found, language))
    offer, seller, actor = found
    price = int(match.group(2)) * 100 + int((match.group(3) or "0").ljust(2, "0"))
    if not replay:
        # The website's own limit on the field (`PriceSantim`), then its service.
        if not 0 < price <= MAX_PRICE_SANTIM:
            return _reply(press, error_text("price_invalid", language))
        try:
            with db.begin_nested():
                offers.update_offer(db, actor, seller, offer.id, price_santim=price)
        except AppError as exc:
            return _reply(press, error_text(exc.code, language))
    row = _offer_summary(db, press, offer)
    return _reply(
        press,
        say("price_set", language, ref=offer_ref(offer.id), price=_birr(row["price_santim"])),
    )


def _stock(db: Session, press: Press, args: str, *, replay: bool) -> dict[str, Any]:
    language = press.language
    match = _STOCK_ARGS.fullmatch(args)
    if match is None:
        return _reply(press, say("usage_stock", language))
    found = _find_offer(db, press, match.group(1))
    if isinstance(found, str):
        return _reply(press, say(found, language))
    offer, seller, actor = found
    count = int(match.group(2))
    if not replay:
        # The website's own limit on the field (`Quantity`), then its service.
        if not 0 <= count <= MAX_STOCK:
            return _reply(press, error_text("stock_invalid", language))
        try:
            with db.begin_nested():
                offers.set_stock(db, actor, seller, offer.id, on_hand=count)
        except AppError as exc:
            return _reply(press, error_text(exc.code, language))
    row = _offer_summary(db, press, offer)
    return _reply(
        press,
        say(
            "stock_set",
            language,
            ref=offer_ref(offer.id),
            on_hand=row["on_hand"],
            available=row["available"],
        ),
    )


def _checkin(db: Session, press: Press, *, replay: bool) -> dict[str, Any]:
    """The one-tap check-in (S-08) for every store where this person may
    manage offers, each checked as the website checks it."""
    assert press.user is not None
    language = press.language
    stores = _stores(db, press.user, SellerCapability.MANAGE_OFFERS)
    if not stores:
        return _reply(press, error_text("permission_denied", language))
    if replay:
        return _offers(db, press)
    actor = Actor(type="user", user_id=press.user.id)
    confirmed = 0
    for store in stores:
        try:
            _, seller = seller_membership(
                db, press.user.id, store.id, SellerCapability.MANAGE_OFFERS
            )
            with db.begin_nested():
                confirmed += offers.confirm_offers(db, actor, seller, None)
        except AppError as exc:
            if len(stores) == 1:
                return _reply(press, error_text(exc.code, language))
    return _reply(press, say("checked_in", language, count=confirmed))
