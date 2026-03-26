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
    Document,
    Memory,
    SandboxProfile,
    SharedWorkspace,
    Skill as SkillRow,
    ToolEmbedding,
)
from app.dependencies import get_db, verify_auth_or_user

from ._helpers import _bot_to_out
from ._schemas import BotListOut, BotOut, MemoryListOut, MemoryOut

router = APIRouter()


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------

@router.get("/bots", response_model=BotListOut)
async def admin_bots_list(
    _auth: str = Depends(verify_auth_or_user),
):
    """List all bots with full config."""
    from app.agent.persona import resolve_workspace_persona

    bots = list_bots()
    out = []
    for b in bots:
        ws_persona = None
        if b.shared_workspace_id:
            ws_persona = resolve_workspace_persona(b.shared_workspace_id, b.id)
        out.append(_bot_to_out(
            b,
            persona_from_workspace=ws_persona is not None,
            workspace_persona_content=ws_persona,
        ))
    return BotListOut(bots=out, total=len(bots))


@router.get("/bots/{bot_id}", response_model=BotOut)
async def admin_bot_detail(
    bot_id: str,
    _auth: str = Depends(verify_auth_or_user),
):
    """Get a single bot's full config."""
    from app.agent.persona import get_persona, resolve_workspace_persona
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")
    persona_content = await get_persona(bot_id)
    ws_persona = None
    if bot.shared_workspace_id:
        ws_persona = resolve_workspace_persona(bot.shared_workspace_id, bot_id)
    return _bot_to_out(
        bot,
        persona_content=persona_content,
        persona_from_workspace=ws_persona is not None,
        workspace_persona_content=ws_persona,
    )


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


class WorkspaceSkillOut(BaseModel):
    skill_id: str
    name: str
    mode: str  # pinned | rag | on_demand
    source_path: str
    bot_id: Optional[str] = None  # None = common skill
    workspace_id: str
    workspace_name: Optional[str] = None
    chunk_count: int = 0


class BotEditorDataOut(BaseModel):
    bot: BotOut
    tool_groups: list[ToolGroupOut] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    all_skills: list[SkillOptionOut] = []
    workspace_skills: list[WorkspaceSkillOut] = []
    all_bots: list[dict] = []
    all_harnesses: list[str] = []
    all_sandbox_profiles: list[dict] = []
    model_param_definitions: list[dict] = []
    model_param_support: dict[str, list[str]] = {}


