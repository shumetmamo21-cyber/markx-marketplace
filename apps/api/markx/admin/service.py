"""Staff tools behind the admin dashboard (blueprint D.18, AD-05, AD-06, AD-13,
AD-14, AD-17, C.4; D-065).

Every change here is audit-logged with before and after values (P11
criterion 3). Who may do what follows C.4 exactly; the routes check it, and
the rules that a capability alone cannot express (a super administrator
never removes the last super administrator, nor locks themselves out) are
checked here.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from markx.accounts import service as accounts
from markx.accounts.models import Session as UserSession
from markx.accounts.models import SessionKind, StaffMember, StaffRole, User
from markx.accounts.permissions import StaffCapability, staff_can
from markx.audit.models import AuditLog
from markx.audit.service import Actor, record_by
from markx.catalog.models import Product, ProductStatus, ProductVariant
from markx.core import settings_store
from markx.core.errors import Conflict, NotFound, PermissionDenied
from markx.delivery.models import DeliveryMode, DeliveryZone, Shipment, ShipmentStatus
from markx.offers.models import Offer, OfferStatus
from markx.orders.models import Cart, CartItem, Order, SellerOrder, SellerOrderStatus
from markx.search.models import SearchQuery
from markx.sellers.models import Seller, SellerStatus, Store
from markx.trust.models import CaseStatus, DisputeCase

# -- the audit-log viewer (AD-17) ----------------------------------------------------------


def audit_entries(
    db: Session,
    *,
    action: str | None,
    target_type: str | None,
    target_id: str | None,
    actor_user_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
    before: uuid.UUID | None,
    limit: int,
) -> list[AuditLog]:
    """Newest first, paged by id (ids are time-ordered). `action` matches a
    whole action or every action under a prefix ending in a dot
    ("seller." finds every seller action)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        if action.endswith("."):
            query = query.where(AuditLog.action.startswith(action, autoescape=True))
        else:
            query = query.where(AuditLog.action == action)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    if actor_user_id:
        query = query.where(AuditLog.actor_user_id == actor_user_id)
    if since:
        query = query.where(AuditLog.occurred_at >= since)
    if until:
        query = query.where(AuditLog.occurred_at < until)
    if before:
        query = query.where(AuditLog.id < before)
    return list(db.scalars(query))


# -- settings, switches and risk limits (AD-06, AD-13) -----------------------------------

# Risk limits (AD-13): operations may change these too (C.4, "delivery zones,
# rates and risk limits"). Every other setting is the super administrator's.
RISK_LIMITS = frozenset(
    {
        "orders.max_open_direct_orders",
        "orders.max_order_value_santim",
        "sellers.min_level_to_publish",
        "auth.otp_per_phone_per_hour",
        "auth.otp_per_ip_per_hour",
        "auth.sms_daily_budget",
        "auth.otp_resend_cooldown_seconds",
        "search.requests_per_ip_per_minute",
        "search.suggestions_per_ip_per_minute",
    }
)


def capability_for_setting(key: str) -> StaffCapability:
    return (
        StaffCapability.CHANGE_DELIVERY_AND_RISK
        if key in RISK_LIMITS
        else StaffCapability.MANAGE_STAFF_AND_SETTINGS
    )


def list_settings(db: Session, staff_role: str) -> list[dict[str, Any]]:
    return [
        {**row, "may_change": staff_can(staff_role, capability_for_setting(row["key"]))}
        for row in settings_store.list_settings(db)
    ]


def change_setting(
    db: Session, actor: Actor, staff_role: str, key: str, value: Any
) -> dict[str, Any]:
    if key not in settings_store.SETTINGS:
        raise NotFound("setting_not_found", "There is no setting with that name.")
    if not staff_can(staff_role, capability_for_setting(key)):
        raise PermissionDenied("permission_denied", "Your role does not allow this.")
    before, after = settings_store.set_setting(db, key, value)
    record_by(db, actor, "setting.change", "setting", key, before={"value": before},
              after={"value": after})  # fmt: skip
    (row,) = [r for r in list_settings(db, staff_role) if r["key"] == key]
    return row


# -- staff accounts (AD-06) ----------------------------------------------------------------


def staff_rows(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(StaffMember, User)
        .join(User, User.id == StaffMember.user_id)
        .order_by(StaffMember.created_at, StaffMember.id)
    ).all()
    return [
        {
            "id": staff.id,
            "user_id": user.id,
            "name": user.name,
            "phone_last4": user.phone[-4:],
            "role": staff.role,
            "is_active": staff.is_active,
            "locked_until": staff.locked_until,
            "created_at": staff.created_at,
        }
        for staff, user in rows
    ]


def _staff(db: Session, staff_id: uuid.UUID) -> StaffMember:
    staff = db.scalar(select(StaffMember).where(StaffMember.id == staff_id).with_for_update())
    if staff is None:
        raise NotFound("staff_not_found", "That staff account was not found.")
    return staff


