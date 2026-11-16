"""The MarkX API application (blueprint F.2, F.5).

JSON over HTTPS under /api/v1. One error format, a request ID on every
response, and an anti-forgery guard on every request that changes data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from markx.accounts.router import router as accounts_router
from markx.accounts.schemas import DevSmsOut
from markx.core.config import get_config
from markx.core.db import get_engine
from markx.core.http import enforce_request_origin, install_error_handlers, install_middleware
from markx.core.logging import configure_logging
from markx.core.phone import normalize_phone
from markx.delivery.router import admin_router as delivery_admin_router
from markx.delivery.router import router as delivery_router
from markx.notifications.sms import read_dev_sms_inbox

API_PREFIX = "/api/v1"


def _health_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/healthz")
    def healthz() -> JSONResponse:
        """Used by uptime monitors. Reports the API and the database."""
        try:
            with get_engine().connect() as connection:
                connection.execute(text("select 1"))
        except Exception:
            return JSONResponse(
                status_code=503, content={"status": "degraded", "api": "up", "database": "down"}
            )
        return JSONResponse(content={"status": "ok", "api": "up", "database": "up"})

    return router


def _dev_router() -> APIRouter:
    """Helpers that exist only on a laptop and in tests. Never on a real server."""
    router = APIRouter(prefix="/dev", tags=["dev"])

    @router.get("/sms-inbox", response_model=list[DevSmsOut])
    def sms_inbox(phone: str = Query(min_length=9, max_length=24)) -> list[DevSmsOut]:
        return [DevSmsOut(**m) for m in read_dev_sms_inbox(normalize_phone(phone))]

    return router


def create_app() -> FastAPI:
    config = get_config()
    configure_logging(config.log_level)
    app = FastAPI(
        title="MarkX API",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs" if not config.is_real_environment else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
        dependencies=[Depends(enforce_request_origin)],
    )
    install_middleware(app)
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(_health_router())
    api.include_router(accounts_router)
    api.include_router(delivery_router)
    api.include_router(delivery_admin_router)
    if config.dev_tools_enabled:
        api.include_router(_dev_router())
    app.include_router(api)
    return app


app = create_app()
