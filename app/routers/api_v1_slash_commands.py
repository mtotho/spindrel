"""Shared slash command API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
from app.routers.api_v1_channels import _auth_channel_context, _check_protected
from app.db.models import Channel, Session
from app.services.api_keys import has_scope
from app.services.slash_commands import (
    SlashCommandResult,
    execute_slash_command,
    list_supported_slash_commands,
)

router = APIRouter(prefix="/slash-commands", tags=["slash-commands"])


class SlashCommandExecuteRequest(BaseModel):
    command_id: str
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    surface: str = "web"
    args: list[str] = []


def _auth_has_scope(auth, scope: str) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return has_scope(auth.scopes, scope)
    scopes = getattr(auth, "_resolved_scopes", None) or []
    return bool(getattr(auth, "is_admin", False) or has_scope(scopes, scope))


def _require_scope(auth, scope: str):
    if not _auth_has_scope(auth, scope):
        raise HTTPException(status_code=403, detail=f"{scope} required")


@router.get("")
async def list_slash_commands():
    return {"commands": list_supported_slash_commands()}


@router.post("/execute", response_model=SlashCommandResult)
async def run_slash_command(
    body: SlashCommandExecuteRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    if bool(body.channel_id) == bool(body.session_id):
        raise HTTPException(status_code=422, detail="Exactly one of channel_id or session_id is required")

    if body.channel_id is not None:
        channel = await db.get(Channel, body.channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if body.command_id == "context":
            await _auth_channel_context(body.channel_id, auth, db)
        else:
            _require_scope(auth, "channels.messages:write")
            _check_protected(channel, auth)
    else:
        session = await db.get(Session, body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if body.command_id == "context":
            _require_scope(auth, "sessions:read")
        else:
            _require_scope(auth, "sessions:write")

    try:
        return await execute_slash_command(
            command_id=body.command_id,
            channel_id=body.channel_id,
            session_id=body.session_id,
            db=db,
            args=list(body.args or []),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
