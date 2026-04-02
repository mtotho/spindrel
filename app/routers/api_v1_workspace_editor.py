"""Reverse proxy for code-server running inside workspace containers.

Routes:
- HTTP:      /api/v1/workspaces/{workspace_id}/editor/{path:path}
- WebSocket: /api/v1/workspaces/{workspace_id}/editor/{path:path}

Auth flow:
1. First load: browser opens URL with ?tkn=<jwt> query param
2. Proxy validates token, sets httpOnly cookie, redirects to same URL without ?tkn
3. Subsequent requests (assets, API calls, WebSocket) use the cookie
"""
from __future__ import annotations

import logging
import uuid
from urllib.parse import urlencode, parse_qs, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from starlette.responses import RedirectResponse

from app.config import settings
from app.db.models import SharedWorkspace
from app.dependencies import get_db, verify_auth_or_user
from app.services.workspace_editor import write_chat_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspace-editor"])

# Cookie name per workspace
def _cookie_name(workspace_id: str) -> str:
    return f"editor_{workspace_id.replace('-', '_')}"


def _proxy_host() -> str:
    """Where to reach the workspace container's mapped port from the server."""
    if settings.WORKSPACE_LOCAL_DIR:
        return "host.docker.internal"
    return "127.0.0.1"


async def _get_ws_for_editor(workspace_id: str, db) -> SharedWorkspace:
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if not ws.editor_enabled or not ws.editor_port:
        raise HTTPException(400, "Editor not enabled for this workspace")
    return ws


async def _validate_token(token: str, db) -> bool:
    """Validate a bearer token. Returns True if valid."""
    try:
        await verify_auth_or_user(authorization=f"Bearer {token}", db=db)
        return True
    except HTTPException:
        return False


async def _verify_editor_auth(request: Request, workspace_id: str, db):
    """Check auth via Authorization header or session cookie."""
    # Try Authorization header first
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return await verify_auth_or_user(authorization=auth_header, db=db)

    # Fall back to session cookie
    cookie_val = request.cookies.get(_cookie_name(workspace_id))
    if cookie_val:
        try:
            return await verify_auth_or_user(authorization=f"Bearer {cookie_val}", db=db)
        except HTTPException:
            pass

    raise HTTPException(401, "Authentication required")


# ── HTTP proxy ──────────────────────────────────────────────────

@router.api_route(
    "/{workspace_id}/editor/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_editor_http(
    workspace_id: str,
    path: str,
    request: Request,
    db=Depends(get_db),
):
    # Check for ?tkn= bootstrap param (first load from UI)
    tkn = request.query_params.get("tkn")
    if tkn:
        if not await _validate_token(tkn, db):
            raise HTTPException(401, "Invalid token")

        # Write chat extension config into the container (best-effort)
        ws = await _get_ws_for_editor(workspace_id, db)
        if ws.container_name:
            try:
                server_url = str(request.base_url).rstrip("/")
                await write_chat_config(
                    container_name=ws.container_name,
                    server_url=server_url,
                    token=tkn,
                )
            except Exception as exc:
                logger.debug("Failed to write chat config to container: %s", exc)

        # Build redirect URL without the tkn param
        params = dict(request.query_params)
        params.pop("tkn", None)
        clean_path = request.url.path
        if params:
            clean_path += "?" + urlencode(params)

        response = RedirectResponse(url=clean_path, status_code=302)
        cookie_path = f"/api/v1/workspaces/{workspace_id}/editor"
        response.set_cookie(
            key=_cookie_name(workspace_id),
            value=tkn,
            path=cookie_path,
            httponly=True,
            samesite="lax",
            max_age=86400,  # 24 hours
        )
        return response

    # Normal auth check (header or cookie)
    await _verify_editor_auth(request, workspace_id, db)
    ws = await _get_ws_for_editor(workspace_id, db)

    # Build target URL — strip the tkn param from forwarded query
    target_url = f"http://{_proxy_host()}:{ws.editor_port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Forward request with retry for startup race
    body = await request.body()
    headers = dict(request.headers)
    for h in ("host", "connection", "transfer-encoding"):
        headers.pop(h, None)

    import asyncio

    last_exc = None
    for attempt in range(4):  # up to ~6s of retries
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    follow_redirects=False,
                )
                break
            except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(2)
    else:
        raise HTTPException(502, f"Editor not reachable — it may still be starting up ({last_exc})")

    # Build response, preserving status and headers
    response_headers = dict(resp.headers)
    for h in ("transfer-encoding", "connection", "content-encoding", "content-length"):
        response_headers.pop(h, None)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
    )


# ── WebSocket proxy ─────────────────────────────────────────────

@router.websocket("/{workspace_id}/editor/{path:path}")
async def proxy_editor_ws(
    workspace_id: str,
    path: str,
    websocket: WebSocket,
    db=Depends(get_db),
):
    # Auth via cookie or query param
    cookie_val = websocket.cookies.get(_cookie_name(workspace_id))
    if not cookie_val:
        cookie_val = websocket.query_params.get("tkn")
    if not cookie_val:
        await websocket.close(code=4001, reason="Authentication required")
        return
    if not await _validate_token(cookie_val, db):
        await websocket.close(code=4001, reason="Invalid authentication")
        return

    ws = await _get_ws_for_editor(workspace_id, db)
    target_url = f"ws://{_proxy_host()}:{ws.editor_port}/{path}"
    if websocket.url.query:
        # Strip tkn from query forwarded to upstream
        params = dict(websocket.query_params)
        params.pop("tkn", None)
        if params:
            target_url += "?" + urlencode(params)

    await websocket.accept()

    import asyncio
    import websockets

    try:
        async with websockets.connect(target_url, max_size=16 * 1024 * 1024) as upstream:
            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive()
                        if "text" in data:
                            await upstream.send(data["text"])
                        elif "bytes" in data:
                            await upstream.send(data["bytes"])
                except WebSocketDisconnect:
                    await upstream.close()

            async def upstream_to_client():
                try:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except websockets.exceptions.ConnectionClosed:
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except Exception as exc:
        logger.debug("WebSocket proxy error for workspace %s: %s", workspace_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
