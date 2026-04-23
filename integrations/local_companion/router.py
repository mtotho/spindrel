from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from integrations.sdk import async_session, verify_admin_auth

from app.services.local_machine_control import (
    build_targets_status,
    create_enrollment,
    get_target_by_id,
    register_connected_target,
    revoke_target,
)

from .bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter()


class EnrollRequest(BaseModel):
    label: str | None = None


def _target_token(target_id: str) -> str:
    target = get_target_by_id(target_id)
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

    target = get_target_by_id(target_id) or {}
    label = str(hello.get("label") or target.get("label") or target_id)
    hostname = str(hello.get("hostname") or "")
    platform = str(hello.get("platform") or "")
    capabilities = [str(v) for v in (hello.get("capabilities") or []) if str(v).strip()]

    async def _send(payload: dict) -> None:
        await websocket.send_json(payload)

    async with async_session() as db:
        await register_connected_target(
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


@router.get("/admin/status", dependencies=[Depends(verify_admin_auth)])
async def admin_status() -> dict:
    return {"targets": build_targets_status()}


@router.post("/admin/enroll", dependencies=[Depends(verify_admin_auth)])
async def admin_enroll(request: Request, body: EnrollRequest | None = None) -> dict:
    async with async_session() as db:
        enrolled = await create_enrollment(db, label=body.label if body else None)
    from app.agent.tools import index_local_tools
    from app.services import file_sync
    from app.services.integration_settings import get_status, set_status
    from app.tools.loader import load_integration_tools
    from integrations import _iter_integration_candidates

    if get_status("local_companion") != "enabled":
        await set_status("local_companion", "enabled")
        for candidate, iid, _is_external, _source in _iter_integration_candidates():
            if iid == "local_companion":
                load_integration_tools(candidate)
                break
        await index_local_tools()
        await file_sync.sync_all_files()
    server_url = str(request.base_url).rstrip("/")
    return {
        "target": {k: v for k, v in enrolled.items() if k != "token"},
        "token": enrolled["token"],
        "example_command": (
            "python -m integrations.local_companion.client "
            f"--server-url {server_url} --target-id {enrolled['target_id']} "
            f"--token {enrolled['token']}"
        ),
        "websocket_path": enrolled["websocket_path"],
    }


@router.delete("/admin/targets/{target_id}", dependencies=[Depends(verify_admin_auth)])
async def admin_delete_target(target_id: str) -> dict:
    async with async_session() as db:
        removed = await revoke_target(db, target_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Machine target not found")
    return {"status": "ok", "target_id": target_id}
