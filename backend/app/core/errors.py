"""Domain exceptions mapped to HTTP responses by the app error handlers."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-presentable failures."""

    status_code = 400
    code = "app_error"

    def __init__(
        self, message: str, *, details: Any = None, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": {"code": self.code, "message": self.message}
        }
        if self.details is not None:
            payload["error"]["details"] = self.details
        return payload


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationFailure(AppError):
    status_code = 422
    code = "validation_failed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ProviderNotConfigured(AppError):
    status_code = 503
    code = "provider_not_configured"


class UpstreamError(AppError):
    """A third-party API (Hunar / people-search) failed."""

    status_code = 502
    code = "upstream_error"

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message, details=details)
        self.provider = provider
        self.upstream_status = status

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["error"]["provider"] = self.provider
        if self.upstream_status is not None:
            payload["error"]["upstream_status"] = self.upstream_status
        return payload
