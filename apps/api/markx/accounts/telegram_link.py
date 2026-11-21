"""Connecting a person's Telegram account to MarkX (D-093).

The person proves they control the Telegram account before it is linked;
nothing the browser says about Telegram (a username, a number, an id) is
believed. Two proofs are accepted:

* **The bot's one-time link** (`start_link`, `handle_update`). A signed-in
  person asks for a link; MarkX makes a random 256-bit token, stores only a
  keyed hash of it with the account, the sign-in session and an expiry, and
  answers `https://t.me/<bot>?start=<token>`. Opening it in Telegram sends
  the bot `/start <token>`; Telegram delivers that message to
  `POST /telegram/webhook` with the webhook secret in the
  `X-Telegram-Bot-Api-Secret-Token` header. The sender's id in that update
  comes from Telegram, not from the person, so the token links exactly the
  Telegram account that opened it.
* **The Mini App's signed start-up data** (`link_with_init_data`), which
  Telegram signs with the bot token (`service.verify_telegram_init_data`).

Rules, each enforced here and backed by the database:

* A token is single-use (`status` leaves `pending` the first time it is
  used, whatever the outcome), expires after `telegram_link_ttl_minutes`,
  and is replaced by a newer one (one pending link per account: a partial
  unique index). It is never logged, audited or stored in plain text.
* Completing re-checks the account (still active) and the sign-in session
  that asked (not signed out, not expired).
* One Telegram account per MarkX account and one MarkX account per Telegram
  account (`users.telegram_id` is unique). Every link to one Telegram
  account takes the same advisory lock, so two at once cannot both pass.
* A refused link says the same thing whatever the reason, so nobody learns
  whether a Telegram account is linked elsewhere.
* The webhook handles one thing, `/start` in a private chat from a person,
  and remembers every update id it has handled, so a repeated delivery does
  nothing. It answers through the webhook reply itself; MarkX makes no call
  to Telegram here.
* Everything is OFF unless `MARKX_TELEGRAM_LINKING_ENABLED` is true and the
  bot's username and webhook secret are configured. Disconnecting always
  works.

Linking changes nothing about notifications already recorded: an earlier
`skipped` or `unavailable` delivery stays as it is and is never resent.
Future notifications reach Telegram only while a push provider is configured
(`MARKX_TELEGRAM_PUSH_PROVIDER`, D-092), and stop the moment the person
disconnects (the delivery reads `users.telegram_id` at each attempt).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import Text, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import (
    Session,
    SessionKind,
    TelegramLinkFailure,
    TelegramLinkStatus,
    TelegramLinkToken,
    TelegramUpdate,
    User,
    UserStatus,
)
from markx.audit import service as audit
from markx.audit.service import Actor
from markx.core import ratelimit
from markx.core.config import get_config
from markx.core.errors import (
    AppError,
    Conflict,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    RateLimited,
)
from markx.core.security import constant_time_equal, keyed_hash, new_token
from markx.notifications import push

logger = logging.getLogger("markx.accounts.telegram")

WEBHOOK_SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105 (a header name)
# Telegram's updates are a few kilobytes; anything larger is not one.
MAX_UPDATE_BYTES = 64 * 1024
# Links one account may ask for in an hour.
LINKS_PER_ACCOUNT_PER_HOUR = 10
# `/start <token>` attempts one Telegram account may make in an hour.
ATTEMPTS_PER_TELEGRAM_ACCOUNT_PER_HOUR = 20
# Webhook calls without the right secret one address may make in an hour.
REFUSED_WEBHOOK_CALLS_PER_HOUR = 30
# `secrets.token_urlsafe(32)`: 43 characters Telegram allows in a start parameter.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_START = re.compile(r"/start(?:@[A-Za-z0-9_]{5,32})?(?:[ \t]+(\S{1,64}))?[ \t]*")
_MAX_TELEGRAM_ID = 2**52  # Telegram promises ids fit in 52 bits
_MAX_UPDATE_ID = 2**63 - 1
# The first key of the advisory lock taken for one Telegram account. "MXTG".
_TELEGRAM_LOCK_SPACE = 0x4D585447


class ConnectionState(StrEnum):
    NOT_CONNECTED = "not_connected"
    PENDING = "pending"  # a link is waiting to be opened in Telegram
    CONNECTED = "connected"
    EXPIRED = "expired"  # the latest link was not used in time
    FAILED = "failed"  # the latest link was used but refused
    DISCONNECTED = "disconnected"  # the person disconnected Telegram


@dataclass(frozen=True, slots=True)
class Connection:
    available: bool
    state: ConnectionState
    # Whether a push provider carries notifications to Telegram at all
    # (D-092), so a "connected" page never implies messages that are not sent.
    messages_on: bool
    connected_at: datetime | None = None
    expires_at: datetime | None = None
    link: str | None = None


class Outcome(StrEnum):
    """What a `/start <token>` came to. Logged and answered; never the token."""

    LINKED = "linked"
    INVALID = "invalid"  # unknown, already used, replaced or cancelled
    EXPIRED = "expired"
    REFUSED = "refused"  # see TelegramLinkFailure


# The bot's answers, in both languages because the sender may not have a
# MarkX account at all. They name no account, phone number or reason.
REPLIES: dict[Outcome | str, str] = {
    Outcome.LINKED: (
        "✅ ቴሌግራምዎ ከማርክኤክስ መለያዎ ጋር ተገናኝቷል። አሁን ወደ ማርክኤክስ መመለስ ይችላሉ።\n"
        "Your Telegram is now connected to your MarkX account. You can return to MarkX."
    ),
    Outcome.INVALID: (
        "ይህ የማገናኛ ሊንክ አይሰራም ወይም ጊዜው አልፏል። በማርክኤክስ መለያዎ ውስጥ አዲስ ሊንክ ይጠይቁ።\n"
        "This connection link is not valid or has expired. "
        "Ask for a new one in your MarkX account."
    ),
    Outcome.REFUSED: (
        "ይህን የቴሌግራም መለያ ማገናኘት አልተቻለም። ወደ ማርክኤክስ ይመለሱና እንደገና ይሞክሩ።\n"
        "This Telegram account could not be connected. Return to MarkX and try again."
    ),
    "help": (
        "የማርክኤክስ መልዕክቶችን እዚህ ለመቀበል፣ በማርክኤክስ መለያዎ ውስጥ «ቴሌግራም አገናኝ»ን ይጫኑ።\n"
        "To get MarkX notifications here, open your MarkX account and choose "
        "“Connect Telegram”."
    ),
}
REPLIES[Outcome.EXPIRED] = REPLIES[Outcome.INVALID]


def _now() -> datetime:
    return datetime.now(UTC)


def linking_available() -> bool:
    return get_config().telegram_linking_ready


def bot_username() -> str | None:
    """The bot's public username, for t.me links (D-093, D-101)."""
    return get_config().telegram_bot_username


