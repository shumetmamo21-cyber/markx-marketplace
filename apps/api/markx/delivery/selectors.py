"""Read queries for delivery zones, areas and rates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.delivery.models import DeliveryArea, DeliveryMode, DeliveryRate, DeliveryZone


@dataclass(frozen=True, slots=True)
class ZoneView:
    zone: DeliveryZone
    areas: list[DeliveryArea]
    rates: list[DeliveryRate]


def list_zones(db: Session, *, active_only: bool) -> list[ZoneView]:
    zone_query = select(DeliveryZone).order_by(DeliveryZone.position, DeliveryZone.name_en)
    area_query = select(DeliveryArea).order_by(DeliveryArea.position, DeliveryArea.name_en)
    rate_query = select(DeliveryRate).order_by(DeliveryRate.method)
    if active_only:
        zone_query = zone_query.where(DeliveryZone.is_active)
        area_query = area_query.where(DeliveryArea.is_active)
        rate_query = rate_query.where(DeliveryRate.is_active)
    areas: dict[uuid.UUID, list[DeliveryArea]] = {}
    for area in db.scalars(area_query):
        areas.setdefault(area.zone_id, []).append(area)
    rates: dict[uuid.UUID, list[DeliveryRate]] = {}
    for rate in db.scalars(rate_query):
        rates.setdefault(rate.zone_id, []).append(rate)
    return [
        ZoneView(zone=zone, areas=areas.get(zone.id, []), rates=rates.get(zone.id, []))
        for zone in db.scalars(zone_query)
    ]


def active_rates_for_zone(db: Session, zone_id: uuid.UUID) -> dict[DeliveryMode, DeliveryRate]:
    """The fee table for one destination zone, by delivery method."""
    rows = db.scalars(
        select(DeliveryRate).where(DeliveryRate.zone_id == zone_id, DeliveryRate.is_active)
    )
    return {DeliveryMode(rate.method): rate for rate in rows}
