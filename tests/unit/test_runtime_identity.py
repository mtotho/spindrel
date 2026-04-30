from __future__ import annotations

from pathlib import Path

import pytest

from app.services import runtime_identity as identity_service


@pytest.mark.asyncio
async def test_public_health_shape_remains_liveness_only() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.config import VERSION
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": VERSION}


@pytest.mark.asyncio
async def test_system_health_runtime_identity_endpoint_requires_auth() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/system-health/runtime")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_system_health_runtime_identity_endpoint_returns_safe_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    monkeypatch.setenv("SPINDREL_BUILD_SHA", "abc123")
    monkeypatch.setenv("SPINDREL_BUILD_REF", "development")
    monkeypatch.setenv("SPINDREL_BUILD_TIME", "2026-04-30T16:00:00Z")
    monkeypatch.setenv("SPINDREL_BUILD_SOURCE", "test")
    monkeypatch.setenv("SPINDREL_DEPLOY_ID", "deploy-1")
    monkeypatch.setenv("SPINDREL_SECRET_SENTINEL", "must-not-leak")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/v1/system-health/runtime",
            headers={"Authorization": "Bearer test-key"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]
    assert payload["build"] == {
        "commit_sha": "abc123",
        "ref": "development",
        "built_at": "2026-04-30T16:00:00Z",
        "source": "test",
        "deploy_id": "deploy-1",
    }
    assert payload["process"]["started_at"]
    assert isinstance(payload["process"]["uptime_seconds"], int)
    assert payload["features"]["recent_errors_review_state"] is True
    assert "must-not-leak" not in str(payload)


def test_runtime_identity_normalizes_empty_build_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "SPINDREL_BUILD_SHA",
        "SPINDREL_BUILD_REF",
        "SPINDREL_BUILD_TIME",
        "SPINDREL_BUILD_SOURCE",
        "SPINDREL_DEPLOY_ID",
    ):
        monkeypatch.setenv(key, "unknown")

    payload = identity_service.runtime_identity()

    assert payload["build"] == {
        "commit_sha": None,
        "ref": None,
        "built_at": None,
        "source": None,
        "deploy_id": None,
    }


def test_admin_health_no_longer_shells_out_to_git() -> None:
    source = Path("app/routers/api_v1_admin/health.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "git" not in source
