from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey, in_check


class Outbox(UUIDPrimaryKey, CreatedAt, Base):
    """Work to do after a transaction commits (blueprint D.16, F.8).

    A row is written in the same transaction as the change that caused it, so
    work from a rolled-back transaction never exists. The worker claims rows
    with FOR UPDATE SKIP LOCKED; this table is the job queue.
    """

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'done', 'failed')", name="status_allowed"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_outbox_due", "run_after", postgresql_where=text("status = 'pending'")),
    )

    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Notification(UUIDPrimaryKey, CreatedAt, Base):
    """The in-app list and the delivery record for every channel (blueprint G.2)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel in ('in_app', 'telegram', 'sms')", name="channel_allowed"),
        CheckConstraint("status in ('sent', 'failed', 'read')", name="status_allowed"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="sent")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SmsStatus(StrEnum):
    """A delivery record's status. `pending`: written, the provider has not
    answered yet. `accepted`: the provider took the message. `failed`: it
    was not sent. `unknown`: the provider may or may not have taken it (a
    timeout, an unreadable answer). `delivered` and `undelivered` come from
    delivery reports, which do not exist yet (no webhook, D-089)."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"


class SmsPurpose(StrEnum):
    LOGIN_CODE = "login_code"
    NOTIFICATION = "notification"


class SmsMessage(UUIDPrimaryKey, Base):
    """The delivery record of one SMS (D-089). It never holds the message
    text, a login code or the whole phone number: `phone_ref` is a keyed
    hash of the number under the server secret (`sms.phone_reference`).

    A login code's record names its challenge, a notification's its
    notification. They are plain references, not foreign keys, so a record
    never stands in the way of removing a challenge or a notification.
    """

    __tablename__ = "sms_messages"
    __table_args__ = (
        in_check("purpose", SmsPurpose),
        in_check("status", SmsStatus),
        CheckConstraint("octet_length(phone_ref) = 32", name="phone_ref_is_a_keyed_hash"),
        CheckConstraint(
            "(purpose = 'login_code' and otp_challenge_id is not null and notification_id is null)"
            " or (purpose = 'notification' and notification_id is not null"
            " and otp_challenge_id is null)",
            name="reference_matches_purpose",
        ),
        CheckConstraint("segments between 1 and 255", name="segments_range"),
        CheckConstraint(
            "status not in ('failed', 'unknown', 'undelivered') or error_code is not null",
            name="failure_has_an_error_code",
        ),
        CheckConstraint(
            "provider_message_id is null or length(provider_message_id) between 1 and 128",
            name="provider_message_id_length",
        ),
        CheckConstraint("error_code is null or length(error_code) <= 64", name="error_code_length"),
        Index("ix_sms_messages_phone_ref_created", "phone_ref", "created_at"),
        Index("ix_sms_messages_created", "created_at"),
        Index(
            "ix_sms_messages_unfinished",
            "created_at",
            postgresql_where=text("status in ('pending', 'unknown')"),
        ),
    )

    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    phone_ref: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    otp_challenge_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    error_code: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # When the provider answered, or the attempt otherwise ended.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # From a delivery report, once one exists.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
