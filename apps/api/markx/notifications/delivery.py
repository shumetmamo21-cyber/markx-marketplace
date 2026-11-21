"""Carrying a notification to the channels outside the app (D-092).

The in-app record (`notifications`, channel `in_app`) is written with the
change that caused it and never depends on a provider. Its outbox row
(`notify.push`) then reaches this module through the worker, which tries each
outside channel once per notification:

* **Telegram**, for a person who linked it, when a push provider is
  configured. Every notification is pushed (it costs nothing per message).
* **SMS**, only for order alerts (`texts.ORDER_TEXTS`), only while the
  `notifications.sms_enabled` switch is on (it is OFF by default: N-1), and
  by default only for a person Telegram cannot reach. It has its own daily
  budget, separate from the sign-in codes', a per-person hourly limit and a
  per-number cooldown.

Every outcome is a `notification_deliveries` row with an explicit status and
reason: `accepted`, `failed`, `unknown`, `skipped` or `unavailable`. A missing
provider is `unavailable`, never an exception (the defect D-092 fixes).

**Delivery semantics.** A message that leaves the server cannot join a
database transaction, and no provider MarkX may use is known to refuse a
repeat (Telegram's Bot API has no idempotency key; no SMS provider is chosen,
F-11). So exactly-once delivery is impossible, and this module does not
claim it. Instead, the delivery row is moved to `sending` and **committed
before** the provider is called, and the outcome is committed right after.
A worker that dies in between leaves `sending` behind, and the next attempt
knows the earlier one was interrupted and may or may not have gone out:

* Telegram sends again (at-least-once, D-034: an order alert seen twice is
  harmless, one never sent is not, and a push costs nothing).
* SMS does not: the delivery becomes `unknown` (at-most-once). A repeated SMS
  is a second paid message, the in-app message is always there, and the
  monitoring reports unknown deliveries. An SMS timeout or an unreadable 2xx
  answer is `unknown` for the same reason.

A delivery that certainly did not go out and may succeed later
(a refused connection, a 5xx, a 429) raises `DeliveryRetry`, so the outbox row
is retried after its growing delay; after `MAX_DELIVERY_ATTEMPTS` the
delivery is `failed` and the row completes. Nothing personal is ever written
to a log or an error: ids, channels and codes only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from markx.accounts.models import User, UserStatus
from markx.accounts.permissions import SellerCapability, seller_can
from markx.core import ratelimit, settings_store
from markx.core.config import get_config
from markx.core.db import session_scope
from markx.core.errors import RateLimited
from markx.core.ids import uuid7
from markx.notifications import sms, texts
from markx.notifications.models import (
    FINAL_DELIVERY_STATUSES,
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    Outbox,
    SmsMessage,
    SmsPurpose,
    SmsStatus,
)
from markx.notifications.push import (
    RETRYABLE_PUSH_ERRORS,
    PushSender,
    PushSendError,
    PushStatus,
)
from markx.orders.models import SellerOrder
from markx.sellers.models import Seller, SellerMember, SellerStatus

logger = logging.getLogger("markx.notifications.delivery")

# Fewer than the outbox's own eight, so a delivery always ends with its own
# explicit status before the outbox would give the row up.
MAX_DELIVERY_ATTEMPTS = 6

# The rate-limit buckets of notification SMS, never shared with sign-in codes
# (`sms:daily`, D-089), so neither can use up the other's budget.
SMS_BUDGET_BUCKET = "sms:notification:daily"
SMS_PERSON_BUCKET = "sms:notification:user:{user_id}"

RETRYABLE_SMS_ERRORS = frozenset(
    {
        sms.SmsErrorCode.RATE_LIMITED,
        sms.SmsErrorCode.PROVIDER_UNAVAILABLE,
        sms.SmsErrorCode.CONNECTION_FAILED,
    }
)

# The statuses after which a number waits out the notification cooldown.
_SMS_COOLDOWN_STATUSES = tuple(s.value for s in SmsStatus if s is not SmsStatus.FAILED)


class DeliveryRetry(Exception):
    """At least one channel certainly did not go out and should be tried
    again: the outbox retries the row. The text names channels and error
    codes only."""


class Reason:
    """Why a delivery ended as it did. Stable strings, stored and counted."""

    NO_TELEGRAM = "no_telegram_linked"
    TELEGRAM_UNAVAILABLE = "telegram_provider_not_configured"
    SMS_DISABLED = "sms_notifications_disabled"
    TELEGRAM_PREFERRED = "reached_by_telegram"
    SMS_BUDGET = "sms_budget_spent"
    SMS_PERSON_LIMIT = "sms_person_hourly_limit"
    SMS_COOLDOWN = "sms_cooldown"
    INACTIVE = "recipient_inactive"
    NOT_AUTHORIZED = "recipient_not_authorized"
    INTERRUPTED = "interrupted"
    UNSAFE_TEXT = "unsafe_text"
    SEND_ERROR = "send_error"


@dataclass(frozen=True, slots=True)
class Senders:
    """Where outside messages go. Factories, so a provider configured (or
    removed) between two attempts is seen at once."""

    push: Callable[[], PushSender | None]
    sms: Callable[[], sms.SmsSender]


# -- the delivery record, in short transactions of its own -------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _current(notification_id: uuid.UUID, channel: DeliveryChannel) -> NotificationDelivery | None:
    """The delivery as committed now (never the worker's own, older view)."""
    with session_scope() as side:
        row = side.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.channel == channel.value,
            )
        )
        if row is not None:
            side.expunge(row)
        return row


