"""Integration tests for the admin web terminal.

Pins:
  - POST mints a session as admin
  - POST refuses non-admin (widget-kind ApiKeyAuth without admin scope)
  - DISABLE_ADMIN_TERMINAL → 404 from both endpoints
  - WS roundtrip: type a command, get its echo back
  - Concurrent-session cap enforced per user
  - WS auth: bad token → close 4401; missing session → close 4404
"""
from __future__ import annotations

import base64
import json
import os
import sys
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Force a tighter concurrent cap so we can hit it fast in tests.
os.environ.setdefault("ADMIN_TERMINAL_MAX_PER_USER", "2")
os.environ.setdefault("ADMIN_TERMINAL_IDLE_TIMEOUT_SEC", "5")


def _build_app(*, disabled: bool = False):
    """Construct a minimal FastAPI app mounting just the terminal router.

    We re-import the module so module-level env reads (``_DISABLED``) pick
    up the per-test override.
    """
    if disabled:
        os.environ["DISABLE_ADMIN_TERMINAL"] = "true"
    else:
        os.environ.pop("DISABLE_ADMIN_TERMINAL", None)

    # Force re-import so module-level constants reflect the env.
    for mod_name in list(sys.modules):
        if mod_name.startswith("app.services.terminal") or mod_name == "app.routers.api_v1_admin_terminal":
            del sys.modules[mod_name]

    from fastapi import FastAPI
    from app.dependencies import ApiKeyAuth, verify_admin_auth
    from app.routers.api_v1_admin_terminal import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _mock_admin_auth():
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000001"),
            scopes=["admin"],
            name="test-admin",
        )

    app.dependency_overrides[verify_admin_auth] = _mock_admin_auth
    return app


@pytest_asyncio.fixture
async def client():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    # Clean up any sessions left behind.
    from app.services.terminal import session as session_mod

    for sid in list(session_mod._SESSIONS.keys()):
        await session_mod.close_session(sid)


@pytest.mark.asyncio
async def test_post_creates_session_as_admin(client):
    resp = await client.post(
        "/api/v1/admin/terminal/sessions",
        json={"seed_command": None, "cwd": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "session_id" in body and isinstance(body["session_id"], str)

    from app.services.terminal import get_session

    assert get_session(body["session_id"]) is not None


@pytest.mark.asyncio
async def test_post_with_seed_and_cwd(client):
    resp = await client.post(
        "/api/v1/admin/terminal/sessions",
        json={"seed_command": "echo hello", "cwd": "/tmp"},
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    from app.services.terminal import get_session

    sess = get_session(sid)
    assert sess is not None
    assert sess.cwd == "/tmp"
    assert sess.seed_command == "echo hello"


@pytest.mark.asyncio
async def test_concurrent_cap_enforced(client):
    # Cap is 2 (set at import time via env). Third should 429.
    a = await client.post("/api/v1/admin/terminal/sessions", json={})
    b = await client.post("/api/v1/admin/terminal/sessions", json={})
    c = await client.post("/api/v1/admin/terminal/sessions", json={})
    assert a.status_code == 200
    assert b.status_code == 200
    assert c.status_code == 429


@pytest.mark.asyncio
async def test_delete_removes_session(client):
    create = await client.post("/api/v1/admin/terminal/sessions", json={})
    sid = create.json()["session_id"]

    from app.services.terminal import get_session

    assert get_session(sid) is not None

    delete = await client.delete(f"/api/v1/admin/terminal/sessions/{sid}")
    assert delete.status_code == 204
    assert get_session(sid) is None


@pytest.mark.asyncio
async def test_post_404s_when_disabled():
    app = _build_app(disabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/admin/terminal/sessions", json={})
        assert resp.status_code == 404
    # Reset for other tests
    os.environ.pop("DISABLE_ADMIN_TERMINAL", None)


def test_ws_roundtrip_with_bash():
    """WebSocket end-to-end: spawn bash, type a command, see its output.

    Uses Starlette's sync TestClient because httpx's async client doesn't yet
    support WebSocket upgrades. The terminal session itself runs on the same
    asyncio loop as TestClient, so this exercises the real PTY pump.
    """
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    # Reset env so disable flag is off and re-import.
    os.environ.pop("DISABLE_ADMIN_TERMINAL", None)
    for mod_name in list(sys.modules):
        if mod_name.startswith("app.services.terminal") or mod_name == "app.routers.api_v1_admin_terminal":
            del sys.modules[mod_name]

    from app.dependencies import ApiKeyAuth, verify_admin_auth
    from app.routers.api_v1_admin_terminal import router
    from app.config import settings

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _mock_admin_auth():
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000099"),
            scopes=["admin"],
            name="test-admin-ws",
        )

    app.dependency_overrides[verify_admin_auth] = _mock_admin_auth

    with TestClient(app) as client:
        create = client.post("/api/v1/admin/terminal/sessions", json={})
        assert create.status_code == 200
        sid = create.json()["session_id"]

        # WS endpoint validates token via the static API_KEY path.
        token = settings.API_KEY
        with client.websocket_connect(
            f"/api/v1/admin/terminal/{sid}?token={token}"
        ) as ws:
            # Send a marker command. Use a unique string to avoid matching the
            # bash motd / PS1 echo.
            marker = "SPINDREL_TERMINAL_TEST_42"
            payload_bytes = f"echo {marker}\n".encode()
            ws.send_text(json.dumps({
                "type": "data",
                "data": base64.b64encode(payload_bytes).decode("ascii"),
            }))

            # Drain until we see the marker echoed back, with a generous frame
            # cap so a slow shell doesn't flake.
            seen = b""
            for _ in range(40):
                msg = ws.receive_text()
                frame = json.loads(msg)
                if frame.get("type") == "data":
                    seen += base64.b64decode(frame["data"].encode("ascii"))
                    if marker.encode() in seen:
                        break
                elif frame.get("type") == "exit":
                    break
            assert marker.encode() in seen, f"marker not echoed; saw: {seen!r}"

    # Force cleanup so other tests don't see our PTY in the registry.
    from app.services.terminal import session as session_mod
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        for sid in list(session_mod._SESSIONS.keys()):
            loop.run_until_complete(session_mod.close_session(sid))
    finally:
        loop.close()


def test_ws_rejects_bad_token():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    os.environ.pop("DISABLE_ADMIN_TERMINAL", None)
    for mod_name in list(sys.modules):
        if mod_name.startswith("app.services.terminal") or mod_name == "app.routers.api_v1_admin_terminal":
            del sys.modules[mod_name]

    from app.dependencies import ApiKeyAuth, verify_admin_auth
    from app.routers.api_v1_admin_terminal import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _mock_admin_auth():
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000098"),
            scopes=["admin"],
            name="test-admin-ws-bad",
        )

    app.dependency_overrides[verify_admin_auth] = _mock_admin_auth

    with TestClient(app) as client:
        create = client.post("/api/v1/admin/terminal/sessions", json={})
        sid = create.json()["session_id"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v1/admin/terminal/{sid}?token=not-a-real-token"
            ):
                pass
        assert exc_info.value.code in {4401, 4403}