def _messages_on() -> bool:
    return push.get_push_sender() is not None


def require_linking_available() -> None:
    if not linking_available():
        raise AppError(
            "telegram_linking_unavailable",
            "Connecting Telegram is not available yet.",
            status_code=503,
        )


def token_hash(token: str) -> bytes:
    """A keyed hash: a copy of the table alone cannot be turned into links."""
    return keyed_hash("telegram-link", token)


def _telegram_ref(telegram_id: int) -> str:
    """A rate-limit key that does not reveal the Telegram id."""
    return keyed_hash("telegram-ref", str(telegram_id)).hex()[:32]


def _lock_user(db: DbSession, user_id: uuid.UUID) -> User:
    # FOR NO KEY UPDATE: rows that only reference the user can still be
    # written meanwhile (D-027).
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise NotFound("not_found", "Not found.")
    return user


def _lock_telegram_account(db: DbSession, telegram_id: int) -> None:
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                _TELEGRAM_LOCK_SPACE, func.hashtext(literal(str(telegram_id), type_=Text))
            )
        )
    )


def _revoke_pending(db: DbSession, user_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.user_id == user_id,
            TelegramLinkToken.status == TelegramLinkStatus.PENDING,
        )
        .values(status=TelegramLinkStatus.REVOKED, finished_at=now)
        .execution_options(synchronize_session=False)
    )


