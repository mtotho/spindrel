"""HTTP + WebSocket surface for browser_live.

Mounted under /integrations/browser_live (see app/main.py:554 — routers
on integrations are auto-discovered).

Endpoints:
- GET  /admin/status        — list paired connections (admin)
- POST /admin/token/rotate  — generate a new pairing token (admin)
- WS   /ws?token=…&label=…  — extension connects here
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from integrations.sdk import async_session, get_setting, update_settings, verify_admin_auth

from .bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter()

INTEGRATION_ID = "browser_live"
TOKEN_KEY = "BROWSER_LIVE_PAIRING_TOKEN"


def _stored_token() -> str:
    return get_setting(INTEGRATION_ID, TOKEN_KEY, "")


@router.websocket("/ws")
async def extension_ws(
    websocket: WebSocket,
    token: str = Query(...),
    label: str = Query("browser"),
):
    expected = _stored_token()
    if not expected:
        await websocket.close(code=4401, reason="pairing token not configured")
        return
    # Constant-time compare guards against timing oracles even though both
    # sides are local — cheap habit, no downside.
    if not secrets.compare_digest(token, expected):
        await websocket.close(code=4401, reason="invalid pairing token")
        return

    await websocket.accept()

    async def _send(payload: dict) -> None:
        await websocket.send_json(payload)

    conn = await bridge.register(_send, label=label)
    try:
        await websocket.send_json({"type": "hello", "connection_id": conn.connection_id})
        while True:
            msg = await websocket.receive_json()
            if "request_id" in msg:
                bridge.handle_reply(conn, msg)
            else:
                # Unsolicited extension events (tab opened, navigation,
                # console error, etc.) — TODO: forward onto channel_events
                # bus so widgets can subscribe via spindrel.stream.
                logger.debug("browser_live event: %s", msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("browser_live ws error")
    finally:
        await bridge.unregister(conn)


@router.get("/admin/status", dependencies=[Depends(verify_admin_auth)])
async def admin_status() -> dict:
    return {
        "token_configured": bool(_stored_token()),
        "connections": bridge.list_connections(),
    }


@router.post("/admin/token/rotate", dependencies=[Depends(verify_admin_auth)])
async def admin_rotate_token() -> dict:
    """Generate and persist a fresh pairing token. Returns the plaintext —
    surface it once in the admin UI; the user pastes it into the extension.
    Subsequent reads via the regular settings endpoint will be masked."""
    new_token = secrets.token_urlsafe(32)
    setup_var = [{"key": TOKEN_KEY, "secret": True}]
    async with async_session() as db:
        await update_settings(INTEGRATION_ID, {TOKEN_KEY: new_token}, setup_var, db)

    # Force any currently-paired extension to reconnect with the new token.
    for c in list(bridge._conns):  # noqa: SLF001 — internal cleanup is fine
        await bridge.unregister(c)

    return {"token": new_token}
