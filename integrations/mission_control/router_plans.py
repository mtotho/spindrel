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
from integrations.mission_control.schemas import (
    MCPlan,
    MCPlanCreateRequest,
    MCPlanStep,
    MCPlanUpdateRequest,
    MCPlansResponse,
    PlanFromTemplateRequest,
    PlanTemplateCreateRequest,
    SaveAsTemplateRequest,
)
from integrations.mission_control.services import (
    approve_plan,
    create_plan_from_template,
    create_plan_template,
    delete_plan_template,
    export_plan_json,
    export_plan_md,
    get_plan_template,
    get_single_plan,
    list_plan_templates,
    reject_plan,
    resume_plan,
    save_plan_as_template,
)

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
                created_at=p.get("created_at"),
                updated_at=p.get("updated_at"),
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


@router.get("/channels/{channel_id}/plans/{plan_id}")
async def get_plan_detail(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Get a single plan with full detail."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    plan_dict = await get_single_plan(str(channel.id), plan_id)
    if not plan_dict:
        raise HTTPException(404, f"Plan '{plan_id}' not found")

    return MCPlan(
        id=plan_dict["meta"].get("id", ""),
        title=plan_dict["title"],
        status=plan_dict["status"],
        meta=plan_dict.get("meta", {}),
        steps=[MCPlanStep(**s) for s in plan_dict.get("steps", [])],
        notes=plan_dict.get("notes", ""),
        channel_id=str(channel.id),
        channel_name=channel.name,
        created_at=plan_dict.get("created_at"),
        updated_at=plan_dict.get("updated_at"),
    )


@router.post("/channels/{channel_id}/plans")
async def create_plan_endpoint(
    channel_id: uuid.UUID,
    body: MCPlanCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Create a draft plan from the UI."""
    from datetime import date

    from app.services.plan_board import generate_plan_id
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.services import (
        _ensure_plans_migrated,
        _render_plans_md,
        append_timeline,
    )

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    if not body.steps:
        raise HTTPException(422, "At least one step is required")

    ch_id = str(channel.id)
    await _ensure_plans_migrated(ch_id)

    new_plan_id = generate_plan_id()

    async with await mc_session() as session:
        db_plan = McPlan(
            channel_id=ch_id,
            plan_id=new_plan_id,
            title=body.title,
            status="draft",
            notes=body.notes,
            created_date=date.today().isoformat(),
        )
        session.add(db_plan)
        await session.flush()

        for i, step in enumerate(body.steps, 1):
            session.add(McPlanStep(
                plan_id=db_plan.id,
                position=i,
                content=step.content,
                status="pending",
                requires_approval=step.requires_approval,
            ))

        await session.commit()

    await _render_plans_md(ch_id)

    try:
        await append_timeline(ch_id, f"Plan drafted: **{body.title}** ({new_plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan create", exc_info=True)

    return {"ok": True, "plan_id": new_plan_id, "status": "draft"}


@router.patch("/channels/{channel_id}/plans/{plan_id}")
async def update_plan_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    body: MCPlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Edit a draft plan (title, notes, steps). Steps are full-replacement."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep
    from integrations.mission_control.services import (
        _ensure_plans_migrated,
        _render_plans_md,
        append_timeline,
    )
    from sqlalchemy import select as sa_select

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    ch_id = str(channel.id)
    await _ensure_plans_migrated(ch_id)

    async with await mc_session() as session:
        result = await session.execute(
            sa_select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == ch_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            raise HTTPException(404, f"Plan '{plan_id}' not found")
        if db_plan.status != "draft":
            raise HTTPException(409, f"Can only edit draft plans (current: {db_plan.status})")

        if body.title is not None:
            db_plan.title = body.title
        if body.notes is not None:
            db_plan.notes = body.notes

        if body.steps is not None:
            if not body.steps:
                raise HTTPException(422, "At least one step is required")
            # Full replacement: delete existing steps, insert new
            await session.refresh(db_plan, ["steps"])
            for s in list(db_plan.steps):
                await session.delete(s)
            await session.flush()
            for i, step in enumerate(body.steps, 1):
                session.add(McPlanStep(
                    plan_id=db_plan.id,
                    position=i,
                    content=step.content,
                    status="pending",
                    requires_approval=step.requires_approval,
                ))

        await session.commit()

    await _render_plans_md(ch_id)

    try:
        await append_timeline(ch_id, f"Plan edited: **{db_plan.title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan edit", exc_info=True)

    return {"ok": True, "plan_id": plan_id, "status": "draft"}


@router.post("/channels/{channel_id}/plans/{plan_id}/steps/{position}/skip")
async def skip_step_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    position: int,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Skip a pending step in an executing/awaiting_approval plan."""
    from datetime import datetime, timezone

    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan
    from integrations.mission_control.plan_executor import advance_plan
    from integrations.mission_control.services import _render_plans_md, append_timeline
    from sqlalchemy import select as sa_select

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    ch_id = str(channel.id)

    async with await mc_session() as session:
        result = await session.execute(
            sa_select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == ch_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            raise HTTPException(404, f"Plan '{plan_id}' not found")
        if db_plan.status not in ("executing", "awaiting_approval"):
            raise HTTPException(
                409,
                f"Plan is [{db_plan.status}], expected [executing] or [awaiting_approval]",
            )

        await session.refresh(db_plan, ["steps"])
        step = next((s for s in db_plan.steps if s.position == position), None)
        if not step:
            raise HTTPException(404, f"Step {position} not found in plan '{plan_id}'")
        if step.status != "pending":
            raise HTTPException(409, f"Step {position} is [{step.status}], expected [pending]")

        step.status = "skipped"
        step.completed_at = datetime.now(timezone.utc)

        # If plan was awaiting_approval at this step, set back to executing
        if db_plan.status == "awaiting_approval":
            db_plan.status = "executing"

        plan_db_id = db_plan.id
        step_content = step.content
        await session.commit()

    await _render_plans_md(ch_id)

    try:
        await append_timeline(
            ch_id,
            f"Plan step {position} skipped: **{step_content}** ({plan_id})",
        )
    except Exception:
        pass

    # Advance to next step
    try:
        await advance_plan(plan_db_id)
    except Exception:
        logger.warning("Failed to advance plan after skip", exc_info=True)

    return {"ok": True, "plan_id": plan_id, "step": position, "status": "skipped"}


@router.delete("/channels/{channel_id}/plans/{plan_id}")
async def delete_plan_endpoint(
    channel_id: uuid.UUID,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Delete a plan. Only allowed for draft/complete/abandoned plans."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan
    from integrations.mission_control.services import (
        _ensure_plans_migrated,
        _render_plans_md,
        append_timeline,
    )
    from sqlalchemy import select as sa_select

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    ch_id = str(channel.id)
    await _ensure_plans_migrated(ch_id)

    async with await mc_session() as session:
        result = await session.execute(
            sa_select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == ch_id)
        )
        db_plan = result.scalar_one_or_none()
        if not db_plan:
            raise HTTPException(404, f"Plan '{plan_id}' not found")
        if db_plan.status not in ("draft", "complete", "abandoned"):
            raise HTTPException(
                409,
                f"Cannot delete plan in [{db_plan.status}] status "
                f"(allowed: draft, complete, abandoned)",
            )

        plan_title = db_plan.title
        # Cascade delete handles steps
        await session.delete(db_plan)
        await session.commit()

    await _render_plans_md(ch_id)

    try:
        await append_timeline(ch_id, f"Plan deleted: **{plan_title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan delete", exc_info=True)

    return {"ok": True, "plan_id": plan_id}


# ---------------------------------------------------------------------------
# Plan Templates
# ---------------------------------------------------------------------------

@router.get("/plans/templates")
async def list_templates(auth=Depends(verify_auth_or_user)):
    """List all plan templates."""
    templates = await list_plan_templates()
    return {"templates": templates}


@router.post("/plans/templates")
async def create_template(
    body: PlanTemplateCreateRequest,
    auth=Depends(verify_auth_or_user),
):
    """Create a plan template."""
    if not body.steps:
        raise HTTPException(422, "At least one step is required")

    steps = [{"content": s.content, "requires_approval": s.requires_approval} for s in body.steps]
    tpl = await create_plan_template(body.name, body.description, steps)
    return {"ok": True, "template": tpl}


@router.delete("/plans/templates/{template_id}")
async def delete_template(
    template_id: str,
    auth=Depends(verify_auth_or_user),
):
    """Delete a plan template."""
    try:
        await delete_plan_template(template_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/plans/templates/{template_id}/create-plan")
async def create_plan_from_template_endpoint(
    template_id: str,
    body: PlanFromTemplateRequest,
    channel_id: str = Query(..., description="Channel ID to create plan in"),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Create a draft plan from a template."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        plan_id = await create_plan_from_template(
            template_id, str(channel.id), body.title, body.notes,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"ok": True, "plan_id": plan_id, "status": "draft"}


@router.post("/channels/{channel_id}/plans/{plan_id}/save-template")
async def save_as_template(
    channel_id: uuid.UUID,
    plan_id: str,
    body: SaveAsTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Save a plan's steps as a reusable template."""
    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    try:
        tpl = await save_plan_as_template(
            str(channel.id), plan_id, body.name, body.description,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"ok": True, "template": tpl}


# ---------------------------------------------------------------------------
# Plan Export
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/plans/{plan_id}/export")
async def export_plan(
    channel_id: uuid.UUID,
    plan_id: str,
    format: str = Query("json", description="markdown or json"),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Export a plan as markdown or JSON."""
    from fastapi.responses import PlainTextResponse

    user = get_user(auth)
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    ch_id = str(channel.id)
    try:
        if format == "markdown":
            content = await export_plan_md(ch_id, plan_id)
            return PlainTextResponse(
                content,
                headers={"Content-Disposition": f'attachment; filename="plan-{plan_id}.md"'},
            )
        else:
            data = await export_plan_json(ch_id, plan_id)
            return data
    except ValueError as e:
        raise HTTPException(404, str(e))