# -- the person's own view -----------------------------------------------------------------


def connection_status(db: DbSession, user: User, *, now: datetime | None = None) -> Connection:
    """Where the person's own Telegram connection stands. Never the Telegram id."""
    now = now or _now()
    available = linking_available()
    on = _messages_on()
    if user.telegram_id is not None:
        return Connection(
            available=available, messages_on=on, state=ConnectionState.CONNECTED,
            connected_at=user.telegram_linked_at,
        )  # fmt: skip
    latest = db.scalar(
        select(TelegramLinkToken)
        .where(TelegramLinkToken.user_id == user.id)
        .order_by(TelegramLinkToken.created_at.desc(), TelegramLinkToken.id.desc())
        .limit(1)
    )
    unlinked_at = user.telegram_unlinked_at
    if latest is not None and (unlinked_at is None or latest.created_at > unlinked_at):
        if latest.status == TelegramLinkStatus.PENDING:
            if latest.expires_at > now:
                return Connection(
                    available=available, messages_on=on, state=ConnectionState.PENDING,
                    expires_at=latest.expires_at,
                )  # fmt: skip
            return Connection(available=available, messages_on=on, state=ConnectionState.EXPIRED)
        if latest.status == TelegramLinkStatus.FAILED:
            return Connection(available=available, messages_on=on, state=ConnectionState.FAILED)
    if unlinked_at is not None:
        return Connection(available=available, messages_on=on, state=ConnectionState.DISCONNECTED)
    return Connection(available=available, messages_on=on, state=ConnectionState.NOT_CONNECTED)


def start_link(db: DbSession, user: User, session: Session, actor: Actor) -> Connection:
    """A new one-time link for the signed-in person. Any earlier link that
    was not used yet stops working."""
    require_linking_available()
    if session.kind != SessionKind.CUSTOMER:
        # Staff powers and personal settings never mix in one session (C.1).
        raise PermissionDenied(
            "customer_session_required", "Sign in with your phone code to connect Telegram."
        )
    ratelimit.hit(f"telegram:link:user:{user.id}", LINKS_PER_ACCOUNT_PER_HOUR, timedelta(hours=1))
    config = get_config()
    user = _lock_user(db, user.id)
    now = _now()
    if user.telegram_id is not None:
        raise Conflict(
            "telegram_already_connected",
            "Your account is already connected to Telegram. Disconnect it first.",
        )
    _revoke_pending(db, user.id, now)
    token = new_token()
    expires_at = now + timedelta(minutes=config.telegram_link_ttl_minutes)
    row = TelegramLinkToken(
        user_id=user.id, session_id=session.id, token_hash=token_hash(token),
        created_at=now, expires_at=expires_at,
    )  # fmt: skip
    db.add(row)
    db.flush()
    audit.record_by(
        db, actor, "telegram.link_requested", "user", user.id,
        after={"link_id": str(row.id), "expires_at": expires_at.isoformat()},
    )  # fmt: skip
    return Connection(
        available=True,
        messages_on=_messages_on(),
        state=ConnectionState.PENDING,
        expires_at=expires_at,
        link=f"https://t.me/{config.telegram_bot_username}?start={token}",
    )


def disconnect(db: DbSession, user: User, actor: Actor) -> Connection:
    """Disconnect Telegram and cancel any link not used yet. Always allowed:
    it only ever removes access. Signing in to MarkX never depended on it."""
    user = _lock_user(db, user.id)
    now = _now()
    _revoke_pending(db, user.id, now)
    if user.telegram_id is not None:
        user.telegram_id = None
        user.telegram_linked_at = None
        user.telegram_unlinked_at = now
        audit.record_by(db, actor, "telegram.unlinked", "user", user.id)
    db.flush()
    return connection_status(db, user, now=now)


# -- attaching a proven Telegram account ----------------------------------------------------


