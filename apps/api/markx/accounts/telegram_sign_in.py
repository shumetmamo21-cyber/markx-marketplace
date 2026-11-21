"""Signing in on the website with Telegram (D-101, decision SI-1).

Everyone (buyers, sellers and staff) signs in with Telegram. On a phone the
button opens the Telegram app straight away; nothing is typed and no SMS is
paid for. The steps:

1. **The browser asks** (`start`). MarkX makes two random 256-bit values: a
   *token*, which goes into the link `https://t.me/<bot>?start=si-<token>`,
   and a *browser secret*, which goes into an HttpOnly cookie only that
   browser holds. Only keyed hashes of both are stored, with an expiry
   (`auth.telegram_sign_in_minutes`, PROVISIONAL P-101-1).
2. **Telegram opens the link** and sends the bot `/start si-<token>` from
   the person's Telegram account; Telegram, not the person, says who sent
   it (`open_from_telegram`). The bot answers with Telegram's own "share my
   phone number" button.
3. **The person shares their number** (`contact_from_telegram`). Telegram
   sends the contact with the sender's own user id; a contact that is not
   the sender's own, or that was forwarded, is not accepted. The number must
   be an Ethiopian mobile number. MarkX then chooses the account (the rules
   below) and marks the sign-in confirmed.
4. **The browser collects its session** (`check`): only the browser holding
   the secret, only once, only before the expiry.

So the link alone signs nobody in: whoever opens it must also hold the
Telegram account (and press the button in it), and only the browser that
started can receive the session. A link sent to someone else ("click this to
sign in") would sign the sender's browser in to that person's account; the
bot's message therefore says plainly to continue only if they started
signing in themselves, and the person is told in the app of every new
sign-in (`auth.new_sign_in`), as with SMS codes.

**Which account (PROVISIONAL P-101-6, D-101).** T is the Telegram account,
P the number Telegram confirmed. One number is one account; one Telegram
account is one account.

"The account with T" is the account T belongs to (`users.bound_telegram_id`):
the first Telegram account ever attached to it, remembered for ever, even
after "Disconnect Telegram", which only stops messages.

* An account already has both T and P: that account.
* Neither exists: a new account with P and T.
* An account has P and has never had any Telegram account (for example it
  was made by SMS, by an invitation, or by staff for a new staff member): T
  is connected to it, and it belongs to T from then on.
* An account has P but belongs to a DIFFERENT Telegram account, connected or
  disconnected: refused. A number is never moved from one Telegram account
  to another automatically, because Ethiopian numbers are recycled; the
  person asks MarkX support (F-24).
* The account with T was disconnected from Telegram: signing in with T
  connects it again (only T can).
* The account with T has another number, and P belongs to nobody: the
  account's number becomes P (Telegram confirmed it), recorded in the audit
  log and told to the person in the app.
* The account with T has another number and P belongs to a second account:
  refused (one number, one account).

Everything is OFF unless the bot is configured (`telegram_link.linking_available`):
the same bot, webhook and secret as connecting Telegram (D-093).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import Text, func, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts import telegram_link
from markx.accounts.models import (
    LANGUAGES,
    Session,
    TelegramSignIn,
    TelegramSignInFailure,
    TelegramSignInStatus,
    User,
    UserStatus,
)
from markx.audit import service as audit
from markx.audit.service import Actor
from markx.core import ratelimit
from markx.core import settings_store as settings
from markx.core.errors import AppError, RateLimited
from markx.core.ids import uuid7
from markx.core.phone import InvalidPhoneNumber, mask_phone, normalize_phone
from markx.core.security import keyed_hash, new_token
from markx.notifications import service as notifications

logger = logging.getLogger("markx.accounts.telegram_sign_in")

# The prefix that tells a sign-in link from a connection link (D-093), whose
# token is 43 characters with no prefix.
PAYLOAD_PREFIX = "si-"
PAYLOAD = re.compile(r"si-([A-Za-z0-9_-]{43})")
# `/start si-<token>` and shared numbers one Telegram account may send in an hour.
ATTEMPTS_PER_TELEGRAM_ACCOUNT_PER_HOUR = 20
# The first key of the advisory lock taken for one phone number. "MXPH".
_PHONE_LOCK_SPACE = 0x4D585048


class State(StrEnum):
    """What the browser is told about its sign-in. Never a number or an id."""

    NONE = "none"  # nothing started in this browser, or it was replaced
    WAITING = "waiting"  # the link was not opened in Telegram yet
    WAITING_FOR_PHONE = "waiting_for_phone"  # opened; the number was not shared yet
    SIGNED_IN = "signed_in"  # done: the session cookie came with this answer
    EXPIRED = "expired"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class Started:
    link: str
    browser_secret: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Checked:
    state: State
    expires_at: datetime | None = None
    reason: str | None = None
    user: User | None = None
    session_token: str | None = None
    is_new_account: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def available() -> bool:
    return telegram_link.linking_available()


def require_available() -> None:
    if not available():
        raise AppError(
            "telegram_sign_in_unavailable",
            "Signing in with Telegram is not available yet.",
            status_code=503,
        )


def token_hash(token: str) -> bytes:
    return keyed_hash("telegram-sign-in", token)


def browser_hash(secret: str) -> bytes:
    return keyed_hash("telegram-sign-in-browser", secret)


# -- 1. the browser asks ------------------------------------------------------------------


def start(db: DbSession, *, ip: str | None, language: str, previous_secret: str | None) -> Started:
    """A new one-time sign-in link and the secret only this browser keeps.
    A sign-in this browser started before and did not finish stops working."""
    require_available()
    ratelimit.hit(
        f"telegram:sign-in:ip:{ip or 'unknown'}",
        settings.get_int(db, "auth.telegram_sign_ins_per_ip_per_hour"),
        timedelta(hours=1),
    )
    now = _now()
    if previous_secret:
        _revoke(db, TelegramSignIn.browser_hash == browser_hash(previous_secret), now)
    token, secret = new_token(), new_token()
    expires_at = now + timedelta(minutes=settings.get_int(db, "auth.telegram_sign_in_minutes"))
    db.add(
        TelegramSignIn(
            id=uuid7(),
            token_hash=token_hash(token),
            browser_hash=browser_hash(secret),
            language=language if language in LANGUAGES else "am",
            created_at=now,
            expires_at=expires_at,
            ip=ip,
        )
    )
    db.flush()
    username = telegram_link.bot_username()
    return Started(
        link=f"https://t.me/{username}?start={PAYLOAD_PREFIX}{token}",
        browser_secret=secret,
        expires_at=expires_at,
    )


def _revoke(db: DbSession, condition: Any, now: datetime) -> None:
    db.execute(
        update(TelegramSignIn)
        .where(
            condition,
            TelegramSignIn.status.in_((TelegramSignInStatus.PENDING, TelegramSignInStatus.OPENED)),
        )
        .values(status=TelegramSignInStatus.REVOKED, finished_at=now)
        .execution_options(synchronize_session=False)
    )


# -- 4. the browser collects its session --------------------------------------------------


def check(
    db: DbSession,
    *,
    browser_secret: str | None,
    start_session: Any,
) -> Checked:
    """Where this browser's sign-in stands; once Telegram confirmed it, the
    session (exactly once). `start_session(user) -> token` makes the session,
    so the caller decides its kind and transport."""
    if not browser_secret:
        return Checked(State.NONE)
    row = db.scalar(
        select(TelegramSignIn)
        .where(TelegramSignIn.browser_hash == browser_hash(browser_secret))
        .with_for_update()
    )
    if row is None or row.status in (TelegramSignInStatus.REVOKED, TelegramSignInStatus.CONSUMED):
        return Checked(State.NONE)
    now = _now()
    if row.status == TelegramSignInStatus.REFUSED:
        return Checked(State.REFUSED, reason=row.failure_reason)
    if row.expires_at <= now:
        return Checked(State.EXPIRED)
    if row.status == TelegramSignInStatus.PENDING:
        return Checked(State.WAITING, expires_at=row.expires_at)
    if row.status == TelegramSignInStatus.OPENED:
        return Checked(State.WAITING_FOR_PHONE, expires_at=row.expires_at)
    assert row.status == TelegramSignInStatus.CONFIRMED
    assert row.user_id is not None
    user = db.get(User, row.user_id)
    row.status = TelegramSignInStatus.CONSUMED
    row.finished_at = now
    if user is None or user.status != UserStatus.ACTIVE:
        db.flush()
        return Checked(State.REFUSED, reason=TelegramSignInFailure.ACCOUNT_INACTIVE.value)
    had_other_sessions = (
        db.scalar(
            select(Session.id)
            .where(
                Session.user_id == user.id, Session.revoked_at.is_(None), Session.expires_at > now
            )
            .limit(1)
        )
        is not None
    )
    token = start_session(user)
    if had_other_sessions:
        notifications.notify(db, user.id, "auth.new_sign_in")
    audit.record_by(
        db, Actor(type="user", user_id=user.id), "auth.telegram_sign_in", "user", user.id,
        after={"sign_in_id": str(row.id)},
    )  # fmt: skip
    db.flush()
    # An account made after this sign-in began was made by it.
    return Checked(
        State.SIGNED_IN,
        user=user,
        session_token=token,
        is_new_account=user.created_at >= row.created_at,
    )


# -- 2. and 3. what Telegram tells the bot ----------------------------------------------------

_BOTH = "\n"

REPLIES: dict[str, str] = {
    "share_phone": (
        "ወደ ማርክኤክስ ለመግባት ከታች ያለውን «📱 ስልክ ቁጥሬን አጋራ» ቁልፍ ይጫኑ። "
        "ይህን የሚያደርጉት እርስዎ ራስዎ አሁን ወደ ማርክኤክስ ለመግባት ከጀመሩ ብቻ ነው፤ "
        "ሌላ ሰው ሊንኩን ከላከልዎ አይቀጥሉ።"
        + _BOTH
        + "To sign in to MarkX, press “📱 Share my phone number” below. Only continue if you "
        "started signing in to MarkX yourself just now; if someone sent you this link, stop."
    ),
    "signed_in": (
        "✅ ገብተዋል። አሁን ወደ ማርክኤክስ ገጹ ይመለሱ።"
        + _BOTH
        + "✅ You are signed in. Go back to the MarkX page now."
    ),
    "invalid": (
        "ይህ የመግቢያ ሊንክ አይሰራም ወይም ጊዜው አልፏል። በማርክኤክስ ገጹ ላይ እንደገና «በቴሌግራም ግባ»ን ይጫኑ።"
        + _BOTH
        + "This sign-in link is not valid or has expired. Press “Sign in with Telegram” on "
        "the MarkX page again."
    ),
    "own_number_only": (
        "እባክዎ ከታች ያለውን ቁልፍ ተጠቅመው የራስዎን ቁጥር ያጋሩ።"
        + _BOTH
        + "Please share your own number with the button below."
    ),
    "nothing_waiting": (
        "ምንም የሚጠብቅ መግቢያ የለም። በማርክኤክስ ገጹ ላይ «በቴሌግራም ግባ»ን ይጫኑ።"
        + _BOTH
        + "No sign-in is waiting. Press “Sign in with Telegram” on the MarkX page."
    ),
    "not_ethiopian": (
        "ማርክኤክስ የኢትዮጵያ ሞባይል ቁጥር (+2519… ወይም +2517…) ያስፈልገዋል። ይህ የቴሌግራም መለያ ሌላ ቁጥር አለው።"
        + _BOTH
        + "MarkX needs an Ethiopian mobile number (+2519… or +2517…). This Telegram account "
        "has another number."
    ),
    "refused": (
        "በዚህ የቴሌግራም መለያ መግባት አልተቻለም። ለምን እንደሆነ በማርክኤክስ ገጹ ላይ ያያሉ።"
        + _BOTH
        + "Signing in with this Telegram account was not possible. The MarkX page says why."
    ),
    "try_again": (
        "ትንሽ ቆይተው ቁጥርዎን እንደገና ያጋሩ።" + _BOTH + "Please share your number again in a moment."
    ),
}

SHARE_BUTTON = "📱 ስልክ ቁጥሬን አጋራ / Share my phone number"
_ASK_FOR_PHONE = {
    "keyboard": [[{"text": SHARE_BUTTON, "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
_REMOVE_KEYBOARD = {"remove_keyboard": True}


def _reply(chat_id: int, key: str, markup: dict[str, Any] | None = None) -> dict[str, Any]:
    return telegram_link.WebhookReply.message(chat_id, REPLIES[key], reply_markup=markup)


def _telegram_ref(telegram_id: int) -> str:
    return keyed_hash("telegram-ref", str(telegram_id)).hex()[:32]


def _limited(telegram_id: int) -> bool:
    try:
        ratelimit.hit(
            f"telegram:sign-in:tg:{_telegram_ref(telegram_id)}",
            ATTEMPTS_PER_TELEGRAM_ACCOUNT_PER_HOUR,
            timedelta(hours=1),
        )
    except RateLimited:
        return True
    return False


def open_from_telegram(db: DbSession, token: str, telegram_id: int) -> dict[str, Any] | None:
    """`/start si-<token>` from `telegram_id`. Returns the bot's answer, or
    None when the account is past its hourly limit (nothing is answered)."""
    if _limited(telegram_id):
        return None
    now = _now()
    row = db.scalar(
        select(TelegramSignIn)
        .where(TelegramSignIn.token_hash == token_hash(token))
        .with_for_update()
    )
    if row is None or row.status != TelegramSignInStatus.PENDING or row.expires_at <= now:
        logger.info("telegram sign-in link refused", extra={"outcome": "invalid"})
        return _reply(telegram_id, "invalid", _REMOVE_KEYBOARD)
    # One sign-in at a time per Telegram account: an earlier one that was
    # opened and not finished stops working.
    _revoke(
        db,
        (TelegramSignIn.telegram_id == telegram_id) & (TelegramSignIn.id != row.id),
        now,
    )
    row.status = TelegramSignInStatus.OPENED
    row.telegram_id = telegram_id
    row.opened_at = now
    db.flush()
    logger.info("telegram sign-in link opened", extra={"outcome": "opened"})
    return _reply(telegram_id, "share_phone", _ASK_FOR_PHONE)


def contact_from_telegram(
    db: DbSession, message: dict[str, Any], telegram_id: int
) -> dict[str, Any] | None:
    """A shared contact from `telegram_id` in its private chat with the bot."""
    if _limited(telegram_id):
        return None
    now = _now()
    row = db.scalar(
        select(TelegramSignIn)
        .where(
            TelegramSignIn.telegram_id == telegram_id,
            TelegramSignIn.status == TelegramSignInStatus.OPENED,
            TelegramSignIn.expires_at > now,
        )
        .order_by(TelegramSignIn.opened_at.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None:
        return _reply(telegram_id, "nothing_waiting", _REMOVE_KEYBOARD)
    contact = message.get("contact")
    forwarded = any(key in message for key in ("forward_origin", "forward_from", "forward_date"))
    owner = contact.get("user_id") if isinstance(contact, dict) else None
    raw_phone = contact.get("phone_number") if isinstance(contact, dict) else None
    # Telegram fills `user_id` with the account a number belongs to; only the
    # sender's own number, shared (not forwarded), proves anything.
    if (
        forwarded
        or owner != telegram_id
        or isinstance(owner, bool)
        or not isinstance(raw_phone, str)
    ):
        return _reply(telegram_id, "own_number_only", _ASK_FOR_PHONE)
    try:
        phone = normalize_phone(raw_phone if raw_phone.startswith("+") else f"+{raw_phone}")
    except InvalidPhoneNumber:
        _refuse(db, row, TelegramSignInFailure.PHONE_NOT_ETHIOPIAN, now)
        return _reply(telegram_id, "not_ethiopian", _REMOVE_KEYBOARD)
    try:
        failure = _settle_account(db, row, telegram_id, phone, now)
    except _Changed:
        # Another sign-in for the same number or Telegram account moved
        # something at this very moment. The sign-in stays open.
        return _reply(telegram_id, "try_again", _ASK_FOR_PHONE)
    if failure is not None:
        _refuse(db, row, failure, now)
        return _reply(telegram_id, "refused", _REMOVE_KEYBOARD)
    return _reply(telegram_id, "signed_in", _REMOVE_KEYBOARD)


def _refuse(
    db: DbSession, row: TelegramSignIn, failure: TelegramSignInFailure, now: datetime
) -> None:
    row.status = TelegramSignInStatus.REFUSED
    row.failure_reason = failure.value
    row.finished_at = now
    db.flush()
    logger.info("telegram sign-in refused", extra={"outcome": failure.value})


def _reconnect(db: DbSession, user: User, telegram_id: int, now: datetime) -> None:
    """The account's own Telegram account signed in after "Disconnect
    Telegram": connect it again, as signing in with it always did."""
    assert user.bound_telegram_id in (None, telegram_id)
    if user.telegram_id is not None:
        return
    user.telegram_id = telegram_id
    user.bound_telegram_id = telegram_id
    user.telegram_linked_at = now
    user.telegram_unlinked_at = None
    db.flush()
    telegram_link._revoke_pending(db, user.id, now)
    audit.record_by(
        db, Actor(type="user", user_id=user.id), "telegram.linked", "user", user.id,
        after={"method": "telegram_sign_in"},
    )  # fmt: skip


