from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel

ZoneCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
# The most a delivery could plausibly cost: ETB 100,000.
FeeSantim = Annotated[int, Field(ge=0, le=10_000_000)]


class ZoneIn(ApiModel):
    code: ZoneCode
    name_am: Name
    name_en: Name
    position: int = Field(default=0, ge=0, le=10_000)


class ZoneUpdateIn(ApiModel):
    name_am: Name | None = None
    name_en: Name | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


class AreaIn(ApiModel):
    name_am: Name
    name_en: Name
    position: int = Field(default=0, ge=0, le=10_000)


class AreaActiveIn(ApiModel):
    is_active: bool


class RateIn(ApiModel):
    method: Literal["seller_rider", "partner_courier"]
    fee_santim: FeeSantim
    promised_hours: int = Field(ge=1, le=720)
    is_active: bool = True


class AreaOut(ApiModel):
    id: uuid.UUID
    zone_id: uuid.UUID
    name_am: str
    name_en: str
    is_active: bool


class RateOut(ApiModel):
    id: uuid.UUID
    method: str
    fee_santim: int
    promised_hours: int
    is_active: bool


class ZoneOut(ApiModel):
    id: uuid.UUID
    code: str
    name_am: str
    name_en: str
    position: int
    is_active: bool
    areas: list[AreaOut]
    rates: list[RateOut]
