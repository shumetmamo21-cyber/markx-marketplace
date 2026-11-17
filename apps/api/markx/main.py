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
from markx.admin.router import router as admin_router
from markx.catalog.router import admin_router as catalog_admin_router
from markx.catalog.router import router as catalog_router
from markx.core.config import get_config
from markx.core.db import get_engine
from markx.core.http import enforce_request_origin, install_error_handlers, install_middleware
from markx.core.logging import configure_logging
from markx.core.phone import normalize_phone
from markx.delivery.router import admin_router as delivery_admin_router
from markx.delivery.router import router as delivery_router
from markx.exports.router import router as exports_router
from markx.images.router import admin_router as images_admin_router
from markx.images.router import buyer_router as images_buyer_router
from markx.images.router import media_router as images_media_router
from markx.images.router import public_router as images_public_router
from markx.images.router import seller_router as images_seller_router
from markx.notifications.sms import read_dev_sms_inbox
from markx.offers.router import admin_router as offers_admin_router
from markx.offers.router import public_router as offers_public_router
from markx.offers.router import router as offers_router
from markx.ops.router import admin_router as ops_admin_router
from markx.ops.router import public_router as ops_public_router
from markx.orders.router import admin_router as orders_admin_router
from markx.orders.router import router as orders_router
from markx.orders.router import seller_router as orders_seller_router
from markx.reports.router import admin_router as reports_admin_router
from markx.reports.router import router as reports_router
from markx.reviews.router import admin_router as reviews_admin_router
from markx.reviews.router import buyer_router as reviews_buyer_router
from markx.reviews.router import public_router as reviews_public_router
from markx.reviews.router import seller_router as reviews_seller_router
from markx.search.router import admin_router as search_admin_router
from markx.search.router import router as search_router
from markx.sellers.router import admin_router as sellers_admin_router
from markx.sellers.router import public_router as sellers_public_router
from markx.sellers.router import router as sellers_router

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
    api.include_router(catalog_router)
    api.include_router(catalog_admin_router)
    api.include_router(sellers_public_router)
    api.include_router(sellers_router)
    api.include_router(sellers_admin_router)
    api.include_router(offers_public_router)
    api.include_router(offers_router)
    api.include_router(offers_admin_router)
    api.include_router(orders_router)
    api.include_router(orders_seller_router)
    api.include_router(orders_admin_router)
    api.include_router(search_router)
    api.include_router(search_admin_router)
    api.include_router(images_public_router)
    api.include_router(images_admin_router)
    api.include_router(images_seller_router)
    api.include_router(images_buyer_router)
    api.include_router(ops_public_router)
    api.include_router(ops_admin_router)
    api.include_router(admin_router)
    api.include_router(reviews_public_router)
    api.include_router(reviews_buyer_router)
    api.include_router(reviews_seller_router)
    api.include_router(reviews_admin_router)
    api.include_router(reports_router)
    api.include_router(reports_admin_router)
    api.include_router(exports_router)
    if config.dev_tools_enabled:
        api.include_router(_dev_router())
        api.include_router(images_media_router)
    app.include_router(api)
    return app


app = create_app()
