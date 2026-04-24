"""Cluster 3 — domain-error → HTTP adapter tests.

Pins:
1. Each ``DomainError`` subclass carries the correct ``http_status``.
2. A service function raising ``DomainError`` from a route returns the
   same ``{"detail": ...}`` JSON shape that ``HTTPException`` produced
   before. Regression guard for Cluster 3 migration.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    InternalError,
    NotFoundError,
    UnprocessableError,
    ValidationError,
)


def test_http_status_mapping():
    assert NotFoundError("x").http_status == 404
    assert ValidationError("x").http_status == 400
    assert UnprocessableError("x").http_status == 422
    assert ConflictError("x").http_status == 409
    assert ForbiddenError("x").http_status == 403
    assert InternalError("x").http_status == 500


def test_detail_preserved_on_exception():
    exc = NotFoundError("bot xyz")
    assert exc.detail == "bot xyz"
    assert str(exc) == "bot xyz"


def test_all_subclasses_inherit_from_domain_error():
    for cls in (
        NotFoundError, ValidationError, UnprocessableError,
        ConflictError, ForbiddenError, InternalError,
    ):
        assert issubclass(cls, DomainError)


@pytest.fixture
def adapter_app():
    """Mirror the wiring in ``app/main.py`` so the router-boundary adapter
    behavior is testable in isolation.
    """
    from fastapi.responses import JSONResponse
    from starlette.requests import Request

    app = FastAPI()

    @app.exception_handler(DomainError)
    async def handler(_req: Request, exc: DomainError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.http_status)

    @app.get("/boom/notfound")
    def _boom_nf():
        raise NotFoundError("no such bot")

    @app.get("/boom/validation")
    def _boom_v():
        raise ValidationError("slug must be a string")

    @app.get("/boom/conflict")
    def _boom_c():
        raise ConflictError("already exists")

    @app.get("/boom/unprocessable")
    def _boom_u():
        raise UnprocessableError("bad verdict")

    @app.get("/boom/forbidden")
    def _boom_f():
        raise ForbiddenError("admin only")

    return app


def test_router_boundary_returns_fastapi_default_json_shape(adapter_app):
    client = TestClient(adapter_app)
    r = client.get("/boom/notfound")
    assert r.status_code == 404
    assert r.json() == {"detail": "no such bot"}


def test_router_boundary_validation(adapter_app):
    client = TestClient(adapter_app)
    r = client.get("/boom/validation")
    assert r.status_code == 400
    assert r.json() == {"detail": "slug must be a string"}


def test_router_boundary_conflict(adapter_app):
    client = TestClient(adapter_app)
    r = client.get("/boom/conflict")
    assert r.status_code == 409
    assert r.json() == {"detail": "already exists"}


def test_router_boundary_unprocessable(adapter_app):
    client = TestClient(adapter_app)
    r = client.get("/boom/unprocessable")
    assert r.status_code == 422
    assert r.json() == {"detail": "bad verdict"}


def test_router_boundary_forbidden(adapter_app):
    client = TestClient(adapter_app)
    r = client.get("/boom/forbidden")
    assert r.status_code == 403
    assert r.json() == {"detail": "admin only"}
