from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from markx.accounts.deps import Principal, require_staff
from markx.accounts.permissions import StaffCapability
from markx.core.http import Db
from markx.delivery import selectors, service
from markx.delivery.models import DeliveryMode
from markx.delivery.schemas import (
    AreaActiveIn,
    AreaIn,
    AreaOut,
    RateIn,
    RateOut,
    ZoneIn,
    ZoneOut,
    ZoneUpdateIn,
)

router = APIRouter(prefix="/delivery", tags=["delivery"])
admin_router = APIRouter(prefix="/admin/delivery", tags=["admin: delivery"])

# Blueprint C.4: only the super administrator and operations change zones and rates.
DeliveryStaff = Annotated[
    Principal, Depends(require_staff(StaffCapability.CHANGE_DELIVERY_AND_RISK))
]


def _zone_out(view: selectors.ZoneView) -> ZoneOut:
    return ZoneOut(
        id=view.zone.id,
        code=view.zone.code,
        name_am=view.zone.name_am,
        name_en=view.zone.name_en,
        position=view.zone.position,
        is_active=view.zone.is_active,
        areas=[AreaOut.model_validate(a) for a in view.areas],
        rates=[RateOut.model_validate(r) for r in view.rates],
    )


@router.get("/zones", response_model=list[ZoneOut])
def list_public_zones(db: Db, response: Response) -> list[ZoneOut]:
    """Active zones with their neighbourhoods and fees, for the address picker.
    Fees are shown before checkout (blueprint D.13)."""
    # Public reference data: safe for the edge to cache briefly (blueprint F.1).
    response.headers["Cache-Control"] = "public, max-age=60"
    return [_zone_out(v) for v in selectors.list_zones(db, active_only=True)]


@admin_router.get("/zones", response_model=list[ZoneOut])
def list_all_zones(_: DeliveryStaff, db: Db) -> list[ZoneOut]:
    return [_zone_out(v) for v in selectors.list_zones(db, active_only=False)]


def _one_zone(db: Db, zone_id: uuid.UUID) -> ZoneOut:
    view = next(v for v in selectors.list_zones(db, active_only=False) if v.zone.id == zone_id)
    return _zone_out(view)


@admin_router.post("/zones", response_model=ZoneOut, status_code=201)
def create_zone(body: ZoneIn, staff: DeliveryStaff, request: Request, db: Db) -> ZoneOut:
    zone = service.create_zone(
        db, staff.actor(request), code=body.code, name_am=body.name_am,
        name_en=body.name_en, position=body.position,
    )  # fmt: skip
    return _one_zone(db, zone.id)


@admin_router.patch("/zones/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: uuid.UUID, body: ZoneUpdateIn, staff: DeliveryStaff, request: Request, db: Db
) -> ZoneOut:
    service.update_zone(
        db, staff.actor(request), zone_id, name_am=body.name_am, name_en=body.name_en,
        position=body.position, is_active=body.is_active,
    )  # fmt: skip
    return _one_zone(db, zone_id)


@admin_router.post("/zones/{zone_id}/areas", response_model=AreaOut, status_code=201)
def create_area(
    zone_id: uuid.UUID, body: AreaIn, staff: DeliveryStaff, request: Request, db: Db
) -> AreaOut:
    area = service.create_area(
        db, staff.actor(request), zone_id, name_am=body.name_am, name_en=body.name_en,
        position=body.position,
    )  # fmt: skip
    return AreaOut.model_validate(area)


@admin_router.patch("/areas/{area_id}", response_model=AreaOut)
def set_area_active(
    area_id: uuid.UUID, body: AreaActiveIn, staff: DeliveryStaff, request: Request, db: Db
) -> AreaOut:
    area = service.set_area_active(db, staff.actor(request), area_id, is_active=body.is_active)
    return AreaOut.model_validate(area)


@admin_router.put("/zones/{zone_id}/rates", response_model=RateOut)
def set_rate(
    zone_id: uuid.UUID, body: RateIn, staff: DeliveryStaff, request: Request, db: Db
) -> RateOut:
    rate = service.set_rate(
        db, staff.actor(request), zone_id, method=DeliveryMode(body.method),
        fee_santim=body.fee_santim, promised_hours=body.promised_hours, is_active=body.is_active,
    )  # fmt: skip
    return RateOut.model_validate(rate)
