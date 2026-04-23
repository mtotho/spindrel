from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from integrations.sdk import async_session

from app.services.machine_control import get_provider, get_target_by_id

from .bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter()


def _target_token(target_id: str) -> str:
    provider = get_provider("local_companion")
    target = provider.get_target(target_id)
    return str((target or {}).get("token") or "")


@router.websocket("/ws")
async def companion_ws(
    websocket: WebSocket,
    target_id: str = Query(...),
    token: str = Query(...),
):
    expected = _target_token(target_id)
    if not expected:
        await websocket.close(code=4404, reason="unknown target")
        return
    if not secrets.compare_digest(token, expected):
        await websocket.close(code=4401, reason="invalid target token")
        return

    await websocket.accept()
    hello = await websocket.receive_json()
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await websocket.close(code=4400, reason="first frame must be hello")
        return

    target = get_target_by_id("local_companion", target_id) or {}
    label = str(hello.get("label") or target.get("label") or target_id)
    hostname = str(hello.get("hostname") or "")
    platform = str(hello.get("platform") or "")
    capabilities = [str(v) for v in (hello.get("capabilities") or []) if str(v).strip()]

    async def _send(payload: dict) -> None:
        await websocket.send_json(payload)

    async with async_session() as db:
        provider = get_provider("local_companion")
        await provider.register_connected_target(
            db,
            target_id=target_id,
            label=label,
            hostname=hostname,
            platform=platform,
            capabilities=capabilities or ["shell"],
        )

    conn = await bridge.register(
        _send,
        target_id=target_id,
        label=label,
        hostname=hostname,
        platform=platform,
        capabilities=capabilities or ["shell"],
    )
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "target_id": target_id,
                "connection_id": conn.connection_id,
            }
        )
        while True:
            msg = await websocket.receive_json()
            if "request_id" in msg:
                bridge.handle_reply(conn, msg)
            else:
                logger.debug("local_companion event: %s", msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("local_companion ws error")
    finally:
        await bridge.unregister(conn)