def _write(
    side: Session,
    notification: Notification,
    channel: DeliveryChannel,
    *,
    status: DeliveryStatus,
    reason: str | None = None,
    provider: str | None = None,
    provider_message_id: str | None = None,
    sms_message_id: uuid.UUID | None = None,
    new_attempt: bool = False,
) -> NotificationDelivery:
    """Create or update the one delivery of a notification on a channel, in
    the given session (the caller commits)."""
    now = _now()
    side.execute(
        insert(NotificationDelivery)
        .values(
            id=uuid7(), notification_id=notification.id, channel=channel.value,
            template=notification.template, status=status.value, reason=reason,
            created_at=now, updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["notification_id", "channel"])
    )  # fmt: skip
    row = side.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.notification_id == notification.id,
            NotificationDelivery.channel == channel.value,
        )
        .with_for_update()
    )
    assert row is not None
    row.status = status.value
    row.reason = reason
    if provider is not None:
        row.provider = provider
    if provider_message_id is not None:
        row.provider_message_id = provider_message_id[:128]
    if sms_message_id is not None:
        row.sms_message_id = sms_message_id
    if new_attempt:
        row.attempts += 1
    row.updated_at = now
    row.completed_at = now if status in FINAL_DELIVERY_STATUSES else None
    side.flush()
    return row


def _record(notification: Notification, channel: DeliveryChannel, **values: Any) -> int:
    """`_write` in its own committed transaction. Returns the attempts so far."""
    with session_scope() as side:
        return _write(side, notification, channel, **values).attempts


def _log(
    notification: Notification, channel: DeliveryChannel, status: str, reason: str | None
) -> None:
    logger.info(
        "notification delivery",
        extra={
            "notification_id": str(notification.id),
            "template": notification.template,
            "channel": channel.value,
            "delivery_status": status,
            "reason": reason,
        },
    )


# -- who may receive it ------------------------------------------------------------------


