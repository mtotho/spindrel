"""Bot CRUD endpoints: /bots, /bots/{id}, /bots/{id}/editor-data, /bots/{id}/memories."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.db.models import (
    Bot as BotRow,
    Memory,
    SandboxProfile,
    Skill as SkillRow,
    ToolEmbedding,
)
from app.dependencies import get_db, verify_auth

from ._helpers import _bot_to_out
from ._schemas import BotListOut, BotOut, MemoryListOut, MemoryOut

router = APIRouter()


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------

@router.get("/bots", response_model=BotListOut)
async def admin_bots_list(
    _auth: str = Depends(verify_auth),
):
    """List all bots with full config."""
    bots = list_bots()
    return BotListOut(
        bots=[_bot_to_out(b) for b in bots],
        total=len(bots),
    )


@router.get("/bots/{bot_id}", response_model=BotOut)
async def admin_bot_detail(
    bot_id: str,
    _auth: str = Depends(verify_auth),
):
    """Get a single bot's full config."""
    from app.agent.persona import get_persona
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")
    persona_content = await get_persona(bot_id)
    return _bot_to_out(bot, persona_content=persona_content)


# ---------------------------------------------------------------------------
# Editor data
# ---------------------------------------------------------------------------

class ToolGroupOut(BaseModel):
    integration: str
    is_core: bool
    packs: list[dict] = []
    total: int = 0


class SkillOptionOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class BotEditorDataOut(BaseModel):
    bot: BotOut
    tool_groups: list[ToolGroupOut] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    all_skills: list[SkillOptionOut] = []
    all_bots: list[dict] = []
    all_harnesses: list[str] = []
    all_sandbox_profiles: list[dict] = []


