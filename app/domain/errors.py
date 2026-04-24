"""Domain exception hierarchy.

Services, agent loop code, and tools raise these instead of ``HTTPException``
so they do not import from ``fastapi``. The router boundary registers a
handler (see ``app/main.py``) that converts any ``DomainError`` into a
``{"detail": ...}`` JSON response with the appropriate status code — the
same wire shape FastAPI's built-in ``HTTPException`` handler produces.

``detail`` may be a string or a JSON-serializable dict. The dict form
mirrors ``HTTPException(detail={...})`` so responses like
``{"error": "local_control_required", "message": "..."}`` round-trip
unchanged through the adapter.

Callers in background workers / tools can catch ``DomainError`` directly
without pulling in the ``fastapi`` package.
"""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base for all service-layer errors that a router should surface as HTTP."""

    http_status: int = 500

    def __init__(self, detail: Any) -> None:
        super().__init__(detail if isinstance(detail, str) else str(detail))
        self.detail = detail


class NotFoundError(DomainError):
    http_status = 404


class ValidationError(DomainError):
    http_status = 400


class UnprocessableError(DomainError):
    http_status = 422


class ConflictError(DomainError):
    http_status = 409


class ForbiddenError(DomainError):
    http_status = 403


class InternalError(DomainError):
    http_status = 500


def install_domain_error_handler(app) -> None:
    """Register the ``DomainError`` → ``{"detail": ...}`` JSON handler on ``app``.

    Called by ``app/main.py`` during startup and by the integration test
    app factory so services that raise ``DomainError`` produce the same
    wire shape as the legacy ``HTTPException`` raises.
    """
    from fastapi.responses import JSONResponse

    async def _handler(_req, exc: DomainError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.http_status)

    app.add_exception_handler(DomainError, _handler)


__all__ = [
    "DomainError",
    "NotFoundError",
    "ValidationError",
    "UnprocessableError",
    "ConflictError",
    "ForbiddenError",
    "InternalError",
    "install_domain_error_handler",
]
