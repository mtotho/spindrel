"""Workspace Command Center API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import actor_label
from app.services.workspace_command_center import (
    build_command_center,
    create_command_center_intake,
)


router = APIRouter(prefix="/workspace/command-center", tags=["workspace-command-center"])


class CommandCenterIntakeRequest(BaseModel):
    channel_id: uuid.UUID
    title: str = Field(min_length=1)
    message: str = ""
    severity: str = "warning"
    next_steps: list[str] = Field(default_factory=list)
    assign_bot_id: str | None = None
    assignment_mode: str | None = None
    assignment_instructions: str | None = None


@router.get("")
async def get_command_center(
    recent_hours: int = Query(24, ge=1, le=168),
    upcoming_hours: int = Query(24, ge=1, le=168),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await build_command_center(
        db,
        auth=auth,
        recent_hours=recent_hours,
        upcoming_hours=upcoming_hours,
    )


@router.post("/intake", status_code=201)
async def create_intake(
    body: CommandCenterIntakeRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_command_center_intake(
            db,
            auth_label=actor_label(auth) or "user",
            channel_id=body.channel_id,
            title=body.title,
            message=body.message,
            severity=body.severity,
            next_steps=body.next_steps,
            assign_bot_id=body.assign_bot_id,
            assignment_mode=body.assignment_mode,
            assignment_instructions=body.assignment_instructions,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