def _other_active_super_admins(db: Session, staff_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(StaffMember)
            .where(
                StaffMember.role == StaffRole.SUPER_ADMIN,
                StaffMember.is_active,
                StaffMember.id != staff_id,
            )
        )
        or 0
    )


def _lock_staff_table(db: Session) -> None:
    # Role changes and deactivations take turns, so two at once can never
    # leave MarkX without an active super administrator.
    db.execute(select(func.pg_advisory_xact_lock(0x4D585354)))  # "MXST"


def create_staff(
    db: Session, actor: Actor, *, phone: str, name: str, role: StaffRole, password: str
) -> accounts.NewStaff:
    """A new staff account. The authenticator secret is shown once, to the
    super administrator creating it, and stored only encrypted."""
    assert actor.user_id is not None
    return accounts.create_staff(
        db, raw_phone=phone, name=name, role=role, password=password,
        actor_user_id=actor.user_id, ip=actor.ip,
    )  # fmt: skip


def change_staff_role(
    db: Session, actor: Actor, staff_id: uuid.UUID, role: StaffRole
) -> StaffMember:
    _lock_staff_table(db)
    staff = _staff(db, staff_id)
    if staff.user_id == actor.user_id:
        raise Conflict("own_account", "Ask another super administrator to change your own role.")
    if staff.role == role.value:
        return staff
    if (
        staff.role == StaffRole.SUPER_ADMIN
        and staff.is_active
        and _other_active_super_admins(db, staff.id) == 0
    ):
        raise Conflict("last_super_admin", "MarkX must keep one active super administrator.")
    before = staff.role
    staff.role = role.value
    db.flush()
    _end_staff_sessions(db, staff.user_id)
    record_by(db, actor, "staff.change_role", "staff_member", staff.id,
              before={"role": before}, after={"role": role.value})  # fmt: skip
    return staff


def set_staff_active(
    db: Session, actor: Actor, staff_id: uuid.UUID, *, active: bool, reason: str
) -> StaffMember:
    _lock_staff_table(db)
    staff = _staff(db, staff_id)
    if staff.user_id == actor.user_id:
        raise Conflict("own_account", "Ask another super administrator to do this.")
    if staff.is_active == active:
        return staff
    if (
        not active
        and staff.role == StaffRole.SUPER_ADMIN
        and _other_active_super_admins(db, staff.id) == 0
    ):
        raise Conflict("last_super_admin", "MarkX must keep one active super administrator.")
    staff.is_active = active
    db.flush()
    if not active:
        _end_staff_sessions(db, staff.user_id)
    record_by(db, actor, "staff.activate" if active else "staff.deactivate", "staff_member",
              staff.id, before={"is_active": not active},
              after={"is_active": active, "reason": reason})  # fmt: skip
    return staff


def _end_staff_sessions(db: Session, user_id: uuid.UUID) -> None:
    """A change of privilege ends the person's staff sessions (H.2: "a new
    session at sign-in and at any change of privilege")."""
    for session in db.scalars(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.kind == SessionKind.STAFF,
            UserSession.revoked_at.is_(None),
        )
    ):
        accounts.end_session(db, session)


# -- the dispatch board (AD-05) -----------------------------------------------------------


