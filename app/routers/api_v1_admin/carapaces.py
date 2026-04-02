"""Carapaces CRUD: /carapaces."""
from __future__ import annotations

from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Carapace as CarapaceRow
from app.dependencies import get_db, verify_auth_or_user
from app.routers._carapace_schemas import (
    CarapaceCreateIn,
    CarapaceOut,
    CarapaceUpdateIn,
    try_reload as _try_reload,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/carapaces", response_model=list[CarapaceOut])
async def admin_list_carapaces(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    rows = (await db.execute(
        select(CarapaceRow).order_by(CarapaceRow.name)
    )).scalars().all()
    return [CarapaceOut.model_validate(r) for r in rows]


@router.get("/carapaces/{carapace_id}", response_model=CarapaceOut)
async def admin_get_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    return CarapaceOut.model_validate(row)


@router.post("/carapaces", response_model=CarapaceOut, status_code=201)
async def admin_create_carapace(
    body: CarapaceCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    cid = body.id.strip().lower().replace(" ", "-")
    if not cid or not body.name.strip():
        raise HTTPException(status_code=422, detail="id and name are required")

    existing = await db.get(CarapaceRow, cid)
    if existing:
        raise HTTPException(status_code=409, detail=f"Carapace '{cid}' already exists")

    now = datetime.now(timezone.utc)
    row = CarapaceRow(
        id=cid,
        name=body.name.strip(),
        description=body.description,
        skills=body.skills,
        local_tools=body.local_tools,
        mcp_tools=body.mcp_tools,
        pinned_tools=body.pinned_tools,
        system_prompt_fragment=body.system_prompt_fragment,
        includes=body.includes,
        delegates=body.delegates,
        tags=body.tags,
        source_type="manual",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Reload in-memory registry (best-effort — won't work in tests)
    await _try_reload()

    return CarapaceOut.model_validate(row)


@router.put("/carapaces/{carapace_id}", response_model=CarapaceOut)
async def admin_update_carapace(
    carapace_id: str,
    body: CarapaceUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot edit a file-managed carapace")

    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description
    if body.skills is not None:
        row.skills = body.skills
    if body.local_tools is not None:
        row.local_tools = body.local_tools
    if body.mcp_tools is not None:
        row.mcp_tools = body.mcp_tools
    if body.pinned_tools is not None:
        row.pinned_tools = body.pinned_tools
    if body.system_prompt_fragment is not None:
        row.system_prompt_fragment = body.system_prompt_fragment
    if body.includes is not None:
        row.includes = body.includes
    if body.delegates is not None:
        row.delegates = body.delegates
    if body.tags is not None:
        row.tags = body.tags
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    await _try_reload()

    return CarapaceOut.model_validate(row)


@router.delete("/carapaces/{carapace_id}")
async def admin_delete_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")
    if row.source_type in ("file", "integration"):
        raise HTTPException(status_code=403, detail="Cannot delete a file-managed carapace")
    await db.delete(row)
    await db.commit()

    await _try_reload()

    return {"ok": True}


class ResolvedCarapaceOut(BaseModel):
    """Flattened result of resolving a carapace + all its includes."""
    skills: list[dict] = []
    local_tools: list[str] = []
    mcp_tools: list[str] = []
    pinned_tools: list[str] = []
    system_prompt_fragments: list[str] = []
    delegates: list[dict] = []
    resolved_ids: list[str] = []  # All carapace IDs that contributed


@router.get("/carapaces/{carapace_id}/resolve", response_model=ResolvedCarapaceOut)
async def admin_resolve_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Resolve a carapace and its includes into a flat preview."""
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")

    from app.agent.carapaces import resolve_carapaces
    resolved = resolve_carapaces([carapace_id])

    # Collect all contributing carapace IDs by walking the tree
    contributing: list[str] = []
    def _walk(cid: str, visited: set[str]) -> None:
        if cid in visited:
            return
        visited.add(cid)
        contributing.append(cid)
        from app.agent.carapaces import get_carapace
        c = get_carapace(cid)
        if c:
            for inc in c.get("includes", []):
                _walk(inc, visited)
    _walk(carapace_id, set())

    return ResolvedCarapaceOut(
        skills=[{"id": s.id, "mode": s.mode} for s in resolved.skills],
        local_tools=resolved.local_tools,
        mcp_tools=resolved.mcp_tools,
        pinned_tools=resolved.pinned_tools,
        system_prompt_fragments=resolved.system_prompt_fragments,
        delegates=[
            {"id": d.id, "type": d.type, "description": d.description, "model_tier": d.model_tier, "source_carapace": d.source_carapace}
            for d in resolved.delegates
        ],
        resolved_ids=contributing,
    )


class CarapaceUsageItem(BaseModel):
    type: str  # "bot" | "channel_extra" | "channel_inherited"
    id: str
    name: str | None = None
    auto_injected: bool = False  # True for the orchestrator:home auto-injection


@router.get("/carapaces/{carapace_id}/usage", response_model=list[CarapaceUsageItem])
async def admin_carapace_usage(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Return bots and channels that reference this carapace."""
    from app.db.models import Bot as BotModel, Channel as ChannelModel

    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")

    items: list[CarapaceUsageItem] = []

    # Bots with this carapace in their config
    bots = (await db.execute(select(BotModel))).scalars().all()
    for bot in bots:
        if carapace_id in (bot.carapaces or []):
            items.append(CarapaceUsageItem(type="bot", id=bot.id, name=bot.name))

    # Channels with this carapace in carapaces_extra
    channels = (await db.execute(
        select(ChannelModel).where(ChannelModel.carapaces_extra.isnot(None))
    )).scalars().all()
    for ch in channels:
        if carapace_id in (ch.carapaces_extra or []):
            auto = ch.client_id == "orchestrator:home" and carapace_id == "orchestrator"
            items.append(CarapaceUsageItem(
                type="channel_extra",
                id=str(ch.id),
                name=ch.name or ch.client_id,
                auto_injected=auto,
            ))

    # Channels that inherit via their bot's carapaces list
    bot_ids_with_carapace = {b.id for b in bots if carapace_id in (b.carapaces or [])}
    if bot_ids_with_carapace:
        inherited_chs = (await db.execute(
            select(ChannelModel).where(ChannelModel.bot_id.in_(bot_ids_with_carapace))
        )).scalars().all()
        extra_ch_ids = {str(ch.id) for ch in channels if carapace_id in (ch.carapaces_extra or [])}
        for ch in inherited_chs:
            if str(ch.id) not in extra_ch_ids:
                items.append(CarapaceUsageItem(
                    type="channel_inherited",
                    id=str(ch.id),
                    name=ch.name or ch.client_id,
                ))

    return items


@router.post("/carapaces/{carapace_id}/export")
async def admin_export_carapace(
    carapace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Export a carapace as YAML."""
    row = await db.get(CarapaceRow, carapace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Carapace not found")

    data = {
        "id": row.id,
        "name": row.name,
    }
    if row.description:
        data["description"] = row.description
    if row.tags:
        data["tags"] = row.tags
    if row.skills:
        data["skills"] = row.skills
    if row.local_tools:
        data["local_tools"] = row.local_tools
    if row.mcp_tools:
        data["mcp_tools"] = row.mcp_tools
    if row.pinned_tools:
        data["pinned_tools"] = row.pinned_tools
    if row.includes:
        data["includes"] = row.includes
    if row.delegates:
        data["delegates"] = row.delegates
    if row.system_prompt_fragment:
        data["system_prompt_fragment"] = row.system_prompt_fragment

    return PlainTextResponse(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        media_type="text/yaml",
    )
