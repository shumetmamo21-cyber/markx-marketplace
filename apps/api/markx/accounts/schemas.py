from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel, Language, LongText, PhoneText, ShortText

OtpCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]


class OtpRequestIn(ApiModel):
    phone: PhoneText
    language: Language = "am"
    bot_token: str | None = Field(default=None, max_length=4096)


class OtpRequestOut(ApiModel):
    phone_masked: str
    expires_in_seconds: int


class OtpVerifyIn(ApiModel):
    phone: PhoneText
    code: OtpCode
    language: Language = "am"


class StaffSignInIn(ApiModel):
    phone: PhoneText
    password: str = Field(min_length=1, max_length=256)
    totp_code: OtpCode


class TelegramSignInIn(ApiModel):
    init_data: str = Field(min_length=1, max_length=8192)


class StaffStepUpIn(ApiModel):
    """The staff step on top of a Telegram sign-in (D-101): no phone number,
    which comes from the signed-in account."""

    password: str = Field(min_length=1, max_length=256)
    totp_code: OtpCode


class SignInMethodsOut(ApiModel):
    """Which ways of signing in this server offers (D-101, decision SI-1)."""

    telegram: bool = Field(description="Signing in with Telegram is set up and switched on.")
    sms: bool = Field(description="Signing in with an SMS code is switched on (a backup).")
    staff_phone_password: bool = Field(
        description="Staff may sign in with phone, password and code without Telegram. "
        "False while SMS is switched off: staff sign in with Telegram, then add their step."
    )


class TelegramWebSignInIn(ApiModel):
    language: Language = "am"


class TelegramWebSignInOut(ApiModel):
    """A new website sign-in with Telegram (D-101). The browser's private
    secret travels in an HttpOnly cookie, never in this body."""

    link: str = Field(description="The one-time t.me link to open in Telegram.")
    expires_at: datetime


class TelegramWebSignInStateOut(ApiModel):
    """Where this browser's Telegram sign-in stands (D-101)."""

    state: Literal["none", "waiting", "waiting_for_phone", "signed_in", "expired", "refused"]
    expires_at: datetime | None = None
    reason: (
        Literal[
            "phone_not_ethiopian", "phone_on_other_telegram", "phone_in_use", "account_inactive"
        ]
        | None
    ) = Field(default=None, description="Why it was refused, in the person's own terms.")
    me: MeOut | None = Field(default=None, description="The signed-in account, once signed in.")
    is_new_account: bool = False


class TelegramConnectionOut(ApiModel):
    """The signed-in person's own Telegram connection (D-093). Never the
    Telegram id or username; `link` only in the answer that created it."""

    available: bool = Field(description="Connecting Telegram is switched on and set up.")
    telegram_messages_on: bool = Field(
        description="A provider carries MarkX messages to Telegram. False: none are sent there."
    )
    state: Literal["not_connected", "pending", "connected", "expired", "failed", "disconnected"]
    connected_at: datetime | None = None
    expires_at: datetime | None = Field(
        default=None, description="When the pending link stops working."
    )
    link: str | None = Field(
        default=None,
        description="The one-time t.me link to open in Telegram. Returned once, never stored.",
    )


class SellerMembershipOut(ApiModel):
    seller_id: uuid.UUID
    role: str
    capabilities: list[str]
    trade_name: str
    status: str
    review_state: str
    verification_level: int
    store_slug: str | None


class StaffOut(ApiModel):
    role: str
    capabilities: list[str]


class MeOut(ApiModel):
    id: uuid.UUID
    phone: str
    name: str | None
    language: str
    session_kind: str
    csrf_token: str
    staff: StaffOut | None
    sellers: list[SellerMembershipOut]
    unread_notifications: int


class SessionOut(ApiModel):
    me: MeOut
    is_new_account: bool = False
    # Only returned to header-transport clients (the Telegram Mini App).
    session_token: str | None = None


class ProfileIn(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    language: Language | None = None


class AddressIn(ApiModel):
    recipient_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)
    ]
    phone: PhoneText
    phone2: PhoneText | None = None
    delivery_area_id: uuid.UUID
    landmark: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    driver_notes: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None
    ) = None


class AddressOut(ApiModel):
    id: uuid.UUID
    recipient_name: str
    phone: str
    phone2: str | None
    delivery_area_id: uuid.UUID
    area_name_am: str
    area_name_en: str
    zone_id: uuid.UUID
    landmark: str
    latitude: float | None
    longitude: float | None
    driver_notes: str | None
    # The gate photo (C-08; D-107): a five-minute link for the buyer only;
    # null without a photo.
    gate_photo_url: str | None = None


class DataRequestIn(ApiModel):
    kind: Literal["export", "correct", "delete"]
    note: LongText | None = None


class DataRequestOut(ApiModel):
    id: uuid.UUID
    kind: str
    note: str | None
    status: str
    created_at: datetime


class NotificationOut(ApiModel):
    id: uuid.UUID
    template: str
    params: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class DevSmsOut(ApiModel):
    phone: str
    text: str
    sent_at: str


__all__ = ["ShortText"]
