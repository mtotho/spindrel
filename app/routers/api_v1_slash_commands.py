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
    current_session_id: uuid.UUID | None = None
    surface: str = "web"
    args: list[str] = []
    args_text: str | None = None


def _auth_has_scope(auth, scope: str) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return has_scope(auth.scopes, scope)
    scopes = getattr(auth, "_resolved_scopes", None) or []
    return bool(getattr(auth, "is_admin", False) or has_scope(scopes, scope))


def _require_scope(auth, scope: str):
    if not _auth_has_scope(auth, scope):
        raise HTTPException(status_code=403, detail=f"{scope} required")


def _session_belongs_to_channel(session: Session, channel_id: uuid.UUID) -> bool:
    return session.channel_id == channel_id or session.parent_channel_id == channel_id


@router.get("")
async def list_slash_commands(
    bot_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Slash-command catalog.

    Optional ``?bot_id=`` intersects the catalog with the bot's runtime
    slash policy when the bot is a harness — so harness sessions get a
    pre-filtered list and the picker matches ``/help`` exactly. Non-harness
    bots / omitted query → full catalog. ``bot_id`` is a STRING (e.g.
    ``"claude-code-bot"``), not a UUID — Bot row PKs are text, not uuid.
    """
    return {
        "commands": await list_supported_slash_commands(db=db, bot_id=bot_id),
    }


@router.post("/execute", response_model=SlashCommandResult)
async def run_slash_command(
    body: SlashCommandExecuteRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    if bool(body.channel_id) == bool(body.session_id):
        raise HTTPException(status_code=422, detail="Exactly one of channel_id or session_id is required")
    if body.current_session_id is not None and body.channel_id is None:
        raise HTTPException(status_code=422, detail="current_session_id is only valid with channel_id")

    if body.channel_id is not None:
        channel = await db.get(Channel, body.channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if body.current_session_id is not None:
            current_session = await db.get(Session, body.current_session_id)
            if current_session is None:
                raise HTTPException(status_code=404, detail="Current session not found")
            if not _session_belongs_to_channel(current_session, body.channel_id):
                raise HTTPException(status_code=422, detail="current_session_id does not belong to channel")
        if body.command_id == "context":
            await _auth_channel_context(body.channel_id, auth, db)
        else:
            _require_scope(auth, "channels.messages:write")
            _check_protected(channel, auth)
    else:
        session = await db.get(Session, body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if body.command_id == "style":
            parent_channel_id = session.channel_id or session.parent_channel_id
            if parent_channel_id is None:
                raise HTTPException(status_code=400, detail="/style is only available for sessions inside a channel")
            channel = await db.get(Channel, parent_channel_id)
            if channel is None:
                raise HTTPException(status_code=404, detail="Channel not found")
            _require_scope(auth, "channels.messages:write")
            _check_protected(channel, auth)
        elif body.command_id == "context":
            _require_scope(auth, "sessions:read")
        else:
            _require_scope(auth, "sessions:write")

    try:
        return await execute_slash_command(
            command_id=body.command_id,
            channel_id=body.channel_id,
            session_id=body.session_id,
            current_session_id=body.current_session_id,
            db=db,
            args=list(body.args or []),
            args_text=body.args_text,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
