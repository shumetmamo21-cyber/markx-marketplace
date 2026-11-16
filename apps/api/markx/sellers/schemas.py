from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel, LongText, PhoneText, ShortText

StoreSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", min_length=3, max_length=60)]  # fmt: skip
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
TinText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20)]
LicenceText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
AreaName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


# -- seller side -----------------------------------------------------------------


class ApplicationIn(ApiModel):
    kind: Literal["business", "individual"] = "business"
    legal_name: ShortText
    trade_name: ShortText
    tin: TinText | None = None
    licence_number: LicenceText | None = None
    contact_phone: PhoneText
    shop_address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]  # fmt: skip
    shop_latitude: Latitude | None = None
    shop_longitude: Longitude | None = None
    store_slug: StoreSlug | None = None


class LegalUpdateIn(ApiModel):
    legal_name: ShortText | None = None
    trade_name: ShortText | None = None
    tin: TinText | None = None
    licence_number: LicenceText | None = None
    contact_phone: PhoneText | None = None
    shop_address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)] | None = None  # fmt: skip
    shop_latitude: Latitude | None = None
    shop_longitude: Longitude | None = None


class EligibilityOut(ApiModel):
    invite_only: bool
    invited: bool
    may_apply: bool
    individual_enabled: bool


class StoreBriefOut(ApiModel):
    slug: str
    name: str


class SellerOut(ApiModel):
    """What any member of the seller sees. Legal details are separate."""

    id: uuid.UUID
    kind: str
    trade_name: str
    status: str
    review_state: str
    review_note: str | None
    verification_level: int
    checks: dict[str, bool]
    plan: str
    submitted_at: datetime | None
    recheck_due_on: date | None
    store: StoreBriefOut
    role: str
    capabilities: list[str]
    # What is still needed before the application can be submitted.
    missing: list[str]


class LegalOut(ApiModel):
    legal_name: str
    trade_name: str
    tin: str | None
    licence_number: str | None
    contact_phone: str
    shop_address: str
    shop_latitude: float | None
    shop_longitude: float | None


class DocumentOut(ApiModel):
    id: uuid.UUID
    doc_type: str
    content_type: str
    size_bytes: int
    review_status: str
    review_note: str | None
    expires_on: date | None
    created_at: datetime


class DocumentLinkOut(ApiModel):
    url: str
    expires_at: datetime


class PayoutAccountIn(ApiModel):
    kind: Literal["bank", "wallet"]
    provider_name: ShortText
    account_name: ShortText
    account_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=40)]  # fmt: skip


class PayoutAccountOut(ApiModel):
    """The account number itself is never sent back."""

    id: uuid.UUID
    kind: str
    provider_name: str
    account_name: str
    account_last4: str
    status: str
    effective_from: datetime


class StoreUpdateIn(ApiModel):
    name: ShortText | None = None
    slug: StoreSlug | None = None
    description: LongText | None = None
    return_policy: LongText | None = None
    working_hours: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None  # fmt: skip
    areas_served: Annotated[list[AreaName], Field(max_length=50)] | None = None
    telegram_channel: Annotated[str, StringConstraints(pattern=r"^(@[A-Za-z0-9_]{5,32})?$")] | None = None  # fmt: skip


class StoreOut(ApiModel):
    slug: str
    name: str
    description: str
    return_policy: str
    working_hours: str
    areas_served: list[str]
    telegram_channel: str | None


class MemberIn(ApiModel):
    phone: PhoneText
    role: Literal["manager", "catalogue", "orders", "finance"] = "manager"


class MemberOut(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str | None
    phone: str
    role: str
    created_at: datetime


# -- public ----------------------------------------------------------------------


class PublicStoreOut(ApiModel):
    """The store page (S-03). No phone number: buyer and seller see each
    other's number only after the seller confirms an order (blueprint C.5)."""

    slug: str
    name: str
    description: str
    return_policy: str
    working_hours: str
    areas_served: list[str]
    telegram_channel: str | None
    seller_kind: str
    shop_address: str
    shop_latitude: float | None
    shop_longitude: float | None
    verification_level: int
    checks: dict[str, bool]
    member_since: datetime
    completed_orders: int


# -- staff -----------------------------------------------------------------------


class InvitationIn(ApiModel):
    phone: PhoneText
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class InvitationOut(ApiModel):
    id: uuid.UUID
    phone: str
    note: str | None
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    used_by_seller_id: uuid.UUID | None
    revoked_at: datetime | None


class SellerListItemOut(ApiModel):
    id: uuid.UUID
    kind: str
    trade_name: str
    legal_name: str
    status: str
    review_state: str
    verification_level: int
    submitted_at: datetime | None
    recheck_due_on: date | None
    store_slug: str | None


class SellerAdminOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    review_state: str
    review_note: str | None
    verification_level: int
    checks: dict[str, bool]
    plan: str
    created_at: datetime
    submitted_at: datetime | None
    reviewed_at: datetime | None
    verified_at: datetime | None
    shop_visited_at: datetime | None
    recheck_due_on: date | None
    legal: LegalOut
    store: StoreOut
    members: list[MemberOut]
    documents: list[DocumentOut]
    payout_accounts: list[PayoutAccountOut]


class DocumentReviewIn(ApiModel):
    decision: Literal["accepted", "rejected"]
    note: Reason | None = None


class ReasonIn(ApiModel):
    reason: Reason


class ApproveIn(ApiModel):
    verification_level: Literal[1, 2]
    # The reviewer's checklist (AD-01). Level 2 needs a visited shop (C.6).
    shop_visited: bool = False
    payout_account_name_matches: bool


class VerificationLevelIn(ApiModel):
    level: Annotated[int, Field(ge=0, le=3)]
    reason: Reason
    shop_visited: bool = False
