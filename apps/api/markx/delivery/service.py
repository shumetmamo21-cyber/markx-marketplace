"""Delivery zones, neighbourhoods and flat fees (blueprint D.13, AD-05).

Zones and their fees are data that operations staff manage. Every change is
written to the audit log with before and after values.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.core.errors import Conflict, NotFound
from markx.delivery.models import DeliveryArea, DeliveryMode, DeliveryRate, DeliveryZone


def _zone_snapshot(zone: DeliveryZone) -> dict[str, Any]:
    return {
        "code": zone.code,
        "name_am": zone.name_am,
        "name_en": zone.name_en,
        "position": zone.position,
        "is_active": zone.is_active,
    }


def get_zone(db: Session, zone_id: uuid.UUID) -> DeliveryZone:
    zone = db.get(DeliveryZone, zone_id)
    if zone is None:
        raise NotFound("zone_not_found", "That delivery zone was not found.")
    return zone


def create_zone(
    db: Session, actor: Actor, *, code: str, name_am: str, name_en: str, position: int = 0
) -> DeliveryZone:
    zone = DeliveryZone(code=code, name_am=name_am, name_en=name_en, position=position)
    db.add(zone)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("zone_code_taken", "A zone with that code already exists.") from exc
    record_by(
        db, actor, "delivery_zone.create", "delivery_zone", zone.id, after=_zone_snapshot(zone)
    )
    return zone


def update_zone(
    db: Session,
    actor: Actor,
    zone_id: uuid.UUID,
    *,
    name_am: str | None = None,
    name_en: str | None = None,
    position: int | None = None,
    is_active: bool | None = None,
) -> DeliveryZone:
    zone = get_zone(db, zone_id)
    before = _zone_snapshot(zone)
    if name_am is not None:
        zone.name_am = name_am
    if name_en is not None:
        zone.name_en = name_en
    if position is not None:
        zone.position = position
    if is_active is not None:
        zone.is_active = is_active
    db.flush()
    record_by(
        db, actor, "delivery_zone.update", "delivery_zone", zone.id,
        before=before, after=_zone_snapshot(zone),
    )  # fmt: skip
    return zone


def create_area(
    db: Session, actor: Actor, zone_id: uuid.UUID, *, name_am: str, name_en: str, position: int = 0
) -> DeliveryArea:
    zone = get_zone(db, zone_id)
    area = DeliveryArea(zone_id=zone.id, name_am=name_am, name_en=name_en, position=position)
    db.add(area)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("area_exists", "That area is already in this zone.") from exc
    record_by(
        db, actor, "delivery_area.create", "delivery_area", area.id,
        after={"zone_id": str(zone.id), "name_am": name_am, "name_en": name_en},
    )  # fmt: skip
    return area


def set_area_active(
    db: Session, actor: Actor, area_id: uuid.UUID, *, is_active: bool
) -> DeliveryArea:
    area = db.get(DeliveryArea, area_id)
    if area is None:
        raise NotFound("area_not_found", "That area was not found.")
    before = {"is_active": area.is_active}
    area.is_active = is_active
    db.flush()
    record_by(
        db, actor, "delivery_area.update", "delivery_area", area.id,
        before=before, after={"is_active": is_active},
    )  # fmt: skip
    return area


def set_rate(
    db: Session,
    actor: Actor,
    zone_id: uuid.UUID,
    *,
    method: DeliveryMode,
    fee_santim: int,
    promised_hours: int,
    is_active: bool = True,
) -> DeliveryRate:
    """Set the flat fee for one delivery method into one zone.

    There is one rate per zone and method; setting it again replaces it and
    records the old and new fee. Collection at the shop has no rate.
    """
    zone = get_zone(db, zone_id)
    rate = db.scalar(
        select(DeliveryRate)
        .where(DeliveryRate.zone_id == zone.id, DeliveryRate.method == method.value)
        .with_for_update()
    )
    before = None
    if rate is None:
        rate = DeliveryRate(zone_id=zone.id, method=method.value)
        db.add(rate)
    else:
        before = {
            "fee_santim": rate.fee_santim,
            "promised_hours": rate.promised_hours,
            "is_active": rate.is_active,
        }
    rate.fee_santim = fee_santim
    rate.promised_hours = promised_hours
    rate.is_active = is_active
    db.flush()
    record_by(
        db, actor, "delivery_rate.set", "delivery_rate", rate.id, before=before,
        after={
            "zone_id": str(zone.id), "method": method.value, "fee_santim": fee_santim,
            "promised_hours": promised_hours, "is_active": is_active,
        },
    )  # fmt: skip
    return rate