def recipient_may_receive(db: Session, notification: Notification, user: User) -> str | None:
    """Why this person must not get the message outside the app now, or None.

    A seller's order notification (it names `seller_id` and
    `seller_order_id`) goes only to an active member who may handle that
    store's orders, of a store that is not closed, about one of that store's
    own orders: membership can end between the order and the delivery."""
    if user.status != UserStatus.ACTIVE:
        return Reason.INACTIVE
    params: dict[str, Any] = notification.params or {}
    if "seller_id" in params and "seller_order_id" in params:
        try:
            seller_id = uuid.UUID(str(params["seller_id"]))
            seller_order_id = uuid.UUID(str(params["seller_order_id"]))
        except ValueError:
            return Reason.NOT_AUTHORIZED
        found = db.execute(
            select(SellerMember.role, Seller.status)
            .join(Seller, Seller.id == SellerMember.seller_id)
            .join(SellerOrder, SellerOrder.seller_id == Seller.id)
            .where(
                SellerMember.seller_id == seller_id,
                SellerMember.user_id == user.id,
                SellerMember.is_active,
                SellerOrder.id == seller_order_id,
            )
        ).first()
        if found is None:
            return Reason.NOT_AUTHORIZED
        role, store_status = found
        if store_status == SellerStatus.CLOSED or not seller_can(
            role, SellerCapability.HANDLE_ORDERS
        ):
            return Reason.NOT_AUTHORIZED
    return None


# -- Telegram ----------------------------------------------------------------------------


def _telegram(
    db: Session, row: Outbox, notification: Notification, user: User, senders: Senders
) -> None:
    channel = DeliveryChannel.TELEGRAM
    existing = _current(notification.id, channel)
    if existing is not None and existing.status in FINAL_DELIVERY_STATUSES:
        return  # decided on an earlier attempt of this row
    if existing is None:
        if user.telegram_id is None:
            _record(notification, channel, status=DeliveryStatus.SKIPPED, reason=Reason.NO_TELEGRAM)
            return
        refused = recipient_may_receive(db, notification, user)
        if refused is not None:
            _record(notification, channel, status=DeliveryStatus.SKIPPED, reason=refused)
            return
    else:
        # Unlinked, blocked or removed from the store since the last attempt.
        refused = (
            Reason.NO_TELEGRAM
            if user.telegram_id is None
            else recipient_may_receive(db, notification, user)
        )
        if refused is not None:
            _record(notification, channel, status=DeliveryStatus.SKIPPED, reason=refused)
            return
    sender = senders.push()
    if sender is None:
        _record(
            notification, channel, status=DeliveryStatus.UNAVAILABLE,
            reason=Reason.TELEGRAM_UNAVAILABLE,
        )  # fmt: skip
        _log(notification, channel, DeliveryStatus.UNAVAILABLE.value, Reason.TELEGRAM_UNAVAILABLE)
        return
    assert user.telegram_id is not None
    provider = str(getattr(sender, "provider", "unknown"))
    # An earlier attempt left `sending`: it was interrupted and may have gone
    # out. Telegram is at-least-once (D-034), so it is sent again, and the
    # delivery keeps saying so (a possible duplicate) even once accepted.
    interrupted = existing is not None and existing.status == DeliveryStatus.SENDING
    resumed = Reason.INTERRUPTED if interrupted else None
    attempts = _record(
        notification, channel, status=DeliveryStatus.SENDING, reason=resumed,
        provider=provider, new_attempt=True,
    )  # fmt: skip
    try:
        result = sender.send(
            telegram_id=user.telegram_id,
            template=notification.template,
            params=dict(notification.params),
            language=user.language,
            idempotency_key=str(row.id),
        )
    except PushSendError as exc:
        ambiguous = exc.status is PushStatus.UNKNOWN
        if exc.code in RETRYABLE_PUSH_ERRORS and attempts < MAX_DELIVERY_ATTEMPTS:
            _record(notification, channel, status=DeliveryStatus.RETRYING, reason=exc.code.value)
            raise DeliveryRetry(f"telegram:{exc.code.value}") from exc
        final = DeliveryStatus.UNKNOWN if ambiguous else DeliveryStatus.FAILED
        _record(notification, channel, status=final, reason=exc.code.value)
        _log(notification, channel, final.value, exc.code.value)
        return
    except Exception as exc:
        # An adapter bug or an unexpected error: it may or may not have gone
        # out. Sent again, as any Telegram attempt that was interrupted.
        logger.warning(
            "the push adapter raised",
            extra={"notification_id": str(notification.id), "error": type(exc).__name__},
        )
        if attempts < MAX_DELIVERY_ATTEMPTS:
            _record(notification, channel, status=DeliveryStatus.RETRYING, reason=Reason.SEND_ERROR)
            raise DeliveryRetry(f"telegram:{Reason.SEND_ERROR}") from exc
        _record(notification, channel, status=DeliveryStatus.UNKNOWN, reason=Reason.SEND_ERROR)
        _log(notification, channel, DeliveryStatus.UNKNOWN.value, Reason.SEND_ERROR)
        return
    with session_scope() as side:
        _write(
            side, notification, channel, status=DeliveryStatus.ACCEPTED, reason=resumed,
            provider_message_id=result.provider_message_id if result else None,
        )  # fmt: skip
        # The delivery record D-034 introduced, kept for what reads it: the
        # notification as pushed, in the same commit as the outcome.
        side.add(
            Notification(
                user_id=user.id, channel="telegram",
                template=notification.template, params=notification.params,
            )
        )  # fmt: skip


