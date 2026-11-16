from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from markx.accounts import service
from markx.accounts.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    CurrentPrincipal,
    presented_token,
)
from markx.accounts.models import Address, SessionKind, StaffMember, User
from markx.accounts.permissions import staff_capabilities
from markx.accounts.schemas import (
    AddressIn,
    AddressOut,
    DataRequestIn,
    DataRequestOut,
    MeOut,
    NotificationOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    ProfileIn,
    SessionOut,
    StaffOut,
    StaffSignInIn,
    TelegramSignInIn,
)
from markx.core.config import get_config
from markx.core.http import Db, client_ip
from markx.core.phone import mask_phone
from markx.core.schemas import Ok
from markx.delivery.models import DeliveryArea
from markx.notifications import service as notifications
from markx.sellers import selectors as seller_selectors

router = APIRouter()


def _set_session_cookies(response: Response, token: str, kind: SessionKind) -> None:
    config = get_config()
    minutes = (
        config.staff_session_max_minutes
        if kind == SessionKind.STAFF
        else config.customer_session_max_minutes
    )
    common = {
        "max_age": minutes * 60,
        "secure": config.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    # Scripts cannot read the session cookie; they can read the CSRF token.
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, service.csrf_token_for(token), httponly=False, **common)  # type: ignore[arg-type]


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _me(db: Db, user: User, kind: str, token: str, staff: StaffMember | None) -> MeOut:
    return MeOut(
        id=user.id,
        phone=user.phone,
        name=user.name,
        language=user.language,
        session_kind=kind,
        csrf_token=service.csrf_token_for(token),
        staff=(
            StaffOut(role=staff.role, capabilities=staff_capabilities(staff.role))
            if staff is not None and kind == SessionKind.STAFF
            else None
        ),
        sellers=seller_selectors.memberships_for_user(db, user.id),  # type: ignore[arg-type]
        unread_notifications=notifications.unread_count(db, user.id),
    )


def _wants_header_session(request: Request) -> bool:
    # The Telegram Mini App cannot rely on cookies (blueprint F.4).
    return request.headers.get("x-markx-client", "").lower() == "tma"


def _previous_token(request: Request) -> str | None:
    presented = presented_token(request)
    return presented[0] if presented else None


@router.post("/auth/otp/request", response_model=OtpRequestOut, tags=["auth"])
def request_otp(body: OtpRequestIn, request: Request, db: Db) -> OtpRequestOut:
    phone = service.request_login_code(
        db,
        raw_phone=body.phone,
        ip=client_ip(request),
        bot_token=body.bot_token,
        language=body.language,
    )
    return OtpRequestOut(
        phone_masked=mask_phone(phone), expires_in_seconds=int(service.OTP_TTL.total_seconds())
    )


@router.post("/auth/otp/verify", response_model=SessionOut, tags=["auth"])
def verify_otp(body: OtpVerifyIn, request: Request, response: Response, db: Db) -> SessionOut:
    header_session = _wants_header_session(request)
    user, token, is_new = service.verify_login_code(
        db,
        raw_phone=body.phone,
        code=body.code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        transport="header" if header_session else "cookie",
        language=body.language,
        previous_session_token=_previous_token(request),
    )
    if not header_session:
        _set_session_cookies(response, token, SessionKind.CUSTOMER)
    return SessionOut(
        me=_me(db, user, SessionKind.CUSTOMER, token, None),
        is_new_account=is_new,
        session_token=token if header_session else None,
    )


@router.post("/auth/staff/sign-in", response_model=SessionOut, tags=["auth"])
def staff_sign_in(body: StaffSignInIn, request: Request, response: Response, db: Db) -> SessionOut:
    user, staff, token = service.staff_sign_in(
        db,
        raw_phone=body.phone,
        password=body.password,
        totp_code=body.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        previous_session_token=_previous_token(request),
    )
    _set_session_cookies(response, token, SessionKind.STAFF)
    return SessionOut(me=_me(db, user, SessionKind.STAFF, token, staff))


