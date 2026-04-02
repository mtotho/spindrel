"""Integration tests for GET /api/v1/admin/version/check-update."""
import pytest
from unittest.mock import patch, AsyncMock
from httpx import Response as HttpxResponse

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_httpx_response(status_code: int, json_data: dict | list | None = None):
    resp = AsyncMock(spec=HttpxResponse)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_check_update_returns_current_version(client):
    """Endpoint returns current VERSION even when GitHub is unreachable."""
    from app.config import VERSION

    with patch("app.routers.api_v1_admin.settings.httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.get = AsyncMock(side_effect=Exception("network error"))
        MockClient.return_value.__aenter__ = AsyncMock(return_value=ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get(
            "/api/v1/admin/version/check-update",
            headers={"Authorization": "Bearer test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == VERSION
    assert data["update_available"] is False
    assert "error" in data


async def test_check_update_detects_new_version(client):
    """When GitHub returns a newer tag, update_available is True."""
    with patch("app.routers.api_v1_admin.settings.httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.get = AsyncMock(return_value=_mock_httpx_response(200, {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/test-org/test-repo/releases/tag/v99.0.0",
            "published_at": "2026-03-01T00:00:00Z",
        }))
        MockClient.return_value.__aenter__ = AsyncMock(return_value=ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get(
            "/api/v1/admin/version/check-update",
            headers={"Authorization": "Bearer test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] == "99.0.0"
    assert data["update_available"] is True
    assert data["latest_url"] == "https://github.com/test-org/test-repo/releases/tag/v99.0.0"
    assert data["published_at"] == "2026-03-01T00:00:00Z"


async def test_check_update_up_to_date(client):
    """When GitHub returns the same version, update_available is False."""
    from app.config import VERSION

    with patch("app.routers.api_v1_admin.settings.httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.get = AsyncMock(return_value=_mock_httpx_response(200, {
            "tag_name": f"v{VERSION}",
            "html_url": f"https://github.com/test-org/test-repo/releases/tag/v{VERSION}",
            "published_at": "2026-01-01T00:00:00Z",
        }))
        MockClient.return_value.__aenter__ = AsyncMock(return_value=ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get(
            "/api/v1/admin/version/check-update",
            headers={"Authorization": "Bearer test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["update_available"] is False
    assert data["latest"] == VERSION


async def test_check_update_falls_back_to_tags(client):
    """When releases/latest returns 404, falls back to /tags."""
    releases_resp = _mock_httpx_response(404)
    tags_resp = _mock_httpx_response(200, [
        {"name": "v2.0.0", "commit": {"sha": "abc123"}},
    ])

    async def _side_effect(url, **kwargs):
        if "releases/latest" in url:
            return releases_resp
        return tags_resp

    with patch("app.routers.api_v1_admin.settings.httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.get = AsyncMock(side_effect=_side_effect)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get(
            "/api/v1/admin/version/check-update",
            headers={"Authorization": "Bearer test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] == "2.0.0"
    assert data["update_available"] is True


async def test_check_update_includes_git_hash(client):
    """Response includes git_hash when git is available."""
    with (
        patch("app.routers.api_v1_admin.settings.httpx.AsyncClient") as MockClient,
        patch("app.routers.api_v1_admin.settings.asyncio.create_subprocess_exec") as mock_git,
    ):
        # Mock git
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"abc1234\n", b""))
        mock_git.return_value = proc

        # Mock httpx (no release)
        ctx = AsyncMock()
        ctx.get = AsyncMock(side_effect=Exception("skip"))
        MockClient.return_value.__aenter__ = AsyncMock(return_value=ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get(
            "/api/v1/admin/version/check-update",
            headers={"Authorization": "Bearer test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["git_hash"] == "abc1234"
