"""WebSocket endpoint the browser extension connects to.

Mounted under /integrations/browser_live (see app/main.py:554 — routers
on integrations are auto-discovered). The extension opens

    wss://<host>/integrations/browser_live/ws?token=<pairing_token>

and exchanges JSON RPC frames with the bridge.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter()


async def _resolve_user_for_token(token: str) -> str | None:
    """Look up which user owns this pairing token.

    TODO: real implementation reads BROWSER_LIVE_PAIRING_TOKEN out of
    per-user IntegrationSettings (one row per user). For the sketch we
    accept any token and treat it as the user_id directly so you can
    smoke-test end-to-end without wiring the settings table first.
    """
    if not token:
        return None
    return token  # SKETCH ONLY — replace with real lookup before shipping


@router.websocket("/ws")
async def extension_ws(websocket: WebSocket, token: str = Query(...)):
    user_id = await _resolve_user_for_token(token)
    if not user_id:
        await websocket.close(code=4401, reason="invalid pairing token")
        return

    await websocket.accept()

    async def _send(payload: dict) -> None:
        await websocket.send_json(payload)

    conn = await bridge.register(user_id, _send)
    try:
        await websocket.send_json({"type": "hello", "connection_id": conn.connection_id})
        while True:
            msg = await websocket.receive_json()
            # Two frame shapes: replies to our RPCs, and unsolicited events.
            if "request_id" in msg:
                bridge.handle_reply(conn, msg)
            else:
                # TODO: forward extension-initiated events (tab opened,
                # navigation, console error) onto channel_events bus so
                # bots / widgets can react.
                logger.debug("browser_live event: %s", msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("browser_live ws error")
    finally:
        await bridge.unregister(conn)