def _attach(
    db: DbSession, user: User, telegram_id: int, now: datetime, actor: Actor, method: str
) -> TelegramLinkFailure | None:
    """Link `telegram_id` to the locked `user`, or say why not. The caller
    holds the user's row lock; this takes the Telegram account's lock."""
    _lock_telegram_account(db, telegram_id)
    if user.telegram_id is not None:
        # The same Telegram account again changes nothing.
        return None if user.telegram_id == telegram_id else TelegramLinkFailure.ALREADY_CONNECTED
    owner = db.scalar(select(User.id).where(User.telegram_id == telegram_id))
    if owner is not None:
        return TelegramLinkFailure.TELEGRAM_IN_USE
    try:
        with db.begin_nested():
            user.telegram_id = telegram_id
            user.telegram_linked_at = now
            user.telegram_unlinked_at = None
            db.flush()
    except IntegrityError:
        # The unique constraint is the last word, should a link ever bypass
        # the advisory lock.
        db.refresh(user)
        return TelegramLinkFailure.TELEGRAM_IN_USE
    _revoke_pending(db, user.id, now)
    audit.record_by(db, actor, "telegram.linked", "user", user.id, after={"method": method})
    return None


def link_with_init_data(db: DbSession, user: User, telegram_id: int, actor: Actor) -> None:
    """The Mini App's way (`POST /me/telegram`): the identity is already
    verified from Telegram's signature."""
    require_linking_available()
    user = _lock_user(db, user.id)
    failure = _attach(db, user, telegram_id, _now(), actor, "mini_app")
    if failure is not None:
        # One answer for every reason: whether a Telegram account belongs to
        # someone else is not this caller's business.
        raise Conflict(
            "telegram_already_linked",
            "This Telegram account cannot be connected to this MarkX account.",
        )