@router.get("/bots/{bot_id}/editor-data")
async def admin_bot_editor_data(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Get bot config + all available options for the editor UI.

    Use bot_id="new" to get a blank default bot for the create form.
    """
    from app.agent.bots import list_bots as _list_bots
    from app.agent.persona import get_persona
    from app.services.harness import harness_service
    from app.tools.mcp import _servers
    from app.tools.client_tools import _client_tools

    is_new = bot_id == "new"

    if is_new:
        bot_out = BotOut(id="", name="", model="", system_prompt="")
        all_skills_rows, tool_rows, sandbox_rows = await asyncio.gather(
            _fetch_all_skills(db),
            _fetch_tool_rows(db),
            _fetch_sandbox_profiles(db),
        )
    else:
        try:
            bot = get_bot(bot_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

        persona_content, all_skills_rows, tool_rows, sandbox_rows = await asyncio.gather(
            get_persona(bot_id),
            _fetch_all_skills(db),
            _fetch_tool_rows(db),
            _fetch_sandbox_profiles(db),
        )
        bot_out = _bot_to_out(bot, persona_content=persona_content)

    tool_groups = _build_tool_groups(tool_rows)
    mcp_servers = sorted(_servers.keys())
    client_tools = sorted(_client_tools.keys())

    all_skills = [
        SkillOptionOut(
            id=s.id,
            name=s.name,
            description=(s.content or "")[:200].split("\n")[0] if s.content else None,
        )
        for s in all_skills_rows
    ]

    all_bots_out = [
        {"id": b.id, "name": b.name}
        for b in _list_bots()
        if b.id != bot_id
    ]

    all_harnesses = harness_service.list_harnesses()

    sandbox_profiles = [
        {"name": p.name, "description": getattr(p, "description", None)}
        for p in sandbox_rows
    ]

    return BotEditorDataOut(
        bot=bot_out,
        tool_groups=[ToolGroupOut(**g) for g in tool_groups],
        mcp_servers=mcp_servers,
        client_tools=client_tools,
        all_skills=all_skills,
        all_bots=all_bots_out,
        all_harnesses=all_harnesses,
        all_sandbox_profiles=sandbox_profiles,
    )


async def _fetch_all_skills(db: AsyncSession):
    return (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()


async def _fetch_tool_rows(db: AsyncSession):
    return (await db.execute(
        select(
            ToolEmbedding.tool_name,
            ToolEmbedding.server_name,
            ToolEmbedding.source_integration,
            ToolEmbedding.source_file,
        ).order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).all()


async def _fetch_sandbox_profiles(db: AsyncSession):
    return (await db.execute(
        select(SandboxProfile)
        .where(SandboxProfile.enabled == True)  # noqa: E712
        .order_by(SandboxProfile.name)
    )).scalars().all()


def _build_tool_groups(tool_rows) -> list[dict]:
    from collections import defaultdict
    integration_packs: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in tool_rows:
        if r.server_name is not None:
            continue
        intg = r.source_integration or "core"
        pack = (r.source_file or "misc").replace(".py", "")
        integration_packs[intg][pack].append({"name": r.tool_name})

    ordered = (["core"] if "core" in integration_packs else []) + sorted(
        k for k in integration_packs if k != "core"
    )
    groups = []
    for intg_id in ordered:
        packs_dict = integration_packs[intg_id]
        groups.append({
            "integration": intg_id,
            "is_core": intg_id == "core",
            "packs": [
                {"pack": pn, "tools": sorted(packs_dict[pn], key=lambda t: t["name"])}
                for pn in sorted(packs_dict)
            ],
            "total": sum(len(v) for v in packs_dict.values()),
        })
    return groups


# ---------------------------------------------------------------------------
# Bot update (JSON PUT)
# ---------------------------------------------------------------------------

class BotUpdateIn(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    model_provider_id: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    client_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    skills: Optional[list[dict]] = None
    tool_retrieval: Optional[bool] = None
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: Optional[dict] = None
    compression_config: Optional[dict] = None
    persona: Optional[bool] = None
    persona_content: Optional[str] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    audio_input: Optional[str] = None
    memory_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_max_inject_chars: Optional[int] = None
    knowledge_max_inject_chars: Optional[int] = None
    integration_config: Optional[dict] = None
    workspace: Optional[dict] = None
    docker_sandbox_profiles: Optional[list[str]] = None
    delegation_config: Optional[dict] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None


@router.put("/bots/{bot_id}", response_model=BotOut)
async def admin_bot_update(
    bot_id: str,
    data: BotUpdateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Update a bot's config via JSON."""
    from app.agent.bots import reload_bots
    from app.agent.persona import get_persona, write_persona

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    updates = data.model_dump(exclude_none=True)

    persona_content_val = updates.pop("persona_content", None)

    if "memory_config" in updates:
        row.memory_config = updates.pop("memory_config")
    if "knowledge_config" in updates:
        row.knowledge_config = updates.pop("knowledge_config")

    if "skills" in updates:
        row.skills = updates.pop("skills")

    for key, val in updates.items():
        if hasattr(row, key):
            setattr(row, key, val)

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if persona_content_val is not None:
        await write_persona(bot_id, persona_content_val)

    await reload_bots()

    bot = get_bot(bot_id)
    pc = await get_persona(bot_id)
    return _bot_to_out(bot, persona_content=pc)


# ---------------------------------------------------------------------------
# Bot create (JSON POST)
# ---------------------------------------------------------------------------

class BotCreateIn(BaseModel):
    id: str
    name: str
    model: str
    system_prompt: Optional[str] = ""
    model_provider_id: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    client_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    skills: Optional[list[dict]] = None
    tool_retrieval: Optional[bool] = True
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: Optional[dict] = None
    compression_config: Optional[dict] = None
    persona: Optional[bool] = False
    persona_content: Optional[str] = None
    context_compaction: Optional[bool] = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    audio_input: Optional[str] = "transcribe"
    memory_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_max_inject_chars: Optional[int] = None
    knowledge_max_inject_chars: Optional[int] = None
    integration_config: Optional[dict] = None
    workspace: Optional[dict] = None
    docker_sandbox_profiles: Optional[list[str]] = None
    delegation_config: Optional[dict] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None


@router.post("/bots", response_model=BotOut, status_code=201)
async def admin_bot_create(
    data: BotCreateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Create a new bot."""
    import re
    from app.agent.bots import reload_bots
    from app.agent.persona import write_persona

    if not data.id or not re.match(r"^[a-z0-9_-]+$", data.id):
        raise HTTPException(status_code=400, detail="Bot ID must be lowercase alphanumeric with hyphens/underscores")
    if not data.name:
        raise HTTPException(status_code=400, detail="Bot name is required")
    if not data.model:
        raise HTTPException(status_code=400, detail="Model is required")

    existing = await db.get(BotRow, data.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Bot already exists: {data.id}")

    fields = data.model_dump(exclude_none=True)
    persona_content_val = fields.pop("persona_content", None)

    row = BotRow(
        id=fields.pop("id"),
        name=fields.pop("name"),
        model=fields.pop("model"),
        system_prompt=fields.pop("system_prompt", ""),
    )

    if "memory_config" in fields:
        row.memory_config = fields.pop("memory_config")
    if "knowledge_config" in fields:
        row.knowledge_config = fields.pop("knowledge_config")
    if "skills" in fields:
        row.skills = fields.pop("skills")

    for key, val in fields.items():
        if hasattr(row, key):
            setattr(row, key, val)

    db.add(row)
    await db.commit()

    if persona_content_val:
        await write_persona(data.id, persona_content_val)

    await reload_bots()

    bot = get_bot(data.id)
    return _bot_to_out(bot)


# ---------------------------------------------------------------------------
# Bot memories
# ---------------------------------------------------------------------------

@router.get("/bots/{bot_id}/memories", response_model=MemoryListOut)
async def admin_bot_memories(
    bot_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """List memories for a specific bot."""
    memories = (await db.execute(
        select(Memory)
        .where(Memory.bot_id == bot_id)
        .order_by(Memory.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    return MemoryListOut(
        memories=[
            MemoryOut(
                id=m.id, session_id=m.session_id, client_id=m.client_id,
                bot_id=m.bot_id, content=m.content,
                message_count=m.message_count, correlation_id=m.correlation_id,
                created_at=m.created_at,
            )
            for m in memories
        ],
    )
