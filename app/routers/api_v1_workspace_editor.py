"""Reverse proxy for code-server running inside workspace containers.

Routes:
- HTTP:      /api/v1/workspaces/{workspace_id}/editor/{path:path}
- WebSocket: /api/v1/workspaces/{workspace_id}/editor/{path:path}

Auth: standard scoped auth for HTTP; session cookie fallback for browser loads.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.config import settings
from app.db.models import SharedWorkspace
from app.dependencies import get_db, require_scopes, verify_auth_or_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspace-editor"])


def _proxy_host() -> str:
    """Where to reach the workspace container's mapped port from the server."""
    if settings.WORKSPACE_LOCAL_DIR:
        # Server runs inside Docker — reach host ports via host.docker.internal
        return "host.docker.internal"
    return "127.0.0.1"


async def _get_ws_for_editor(workspace_id: str, db: AsyncSession) -> SharedWorkspace:
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if not ws.editor_enabled or not ws.editor_port:
        raise HTTPException(400, "Editor not enabled for this workspace")
    return ws


async def _verify_editor_auth(request: Request, db: AsyncSession):
    """Try standard auth first, fall back to session cookie."""
    # Try Authorization header
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return await verify_auth_or_user(authorization=auth_header, db=db)

    # Fall back to session cookie
    workspace_id = request.path_params.get("workspace_id", "")
    cookie_name = f"editor_session_{workspace_id.replace('-', '_')}"
    cookie_val = request.cookies.get(cookie_name)
    if cookie_val:
        # Validate the cookie is a valid token
        from app.dependencies import verify_auth_or_user as _verify
        try:
            return await _verify(authorization=f"Bearer {cookie_val}", db=db)
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
    db: AsyncSession = Depends(get_db),
):
    await _verify_editor_auth(request, db)
    ws = await _get_ws_for_editor(workspace_id, db)

    target_url = f"http://{_proxy_host()}:{ws.editor_port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Forward request
    body = await request.body()
    headers = dict(request.headers)
    # Remove hop-by-hop headers
    for h in ("host", "connection", "transfer-encoding"):
        headers.pop(h, None)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                follow_redirects=False,
            )
        except httpx.ConnectError:
            raise HTTPException(502, "Editor not reachable — it may still be starting up")

    # Build response, preserving status and headers
    response_headers = dict(resp.headers)
    # Remove hop-by-hop headers from response
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
    db: AsyncSession = Depends(get_db),
):
    # Auth via cookie (WebSocket can't send custom headers from browser)
    cookie_name = f"editor_session_{workspace_id.replace('-', '_')}"
    cookie_val = websocket.cookies.get(cookie_name)
    if not cookie_val:
        # Also check query param as fallback
        cookie_val = websocket.query_params.get("token")
    if not cookie_val:
        await websocket.close(code=4001, reason="Authentication required")
        return
    try:
        await verify_auth_or_user(authorization=f"Bearer {cookie_val}", db=db)
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid authentication")
        return

    ws = await _get_ws_for_editor(workspace_id, db)
    target_url = f"ws://{_proxy_host()}:{ws.editor_port}/{path}"
    if websocket.url.query:
        target_url += f"?{websocket.url.query}"

    await websocket.accept()

    import websockets

    try:
        async with websockets.connect(target_url, max_size=16 * 1024 * 1024) as upstream:
            import asyncio

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
