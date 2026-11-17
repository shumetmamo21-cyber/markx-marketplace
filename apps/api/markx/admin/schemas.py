from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from markx.accounts.models import StaffRole


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: str
    before: Any | None
    after: Any | None
    request_id: str | None


class SettingOut(BaseModel):
    key: str
    kind: str
    description: str
    default: bool | int | str
    value: bool | int | str
    is_overridden: bool
    may_change: bool


class SettingIn(BaseModel):
    value: bool | int | str


class StaffAccountOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str | None
    phone_last4: str
    role: str
    is_active: bool
    locked_until: datetime | None
    created_at: datetime


class StaffCreateIn(BaseModel):
    phone: str = Field(min_length=9, max_length=24)
    name: str = Field(min_length=2, max_length=100)
    role: StaffRole
    password: str = Field(min_length=12, max_length=200)


class NewStaffOut(BaseModel):
    """The authenticator secret is shown here once and never again: the new
    member scans `provisioning_uri` into their authenticator app."""

    staff: StaffAccountOut
    totp_secret: str
    provisioning_uri: str


class StaffRoleIn(BaseModel):
    role: StaffRole


class StaffActiveIn(BaseModel):
    active: bool
    reason: str = Field(min_length=3, max_length=500)


class DispatchRowOut(BaseModel):
    seller_order_id: uuid.UUID
    order_code: str
    store_slug: str
    zone_code: str
    mode: str
    status: str
    waiting_since: datetime
    promised_by: datetime | None
    late: bool


class FunnelOut(BaseModel):
    searches: int
    zero_result_searches: int
    carts_filled: int
    orders: int


class BusinessDashboardOut(BaseModel):
    """AD-14. Money in santim; shares between 0 and 1, or null with nothing
    to divide."""

    days: int
    from_time: datetime
    to_time: datetime
    orders: int
    seller_orders: int
    seller_orders_by_status: dict[str, int]
    completed_value_santim: int
    fees_santim: int
    median_minutes_to_confirm: float | None
    answered_share: float | None
    delivery_success_share: float | None
    problems_opened: int
    problems_open: int
    live_offers: int
    products_with_offers: int
    offers_per_product: float | None
    fresh_price_share: float | None
    funnel: FunnelOut