# -- SMS ---------------------------------------------------------------------------------


def _sms_gate(
    db: Session, side: Session, notification: Notification, user: User, senders: Senders
) -> str | None:
    """Why this order alert is not sent by SMS now (first attempt only), or
    None. Runs under the number's advisory lock, in `side`."""
    # Telegram carries it, unless the person has none or no push provider exists.
    if (
        user.telegram_id is not None
        and settings_store.get_bool(db, "notifications.sms_only_without_telegram")
        and senders.push() is not None
    ):
        return Reason.TELEGRAM_PREFERRED
    refused = recipient_may_receive(db, notification, user)
    if refused is not None:
        return refused
    cooldown = settings_store.get_int(db, "notifications.sms_cooldown_seconds")
    now = _now()
    if cooldown > 0:
        recent = side.scalar(
            select(func.count())
            .select_from(SmsMessage)
            .where(
                SmsMessage.phone_ref == sms.phone_reference(user.phone),
                SmsMessage.purpose == SmsPurpose.NOTIFICATION.value,
                SmsMessage.status.in_(_SMS_COOLDOWN_STATUSES),
                SmsMessage.created_at > now - timedelta(seconds=cooldown),
            )
        )
        if recent:
            return Reason.SMS_COOLDOWN
    # The person's hourly limit first, so one busy seller cannot spend the
    # day's budget; each counts in its own transaction (ratelimit.hit).
    try:
        ratelimit.hit(
            SMS_PERSON_BUCKET.format(user_id=user.id),
            settings_store.get_int(db, "notifications.sms_per_person_per_hour"),
            timedelta(hours=1),
        )
    except RateLimited:
        return Reason.SMS_PERSON_LIMIT
    try:
        ratelimit.hit(
            SMS_BUDGET_BUCKET,
            settings_store.get_int(db, "notifications.sms_daily_budget"),
            timedelta(days=1),
        )
    except RateLimited:
        logger.error("the daily notification SMS budget is spent; notification SMS stopped")
        return Reason.SMS_BUDGET
    return None