def dispatch_board(db: Session, *, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Parts waiting to leave a shop by rider or courier, oldest first: what
    staff dispatch for a partner courier (J.9), or chase when a seller's own
    rider is late. Collection orders never appear: the buyer comes to them."""
    rows = db.execute(
        select(SellerOrder, Shipment, Order.code, Store.slug, DeliveryZone.code)
        .join(Shipment, Shipment.seller_order_id == SellerOrder.id)
        .join(Order, Order.id == SellerOrder.order_id)
        .join(Store, Store.seller_id == SellerOrder.seller_id)
        .join(DeliveryZone, DeliveryZone.id == Order.delivery_zone_id)
        .where(
            SellerOrder.status.in_((SellerOrderStatus.CONFIRMED, SellerOrderStatus.READY)),
            Shipment.mode != DeliveryMode.SHOP_COLLECTION,
            Shipment.status.in_((ShipmentStatus.PENDING, ShipmentStatus.READY)),
        )
        .order_by(func.coalesce(SellerOrder.ready_at, SellerOrder.confirmed_at), SellerOrder.id)
        .limit(limit)
    ).all()
    out = []
    for seller_order, shipment, code, store, zone in rows:
        since = seller_order.ready_at or seller_order.confirmed_at or seller_order.created_at
        due = since + timedelta(hours=shipment.promised_hours) if shipment.promised_hours else None
        out.append(
            {
                "seller_order_id": seller_order.id,
                "order_code": code,
                "store_slug": store,
                "zone_code": zone,
                "mode": shipment.mode,
                "status": seller_order.status,
                "waiting_since": since,
                "promised_by": due,
                "late": due is not None and due < now,
            }
        )
    return out


# -- the business dashboard (AD-14) --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Period:
    start: datetime
    end: datetime


def _count(db: Session, query: Any) -> int:
    return int(db.scalar(query) or 0)


def dashboard(db: Session, *, now: datetime, days: int) -> dict[str, Any]:
    """The figures AD-14 names, for the last `days` days. Money in santim.
    Counts only: no buyer or seller is named."""
    period = Period(start=now - timedelta(days=days), end=now)
    in_period = and_(SellerOrder.created_at >= period.start, SellerOrder.created_at < period.end)
    by_status = dict(
        db.execute(
            select(SellerOrder.status, func.count()).where(in_period).group_by(SellerOrder.status)
        ).all()
    )
    orders = _count(
        db,
        select(func.count())
        .select_from(Order)
        .where(Order.created_at >= period.start, Order.created_at < period.end),
    )
    completed_value = _count(
        db,
        select(func.coalesce(func.sum(SellerOrder.items_total_santim), 0)).where(
            SellerOrder.status == SellerOrderStatus.COMPLETED,
            SellerOrder.completed_at >= period.start,
            SellerOrder.completed_at < period.end,
        ),
    )
    fees = _count(
        db,
        select(func.coalesce(func.sum(SellerOrder.commission_santim), 0)).where(
            SellerOrder.status == SellerOrderStatus.COMPLETED,
            SellerOrder.completed_at >= period.start,
            SellerOrder.completed_at < period.end,
        ),
    )
    answer_minutes = [
        (confirmed - created).total_seconds() / 60
        for created, confirmed in db.execute(
            select(SellerOrder.created_at, SellerOrder.confirmed_at).where(
                in_period, SellerOrder.confirmed_at.is_not(None)
            )
        ).all()
        if confirmed is not None
    ]
    answered = sum(
        by_status.get(s, 0)
        for s in SellerOrderStatus
        if s not in (SellerOrderStatus.PLACED, SellerOrderStatus.EXPIRED)
        and s != SellerOrderStatus.CANCELLED
    )
    delivered = _count(
        db,
        select(func.count())
        .select_from(SellerOrder)
        .where(in_period, SellerOrder.delivered_at.is_not(None)),
    )
    failed_deliveries = _count(
        db,
        select(func.count(func.distinct(Shipment.seller_order_id)))
        .join(SellerOrder, SellerOrder.id == Shipment.seller_order_id)
        .where(in_period, Shipment.status.in_((ShipmentStatus.DELIVERY_FAILED,
                                               ShipmentStatus.RETURNED))),
    )  # fmt: skip
    problems_opened = _count(
        db,
        select(func.count())
        .select_from(DisputeCase)
        .where(DisputeCase.created_at >= period.start, DisputeCase.created_at < period.end),
    )
    problems_open = _count(
        db,
        select(func.count())
        .select_from(DisputeCase)
        .where(DisputeCase.status != CaseStatus.RESOLVED),
    )
    min_level = settings_store.get_int(db, "sellers.min_level_to_publish")
    live = (
        select(ProductVariant.product_id, Offer.price_confirmed_at)
        .join(Offer, Offer.variant_id == ProductVariant.id)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            Offer.status == OfferStatus.ACTIVE,
            Seller.status == SellerStatus.ACTIVE,
            Seller.verification_level >= min_level,
            Product.status == ProductStatus.APPROVED,
        )
        .subquery()
    )
    live_offers = _count(db, select(func.count()).select_from(live))
    products_with_offers = _count(db, select(func.count(func.distinct(live.c.product_id))))
    sink_after = timedelta(days=settings_store.get_int(db, "offers.sink_after_days"))
    fresh_offers = _count(
        db,
        select(func.count()).select_from(live).where(live.c.price_confirmed_at >= now - sink_after),
    )
    searches = _count(
        db,
        select(func.count())
        .select_from(SearchQuery)
        .where(SearchQuery.created_at >= period.start, SearchQuery.created_at < period.end),
    )
    zero_result = _count(
        db,
        select(func.count())
        .select_from(SearchQuery)
        .where(
            SearchQuery.created_at >= period.start,
            SearchQuery.created_at < period.end,
            SearchQuery.result_count == 0,
        ),
    )
    carts = _count(
        db,
        select(func.count(func.distinct(CartItem.cart_id)))
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(CartItem.created_at >= period.start, CartItem.created_at < period.end),
    )

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "days": days,
        "from_time": period.start,
        "to_time": period.end,
        "orders": orders,
        "seller_orders": sum(by_status.values()),
        "seller_orders_by_status": by_status,
        "completed_value_santim": completed_value,
        "fees_santim": fees,
        "median_minutes_to_confirm": round(statistics.median(answer_minutes), 1)
        if answer_minutes
        else None,
        "answered_share": share(answered, sum(by_status.values())),
        "delivery_success_share": share(delivered, delivered + failed_deliveries),
        "problems_opened": problems_opened,
        "problems_open": problems_open,
        "live_offers": live_offers,
        "products_with_offers": products_with_offers,
        "offers_per_product": round(live_offers / products_with_offers, 2)
        if products_with_offers
        else None,
        "fresh_price_share": share(fresh_offers, live_offers),
        "funnel": {
            "searches": searches,
            "zero_result_searches": zero_result,
            "carts_filled": carts,
            "orders": orders,
        },
    }
