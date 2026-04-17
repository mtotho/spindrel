"""Channel ↔ pipeline subscription endpoints.

A subscription says "channel X can run pipeline Y, optionally featured in
its launchpad, optionally on a cron schedule". Pipeline definitions are
Task rows (source=system | user with steps); subscriptions live in the
``channel_pipeline_subscriptions`` table.

Routes are mounted at ``/api/v1/admin`` → full paths:

    GET    /admin/channels/{channel_id}/pipelines
    POST   /admin/channels/{channel_id}/pipelines
    PATCH  /admin/channels/{channel_id}/pipelines/{subscription_id}
    DELETE /admin/channels/{channel_id}/pipelines/{subscription_id}
    GET    /admin/tasks/{task_id}/subscriptions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ChannelPipelineSubscription, Task
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubscriptionCreateIn(BaseModel):
    task_id: uuid.UUID
    enabled: bool = True
    featured_override: Optional[bool] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict] = None

    @field_validator("schedule")
    @classmethod
    def _validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        from app.services.cron_utils import validate_cron
        validate_cron(v)
        return v


class SubscriptionPatchIn(BaseModel):
    enabled: Optional[bool] = None
    featured_override: Optional[bool] = None
    schedule: Optional[str] = None
    schedule_config: Optional[dict] = None
    # Sentinel: explicitly clear schedule by sending clear_schedule=True.
    # We cannot use schedule=None to mean "clear" because pydantic's
    # exclude_unset pattern can't distinguish "unset" from "null".
    clear_schedule: bool = False

    @field_validator("schedule")
    @classmethod
    def _validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        from app.services.cron_utils import validate_cron
        validate_cron(v)
        return v


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    task_id: uuid.UUID
    enabled: bool
    featured_override: Optional[bool]
    featured: bool  # resolved: featured_override ?? execution_config.featured
    schedule: Optional[str]
    schedule_config: Optional[dict]
    last_fired_at: Optional[datetime]
    next_fire_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # Joined pipeline detail for UI convenience
    pipeline: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pipeline_dict(task: Task) -> dict:
    ec = task.execution_config or {}
    return {
        "id": str(task.id),
        "title": task.title,
        "bot_id": task.bot_id,
        "source": task.source,
        "task_type": task.task_type,
        "description": ec.get("description"),
        "featured": bool(ec.get("featured")),
        "params_schema": ec.get("params_schema"),
        "requires_channel": bool(ec.get("requires_channel")),
        "requires_bot": bool(ec.get("requires_bot")),
    }


def _sub_out(sub: ChannelPipelineSubscription, task: Task | None) -> dict:
    ec = (task.execution_config or {}) if task else {}
    default_featured = bool(ec.get("featured"))
    featured = (
        sub.featured_override if sub.featured_override is not None else default_featured
    )
    return {
        "id": str(sub.id),
        "channel_id": str(sub.channel_id),
        "task_id": str(sub.task_id),
        "enabled": sub.enabled,
        "featured_override": sub.featured_override,
        "featured": featured,
        "schedule": sub.schedule,
        "schedule_config": sub.schedule_config,
        "last_fired_at": sub.last_fired_at.isoformat() if sub.last_fired_at else None,
        "next_fire_at": sub.next_fire_at.isoformat() if sub.next_fire_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        "pipeline": _pipeline_dict(task) if task else None,
    }


async def _compute_next_fire(schedule: Optional[str]) -> Optional[datetime]:
    """Return the next fire time for a cron expression, or None if unset."""
    if not schedule:
        return None
    from app.services.cron_utils import next_fire_at
    return next_fire_at(schedule, datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Channel-scoped endpoints
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/pipelines")
async def list_channel_pipelines(
    channel_id: uuid.UUID,
    enabled: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """List all pipeline subscriptions for a channel with joined pipeline detail.

    Pass ``enabled=true`` to restrict to active subscriptions (launchpad use).
    """
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    stmt = select(ChannelPipelineSubscription).where(
        ChannelPipelineSubscription.channel_id == channel_id
    )
    if enabled is not None:
        stmt = stmt.where(ChannelPipelineSubscription.enabled == enabled)
    subs = (await db.execute(stmt)).scalars().all()

    # Batch-fetch joined tasks
    task_ids = [s.task_id for s in subs]
    tasks_by_id: dict[uuid.UUID, Task] = {}
    if task_ids:
        rows = (await db.execute(select(Task).where(Task.id.in_(task_ids)))).scalars().all()
        tasks_by_id = {t.id: t for t in rows}

    return {
        "subscriptions": [_sub_out(s, tasks_by_id.get(s.task_id)) for s in subs],
    }


@router.post("/channels/{channel_id}/pipelines", status_code=201)
async def subscribe_channel_pipeline(
    channel_id: uuid.UUID,
    body: SubscriptionCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    """Subscribe a channel to a pipeline definition."""
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    task = await db.get(Task, body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Guard: only pipeline-type tasks (or tasks with steps) make sense here.
    if task.task_type != "pipeline" and not task.steps:
        raise HTTPException(
            status_code=400,
            detail="Only pipeline-type tasks can be subscribed (task has no steps)",
        )

    existing = (await db.execute(
        select(ChannelPipelineSubscription).where(
            ChannelPipelineSubscription.channel_id == channel_id,
            ChannelPipelineSubscription.task_id == body.task_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Channel is already subscribed to this pipeline",
        )

    sub = ChannelPipelineSubscription(
        channel_id=channel_id,
        task_id=body.task_id,
        enabled=body.enabled,
        featured_override=body.featured_override,
        schedule=body.schedule,
        schedule_config=body.schedule_config,
    )
    if body.schedule and body.enabled:
        sub.next_fire_at = await _compute_next_fire(body.schedule)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return _sub_out(sub, task)


@router.patch("/channels/{channel_id}/pipelines/{subscription_id}")
async def update_channel_pipeline_subscription(
    channel_id: uuid.UUID,
    subscription_id: uuid.UUID,
    body: SubscriptionPatchIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    sub = await db.get(ChannelPipelineSubscription, subscription_id)
    if sub is None or sub.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Subscription not found")

    fields = body.model_dump(exclude_unset=True)
    fields.pop("clear_schedule", None)
    schedule_touched = "schedule" in fields or body.clear_schedule or "enabled" in fields

    for key, value in fields.items():
        setattr(sub, key, value)
    if body.clear_schedule:
        sub.schedule = None
        sub.schedule_config = None

    if schedule_touched:
        if sub.schedule and sub.enabled:
            sub.next_fire_at = await _compute_next_fire(sub.schedule)
        else:
            sub.next_fire_at = None

    sub.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    task = await db.get(Task, sub.task_id)
    return _sub_out(sub, task)


@router.delete("/channels/{channel_id}/pipelines/{subscription_id}", status_code=204)
async def unsubscribe_channel_pipeline(
    channel_id: uuid.UUID,
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:write")),
):
    sub = await db.get(ChannelPipelineSubscription, subscription_id)
    if sub is None or sub.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(sub)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Task-scoped mirror (list channels subscribed to a pipeline)
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/subscriptions")
async def list_task_subscriptions(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("tasks:read")),
):
    """List every channel subscribed to this pipeline definition.

    Powers the admin/tasks "Subscribed channels" panel.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    stmt = (
        select(ChannelPipelineSubscription, Channel)
        .join(Channel, Channel.id == ChannelPipelineSubscription.channel_id)
        .where(ChannelPipelineSubscription.task_id == task_id)
        .order_by(Channel.name.asc())
    )
    rows = (await db.execute(stmt)).all()
    return {
        "subscriptions": [
            {
                **_sub_out(sub, task),
                "channel": {
                    "id": str(ch.id),
                    "name": ch.name,
                    "client_id": ch.client_id,
                },
            }
            for sub, ch in rows
        ],
    }
