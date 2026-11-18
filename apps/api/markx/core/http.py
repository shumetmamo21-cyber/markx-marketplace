"""HTTP plumbing shared by every route: request context, the database session,
error handlers, security headers and the anti-forgery guard."""

from __future__ import annotations

import ipaddress
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from markx.core.config import get_config
from markx.core.db import get_session_factory
from markx.core.errors import AppError, PermissionDenied, error_body
from markx.core.logging import request_id_var

logger = logging.getLogger("markx.http")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CLIENT_HEADER = "x-markx-client"
# Routes called by outside services and authenticated by their own signature
# or secret, listed by exact path (SEC-6, D-084). A prefix would also exempt
# every route added under it later, so add each webhook's full path here,
# together with the test that its signature check refuses an unsigned call.
# The Telegram bot's webhook checks its secret header (D-093;
# tests/api/test_telegram_linking.py). Payment webhooks are not built.
CSRF_EXEMPT_PATHS: frozenset[str] = frozenset({"/api/v1/telegram/webhook"})
_DOCS_PATHS = ("/api/v1/docs",)


def get_db() -> Iterator[Session]:
    """One database transaction per request: commit on success, else roll back.

    Declared with scope="function" (see `Db`), so the commit happens before the
    response is sent. A client that reads straight after a write sees it.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


Db = Annotated[Session, Depends(get_db, scope="function")]


def client_ip(request: Request) -> str | None:
    """The caller's network address, or None when it is not a valid one.

    Behind a reverse proxy listed in MARKX_TRUSTED_PROXIES, this is the
    address the proxy saw, taken from X-Forwarded-For by the outermost
    middleware (`install_middleware`); from any other peer, forwarded headers
    are ignored (SEC-3, D-084). The value is validated because it is stored in `inet` columns and used as a
    rate-limit key: a unix socket or a test client reports no real address.
    """
    host = request.client.host if request.client else None
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def current_request_id() -> str:
    return request_id_var.get()


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _clean_inbound_request_id(value: str | None) -> str | None:
    if value and len(value) <= 64 and value.replace("-", "").isalnum():
        return value
    return None


async def _request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = _clean_inbound_request_id(request.headers.get("x-request-id")) or _new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error", extra={"path": request.url.path})
        response = JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong on our side.", request_id),
        )
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # API responses are data, never framed and never cached by shared caches
    # unless a route opts in.
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Frame-Options"] = "DENY"
    # SEC-5 (D-084). API responses are data and pictures, never pages, so they
    # may load nothing. The interactive docs (laptop only) need their scripts.
    if not request.url.path.startswith(_DOCS_PATHS):
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    # HTTPS only from now on, for a year. Sent only where the configuration
    # has already refused to start without an https:// origin and secure
    # cookies. No includeSubDomains or preload: those bind every subdomain and
    # are the founder's decision with the domain.
    if get_config().is_real_environment:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    # Paths only: query strings can carry search terms and are never logged.
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    request_id_var.reset(token)
    return response


def enforce_request_origin(request: Request) -> None:
    """The anti-forgery guard for every request that changes data (blueprint H.2).

    A cross-site page cannot add a custom header without a CORS preflight, and
    MarkX answers none, so requiring the header blocks forged form posts. The
    Origin and Sec-Fetch-Site checks are a second barrier. Requests that carry
    a session cookie must also present the session's CSRF token; that check
    lives with the session code.
    """
    if request.method in SAFE_METHODS:
        return
    if request.url.path in CSRF_EXEMPT_PATHS:
        return
    if not request.headers.get(CLIENT_HEADER):
        raise PermissionDenied("csrf_header_missing", "This request was not sent by the MarkX app.")
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != get_config().public_origin.rstrip("/"):
        raise PermissionDenied("csrf_origin_mismatch", "This request came from another site.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise PermissionDenied("csrf_origin_mismatch", "This request came from another site.")


def _json_error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, current_request_id(), details),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        response = _json_error(exc.status_code, exc.code, exc.message, exc.details)
        retry_after = exc.details.get("retry_after_seconds")
        if retry_after is not None:
            response.headers["Retry-After"] = str(retry_after)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field paths and messages only; submitted values are never echoed back.
        fields = [
            {"field": ".".join(str(part) for part in error["loc"][1:]), "problem": error["msg"]}
            for error in exc.errors()
        ]
        return _json_error(
            422, "validation_failed", "Some fields are not valid.", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}
        code = codes.get(exc.status_code, "http_error")
        return _json_error(exc.status_code, code, str(exc.detail))


def install_middleware(app: FastAPI) -> None:
    app.middleware("http")(_request_context_middleware)
    # Added last, so it runs first: every later layer sees the real caller.
    # Only the configured proxies are believed, the nearest untrusted address
    # in the X-Forwarded-For chain wins, and "*" is refused by the config.
    # The container runs uvicorn with --no-proxy-headers, so this is the one
    # place forwarded headers are read.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=get_config().trusted_proxy_list)
