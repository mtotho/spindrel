"""Admin web terminal — POST to mint a session, WS to stream PTY bytes.

Both endpoints are admin-gated. The terminal is the equivalent of giving the
admin SSH access to the Spindrel container; the env flag
``DISABLE_ADMIN_TERMINAL=true`` returns 404 from both endpoints for paranoid
deployments.

Auth on the WebSocket: browsers can't set ``Authorization`` headers on WS
upgrade requests, so we accept ``?token=<jwt|api_key>`` as a query
parameter. The token is validated through the same path
``verify_admin_auth`` uses for HTTP.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from urllib.parse import unquote, urlparse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies import ApiKeyAuth, get_db, verify_admin_auth
from app.services.terminal import (
    TerminalSessionLimitError,
    close_session,
    create_session,
    get_session,
    is_disabled,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin API"])


def _user_key_from_auth(auth) -> str:
    """Stable per-caller identity used for the concurrent-session cap."""
    if isinstance(auth, ApiKeyAuth):
        return f"key:{auth.key_id}"
    user_id = getattr(auth, "id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return "static"


class CreateTerminalSessionIn(BaseModel):
    seed_command: Optional[str] = Field(
        default=None,
        description="Command piped into the shell on startup (e.g. 'claude login').",
        max_length=2048,
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Working directory to start the shell in. Falls back to $HOME when unset or invalid.",
        max_length=4096,
    )


class CreateTerminalSessionOut(BaseModel):
    session_id: str


def _resolve_terminal_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    if not cwd.startswith("workspace://"):
        return cwd
    parsed = urlparse(cwd)
    workspace_id = parsed.netloc
    try:
        uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="workspace cwd must include a valid workspace id")

    rel = unquote(parsed.path or "").lstrip("/")
    parts = [part for part in rel.replace("\\", "/").split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=422, detail="workspace cwd must stay inside the workspace")

    from app.services.shared_workspace import shared_workspace_service

    root = os.path.realpath(shared_workspace_service.ensure_host_dirs(workspace_id))
    resolved = os.path.realpath(os.path.join(root, *parts)) if parts else root
    root_prefix = root.rstrip(os.sep) + os.sep
    if resolved != root and not resolved.startswith(root_prefix):
        raise HTTPException(status_code=422, detail="workspace cwd must stay inside the workspace")
    os.makedirs(resolved, exist_ok=True)
    return resolved


@router.post(
    "/terminal/sessions",
    response_model=CreateTerminalSessionOut,
)
async def create_terminal_session(
    body: CreateTerminalSessionIn,
    auth=Depends(verify_admin_auth),
):
    """Mint a fresh terminal session. The caller must then connect a WS to
    ``/admin/terminal/{session_id}`` within ~30s or the PTY will be swept.
    """
    if is_disabled():
        raise HTTPException(status_code=404, detail="admin terminal disabled")

    user_key = _user_key_from_auth(auth)
    try:
        session = await create_session(
            user_key,
            seed_command=body.seed_command,
            cwd=_resolve_terminal_cwd(body.cwd),
        )
    except TerminalSessionLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except Exception as exc:
        logger.exception("admin.terminal.create_failed")
        raise HTTPException(status_code=500, detail=f"failed to create terminal: {exc}")

    return CreateTerminalSessionOut(session_id=session.id)


async def _verify_admin_token(token: str, db) -> object:
    """Replay the admin auth path against a token from a query string.

    Mirrors ``verify_admin_auth`` (which only takes a header) but for the WS
    handshake. Raises ``HTTPException`` on failure so the caller can map it
    to a WS close code.
    """
    if not token:
        raise HTTPException(status_code=401, detail="token required")

    # Static admin key paths
    if settings.ADMIN_API_KEY:
        if token == settings.ADMIN_API_KEY:
            return ApiKeyAuth(
                key_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000000"),
                scopes=["admin"],
                name="static-env-key",
            )
    elif token == settings.API_KEY:
        return ApiKeyAuth(
            key_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000000"),
            scopes=["admin"],
            name="static-env-key",
        )

    if token.startswith("ask_"):
        from app.services.api_keys import has_scope, validate_api_key

        api_key = await validate_api_key(db, token)
        if api_key is None:
            raise HTTPException(status_code=401, detail="invalid or expired API key")
        scopes = api_key.scopes or []
        if not has_scope(scopes, "admin"):
            raise HTTPException(status_code=403, detail="admin scope required")
        return ApiKeyAuth(key_id=api_key.id, scopes=scopes, name=api_key.name)

    # JWT
    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt
    from uuid import UUID

    try:
        payload = decode_access_token(token)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    if payload.get("kind") == "widget":
        raise HTTPException(status_code=401, detail="widget tokens cannot access admin endpoints")

    try:
        user_id = UUID(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid token subject")

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active or not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="admin access denied")
    return user


@router.websocket("/terminal/{session_id}")
async def terminal_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(..., description="Bearer token (JWT or API key) — query param because browsers can't set WS auth headers."),
):
    """Streams PTY output to the client and pumps input/resize back.

    Wire format (text frames, JSON):
        client → server: {"type": "data", "data": "<base64-string>"} OR
                         {"type": "resize", "rows": int, "cols": int}
        server → client: {"type": "data", "data": "<base64-string>"} OR
                         {"type": "exit"}

    Base64 is used because xterm.js sends keystrokes as strings (incl. escape
    sequences) and PTY output is raw bytes that may not decode cleanly mid
    multi-byte sequence — base64 is unambiguous and one-line to wire on both
    sides. Volume is fine: terminal traffic is human-paced.
    """
    if is_disabled():
        await websocket.close(code=4404)
        return

    # Auth before accepting the upgrade.
    db_gen = get_db()
    db = await db_gen.__anext__()
    try:
        try:
            await _verify_admin_token(token, db)
        except HTTPException as http_exc:
            code = 4403 if http_exc.status_code == 403 else 4401
            await websocket.close(code=code)
            return
    finally:
        try:
            await db_gen.aclose()
        except Exception:
            pass

    session = get_session(session_id)
    if session is None or session.closed:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    logger.info(
        "admin.terminal.session_attach",
        extra={"session_id": session_id},
    )

    import base64
    import json

    async def pump_output() -> None:
        try:
            while True:
                chunk = await session.read_output()
                if not chunk:
                    try:
                        await websocket.send_text(json.dumps({"type": "exit"}))
                    except Exception:
                        pass
                    return
                payload = {"type": "data", "data": base64.b64encode(chunk).decode("ascii")}
                await websocket.send_text(json.dumps(payload))
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:
            logger.exception("admin.terminal.output_pump_error", extra={"session_id": session_id})

    output_task = asyncio.create_task(pump_output())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "data":
                b64 = msg.get("data") or ""
                try:
                    data = base64.b64decode(b64.encode("ascii"), validate=True)
                except Exception:
                    continue
                session.write_input(data)
            elif kind == "resize":
                try:
                    rows = int(msg.get("rows") or 24)
                    cols = int(msg.get("cols") or 80)
                except (TypeError, ValueError):
                    continue
                session.resize(rows, cols)
            # Unknown frames are ignored — keep the loop forgiving.
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("admin.terminal.input_pump_error", extra={"session_id": session_id})
    finally:
        output_task.cancel()
        try:
            await output_task
        except (asyncio.CancelledError, Exception):
            pass
        # Closing the WS kills the PTY. No reconnect path in v1.
        await close_session(session_id)


@router.delete("/terminal/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_terminal_session(
    session_id: str,
    auth=Depends(verify_admin_auth),
):
    """Optional explicit teardown — the WS close path handles the common case."""
    if is_disabled():
        raise HTTPException(status_code=404, detail="admin terminal disabled")
    await close_session(session_id)
    return None