@router.get("/bots/{bot_id}/editor-data")
async def admin_bot_editor_data(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get bot config + all available options for the editor UI.

    Use bot_id="new" to get a blank default bot for the create form.
    """
    from app.agent.bots import list_bots as _list_bots
    from app.agent.persona import get_persona, resolve_workspace_persona
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
        ws_persona = None
        if bot.shared_workspace_id:
            ws_persona = resolve_workspace_persona(bot.shared_workspace_id, bot_id)
        bot_out = _bot_to_out(
            bot,
            persona_content=persona_content,
            persona_from_workspace=ws_persona is not None,
            workspace_persona_content=ws_persona,
        )

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

    from app.agent.model_params import MODEL_PARAM_SUPPORT, PARAM_DEFINITIONS

    # Fetch workspace skills for this bot (if it belongs to a workspace)
    ws_skills_out: list[WorkspaceSkillOut] = []
    if not is_new:
        ws_id = getattr(bot, "shared_workspace_id", None)
        if ws_id:
            ws_skill_rows = (await db.execute(
                select(
                    Document.metadata_["skill_id"].as_string().label("skill_id"),
                    Document.metadata_["skill_name"].as_string().label("skill_name"),
                    Document.metadata_["workspace_id"].as_string().label("workspace_id"),
                    Document.metadata_["mode"].as_string().label("mode"),
                    Document.metadata_["bot_id"].as_string().label("bot_id"),
                    Document.metadata_["source_path"].as_string().label("source_path"),
                    func.count().label("chunk_count"),
                )
                .where(
                    Document.source.like(f"workspace_skill:{ws_id}:%"),
                    # Common skills (bot_id is null) OR this bot's skills
                    (Document.metadata_["bot_id"].as_string().is_(None))
                    | (Document.metadata_["bot_id"].as_string() == bot_id),
                )
                .group_by("skill_id", "skill_name", "workspace_id", "mode", "bot_id", "source_path")
                .order_by("skill_name")
            )).all()
            # Fetch workspace name
            import uuid as _uuid
            _ws_pk = _uuid.UUID(ws_id) if isinstance(ws_id, str) else ws_id
            ws_row = await db.get(SharedWorkspace, _ws_pk)
            ws_name = ws_row.name if ws_row else ws_id
            for r in ws_skill_rows:
                ws_skills_out.append(WorkspaceSkillOut(
                    skill_id=r.skill_id,
                    name=r.skill_name or r.skill_id,
                    mode=r.mode or "pinned",
                    source_path=r.source_path or "",
                    bot_id=r.bot_id,
                    workspace_id=ws_id,
                    workspace_name=ws_name,
                    chunk_count=r.chunk_count,
                ))

    return BotEditorDataOut(
        bot=bot_out,
        tool_groups=[ToolGroupOut(**g) for g in tool_groups],
        mcp_servers=mcp_servers,
        client_tools=client_tools,
        all_skills=all_skills,
        workspace_skills=ws_skills_out,
        all_bots=all_bots_out,
        all_harnesses=all_harnesses,
        all_sandbox_profiles=sandbox_profiles,
        model_param_definitions=PARAM_DEFINITIONS,
        model_param_support={k: sorted(v) for k, v in MODEL_PARAM_SUPPORT.items()},
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
    history_mode: Optional[str] = None
    audio_input: Optional[str] = None
    memory_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_max_inject_chars: Optional[int] = None
    knowledge_max_inject_chars: Optional[int] = None
    integration_config: Optional[dict] = None
    workspace: Optional[dict] = None
    docker_sandbox_profiles: Optional[list[str]] = None
    model_params: Optional[dict] = None
    delegation_config: Optional[dict] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    user_id: Optional[str] = None


@router.api_route("/bots/{bot_id}", methods=["PUT", "PATCH"], response_model=BotOut)
async def admin_bot_update(
    bot_id: str,
    data: BotUpdateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Update a bot's config via JSON."""
    from app.agent.bots import reload_bots
    from app.agent.persona import get_persona, write_persona

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    updates = data.model_dump(exclude_unset=True)

    persona_content_val = updates.pop("persona_content", None)

    if "memory_config" in updates:
        row.memory_config = updates.pop("memory_config")
    if "knowledge_config" in updates:
        row.knowledge_config = updates.pop("knowledge_config")

    if "skills" in updates:
        row.skills = updates.pop("skills")

    # Convert user_id string to UUID
    if "user_id" in updates:
        import uuid as _uuid
        uid = updates.pop("user_id")
        row.user_id = _uuid.UUID(uid) if uid else None

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
    history_mode: Optional[str] = "summary"
    audio_input: Optional[str] = "transcribe"
    memory_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_max_inject_chars: Optional[int] = None
    knowledge_max_inject_chars: Optional[int] = None
    integration_config: Optional[dict] = None
    workspace: Optional[dict] = None
    docker_sandbox_profiles: Optional[list[str]] = None
    model_params: Optional[dict] = None
    delegation_config: Optional[dict] = None
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    user_id: Optional[str] = None


@router.post("/bots", response_model=BotOut, status_code=201)
async def admin_bot_create(
    data: BotCreateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
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

    # Convert user_id string to UUID
    if "user_id" in fields:
        import uuid as _uuid
        uid = fields.pop("user_id")
        row.user_id = _uuid.UUID(uid) if uid else None

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
    _auth: str = Depends(verify_auth_or_user),
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
