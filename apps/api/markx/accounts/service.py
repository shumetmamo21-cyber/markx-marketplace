"""Sign-in, sessions, profiles and addresses (blueprint D.2, F.4, H.2).

Identity is the phone number. Customers and sellers sign in with a code;
staff sign in with a password and an authenticator app.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qsl

import pyotp
from sqlalchemy import CursorResult, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import (
    Address,
    DataRequest,
    OtpChallenge,
    OtpLock,
    Session,
    SessionKind,
    StaffMember,
    StaffRole,
    User,
    UserStatus,
)
from markx.audit import service as audit
from markx.core import ratelimit
from markx.core import settings_store as settings
from markx.core.botcheck import get_bot_check
from markx.core.codes import new_numeric_code
from markx.core.config import get_config
from markx.core.errors import (
    AppError,
    Conflict,
    NotFound,
    PermissionDenied,
    RateLimited,
    ValidationFailed,
)
from markx.core.ids import uuid7
from markx.core.phone import InvalidPhoneNumber, mask_phone, normalize_phone
from markx.core.security import (
    constant_time_equal,
    decrypt_text,
    encrypt_text,
    hash_password,
    hash_token,
    keyed_hash,
    new_token,
    sign,
    verify_password,
)
from markx.delivery.models import DeliveryArea
from markx.notifications import service as notifications
from markx.notifications import sms
from markx.notifications.models import SmsMessage, SmsPurpose, SmsStatus

logger = logging.getLogger("markx.accounts")

OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5
OTP_LOCK = timedelta(minutes=15)
STAFF_MAX_FAILED_LOGINS = 5
STAFF_LOCK = timedelta(minutes=15)
TOTP_STEP_SECONDS = 30
TELEGRAM_AUTH_MAX_AGE = timedelta(hours=1)
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)
MAX_ACTIVE_ADDRESSES = 10

# Verifying against this when no staff account matches keeps the response time
# the same whether or not the phone number belongs to staff.
_DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-password")


def get_or_create_user_by_phone(db: DbSession, phone: str, language: str = "am") -> User:
    """The account for a normalised phone number, created if the person has
    never signed in. They prove the number is theirs at their first sign-in."""
    user, _ = _get_or_create_user(db, phone, language)
    return user


def _now() -> datetime:
    return datetime.now(UTC)


def parse_phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except InvalidPhoneNumber as exc:
        raise ValidationFailed(
            "phone_invalid", "Enter an Ethiopian mobile number, such as 0911 234 567."
        ) from exc


def csrf_token_for(session_token: str) -> str:
    return sign("csrf", session_token, length=32)


# --------------------------------------------------------------------------- login codes


def _otp_hash(challenge_id: uuid.UUID, code: str) -> bytes:
    return keyed_hash("otp", str(challenge_id), code)


def _lock_remaining(db: DbSession, phone: str, now: datetime) -> int | None:
    lock = db.get(OtpLock, phone)
    if lock is not None and lock.locked_until > now:
        return int((lock.locked_until - now).total_seconds()) + 1
    return None


def _otp_text(code: str, language: str) -> str:
    if language == "en":
        return f"MarkX code: {code}. It expires in 5 minutes. Never share it."
    return f"የMarkX ኮድ፦ {code}። በ5 ደቂቃ ውስጥ ያበቃል። ለማንም አያጋሩ።"


# The statuses after which a number waits out the cooldown: everything except
# a message the provider certainly did not take, so a failed send can be
# retried by the person at once (the hourly limits still apply).
_COOLDOWN_STATUSES = tuple(s.value for s in SmsStatus if s is not SmsStatus.FAILED)


def _refuse_too_early_resend(db: DbSession, phone: str) -> datetime:
    """The per-number resend cooldown (D-089). The transaction lock makes two
    requests for one number at the same moment wait for each other, so only
    one of them can send. Returns the time read once the lock is held, which
    the new challenge and its delivery record then carry."""
    db.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"otp-cooldown:{phone}"},
    )
    now = _now()
    cooldown = settings.get_int(db, "auth.otp_resend_cooldown_seconds")
    if cooldown <= 0:
        return now
    last = db.scalar(
        select(func.max(SmsMessage.created_at)).where(
            SmsMessage.phone_ref == sms.phone_reference(phone),
            SmsMessage.purpose == SmsPurpose.LOGIN_CODE.value,
            SmsMessage.status.in_(_COOLDOWN_STATUSES),
            SmsMessage.created_at > now - timedelta(seconds=cooldown),
        )
    )
    if last is None:
        return now
    wait = math.ceil((last + timedelta(seconds=cooldown) - now).total_seconds())
    if wait > 0:
        raise RateLimited(
            "otp_resend_too_soon",
            "A code was just sent to this number. Wait a moment before asking for another.",
            details={"retry_after_seconds": wait},
        )
    return now


def request_login_code(
    db: DbSession, *, raw_phone: str, ip: str | None, bot_token: str | None, language: str = "am"
) -> str:
    """Send a six-digit login code. Returns the normalised phone number."""
    phone = parse_phone(raw_phone)
    now = _now()

    if not get_bot_check().verify(bot_token, ip):
        raise PermissionDenied("bot_check_failed", "We could not confirm you are a person.")

    remaining = _lock_remaining(db, phone, now)
    if remaining is not None:
        raise RateLimited(
            "otp_locked",
            "Too many wrong codes. Try again in a few minutes.",
            details={"retry_after_seconds": remaining},
        )

    now = _refuse_too_early_resend(db, phone)

    hour = timedelta(hours=1)
    ratelimit.hit(f"otp:phone:{phone}", settings.get_int(db, "auth.otp_per_phone_per_hour"), hour)
    # A caller with no identifiable address shares one bucket: fail safe, not open.
    ratelimit.hit(
        f"otp:ip:{ip or 'unknown'}", settings.get_int(db, "auth.otp_per_ip_per_hour"), hour
    )
    try:
        ratelimit.hit("sms:daily", settings.get_int(db, "auth.sms_daily_budget"), timedelta(days=1))
    except RateLimited as exc:
        logger.error("daily SMS budget is spent; sending stopped")
        raise AppError(
            "sms_budget_spent",
            "Codes by SMS are paused for today. Please try again tomorrow.",
            status_code=503,
        ) from exc

    # Only the newest code for a number is ever valid.
    db.execute(
        update(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    code = new_numeric_code(6)
    text_to_send = _otp_text(code, language)
    challenge_id = uuid7()
    db.add(
        OtpChallenge(
            id=challenge_id,
            phone=phone,
            code_hash=_otp_hash(challenge_id, code),
            expires_at=now + OTP_TTL,
            ip=ip,
        )
    )
    sender = sms.get_sms_sender()
    # The delivery record holds no text and no code (D-089); it is committed
    # with the challenge, so the cooldown sees it before the SMS goes out.
    record = sms.record_message(
        db,
        purpose=SmsPurpose.LOGIN_CODE,
        phone=phone,
        text=text_to_send,
        provider=sender.provider,
        now=now,
        otp_challenge_id=challenge_id,
    )
    # The code goes straight to the SMS adapter and is never written to the
    # outbox or a log: only its keyed hash is stored (blueprint D.2). One
    # attempt only: a login code is never resent automatically.
    db.commit()
    try:
        sms.send_recorded(db, record, sender, phone=phone, text=text_to_send)
    except sms.SmsSendError as exc:
        logger.error(
            "sending a login code failed",
            extra={"phone": mask_phone(phone), "sms_error": exc.code.value},
        )
        raise AppError(
            "sms_send_failed", "We could not send the code. Please try again.", status_code=503
        ) from exc
    return phone


def _get_or_create_user(db: DbSession, phone: str, language: str) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.phone == phone))
    if user is not None:
        return user, False
    # Two first sign-ins for one number may race; the unique index decides.
    inserted = db.execute(
        pg_insert(User)
        .values(id=uuid7(), phone=phone, language=language)
        .on_conflict_do_nothing(index_elements=[User.phone])
        .returning(User.id)
    ).scalar_one_or_none()
    user = db.scalar(select(User).where(User.phone == phone))
    assert user is not None
    return user, inserted is not None


def verify_login_code(
    db: DbSession,
    *,
    raw_phone: str,
    code: str,
    ip: str | None,
    user_agent: str | None,
    transport: str = "cookie",
    language: str = "am",
    previous_session_token: str | None = None,
) -> tuple[User, str, bool]:
    """Check a login code. Returns (user, session token, is_new_account)."""
    phone = parse_phone(raw_phone)
    now = _now()

    remaining = _lock_remaining(db, phone, now)
    if remaining is not None:
        raise RateLimited(
            "otp_locked",
            "Too many wrong codes. Try again in a few minutes.",
            details={"retry_after_seconds": remaining},
        )

    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if challenge is None or challenge.expires_at <= now or challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise AppError("otp_expired", "This code has expired. Ask for a new one.")

    if not constant_time_equal(bytes(challenge.code_hash), _otp_hash(challenge.id, code.strip())):
        challenge.attempts += 1
        attempts_left = OTP_MAX_ATTEMPTS - challenge.attempts
        if attempts_left <= 0:
            challenge.consumed_at = now
            db.execute(
                pg_insert(OtpLock)
                .values(phone=phone, locked_until=now + OTP_LOCK)
                .on_conflict_do_update(
                    index_elements=[OtpLock.phone], set_={"locked_until": now + OTP_LOCK}
                )
            )
        # The failed attempt must be remembered even though this request fails.
        db.commit()
        if attempts_left <= 0:
            raise RateLimited(
                "otp_locked",
                "Too many wrong codes. Try again in a few minutes.",
                details={"retry_after_seconds": int(OTP_LOCK.total_seconds())},
            )
        raise AppError(
            "otp_invalid", "That code is not right.", details={"attempts_left": attempts_left}
        )

    challenge.consumed_at = now
    user, is_new = _get_or_create_user(db, phone, language)
    if user.status != UserStatus.ACTIVE:
        raise PermissionDenied("account_blocked", "This account cannot sign in.")

    # A new session at every sign-in (blueprint F.4): the old one is retired.
    if previous_session_token:
        end_session_by_token(db, previous_session_token)
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
    token = start_session(
        db, user, kind=SessionKind.CUSTOMER, transport=transport, ip=ip, user_agent=user_agent
    )
    if not is_new and had_other_sessions:
        notifications.notify(db, user.id, "auth.new_sign_in")
    return user, token, is_new


# --------------------------------------------------------------------------- sessions


def start_session(
    db: DbSession,
    user: User,
    *,
    kind: SessionKind,
    transport: str,
    ip: str | None,
    user_agent: str | None,
) -> str:
    config = get_config()
    now = _now()
    if kind == SessionKind.STAFF:
        idle = timedelta(minutes=config.staff_session_idle_minutes)
        maximum = timedelta(minutes=config.staff_session_max_minutes)
    else:
        idle = timedelta(minutes=config.customer_session_idle_minutes)
        maximum = timedelta(minutes=config.customer_session_max_minutes)
    token = new_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            kind=kind.value,
            transport=transport,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle,
            expires_at=now + maximum,
            ip=ip,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    user.last_seen_at = now
    db.flush()
    return token


def resolve_session(db: DbSession, token: str) -> tuple[Session, User] | None:
    """The live session for a token, or None. Slides the idle expiry forward."""
    now = _now()
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.idle_expires_at <= now
    ):
        return None
    user = db.get(User, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    if now - session.last_seen_at >= SESSION_TOUCH_INTERVAL:
        config = get_config()
        idle_minutes = (
            config.staff_session_idle_minutes
            if session.kind == SessionKind.STAFF
            else config.customer_session_idle_minutes
        )
        session.last_seen_at = now
        session.idle_expires_at = min(now + timedelta(minutes=idle_minutes), session.expires_at)
    return session, user


def end_session(db: DbSession, session: Session) -> None:
    if session.revoked_at is None:
        session.revoked_at = _now()


def end_session_by_token(db: DbSession, token: str) -> None:
    db.execute(
        update(Session)
        .where(Session.token_hash == hash_token(token), Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def end_all_sessions(db: DbSession, user_id: uuid.UUID) -> int:
    """Sign out everywhere (blueprint D.2)."""
    result = db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    return int(cast(CursorResult[Any], result).rowcount or 0)


# --------------------------------------------------------------------------- staff


@dataclass(frozen=True, slots=True)
class NewStaff:
    staff: StaffMember
    totp_secret: str
    provisioning_uri: str


def create_staff(
    db: DbSession,
    *,
    raw_phone: str,
    name: str,
    role: StaffRole,
    password: str,
    actor_user_id: uuid.UUID | None,
    ip: str | None = None,
) -> NewStaff:
    """Create a staff account. The authenticator secret is returned once and
    stored only in encrypted form."""
    phone = parse_phone(raw_phone)
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise ValidationFailed("password_too_short", str(exc)) from exc
    user, _ = _get_or_create_user(db, phone, "en")
    if not user.name:
        user.name = name.strip()
    if db.scalar(select(StaffMember.id).where(StaffMember.user_id == user.id)) is not None:
        raise Conflict("staff_exists", "This person already has a staff account.")
    secret = pyotp.random_base32()
    staff = StaffMember(
        user_id=user.id,
        role=role.value,
        password_hash=password_hash,
        totp_secret_encrypted=encrypt_text(secret),
    )
    db.add(staff)
    db.flush()
    audit.record(
        db,
        actor_type="staff" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        action="staff.create",
        target_type="staff_member",
        target_id=staff.id,
        after={"role": role.value, "user_id": str(user.id)},
        ip=ip,
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name=phone, issuer_name=get_config().totp_issuer)
    return NewStaff(staff=staff, totp_secret=secret, provisioning_uri=uri)


def _matching_totp_step(secret: str, code: str, now: datetime) -> int | None:
    """The time step a code belongs to, allowing one step of clock drift."""
    totp = pyotp.TOTP(secret)
    current_step = int(now.timestamp()) // TOTP_STEP_SECONDS
    for step in (current_step, current_step - 1, current_step + 1):
        if constant_time_equal(totp.at(step * TOTP_STEP_SECONDS), code):
            return step
    return None


def staff_sign_in(
    db: DbSession,
    *,
    raw_phone: str,
    password: str,
    totp_code: str,
    ip: str | None,
    user_agent: str | None,
    previous_session_token: str | None = None,
) -> tuple[User, StaffMember, str]:
    """Password and authenticator code together (blueprint C.5)."""
    ratelimit.hit(f"staff-login:ip:{ip or 'unknown'}", 30, timedelta(minutes=15))
    failure = AppError(
        "staff_credentials_invalid", "Those sign-in details are not right.", status_code=401
    )
    try:
        phone = normalize_phone(raw_phone)
    except InvalidPhoneNumber:
        verify_password(_DUMMY_PASSWORD_HASH, password)
        raise failure from None

    now = _now()
    row = db.execute(
        select(StaffMember, User)
        .join(User, User.id == StaffMember.user_id)
        .where(User.phone == phone)
        .with_for_update(of=StaffMember)
    ).first()
    if row is None:
        verify_password(_DUMMY_PASSWORD_HASH, password)
        raise failure
    staff, user = row
    if staff.locked_until is not None and staff.locked_until > now:
        raise RateLimited(
            "staff_locked",
            "Too many failed sign-ins. Try again later.",
            details={"retry_after_seconds": int((staff.locked_until - now).total_seconds()) + 1},
        )

    password_ok = verify_password(staff.password_hash, password)
    step = None
    if password_ok and staff.totp_secret_encrypted is not None:
        step = _matching_totp_step(
            decrypt_text(staff.totp_secret_encrypted), totp_code.strip(), now
        )
    # A code that was already used is refused, so it cannot be replayed.
    replayed = (
        step is not None and staff.totp_last_step is not None and step <= staff.totp_last_step
    )
    if (
        not password_ok
        or step is None
        or replayed
        or not staff.is_active
        or user.status != UserStatus.ACTIVE
    ):
        staff.failed_logins += 1
        if staff.failed_logins >= STAFF_MAX_FAILED_LOGINS:
            staff.failed_logins = 0
            staff.locked_until = now + STAFF_LOCK
        audit.record(
            db,
            actor_type="staff",
            actor_user_id=user.id,
            action="staff.sign_in_failed",
            target_type="staff_member",
            target_id=staff.id,
            ip=ip,
        )
        db.commit()
        raise failure

    staff.failed_logins = 0
    staff.locked_until = None
    staff.totp_last_step = step
    if previous_session_token:
        end_session_by_token(db, previous_session_token)
    token = start_session(
        db, user, kind=SessionKind.STAFF, transport="cookie", ip=ip, user_agent=user_agent
    )
    audit.record(
        db,
        actor_type="staff",
        actor_user_id=user.id,
        action="staff.sign_in",
        target_type="staff_member",
        target_id=staff.id,
        ip=ip,
    )
    return user, staff, token


def active_staff_for(db: DbSession, user_id: uuid.UUID) -> StaffMember | None:
    return db.scalar(
        select(StaffMember).where(StaffMember.user_id == user_id, StaffMember.is_active)
    )


# --------------------------------------------------------------------------- Telegram


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    id: int
    first_name: str | None


def verify_telegram_init_data(init_data: str, *, now: datetime | None = None) -> TelegramIdentity:
    """Check a Telegram Mini App's signed start-up data (blueprint D.2, F.4).

    Telegram signs the data with a key derived from the bot token. Both the
    signature and the timestamp are verified here, on the server, every time.
    Returns the verified Telegram identity.
    """
    bot_token = get_config().telegram_bot_token
    if not bot_token:
        raise AppError(
            "telegram_not_configured", "Telegram sign-in is not set up.", status_code=503
        )
    invalid = PermissionDenied(
        "telegram_signature_invalid", "Telegram sign-in could not be verified."
    )

    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash or "auth_date" not in pairs:
        raise invalid
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not constant_time_equal(expected, received_hash):
        raise invalid

    try:
        auth_date = datetime.fromtimestamp(int(pairs["auth_date"]), UTC)
    except (ValueError, OverflowError, OSError):
        raise invalid from None
    now = now or _now()
    if auth_date > now + timedelta(minutes=1) or now - auth_date > TELEGRAM_AUTH_MAX_AGE:
        raise PermissionDenied("telegram_data_expired", "Telegram sign-in data is too old.")

    try:
        telegram_user = json.loads(pairs.get("user", ""))
        telegram_id = int(telegram_user["id"])
    except (ValueError, KeyError, TypeError):
        raise invalid from None
    first_name = telegram_user.get("first_name")
    return TelegramIdentity(
        id=telegram_id, first_name=first_name if isinstance(first_name, str) else None
    )


def telegram_sign_in(
    db: DbSession, *, init_data: str, ip: str | None, user_agent: str | None
) -> tuple[User, str]:
    """Sign in a Telegram identity that is already linked to an account."""
    identity = verify_telegram_init_data(init_data)
    user = db.scalar(select(User).where(User.telegram_id == identity.id))
    if user is None:
        raise Conflict(
            "telegram_not_linked",
            "Confirm your phone number once to link this Telegram account.",
        )
    if user.status != UserStatus.ACTIVE:
        raise PermissionDenied("account_blocked", "This account cannot sign in.")
    # Cookies are unreliable in embedded web views, so the Mini App carries its
    # session in a header, issued afresh at each launch (blueprint F.4).
    token = start_session(
        db, user, kind=SessionKind.CUSTOMER, transport="header", ip=ip, user_agent=user_agent
    )
    return user, token


def link_telegram(db: DbSession, user: User, *, init_data: str) -> None:
    """One Telegram identity per account, and one account per Telegram identity."""
    telegram_id = verify_telegram_init_data(init_data).id
    owner = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if owner is not None and owner.id != user.id:
        raise Conflict(
            "telegram_already_linked", "This Telegram account is linked to another number."
        )
    if user.telegram_id is not None and user.telegram_id != telegram_id:
        raise Conflict(
            "telegram_already_linked", "This account is linked to another Telegram account."
        )
    user.telegram_id = telegram_id


# --------------------------------------------------------------------------- profile


def update_profile(db: DbSession, user: User, *, name: str | None, language: str | None) -> User:
    if name is not None:
        cleaned = " ".join(name.split())
        user.name = cleaned or None
    if language is not None:
        user.language = language
    db.flush()
    return user


def create_address(
    db: DbSession,
    user: User,
    *,
    recipient_name: str,
    raw_phone: str,
    raw_phone2: str | None,
    delivery_area_id: uuid.UUID,
    landmark: str,
    latitude: float | None,
    longitude: float | None,
    driver_notes: str | None,
) -> Address:
    area = db.get(DeliveryArea, delivery_area_id)
    if area is None or not area.is_active:
        raise ValidationFailed("area_unknown", "Choose an area from the list.")
    if (latitude is None) != (longitude is None):
        raise ValidationFailed("map_pin_incomplete", "A map pin needs both latitude and longitude.")
    active = db.scalars(
        select(Address.id).where(Address.user_id == user.id, Address.archived_at.is_(None))
    ).all()
    if len(active) >= MAX_ACTIVE_ADDRESSES:
        raise Conflict("too_many_addresses", "Remove an old address before adding another.")
    address = Address(
        user_id=user.id,
        recipient_name=" ".join(recipient_name.split()),
        phone=parse_phone(raw_phone),
        phone2=parse_phone(raw_phone2) if raw_phone2 else None,
        delivery_area_id=area.id,
        landmark=landmark.strip(),
        latitude=latitude,
        longitude=longitude,
        driver_notes=(driver_notes or "").strip() or None,
    )
    db.add(address)
    db.flush()
    return address


def list_addresses(db: DbSession, user_id: uuid.UUID) -> list[Address]:
    return list(
        db.scalars(
            select(Address)
            .where(Address.user_id == user_id, Address.archived_at.is_(None))
            .order_by(Address.created_at.desc())
        )
    )


def get_own_address(db: DbSession, user_id: uuid.UUID, address_id: uuid.UUID) -> Address:
    address = db.scalar(
        select(Address).where(
            Address.id == address_id, Address.user_id == user_id, Address.archived_at.is_(None)
        )
    )
    if address is None:
        # The same answer whether the address is missing or someone else's.
        raise NotFound("address_not_found", "That address was not found.")
    return address


def archive_address(db: DbSession, user_id: uuid.UUID, address_id: uuid.UUID) -> None:
    get_own_address(db, user_id, address_id).archived_at = _now()


def create_data_request(db: DbSession, user: User, *, kind: str, note: str | None) -> DataRequest:
    request = DataRequest(user_id=user.id, kind=kind, note=(note or "").strip() or None)
    db.add(request)
    db.flush()
    return request


def list_data_requests(db: DbSession, user_id: uuid.UUID) -> list[DataRequest]:
    return list(
        db.scalars(
            select(DataRequest)
            .where(DataRequest.user_id == user_id)
            .order_by(DataRequest.created_at.desc())
        )
    )
