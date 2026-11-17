"""Admin routes (blueprint D.18, C.4; D-065).

`/admin/audit-log`               the audit-log viewer (AD-17)        read_audit_log
`/admin/settings`                switches and risk limits (AD-06, AD-13)
`/admin/staff`                   staff accounts and roles (AD-06)    manage_staff_and_settings
`/admin/dispatch-board`          parts waiting for a rider (AD-05)   intervene_in_orders
`/admin/dashboard`               the business dashboard (AD-14)      find_orders
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from markx.accounts.deps import AnyStaff, Principal, require_staff
from markx.accounts.permissions import StaffCapability, staff_can
from markx.admin import service
from markx.admin.schemas import (
    AuditEntryOut,
    BusinessDashboardOut,
    DispatchRowOut,
    NewStaffOut,
    SettingIn,
    SettingOut,
    StaffAccountOut,
    StaffActiveIn,
    StaffCreateIn,
    StaffRoleIn,
)
from markx.core.errors import PermissionDenied
from markx.core.http import Db

router = APIRouter(prefix="/admin", tags=["admin: operations"])

AuditReader = Annotated[Principal, Depends(require_staff(StaffCapability.READ_AUDIT_LOG))]
StaffManager = Annotated[
    Principal, Depends(require_staff(StaffCapability.MANAGE_STAFF_AND_SETTINGS))
]
OrderIntervener = Annotated[Principal, Depends(require_staff(StaffCapability.INTERVENE_IN_ORDERS))]
DashboardReader = Annotated[Principal, Depends(require_staff(StaffCapability.FIND_ORDERS))]
SettingKey = Annotated[str, Path(pattern=r"^[a-z_]+\.[a-z_]+$", max_length=80)]


def _role(principal: Principal) -> str:
    assert principal.staff is not None
    return principal.staff.role


@router.get("/audit-log", response_model=list[AuditEntryOut])
def audit_log(
    staff: AuditReader,
    db: Db,
    action: Annotated[str | None, Query(pattern=r"^[a-z_]+(\.[a-z_]+)*\.?$", max_length=80)] = None,
    target_type: Annotated[str | None, Query(pattern=r"^[a-z_]+$", max_length=60)] = None,
    target_id: Annotated[str | None, Query(max_length=80)] = None,
    actor_user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEntryOut]:
    """Newest first. Page with `before` set to the last id received. `action`
    ending in a dot matches every action under it ("seller.")."""
    return [
        AuditEntryOut.model_validate(entry)
        for entry in service.audit_entries(
            db,
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor_user_id,
            since=since,
            until=until,
            before=before,
            limit=limit,
        )
    ]


@router.get("/settings", response_model=list[SettingOut])
def settings(staff: AnyStaff, db: Db) -> list[SettingOut]:
    """Every switch and limit with its default and current value, and whether
    this member of staff may change it: the super administrator any, and
    operations the risk limits (C.4)."""
    role = _role(staff)
    if not (
        staff_can(role, StaffCapability.MANAGE_STAFF_AND_SETTINGS)
        or staff_can(role, StaffCapability.CHANGE_DELIVERY_AND_RISK)
    ):
        raise PermissionDenied("permission_denied", "Your role does not allow this.")
    return [SettingOut.model_validate(row) for row in service.list_settings(db, role)]


@router.put("/settings/{key}", response_model=SettingOut)
def change_setting(
    key: SettingKey, body: SettingIn, staff: AnyStaff, request: Request, db: Db
) -> SettingOut:
    """Audit-logged with the value before and after."""
    return SettingOut.model_validate(
        service.change_setting(db, staff.actor(request), _role(staff), key, body.value)
    )


@router.get("/staff", response_model=list[StaffAccountOut])
def list_staff(staff: StaffManager, db: Db) -> list[StaffAccountOut]:
    return [StaffAccountOut.model_validate(row) for row in service.staff_rows(db)]


@router.post("/staff", response_model=NewStaffOut, status_code=201)
def create_staff(body: StaffCreateIn, staff: StaffManager, request: Request, db: Db) -> NewStaffOut:
    created = service.create_staff(
        db, staff.actor(request), phone=body.phone, name=body.name, role=body.role,
        password=body.password,
    )  # fmt: skip
    (row,) = [r for r in service.staff_rows(db) if r["id"] == created.staff.id]
    return NewStaffOut(
        staff=StaffAccountOut.model_validate(row),
        totp_secret=created.totp_secret,
        provisioning_uri=created.provisioning_uri,
    )


@router.post("/staff/{staff_id}/role", response_model=StaffAccountOut)
def change_staff_role(
    staff_id: uuid.UUID, body: StaffRoleIn, staff: StaffManager, request: Request, db: Db
) -> StaffAccountOut:
    """Ends the member's staff sessions: a new role needs a new sign-in."""
    changed = service.change_staff_role(db, staff.actor(request), staff_id, body.role)
    (row,) = [r for r in service.staff_rows(db) if r["id"] == changed.id]
    return StaffAccountOut.model_validate(row)


@router.post("/staff/{staff_id}/active", response_model=StaffAccountOut)
def set_staff_active(
    staff_id: uuid.UUID, body: StaffActiveIn, staff: StaffManager, request: Request, db: Db
) -> StaffAccountOut:
    """Deactivating takes effect on the member's next request."""
    changed = service.set_staff_active(
        db, staff.actor(request), staff_id, active=body.active, reason=body.reason
    )
    (row,) = [r for r in service.staff_rows(db) if r["id"] == changed.id]
    return StaffAccountOut.model_validate(row)


@router.get("/dispatch-board", response_model=list[DispatchRowOut])
def dispatch_board(
    staff: OrderIntervener, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[DispatchRowOut]:
    """Parts waiting to leave a shop by rider or courier, oldest first (AD-05)."""
    return [
        DispatchRowOut.model_validate(row)
        for row in service.dispatch_board(db, now=datetime.now(UTC), limit=limit)
    ]


@router.get("/dashboard", response_model=BusinessDashboardOut)
def dashboard(
    staff: DashboardReader, db: Db, days: Annotated[int, Query(ge=1, le=366)] = 7
) -> BusinessDashboardOut:
    return BusinessDashboardOut.model_validate(
        service.dashboard(db, now=datetime.now(UTC), days=days)
    )
