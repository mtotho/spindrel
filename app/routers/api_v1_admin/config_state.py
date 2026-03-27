"""Config state overview: GET /config-state → aggregated config snapshot."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import list_bots
from app.config import settings as app_settings
from app.db.models import (
    Channel,
    Document,
    ProviderConfig,
    SharedWorkspace,
    SharedWorkspaceBot,
    Skill,
    Task,
    User,
)
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


@router.get("/config-state")
async def get_config_state(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_config import get_global_fallback_models
    from app.services.server_settings import get_all_settings

    # --- System ---
    system = {
        "paused": getattr(app_settings, "SYSTEM_PAUSED", False),
        "pause_behavior": getattr(app_settings, "SYSTEM_PAUSE_BEHAVIOR", "queue"),
    }

    # --- Global fallback models ---
    global_fallback_models = get_global_fallback_models()

    # --- Settings (grouped) ---
    settings_groups = await get_all_settings()
    # Flatten to { group: { key: value } } for dense display
    settings_flat: dict[str, dict] = {}
    for group in settings_groups:
        settings_flat[group["group"]] = {
            s["key"]: s["value"] for s in group["settings"]
        }

    # --- Providers with model counts ---
    provider_rows = (
        await db.execute(
            select(ProviderConfig).options(selectinload(ProviderConfig.models))
        )
    ).scalars().all()
    providers = [
        {
            "id": p.id,
            "display_name": p.display_name,
            "provider_type": p.provider_type,
            "is_enabled": p.is_enabled,
            "base_url": p.base_url,
            "tpm_limit": p.tpm_limit,
            "rpm_limit": p.rpm_limit,
            "models": [
                {"model_id": m.model_id, "display_name": m.display_name, "max_tokens": m.max_tokens}
                for m in p.models
            ],
        }
        for p in provider_rows
    ]

    # --- Bots (from in-memory registry) ---
    bots = []
    for b in list_bots():
        bots.append({
            "id": b.id,
            "name": b.name,
            "model": b.model,
            "model_provider_id": b.model_provider_id,
            "system_prompt": (b.system_prompt[:200] + "...") if len(b.system_prompt) > 200 else b.system_prompt,
            "local_tools": b.local_tools,
            "mcp_servers": b.mcp_servers,
            "client_tools": b.client_tools,
            "skills": [s.id if hasattr(s, "id") else s for s in (b.skills or [])],
            "pinned_tools": b.pinned_tools,
            "tool_retrieval": b.tool_retrieval,
            "memory": {"enabled": b.memory.enabled, "cross_channel": b.memory.cross_channel} if b.memory else {},
            "knowledge": {"enabled": b.knowledge.enabled} if b.knowledge else {},
            "context_compaction": b.context_compaction,
            "elevation_enabled": b.elevation_enabled,
            "delegate_bots": b.delegate_bots if hasattr(b, "delegate_bots") else [],
            "harness_access": b.harness_access if hasattr(b, "harness_access") else [],
            "fallback_models": b.fallback_models or [],
            "history_mode": getattr(b, "history_mode", "file"),
        })

    # --- Channels ---
    channel_rows = (await db.execute(select(Channel))).scalars().all()
    channels = [
        {
            "id": str(ch.id),
            "name": ch.name,
            "bot_id": ch.bot_id,
            "client_id": ch.client_id,
            "integration": ch.integration,
            "overrides": {
                k: getattr(ch, k)
                for k in (
                    "model_override", "elevation_enabled", "context_compaction",
                    "compaction_interval", "compaction_keep_turns",
                    "local_tools_override", "skills_override",
                )
                if hasattr(ch, k) and getattr(ch, k) is not None
            },
        }
        for ch in channel_rows
    ]

    # --- Workspaces ---
    ws_rows = (
        await db.execute(
            select(SharedWorkspace).options(selectinload(SharedWorkspace.bots))
        )
    ).scalars().all()
    workspaces = [
        {
            "id": str(ws.id),
            "name": ws.name,
            "image": ws.image,
            "status": ws.status,
            "bots": [wb.bot_id for wb in ws.bots],
        }
        for ws in ws_rows
    ]

    # --- Skills with chunk counts ---
    skill_rows = (await db.execute(select(Skill))).scalars().all()
    # Count document chunks per skill source
    chunk_counts_q = (
        await db.execute(
            select(Document.source, func.count()).group_by(Document.source)
        )
    )
    chunk_map = {row[0]: row[1] for row in chunk_counts_q.all()}
    skills = [
        {
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "chunk_count": chunk_map.get(s.id, 0),
        }
        for s in skill_rows
    ]

    # --- Active/scheduled tasks (not completed) ---
    task_rows = (
        await db.execute(
            select(Task).where(Task.status.in_(["pending", "running"]))
        )
    ).scalars().all()
    # Also include recurring tasks regardless of status
    recurring_rows = (
        await db.execute(
            select(Task).where(Task.recurrence.isnot(None), Task.status.notin_(["pending", "running"]))
        )
    ).scalars().all()
    all_tasks = list(task_rows) + list(recurring_rows)
    tasks = [
        {
            "id": str(t.id),
            "bot_id": t.bot_id,
            "status": t.status,
            "task_type": t.task_type,
            "recurrence": t.recurrence,
            "channel_id": str(t.channel_id) if t.channel_id else None,
            "title": t.title,
        }
        for t in all_tasks
    ]

    # --- Users ---
    user_rows = (await db.execute(select(User))).scalars().all()
    users = [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
        }
        for u in user_rows
    ]

    return {
        "system": system,
        "global_fallback_models": global_fallback_models,
        "settings": settings_flat,
        "providers": providers,
        "bots": bots,
        "channels": channels,
        "workspaces": workspaces,
        "skills": skills,
        "tasks": tasks,
        "users": users,
    }