@router.post("/auth/telegram", response_model=SessionOut, tags=["auth"])
def telegram_sign_in(body: TelegramSignInIn, request: Request, db: Db) -> SessionOut:
    user, token = service.telegram_sign_in(
        db,
        init_data=body.init_data,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SessionOut(me=_me(db, user, SessionKind.CUSTOMER, token, None), session_token=token)


@router.post("/auth/sign-out", response_model=Ok, tags=["auth"])
def sign_out(principal: CurrentPrincipal, response: Response, db: Db) -> Ok:
    service.end_session(db, principal.session)
    _clear_session_cookies(response)
    return Ok()


@router.post("/auth/sign-out-everywhere", response_model=Ok, tags=["auth"])
def sign_out_everywhere(principal: CurrentPrincipal, response: Response, db: Db) -> Ok:
    service.end_all_sessions(db, principal.user.id)
    _clear_session_cookies(response)
    return Ok()


@router.get("/me", response_model=MeOut, tags=["me"])
def read_me(principal: CurrentPrincipal, db: Db) -> MeOut:
    return _me(db, principal.user, principal.session.kind, principal.token, principal.staff)


@router.patch("/me", response_model=MeOut, tags=["me"])
def update_me(body: ProfileIn, principal: CurrentPrincipal, db: Db) -> MeOut:
    service.update_profile(db, principal.user, name=body.name, language=body.language)
    return _me(db, principal.user, principal.session.kind, principal.token, principal.staff)


@router.post("/me/telegram", response_model=Ok, tags=["me"])
def link_telegram(body: TelegramSignInIn, principal: CurrentPrincipal, db: Db) -> Ok:
    service.link_telegram(db, principal.user, init_data=body.init_data)
    return Ok()


def _address_out(db: Db, address: Address) -> AddressOut:
    area = db.get(DeliveryArea, address.delivery_area_id)
    assert area is not None
    return AddressOut(
        id=address.id,
        recipient_name=address.recipient_name,
        phone=address.phone,
        phone2=address.phone2,
        delivery_area_id=address.delivery_area_id,
        area_name_am=area.name_am,
        area_name_en=area.name_en,
        zone_id=area.zone_id,
        landmark=address.landmark,
        latitude=address.latitude,
        longitude=address.longitude,
        driver_notes=address.driver_notes,
    )


@router.get("/me/addresses", response_model=list[AddressOut], tags=["me"])
def list_addresses(principal: CurrentPrincipal, db: Db) -> list[AddressOut]:
    return [_address_out(db, a) for a in service.list_addresses(db, principal.user.id)]


@router.post("/me/addresses", response_model=AddressOut, status_code=201, tags=["me"])
def create_address(body: AddressIn, principal: CurrentPrincipal, db: Db) -> AddressOut:
    address = service.create_address(
        db,
        principal.user,
        recipient_name=body.recipient_name,
        raw_phone=body.phone,
        raw_phone2=body.phone2,
        delivery_area_id=body.delivery_area_id,
        landmark=body.landmark,
        latitude=body.latitude,
        longitude=body.longitude,
        driver_notes=body.driver_notes,
    )
    return _address_out(db, address)


@router.delete("/me/addresses/{address_id}", response_model=Ok, tags=["me"])
def delete_address(address_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> Ok:
    service.archive_address(db, principal.user.id, address_id)
    return Ok()


@router.get("/me/data-requests", response_model=list[DataRequestOut], tags=["me"])
def list_data_requests(principal: CurrentPrincipal, db: Db) -> list[DataRequestOut]:
    return [
        DataRequestOut.model_validate(r)
        for r in service.list_data_requests(db, principal.user.id)
    ]


@router.post("/me/data-requests", response_model=DataRequestOut, status_code=201, tags=["me"])
def create_data_request(body: DataRequestIn, principal: CurrentPrincipal, db: Db) -> DataRequestOut:
    return DataRequestOut.model_validate(
        service.create_data_request(db, principal.user, kind=body.kind, note=body.note)
    )


@router.get("/me/notifications", response_model=list[NotificationOut], tags=["me"])
def list_notifications(principal: CurrentPrincipal, db: Db) -> list[NotificationOut]:
    return [
        NotificationOut.model_validate(n)
        for n in notifications.list_for_user(db, principal.user.id)
    ]


@router.post("/me/notifications/read", response_model=Ok, tags=["me"])
def read_notifications(principal: CurrentPrincipal, db: Db) -> Ok:
    notifications.mark_all_read(db, principal.user.id)
    return Ok()


__all__ = ["router", "select"]