def _complete(db: DbSession, token: str, telegram_id: int, now: datetime) -> Outcome:
    digest = token_hash(token)
    owner_id = db.scalar(
        select(TelegramLinkToken.user_id).where(TelegramLinkToken.token_hash == digest)
    )
    if owner_id is None:
        return Outcome.INVALID
    # Locks in one order everywhere: the user, then their links. Asking for a
    # new link (or disconnecting) at the moment Telegram confirms the old one
    # then waits instead of deadlocking.
    user = _lock_user(db, owner_id)
    row = db.scalar(
        select(TelegramLinkToken)
        .where(TelegramLinkToken.token_hash == digest)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.status != TelegramLinkStatus.PENDING:
        return Outcome.INVALID
    if row.expires_at <= now:
        return Outcome.EXPIRED
    actor = Actor(type="user", user_id=user.id)
    session = db.get(Session, row.session_id)
    failure: TelegramLinkFailure | None
    if user.status != UserStatus.ACTIVE:
        failure = TelegramLinkFailure.ACCOUNT_INACTIVE
    elif (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.idle_expires_at <= now
    ):
        failure = TelegramLinkFailure.SESSION_ENDED
    else:
        failure = _attach(db, user, telegram_id, now, actor, "bot_link")
    # Used once, whatever the outcome. `_attach` revoked other pending links
    # of this account; this one is ended explicitly.
    row.status = TelegramLinkStatus.CONSUMED if failure is None else TelegramLinkStatus.FAILED
    row.failure_reason = None if failure is None else failure.value
    row.finished_at = now
    if failure is not None:
        audit.record_by(
            db, actor, "telegram.link_refused", "user", user.id,
            after={"link_id": str(row.id), "reason": failure.value},
        )  # fmt: skip
    db.flush()
    return Outcome.LINKED if failure is None else Outcome.REFUSED


# -- the webhook ---------------------------------------------------------------------------


class WebhookReply:
    """What the webhook answers Telegram: nothing to do, or one message back
    to the sender's private chat (Telegram's "reply in the webhook response",
    so MarkX itself makes no call to Telegram)."""

    @staticmethod
    def nothing() -> dict[str, Any]:
        return {"ok": True}

    @staticmethod
    def message(
        chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        reply: dict[str, Any] = {"method": "sendMessage", "chat_id": chat_id, "text": text}
        if reply_markup is not None:
            reply["reply_markup"] = reply_markup
        return reply


def _int(value: Any, upper: int) -> int | None:
    # bool is an int in Python; Telegram never sends one for an id.
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= upper:
        return value
    return None


def authenticate_webhook(secret_header: str | None, ip: str | None) -> None:
    """Refuse a call that is not from Telegram, before anything is read.
    A webhook that is switched off does not exist."""
    config = get_config()
    if not config.telegram_linking_ready:
        raise NotFound("not_found", "Not Found")
    assert config.telegram_webhook_secret is not None
    expected = config.telegram_webhook_secret.get_secret_value()
    if not secret_header or not constant_time_equal(secret_header, expected):
        logger.warning("telegram webhook refused: missing or wrong secret")
        # Past the limit this raises RateLimited (429) instead.
        ratelimit.hit(
            f"telegram:webhook:refused:{ip or 'unknown'}",
            REFUSED_WEBHOOK_CALLS_PER_HOUR,
            timedelta(hours=1),
        )
        raise NotAuthenticated(
            "telegram_webhook_unauthorized", "This request is not from Telegram."
        )


def _parse(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_UPDATE_BYTES:
        raise AppError("payload_too_large", "The update is too large.", status_code=413)
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        data = None
    if not isinstance(data, dict) or _int(data.get("update_id"), _MAX_UPDATE_ID) is None:
        raise AppError("telegram_update_invalid", "This is not a Telegram update.", status_code=400)
    return data


def handle_update(db: DbSession, body: bytes) -> dict[str, Any]:
    """One authenticated Telegram update. Returns the webhook's answer.

    Anything but `/start` in a private chat from a person is acknowledged
    and ignored, so Telegram does not send it again and nothing changes.
    """
    data = _parse(body)
    update_id = int(data["update_id"])
    first_time = db.execute(
        pg_insert(TelegramUpdate)
        .values(update_id=update_id)
        .on_conflict_do_nothing(index_elements=[TelegramUpdate.update_id])
        .returning(TelegramUpdate.update_id)
    ).first()
    if first_time is None:
        logger.info("telegram update ignored", extra={"outcome": "duplicate"})
        return WebhookReply.nothing()

    message = data.get("message")
    if not isinstance(message, dict):
        return _ignored("not_a_message")
    chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
    # A shared phone number carries no text (D-101: signing in with Telegram).
    contact = isinstance(message.get("contact"), dict) and text is None
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return _ignored("not_a_text_message")
    if not isinstance(text, str) and not contact:
        return _ignored("not_a_text_message")
    chat_id = _int(chat.get("id"), _MAX_TELEGRAM_ID)
    sender_id = _int(sender.get("id"), _MAX_TELEGRAM_ID)
    if (
        chat.get("type") != "private"
        or sender.get("is_bot") is not False
        or chat_id is None
        or sender_id is None
        or chat_id != sender_id
    ):
        return _ignored("not_a_private_chat_with_a_person")
    # Imported here: the sign-in module builds on this one.
    from markx.accounts import telegram_sign_in

    if contact:
        answer = telegram_sign_in.contact_from_telegram(db, message, sender_id)
        return answer if answer is not None else _ignored("rate_limited")
    assert isinstance(text, str)
    match = _START.fullmatch(text) if len(text) <= 4096 else None
    if match is None:
        return _ignored("not_start")
    payload = match.group(1)
    if payload is None:
        return WebhookReply.message(chat_id, REPLIES["help"])
    sign_in = telegram_sign_in.PAYLOAD.fullmatch(payload)
    if sign_in is not None:
        answer = telegram_sign_in.open_from_telegram(db, sign_in.group(1), sender_id)
        return answer if answer is not None else _ignored("rate_limited")

    try:
        ratelimit.hit(
            f"telegram:link:tg:{_telegram_ref(sender_id)}",
            ATTEMPTS_PER_TELEGRAM_ACCOUNT_PER_HOUR,
            timedelta(hours=1),
        )
    except RateLimited:
        return _ignored("rate_limited")
    outcome = (
        _complete(db, payload, sender_id, _now()) if _TOKEN.fullmatch(payload) else Outcome.INVALID
    )
    logger.info("telegram link attempt", extra={"outcome": outcome.value})
    return WebhookReply.message(chat_id, REPLIES[outcome])


def _ignored(why: str) -> dict[str, Any]:
    logger.info("telegram update ignored", extra={"outcome": why})
    return WebhookReply.nothing()
