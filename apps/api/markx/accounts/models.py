from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check

LANGUAGES = ("am", "en")
PHONE_PATTERN = r"^\+251[79][0-9]{8}$"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETED = "deleted"


class StaffRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    OPERATIONS = "operations"
    SUPPORT = "support"
    CATALOGUE = "catalogue"
    FINANCE = "finance"


class SessionKind(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"


class User(UUIDPrimaryKey, Timestamps, Base):
    """One row per person, keyed on the phone number (blueprint C.1)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"phone ~ '{PHONE_PATTERN}'", name="phone_international_format"),
        in_check("language", LANGUAGES),
        in_check("status", UserStatus),
        CheckConstraint(
            "buyer_reliability is null or buyer_reliability between 0 and 100",
            name="buyer_reliability_range",
        ),
        CheckConstraint(
            "(telegram_id is null) = (telegram_linked_at is null)",
            name="telegram_linked_at_with_telegram_id",
        ),
    )

    phone: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # The person's Telegram account, set only once they proved they control
    # it (D-093): a signed Mini App start-up or the bot's one-time link.
    # Unique, so one Telegram account belongs to one MarkX account.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the person last disconnected Telegram, so their settings can say so.
    telegram_unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    name: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="am")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    buyer_reliability: Mapped[int | None] = mapped_column(SmallInteger)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OtpChallenge(UUIDPrimaryKey, CreatedAt, Base):
    """A login code. Only a keyed hash is stored; rows are purged after 24 hours."""

    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint(f"phone ~ '{PHONE_PATTERN}'", name="phone_international_format"),
        in_check("channel", ("sms", "telegram")),
        CheckConstraint("attempts between 0 and 5", name="attempts_range"),
        Index("ix_otp_challenges_phone_created", "phone", "created_at"),
    )

    phone: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="sms")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)


class OtpLock(Base):
    """A phone number locked after five wrong codes (blueprint D.2)."""

    __tablename__ = "otp_locks"

    phone: Mapped[str] = mapped_column(Text, primary_key=True)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Session(UUIDPrimaryKey, CreatedAt, Base):
    """A signed-in session. Only the token's hash is stored (blueprint F.4)."""

    __tablename__ = "sessions"
    __table_args__ = (
        in_check("kind", SessionKind),
        in_check("transport", ("cookie", "header")),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        Index("ix_sessions_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="customer")
    transport: Mapped[str] = mapped_column(Text, nullable=False, server_default="cookie")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)


class StaffMember(UUIDPrimaryKey, Timestamps, Base):
    """MarkX staff. Signs in with a password and an authenticator app (blueprint C.5)."""

    __tablename__ = "staff_members"
    __table_args__ = (
        in_check("role", StaffRole),
        CheckConstraint("failed_logins >= 0", name="failed_logins_non_negative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # The last accepted time step, so one authenticator code cannot be replayed.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Address(UUIDPrimaryKey, Timestamps, Base):
    """A buyer's delivery address, built around a landmark (blueprint D.10).

    Each order keeps its own snapshot, so editing or archiving an address never
    changes where a past order went.
    """

    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint(f"phone ~ '{PHONE_PATTERN}'", name="phone_international_format"),
        CheckConstraint(
            f"phone2 is null or phone2 ~ '{PHONE_PATTERN}'", name="phone2_international_format"
        ),
        CheckConstraint("length(btrim(landmark)) > 0", name="landmark_present"),
        CheckConstraint("(latitude is null) = (longitude is null)", name="map_pin_complete"),
        CheckConstraint(
            "latitude is null or (latitude between -90 and 90 and longitude between -180 and 180)",
            name="map_pin_in_range",
        ),
        Index("ix_addresses_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    phone2: Mapped[str | None] = mapped_column(Text)
    delivery_area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_areas.id", ondelete="RESTRICT"), nullable=False
    )
    landmark: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    driver_notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataRequest(UUIDPrimaryKey, CreatedAt, Base):
    """A person's request to see, correct or delete their data (requirement C-28)."""

    __tablename__ = "data_requests"
    __table_args__ = (
        in_check("kind", ("export", "correct", "delete")),
        in_check("status", ("open", "done", "refused")),
        Index("ix_data_requests_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramLinkStatus(StrEnum):
    PENDING = "pending"  # waiting for the bot to see it; expired once expires_at passes
    CONSUMED = "consumed"  # used: the Telegram account was linked
    FAILED = "failed"  # used, but the link was refused (failure_reason says why)
    REVOKED = "revoked"  # replaced by a newer link, cancelled or disconnected


class TelegramLinkFailure(StrEnum):
    TELEGRAM_IN_USE = "telegram_in_use"  # linked to another MarkX account
    ALREADY_CONNECTED = "already_connected"  # this account linked another meanwhile
    ACCOUNT_INACTIVE = "account_inactive"  # blocked or deleted since
    SESSION_ENDED = "session_ended"  # the sign-in that asked for it has ended


class TelegramLinkToken(UUIDPrimaryKey, CreatedAt, Base):
    """A one-time link that connects a person's Telegram (D-093).

    Only a keyed hash of the token is stored: the token itself exists only
    in the link the person opens. It belongs to the account and the sign-in
    session that asked for it, lives `telegram_link_ttl_minutes`, and is
    used at most once. At most one link per account is pending.
    """

    __tablename__ = "telegram_link_tokens"
    __table_args__ = (
        in_check("status", TelegramLinkStatus),
        CheckConstraint(
            "failure_reason is null or failure_reason in "
            "('telegram_in_use', 'already_connected', 'account_inactive', 'session_ended')",
            name="failure_reason_allowed",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint(
            "(status = 'pending') = (finished_at is null)", name="finished_unless_pending"
        ),
        CheckConstraint(
            "(status = 'failed') = (failure_reason is not null)", name="failure_has_a_reason"
        ),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        Index(
            "uq_telegram_link_tokens_one_pending_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_telegram_link_tokens_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class TelegramUpdate(Base):
    """A Telegram webhook update already handled (D-093), so a repeated
    delivery of the same update does nothing. Only Telegram's update id and
    the time: never the message, the sender or the chat."""

    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
