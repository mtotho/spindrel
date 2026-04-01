"""Mission Control — Plans endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel
from app.dependencies import get_db, verify_auth_or_user
from integrations.mission_control.helpers import (
    get_mc_prefs,
    get_user,
    plan_step_summary,
    read_plans_for_channel,
    require_channel_access,
    tracked_channels,
)
from integrations.mission_control.schemas import MCPlan, MCPlanStep, MCPlansResponse
from integrations.mission_control.services import approve_plan, reject_plan, resume_plan

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/plans", response_model=MCPlansResponse)
async def plans(
    scope: Literal["fleet", "personal"] = "fleet",
    status: str | None = Query(None, description="Comma-separated statuses to filter"),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated plans: reads plans.md from all tracked channels."""
    import asyncio

    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    status_filter = {s.strip() for s in status.split(",")} if status else None

    all_raw = await asyncio.gather(
        *(read_plans_for_channel(ch) for ch in channels)
    )

    all_plans: list[MCPlan] = []
    for ch, raw_plans in zip(channels, all_raw):
        for p in raw_plans:
            if status_filter and p["status"] not in status_filter:
                continue
            all_plans.append(MCPlan(
                id=p["meta"].get("id", ""),
                title=p["title"],
                status=p["status"],
                meta=p.get("meta", {}),
                steps=[MCPlanStep(**s) for s in p.get("steps", [])],
                notes=p.get("notes", ""),
                channel_id=str(ch.id),
                channel_name=ch.name,
            ))

    return {"plans": all_plans}


@router.post("/channels/{channel_id}/plans/{plan_id}/approve")
async def approve_plan_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Approve a draft plan — transitions to approved and triggers bot execution."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        result = await approve_plan(str(channel.id), plan_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(409, msg)

    plan = result["plan"]

    # Create execution task with plan-aware context
    task_created = False
    try:
        from app.db.models import Task as TaskModel
        from app.services.channels import ensure_active_session
        from app.services.sessions import store_passive_message

        session_id = await ensure_active_session(db, channel)
        await db.commit()

        step_summary = plan_step_summary(plan)
        prompt = (
            f"Plan '{plan['title']}' ({plan_id}) has been approved. "
            f"Execute the next pending step.\n\n"
            f"Current step status:\n{step_summary}"
        )
        await store_passive_message(db, session_id, prompt, {"source": "mission_control"})
        await db.commit()

        task = TaskModel(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            execution_config={
                "system_preamble": (
                    f"You are executing approved plan '{plan['title']}' ({plan_id}). "
                    "Work through ONE step at a time. For each step: "
                    "1) call update_plan_step to mark it in_progress, "
                    "2) do the work, "
                    "3) call update_plan_step to mark it done (or failed if it cannot be completed). "
                    "Write intermediate results to workspace files. "
                    "After completing a step, if more steps remain, call schedule_task() "
                    "to continue with the next step — use this exact prompt pattern: "
                    f"\"Continue executing plan '{plan['title']}' ({plan_id}). "
                    f"Pick up from the next pending step.\""
                ),
            },
            callback_config={"trigger_rag_loop": True},
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        task_created = True
    except Exception:
        logger.warning("Failed to send approval message to channel %s", channel.id, exc_info=True)

    return {"ok": True, "plan_id": plan_id, "status": "approved", "task_created": task_created}


@router.post("/channels/{channel_id}/plans/{plan_id}/reject")
async def reject_plan_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Reject a draft plan — transitions to abandoned."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        await reject_plan(str(channel.id), plan_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(409, msg)

    return {"ok": True, "plan_id": plan_id, "status": "abandoned"}


@router.post("/channels/{channel_id}/plans/{plan_id}/resume")
async def resume_plan_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Resume a stalled executing plan."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        result = await resume_plan(str(channel.id), plan_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(409, msg)

    plan = result["plan"]

    task_created = False
    try:
        from app.db.models import Task as TaskModel
        from app.services.channels import ensure_active_session
        from app.services.sessions import store_passive_message

        session_id = await ensure_active_session(db, channel)
        await db.commit()

        step_summary = plan_step_summary(plan)
        prompt = (
            f"Continue executing plan '{plan['title']}' ({plan_id}). "
            f"Pick up from the next pending step.\n\n"
            f"Current step status:\n{step_summary}"
        )
        await store_passive_message(db, session_id, prompt, {"source": "mission_control"})
        await db.commit()

        task = TaskModel(
            bot_id=channel.bot_id,
            client_id=channel.client_id,
            session_id=session_id,
            channel_id=channel.id,
            prompt=prompt,
            status="pending",
            task_type="api",
            dispatch_type=channel.integration or "none",
            dispatch_config=channel.dispatch_config or {},
            execution_config={
                "system_preamble": (
                    f"You are resuming execution of plan '{plan['title']}' ({plan_id}). "
                    "Work through ONE step at a time. For each step: "
                    "1) call update_plan_step to mark it in_progress, "
                    "2) do the work, "
                    "3) call update_plan_step to mark it done (or failed if it cannot be completed). "
                    "Write intermediate results to workspace files. "
                    "After completing a step, if more steps remain, call schedule_task() "
                    "to continue with the next step."
                ),
            },
            callback_config={"trigger_rag_loop": True},
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        task_created = True
    except Exception:
        logger.warning("Failed to send resume message to channel %s", channel.id, exc_info=True)

    return {"ok": True, "plan_id": plan_id, "status": "executing", "task_created": task_created}
