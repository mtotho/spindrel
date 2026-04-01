"""Mission Control — Plans endpoints."""
from __future__ import annotations

import logging
import uuid
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
    """Aggregated plans from MC SQLite DB for all tracked channels."""
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
    """Approve a draft plan — transitions to approved and starts plan execution engine."""
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

    # Kick off plan execution engine
    execution_started = False
    try:
        from integrations.mission_control.plan_executor import advance_plan as _advance
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_result = await session.execute(
                select(McPlan)
                .where(McPlan.plan_id == plan_id)
                .where(McPlan.channel_id == str(channel_id))
            )
            db_plan = db_result.scalar_one_or_none()
            if db_plan:
                await _advance(db_plan.id)
                execution_started = True
    except Exception:
        logger.warning("Failed to start plan execution for %s", plan_id, exc_info=True)

    return {
        "ok": True,
        "plan_id": plan_id,
        "status": "approved",
        "execution_started": execution_started,
    }


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
    """Resume a stalled executing or awaiting_approval plan."""
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

    # Re-engage the plan executor
    execution_started = False
    try:
        from integrations.mission_control.plan_executor import advance_plan as _advance
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_result = await session.execute(
                select(McPlan)
                .where(McPlan.plan_id == plan_id)
                .where(McPlan.channel_id == str(channel_id))
            )
            db_plan = db_result.scalar_one_or_none()
            if db_plan:
                await _advance(db_plan.id)
                execution_started = True
    except Exception:
        logger.warning("Failed to resume plan execution for %s", plan_id, exc_info=True)

    return {
        "ok": True,
        "plan_id": plan_id,
        "status": "executing",
        "execution_started": execution_started,
    }


@router.post("/channels/{channel_id}/plans/{plan_id}/steps/{position}/approve")
async def approve_step_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    position: int,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Approve a gated step in an awaiting_approval plan, then advance."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    from datetime import datetime, timezone

    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.plan_executor import _create_step_task
    from integrations.mission_control.services import _render_plans_md, append_timeline
    from sqlalchemy import select

    ch_id = str(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == ch_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            raise HTTPException(404, f"Plan '{plan_id}' not found")
        if db_plan.status != "awaiting_approval":
            raise HTTPException(
                409,
                f"Plan is [{db_plan.status}], expected [awaiting_approval]",
            )

        await session.refresh(db_plan, ["steps"])
        step = next((s for s in db_plan.steps if s.position == position), None)
        if not step:
            raise HTTPException(404, f"Step {position} not found in plan '{plan_id}'")
        if not step.requires_approval:
            raise HTTPException(409, f"Step {position} does not require approval")

        # Mark step as in_progress and set plan back to executing.
        # Preserve requires_approval so the flag remains as metadata.
        step.status = "in_progress"
        step.started_at = datetime.now(timezone.utc)
        db_plan.status = "executing"
        plan_db_id = db_plan.id
        step_db_id = step.id
        step_content = step.content
        plan_title = db_plan.title
        await session.commit()

    await _render_plans_md(ch_id)

    try:
        await append_timeline(
            ch_id,
            f"Plan step {position} approved: **{step_content}** ({plan_id})",
        )
    except Exception:
        pass

    # Create the step task directly (advance_plan would re-pause at the gate)
    try:
        await _create_step_task(
            channel_id=ch_id,
            plan_id=plan_id,
            plan_title=plan_title,
            step_db_id=step_db_id,
            step_position=position,
            step_content=step_content,
        )
    except Exception:
        logger.warning("Failed to create step task for approved step %d", position, exc_info=True)

    return {"ok": True, "plan_id": plan_id, "step": position, "status": "approved"}