class _Changed(Exception):
    """The accounts involved changed between reading and locking them."""


def _lock_phone(db: DbSession, phone: str) -> None:
    db.execute(
        select(
            func.pg_advisory_xact_lock(_PHONE_LOCK_SPACE, func.hashtext(literal(phone, type_=Text)))
        )
    )


def _ids(db: DbSession, telegram_id: int, phone: str) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    # The account T belongs to, connected or disconnected (P-101-6).
    by_telegram = db.scalar(
        select(User.id).where(
            (User.bound_telegram_id == telegram_id) | (User.telegram_id == telegram_id)
        )
    )
    by_phone = db.scalar(select(User.id).where(User.phone == phone))
    return by_telegram, by_phone


def _settle_account(
    db: DbSession, row: TelegramSignIn, telegram_id: int, phone: str, now: datetime
) -> TelegramSignInFailure | None:
    """Choose, connect or create the account (the rules in the module's
    docstring), and mark the sign-in confirmed. Locks in the order used
    everywhere for Telegram (D-093): users' rows (ascending id), then the
    Telegram account's advisory lock; then the number's."""
    first = _ids(db, telegram_id, phone)
    for user_id in sorted({i for i in first if i is not None}):
        telegram_link._lock_user(db, user_id)
    telegram_link._lock_telegram_account(db, telegram_id)
    _lock_phone(db, phone)
    if _ids(db, telegram_id, phone) != first:
        raise _Changed
    by_telegram_id, by_phone_id = first
    by_telegram = db.get(User, by_telegram_id) if by_telegram_id else None
    by_phone = db.get(User, by_phone_id) if by_phone_id else None
    if by_telegram is not None and by_phone is not None:
        if by_telegram.id != by_phone.id:
            return TelegramSignInFailure.PHONE_IN_USE
        user = by_telegram
        if user.status != UserStatus.ACTIVE:
            return TelegramSignInFailure.ACCOUNT_INACTIVE
        _reconnect(db, user, telegram_id, now)
    elif by_telegram is not None:
        # The same Telegram account, a new number Telegram confirmed, and
        # nobody else has it: the account's number follows (P-101-6).
        user = by_telegram
        if user.status != UserStatus.ACTIVE:
            return TelegramSignInFailure.ACCOUNT_INACTIVE
        before = user.phone
        try:
            with db.begin_nested():
                user.phone = phone
                db.flush()
        except IntegrityError:
            db.refresh(user)
            return TelegramSignInFailure.PHONE_IN_USE
        _reconnect(db, user, telegram_id, now)
        audit.record_by(
            db, Actor(type="user", user_id=user.id), "account.phone_changed", "user", user.id,
            before={"phone": mask_phone(before)},
            after={"phone": mask_phone(phone), "confirmed_by": "telegram"},
        )  # fmt: skip
        notifications.notify(db, user.id, "auth.phone_changed")
    elif by_phone is not None:
        user = by_phone
        if user.telegram_id is not None and user.telegram_id != telegram_id:
            # Never moved automatically (P-101-6): numbers are recycled.
            return TelegramSignInFailure.PHONE_ON_OTHER_TELEGRAM
        if user.bound_telegram_id is not None and user.bound_telegram_id != telegram_id:
            # The same, after "Disconnect Telegram": the account still belongs
            # to the Telegram account it had. A stranger given the old number
            # never takes it over (P-101-6); support decides (F-24).
            return TelegramSignInFailure.PHONE_ON_OTHER_TELEGRAM
        if user.status != UserStatus.ACTIVE:
            return TelegramSignInFailure.ACCOUNT_INACTIVE
        try:
            with db.begin_nested():
                user.telegram_id = telegram_id
                user.bound_telegram_id = telegram_id
                user.telegram_linked_at = now
                user.telegram_unlinked_at = None
                db.flush()
        except IntegrityError:
            db.refresh(user)
            raise _Changed from None
        telegram_link._revoke_pending(db, user.id, now)
        audit.record_by(
            db, Actor(type="user", user_id=user.id), "telegram.linked", "user", user.id,
            after={"method": "telegram_sign_in"},
        )  # fmt: skip
    else:
        user = User(
            id=uuid7(),
            phone=phone,
            language=row.language,
            telegram_id=telegram_id,
            bound_telegram_id=telegram_id,
            telegram_linked_at=now,
        )
        try:
            with db.begin_nested():
                db.add(user)
                db.flush()
        except IntegrityError:
            raise _Changed from None
        audit.record_by(
            db, Actor(type="user", user_id=user.id), "account.created", "user", user.id,
            after={"method": "telegram_sign_in"},
        )  # fmt: skip

    if user.status != UserStatus.ACTIVE:
        return TelegramSignInFailure.ACCOUNT_INACTIVE
    row.status = TelegramSignInStatus.CONFIRMED
    row.user_id = user.id
    row.confirmed_at = now
    db.flush()
    logger.info("telegram sign-in confirmed", extra={"outcome": "confirmed"})
    return None