def _sms(
    db: Session, row: Outbox, notification: Notification, user: User, senders: Senders
) -> None:
    if not texts.has_text(notification.template):
        return  # not an order alert: SMS is never considered, nothing to record
    channel = DeliveryChannel.SMS
    existing = _current(notification.id, channel)
    if existing is not None and existing.status in FINAL_DELIVERY_STATUSES:
        return
    if existing is not None and existing.status == DeliveryStatus.SENDING:
        # Interrupted between "about to send" and "outcome stored": it may
        # have gone out. Never sent twice (at-most-once for SMS, D-092).
        _record(notification, channel, status=DeliveryStatus.UNKNOWN, reason=Reason.INTERRUPTED)
        _log(notification, channel, DeliveryStatus.UNKNOWN.value, Reason.INTERRUPTED)
        return
    if not get_config().sms_on or not settings_store.get_bool(db, "notifications.sms_enabled"):
        # SMS switched off for the whole server (D-101), or for notifications.
        _record(notification, channel, status=DeliveryStatus.SKIPPED, reason=Reason.SMS_DISABLED)
        return
    if existing is not None and recipient_may_receive(db, notification, user) is not None:
        _record(notification, channel, status=DeliveryStatus.SKIPPED, reason=Reason.NOT_AUTHORIZED)
        return
    try:
        words = texts.render(notification.template, notification.params, user.language)
    except texts.UnsafeText:
        _record(notification, channel, status=DeliveryStatus.FAILED, reason=Reason.UNSAFE_TEXT)
        _log(notification, channel, DeliveryStatus.FAILED.value, Reason.UNSAFE_TEXT)
        return
    sender = senders.sms()
    with session_scope() as side:
        # Two notifications for one number at once wait for each other here,
        # so the cooldown sees the first before the second is decided.
        side.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"notification-sms:{sms.phone_reference(user.phone).hex()}"},
        )
        if existing is None:
            refused = _sms_gate(db, side, notification, user, senders)
            if refused is not None:
                _write(side, notification, channel, status=DeliveryStatus.SKIPPED, reason=refused)
                _log(notification, channel, DeliveryStatus.SKIPPED.value, refused)
                return
        record = sms.record_message(
            side,
            purpose=SmsPurpose.NOTIFICATION,
            phone=user.phone,
            text=words,
            provider=sender.provider,
            now=_now(),
            notification_id=notification.id,
        )
        side.flush()
        attempts = _write(
            side, notification, channel, status=DeliveryStatus.SENDING,
            provider=sender.provider, sms_message_id=record.id, new_attempt=True,
        ).attempts  # fmt: skip
    # Committed: the record says `pending` and the delivery `sending` before
    # the provider hears anything.
    with session_scope() as side:
        record = side.get(SmsMessage, record.id) or record
        try:
            result = sms.send_recorded(side, record, sender, phone=user.phone, text=words)
        except sms.SmsSendError as exc:
            if exc.status is SmsStatus.UNKNOWN:
                _write(side, notification, channel, status=DeliveryStatus.UNKNOWN,
                       reason=exc.code.value)  # fmt: skip
                _log(notification, channel, DeliveryStatus.UNKNOWN.value, exc.code.value)
                return
            if exc.code in RETRYABLE_SMS_ERRORS and attempts < MAX_DELIVERY_ATTEMPTS:
                _write(side, notification, channel, status=DeliveryStatus.RETRYING,
                       reason=exc.code.value)  # fmt: skip
                side.commit()
                raise DeliveryRetry(f"sms:{exc.code.value}") from exc
            _write(side, notification, channel, status=DeliveryStatus.FAILED, reason=exc.code.value)
            _log(notification, channel, DeliveryStatus.FAILED.value, exc.code.value)
            return
        _write(
            side, notification, channel, status=DeliveryStatus.ACCEPTED,
            provider_message_id=result.provider_message_id,
        )  # fmt: skip


# -- the outbox handler ------------------------------------------------------------------


def deliver(db: Session, row: Outbox, senders: Senders) -> None:
    """Carry one notification to every outside channel it is due on. Raises
    DeliveryRetry when a channel should be tried again; channels already
    decided are never tried twice."""
    payload: dict[str, Any] = row.payload
    notification = db.get(Notification, uuid.UUID(str(payload["notification_id"])))
    if notification is None:
        return  # the person's account, and its notifications, were deleted
    user = db.get(User, notification.user_id)
    if user is None:
        return
    retry: list[str] = []
    for channel in (_telegram, _sms):
        try:
            channel(db, row, notification, user, senders)
        except DeliveryRetry as exc:
            retry.append(str(exc))
    if retry:
        raise DeliveryRetry(", ".join(retry))
