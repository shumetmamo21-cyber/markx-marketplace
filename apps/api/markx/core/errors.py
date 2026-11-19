"""The single error format (blueprint F.5).

Every failure the API returns has a stable machine code, a message key the web
app translates, an English fallback, and the request ID for support.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.code
        self.message = message or self.code.replace("_", " ").capitalize()
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    @property
    def message_key(self) -> str:
        return f"errors.{self.code}"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def error_body(
    code: str, message: str, request_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message_key": f"errors.{code}",
            "message": message,
            "request_id": request_id,
            "details": details or {},
        }
    }
