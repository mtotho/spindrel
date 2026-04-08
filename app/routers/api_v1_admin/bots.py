"""Bot CRUD endpoints: /bots, /bots/{id}, /bots/{id}/editor-data, /bots/{id}/memories."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.agent.bots import get_bot, list_bots
from app.db.models import (
    Bot as BotRow,
    Document,
    SandboxProfile,
    SharedWorkspace,
    SharedWorkspaceBot,
    Skill as SkillRow,
    ToolEmbedding,
)
from app.dependencies import get_db, require_scopes

from ._helpers import _bot_to_out
from ._schemas import BotListOut, BotOut

router = APIRouter()


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------

@router.get("/bots", response_model=BotListOut)
async def admin_bots_list(
    _auth=Depends(require_scopes("bots:read")),
):
    """List all bots with full config."""
    from app.agent.persona import resolve_workspace_persona

    bots = list_bots()
    out = []
    for b in bots:
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
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Get a single bot's full config."""
    from app.agent.persona import get_persona, resolve_workspace_persona
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")
    persona_content = await get_persona(bot_id)
    ws_persona = resolve_workspace_persona(bot.shared_workspace_id, bot_id)

    # Get api_permissions from linked key
    bot_row = await db.get(BotRow, bot_id)
    api_perms = await _get_bot_api_permissions(db, bot_row) if bot_row else None

    return _bot_to_out(
        bot,
        persona_content=persona_content,
        persona_from_workspace=ws_persona is not None,
        workspace_persona_content=ws_persona,
        api_permissions=api_perms,
    )


# ---------------------------------------------------------------------------
# Editor data
# ---------------------------------------------------------------------------

class ToolPackOut(BaseModel):
    pack: str
    label: str
    warning: Optional[str] = None
    tools: list[dict] = []


class ToolGroupOut(BaseModel):
    integration: str
    is_core: bool
    packs: list[ToolPackOut] = []
    total: int = 0


class SkillOptionOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    source_type: str = "manual"


class WorkspaceSkillOut(BaseModel):
    skill_id: str
    name: str
    mode: str  # pinned | rag | on_demand
    source_path: str
    bot_id: Optional[str] = None  # None = common skill
    workspace_id: str
    workspace_name: Optional[str] = None
    chunk_count: int = 0


class ResolvedToolEntry(BaseModel):
    name: str
    source: str  # "bot", "carapace:<id>", "memory_scheme"
    source_label: str  # human-readable: "Bot config", "Capability: Orchestrator", etc.
    integration: str = "core"  # integration grouping for the tool


class ResolvedPreview(BaseModel):
    """Bot-level resolved tools preview (before channel overrides)."""
    tools: list[ResolvedToolEntry] = []
    pinned_tools: list[ResolvedToolEntry] = []
    mcp_servers: list[ResolvedToolEntry] = []


class BotEditorDataOut(BaseModel):
    bot: BotOut
    tool_groups: list[ToolGroupOut] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    all_skills: list[SkillOptionOut] = []
    workspace_skills: list[WorkspaceSkillOut] = []
    all_bots: list[dict] = []
    all_sandbox_profiles: list[dict] = []
    model_param_definitions: list[dict] = []
    model_param_support: dict[str, list[str]] = {}
    resolved_preview: ResolvedPreview | None = None


@router.get("/bots/{bot_id}/editor-data")
async def admin_bot_editor_data(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Get bot config + all available options for the editor UI.

    Use bot_id="new" to get a blank default bot for the create form.
    """
    from app.agent.bots import list_bots as _list_bots
    from app.agent.persona import get_persona, resolve_workspace_persona
    from app.services.mcp_servers import list_server_names
    from app.tools.client_tools import _client_tools

    is_new = bot_id == "new"

    if is_new:
        from app.config import settings as _settings
        bot_out = BotOut(id="", name="", model=_settings.DEFAULT_MODEL, system_prompt="")
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
        ws_persona = resolve_workspace_persona(bot.shared_workspace_id, bot_id)
        bot_row = await db.get(BotRow, bot_id)
        api_perms = await _get_bot_api_permissions(db, bot_row) if bot_row else None
        bot_out = _bot_to_out(
            bot,
            persona_content=persona_content,
            persona_from_workspace=ws_persona is not None,
            workspace_persona_content=ws_persona,
            api_permissions=api_perms,
        )

    bot_memory_scheme = getattr(bot_out, "memory_scheme", None) if not is_new else None
    tool_groups = _build_tool_groups(tool_rows, memory_scheme=bot_memory_scheme)
    mcp_servers = list_server_names()
    client_tools = sorted(_client_tools.keys())

    all_skills = [
        SkillOptionOut(
            id=s.id,
            name=s.name,
            description=(s.content or "")[:200].split("\n")[0] if s.content else None,
            source_type=s.source_type or "manual",
        )
        for s in all_skills_rows
    ]

    all_bots_out = [
        {"id": b.id, "name": b.name}
        for b in _list_bots()
        if b.id != bot_id
    ]

    sandbox_profiles = [
        {"name": p.name, "description": getattr(p, "description", None)}
        for p in sandbox_rows
    ]

    from app.agent.model_params import MODEL_PARAM_SUPPORT, PARAM_DEFINITIONS

    # Fetch workspace skills for this bot (if it belongs to a workspace)
    ws_skills_out: list[WorkspaceSkillOut] = []
    if not is_new:
        ws_id = getattr(bot, "shared_workspace_id", None)
        if ws_id:  # Always true for enrolled bots
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

    # Resolve preview (full tool picture at bot level)
    resolved_preview = None
    if not is_new:
        try:
            resolved_preview = _build_resolved_preview(bot, tool_rows)
        except Exception:
            logger.warning("Failed to build resolved preview", exc_info=True)

    return BotEditorDataOut(
        bot=bot_out,
        tool_groups=[ToolGroupOut(**g) for g in tool_groups],
        mcp_servers=mcp_servers,
        client_tools=client_tools,
        all_skills=all_skills,
        workspace_skills=ws_skills_out,
        all_bots=all_bots_out,
        all_sandbox_profiles=sandbox_profiles,
        model_param_definitions=PARAM_DEFINITIONS,
        model_param_support={k: sorted(v) for k, v in MODEL_PARAM_SUPPORT.items()},
        resolved_preview=resolved_preview,
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
            ToolEmbedding.schema_,
        ).order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).all()


async def _fetch_sandbox_profiles(db: AsyncSession):
    return (await db.execute(
        select(SandboxProfile)
        .where(SandboxProfile.enabled == True)  # noqa: E712
        .order_by(SandboxProfile.name)
    )).scalars().all()


PACK_METADATA: dict[str, dict] = {
    "memory":       {"label": "Memory (DB)",    "deprecated": True},
    "memory_files": {"label": "Memory (Files)"},
    "knowledge":    {"label": "Knowledge (DB)", "deprecated": True},
    "plans":        {"label": "Plans (DB)",      "deprecated": True},
}


def _build_tool_groups(tool_rows, *, memory_scheme: str | None = None) -> list[dict]:
    from collections import defaultdict
    integration_packs: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in tool_rows:
        if r.server_name is not None:
            continue
        intg = r.source_integration or "core"
        pack = (r.source_file or "misc").replace(".py", "")
        schema = r.schema_ or {}
        fn = schema.get("function", {})
        integration_packs[intg][pack].append({
            "name": r.tool_name,
            "description": fn.get("description"),
        })

    ordered = (["core"] if "core" in integration_packs else []) + sorted(
        k for k in integration_packs if k != "core"
    )
    groups = []
    for intg_id in ordered:
        packs_dict = integration_packs[intg_id]
        packs_out = []
        for pn in sorted(packs_dict):
            meta = PACK_METADATA.get(pn, {})
            label = meta.get("label", pn)
            warning = None
            if meta.get("deprecated"):
                if memory_scheme == "workspace-files":
                    warning = "Not recommended with workspace-files memory scheme"
                else:
                    warning = "DB-based — consider workspace-files memory scheme instead"
            packs_out.append({
                "pack": pn,
                "label": label,
                "warning": warning,
                "tools": sorted(packs_dict[pn], key=lambda t: t["name"]),
            })
        groups.append({
            "integration": intg_id,
            "is_core": intg_id == "core",
            "packs": packs_out,
            "total": sum(len(v) for v in packs_dict.values()),
        })
    return groups


def _build_resolved_preview(bot, tool_rows) -> ResolvedPreview:
    """Compute the full resolved tool set at bot level (before channel overrides).

    Resolves carapaces and memory scheme to show what tools the bot will
    actually have at runtime, with provenance labels for each.
    """
    from app.agent.carapaces import get_carapace, resolve_carapaces

    # Build a lookup: tool_name → source_integration
    tool_integration: dict[str, str] = {}
    for r in tool_rows:
        if r.server_name is None:
            tool_integration[r.tool_name] = r.source_integration or "core"

    seen_tools: set[str] = set()
    tools: list[ResolvedToolEntry] = []
    seen_pinned: set[str] = set()
    pinned: list[ResolvedToolEntry] = []
    seen_mcp: set[str] = set()
    mcp: list[ResolvedToolEntry] = []

    def _add_tool(name: str, source: str, source_label: str) -> None:
        if name in seen_tools:
            return
        seen_tools.add(name)
        tools.append(ResolvedToolEntry(
            name=name, source=source, source_label=source_label,
            integration=tool_integration.get(name, "core"),
        ))

    def _add_pinned(name: str, source: str, source_label: str) -> None:
        if name in seen_pinned:
            return
        seen_pinned.add(name)
        pinned.append(ResolvedToolEntry(
            name=name, source=source, source_label=source_label,
            integration=tool_integration.get(name, "core"),
        ))

    def _add_mcp(name: str, source: str, source_label: str) -> None:
        if name in seen_mcp:
            return
        seen_mcp.add(name)
        mcp.append(ResolvedToolEntry(
            name=name, source=source, source_label=source_label,
        ))

    # 1. Bot-level local_tools
    for t in bot.local_tools or []:
        _add_tool(t, "bot", "Bot config")

    # 2. Bot-level pinned_tools
    for t in bot.pinned_tools or []:
        _add_pinned(t, "bot", "Bot config")

    # 3. Bot-level mcp_servers
    for t in bot.mcp_servers or []:
        _add_mcp(t, "bot", "Bot config")

    # 4. Carapace resolution — walk each carapace and its includes recursively
    carapace_ids = list(bot.carapaces or [])
    if carapace_ids:
        _visited_caps: set[str] = set()

        def _walk_carapace(cid: str, via: str | None = None, depth: int = 0) -> None:
            if cid in _visited_caps or depth > 5:
                return
            _visited_caps.add(cid)
            c = get_carapace(cid)
            if not c:
                return
            cap_name = c.get("name", cid)
            source = f"carapace:{cid}"
            label = f"Capability: {cap_name}" + (f" (via {via})" if via else "")

            # Resolve includes first (depth-first, matching resolve_carapaces order)
            for inc_id in c.get("includes", []):
                _walk_carapace(inc_id, via=cap_name, depth=depth + 1)

            for t in c.get("local_tools", []):
                _add_tool(t, source, label)
            for t in c.get("pinned_tools", []):
                _add_pinned(t, source, label)
            for t in c.get("mcp_tools", []):
                _add_mcp(t, source, label)

        for cid in carapace_ids:
            _walk_carapace(cid)

    # 5. Memory scheme injections
    memory_scheme = getattr(bot, "memory_scheme", None)
    if memory_scheme == "workspace-files":
        # Hide knowledge tools
        _hidden = {
            "upsert_knowledge", "append_to_knowledge", "edit_knowledge",
            "delete_knowledge", "get_knowledge", "list_knowledge_bases",
            "search_knowledge", "pin_knowledge", "unpin_knowledge",
            "set_knowledge_similarity_threshold",
        }
        tools[:] = [t for t in tools if t.name not in _hidden]
        seen_tools -= _hidden

        # Inject memory tools
        for t in ["search_memory", "get_memory_file", "file", "manage_bot_skill"]:
            _add_tool(t, "memory_scheme", "Memory scheme (workspace-files)")
            _add_pinned(t, "memory_scheme", "Memory scheme (workspace-files)")

    # 6. Auto-injected tools (always available at runtime)
    tool_retrieval = getattr(bot, "tool_retrieval", True)
    if tool_retrieval:
        _add_tool("get_tool_info", "auto", "Auto-injected (tool retrieval)")
        _add_pinned("get_tool_info", "auto", "Auto-injected (tool retrieval)")
    skills = getattr(bot, "skills", None)
    if skills:
        for _sk in ("get_skill", "get_skill_list"):
            _add_tool(_sk, "auto", "Auto-injected (skills)")
            _add_pinned(_sk, "auto", "Auto-injected (skills)")
    # activate_capability is injected dynamically when capability RAG finds matches
    _add_tool("activate_capability", "auto", "Auto-injected (capability discovery)")

    return ResolvedPreview(tools=tools, pinned_tools=pinned, mcp_servers=mcp)


# ---------------------------------------------------------------------------
# Bot update (JSON PUT)
# ---------------------------------------------------------------------------

class BotUpdateIn(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    model_provider_id: Optional[str] = None
    fallback_models: Optional[list[dict]] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    client_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    skills: Optional[list[dict]] = None
    tool_retrieval: Optional[bool] = None
    tool_discovery: Optional[bool] = None
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: Optional[dict] = None
    persona: Optional[bool] = None
    persona_content: Optional[str] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    context_pruning: Optional[bool] = None
    context_pruning_keep_turns: Optional[int] = None
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
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    user_id: Optional[str] = None
    api_permissions: Optional[list[str]] = None
    memory_scheme: Optional[str] = None  # "workspace-files"|null
    memory_hygiene_enabled: Optional[bool] = None
    memory_hygiene_interval_hours: Optional[int] = None
    memory_hygiene_prompt: Optional[str] = None
    memory_hygiene_only_if_active: Optional[bool] = None
    memory_hygiene_model: Optional[str] = None
    memory_hygiene_model_provider_id: Optional[str] = None
    memory_hygiene_target_hour: Optional[int] = None
    carapaces: Optional[list[str]] = None
    workspace_only: Optional[bool] = None
    system_prompt_workspace_file: Optional[bool] = None
    system_prompt_write_protected: Optional[bool] = None


@router.api_route("/bots/{bot_id}", methods=["PUT", "PATCH"], response_model=BotOut)
async def admin_bot_update(
    bot_id: str,
    data: BotUpdateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:write")),
):
    """Update a bot's config via JSON."""
    from app.agent.bots import reload_bots
    from app.agent.persona import get_persona, write_persona

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    updates = data.model_dump(exclude_unset=True)

    persona_content_val = updates.pop("persona_content", None)
    api_permissions_val = updates.pop("api_permissions", None)

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

    # Clear schedule when hygiene is explicitly disabled (so re-enable re-staggers)
    if updates.get("memory_hygiene_enabled") is False:
        row.next_hygiene_run_at = None

    row.updated_at = datetime.now(timezone.utc)

    # Handle api_permissions: auto-create/update scoped API key for this bot
    if api_permissions_val is not None:
        await _sync_bot_api_key(db, row, api_permissions_val)

    await db.commit()

    if persona_content_val is not None:
        await write_persona(bot_id, persona_content_val)

    # Sync write protection for system_prompt workspace file
    if "system_prompt_write_protected" in updates:
        try:
            sw_row = (await db.execute(
                select(SharedWorkspaceBot.workspace_id).where(SharedWorkspaceBot.bot_id == bot_id)
            )).scalar_one_or_none()
            if sw_row:
                sp_path = f"bots/{bot_id}/system_prompt.md"
                ws = await db.get(SharedWorkspace, sw_row)
                if ws:
                    wp = list(ws.write_protected_paths or [])
                    if updates["system_prompt_write_protected"] and sp_path not in wp:
                        wp.append(sp_path)
                    elif not updates["system_prompt_write_protected"] and sp_path in wp:
                        wp.remove(sp_path)
                    ws.write_protected_paths = wp
                    await db.commit()
        except Exception:
            logger.warning("Failed to sync write protection for bot %s", bot_id, exc_info=True)

    await reload_bots()

    bot = get_bot(bot_id)

    # Bootstrap memory directories when memory_scheme is set via PUT/PATCH
    if updates.get("memory_scheme") == "workspace-files":
        from app.services.memory_scheme import bootstrap_memory_scheme
        try:
            bootstrap_memory_scheme(bot)
        except Exception:
            pass  # non-fatal

    # Bootstrap next_hygiene_run_at when hygiene is enabled for the first time
    if updates.get("memory_hygiene_enabled") is True and row.next_hygiene_run_at is None:
        from app.services.memory_hygiene import bootstrap_hygiene_schedule
        try:
            await bootstrap_hygiene_schedule(row, db)
        except Exception:
            logger.warning("Failed to bootstrap hygiene schedule for bot %s", bot_id, exc_info=True)

    # Recalculate schedule when target_hour changes on an already-enabled bot
    if "memory_hygiene_target_hour" in updates and row.next_hygiene_run_at is not None:
        from app.services.memory_hygiene import _compute_next_run
        try:
            row.next_hygiene_run_at = _compute_next_run(row, datetime.now(timezone.utc), after_run=False)
            await db.commit()
        except Exception:
            logger.warning("Failed to recalculate hygiene schedule for bot %s", bot_id, exc_info=True)

    pc = await get_persona(bot_id)
    return _bot_to_out(bot, persona_content=pc, api_permissions=await _get_bot_api_permissions(db, row))


# ---------------------------------------------------------------------------
# Bot create (JSON POST)
# ---------------------------------------------------------------------------

class BotCreateIn(BaseModel):
    id: str
    name: str
    model: str
    system_prompt: Optional[str] = ""
    model_provider_id: Optional[str] = None
    fallback_models: Optional[list[dict]] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    client_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    skills: Optional[list[dict]] = None
    tool_retrieval: Optional[bool] = True
    tool_discovery: Optional[bool] = True
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: Optional[dict] = None
    persona: Optional[bool] = False
    persona_content: Optional[str] = None
    context_compaction: Optional[bool] = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    context_pruning: Optional[bool] = None
    context_pruning_keep_turns: Optional[int] = None
    history_mode: Optional[str] = "file"
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
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    user_id: Optional[str] = None
    memory_scheme: Optional[str] = None  # "workspace-files"|null
    memory_hygiene_enabled: Optional[bool] = None
    memory_hygiene_interval_hours: Optional[int] = None
    memory_hygiene_prompt: Optional[str] = None
    memory_hygiene_only_if_active: Optional[bool] = None
    memory_hygiene_model: Optional[str] = None
    memory_hygiene_model_provider_id: Optional[str] = None
    memory_hygiene_target_hour: Optional[int] = None


@router.post("/bots", response_model=BotOut, status_code=201)
async def admin_bot_create(
    data: BotCreateIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:write")),
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

    # Default memory_scheme to workspace-files for new bots
    fields.setdefault("memory_scheme", "workspace-files")

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
# Bot delete
# ---------------------------------------------------------------------------

@router.delete("/bots/{bot_id}", status_code=204)
async def admin_bot_delete(
    bot_id: str,
    force: bool = Query(False, description="Force delete even if bot has active channels"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:delete")),
):
    """Delete a bot and optionally its associated data."""
    from app.agent.bots import reload_bots
    from app.db.models import (
        ApiKey,
        BotPersona,
        Channel,
        FilesystemChunk,
        SandboxBotAccess,
        SandboxInstance,
        Session,
        Task,
        ToolCall,
        ToolPolicyRule,
        TraceEvent,
        WorkflowRun,
    )

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    if getattr(row, "source_type", "manual") == "system":
        raise HTTPException(status_code=403, detail="Cannot delete system bot")

    # Check for active channels
    channel_count = (await db.execute(
        select(func.count()).select_from(Channel).where(Channel.bot_id == bot_id)
    )).scalar() or 0

    if channel_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Bot has {channel_count} active channel(s) — delete or reassign them first, or use ?force=true",
        )

    # Cancel any running tasks before deletion (prevents task worker race)
    await db.execute(
        Task.__table__.update()
        .where(Task.bot_id == bot_id, Task.status.in_(["running", "pending"]))
        .values(status="cancelled")
    )

    # Force delete: cascade through associated data
    if force and channel_count > 0:
        # Get channel IDs for this bot
        channel_ids = (await db.execute(
            select(Channel.id).where(Channel.bot_id == bot_id)
        )).scalars().all()

        if channel_ids:
            # Get session IDs for these channels
            session_ids = (await db.execute(
                select(Session.id).where(Session.channel_id.in_(channel_ids))
            )).scalars().all()

            if session_ids:
                # Delete tool calls, trace events for sessions
                await db.execute(
                    ToolCall.__table__.delete().where(ToolCall.session_id.in_(session_ids))
                )
                await db.execute(
                    TraceEvent.__table__.delete().where(TraceEvent.session_id.in_(session_ids))
                )
                # Delete sessions
                await db.execute(
                    Session.__table__.delete().where(Session.id.in_(session_ids))
                )

            # Delete heartbeat configs + runs
            from app.db.models import ChannelHeartbeat, HeartbeatRun
            hb_ids = (await db.execute(
                select(ChannelHeartbeat.id).where(ChannelHeartbeat.channel_id.in_(channel_ids))
            )).scalars().all()
            if hb_ids:
                await db.execute(
                    HeartbeatRun.__table__.delete().where(HeartbeatRun.heartbeat_id.in_(hb_ids))
                )
                await db.execute(
                    ChannelHeartbeat.__table__.delete().where(ChannelHeartbeat.channel_id.in_(channel_ids))
                )

            # Delete channel integrations
            from app.db.models import ChannelIntegration
            await db.execute(
                ChannelIntegration.__table__.delete().where(ChannelIntegration.channel_id.in_(channel_ids))
            )

            # Null out active_session_id before deleting channels (FK constraint)
            await db.execute(
                Channel.__table__.update().where(Channel.id.in_(channel_ids)).values(active_session_id=None)
            )

            # Delete channels
            await db.execute(
                Channel.__table__.delete().where(Channel.id.in_(channel_ids))
            )

    # Delete bot-level associated data
    await db.execute(
        Task.__table__.delete().where(Task.bot_id == bot_id)
    )
    await db.execute(
        BotPersona.__table__.delete().where(BotPersona.bot_id == bot_id)
    )
    await db.execute(
        ToolPolicyRule.__table__.delete().where(ToolPolicyRule.bot_id == bot_id)
    )
    await db.execute(
        SandboxBotAccess.__table__.delete().where(SandboxBotAccess.bot_id == bot_id)
    )
    await db.execute(
        SandboxInstance.__table__.delete().where(
            SandboxInstance.scope_type == "bot", SandboxInstance.scope_key == bot_id
        )
    )
    await db.execute(
        WorkflowRun.__table__.delete().where(WorkflowRun.bot_id == bot_id)
    )

    # Delete shared workspace bot enrollment
    await db.execute(
        SharedWorkspaceBot.__table__.delete().where(SharedWorkspaceBot.bot_id == bot_id)
    )

    # Delete filesystem chunks associated with this bot
    await db.execute(
        FilesystemChunk.__table__.delete().where(FilesystemChunk.bot_id == bot_id)
    )

    # Deactivate bot's API key (credential hygiene)
    if row.api_key_id:
        api_key = await db.get(ApiKey, row.api_key_id)
        if api_key:
            api_key.is_active = False

    # Delete the bot row
    await db.delete(row)
    await db.commit()

    await reload_bots()
    return None


# ---------------------------------------------------------------------------
# Bot API key management helpers
# ---------------------------------------------------------------------------

async def _sync_bot_api_key(db: AsyncSession, bot_row: BotRow, scopes: list[str]) -> None:
    """Create or update the scoped API key for a bot based on permissions."""
    from app.db.models import ApiKey
    from app.services.api_keys import create_api_key, ALL_SCOPES

    # Validate scopes
    invalid = [s for s in scopes if s not in ALL_SCOPES]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid scopes: {invalid}")

    if bot_row.api_key_id:
        # Update existing key's scopes
        api_key = await db.get(ApiKey, bot_row.api_key_id)
        if api_key:
            api_key.scopes = scopes
            api_key.updated_at = datetime.now(timezone.utc)
            return

    # Create new key (store_key_value=True so we can inject it into containers)
    key_row, _full_key = await create_api_key(
        db,
        name=f"bot:{bot_row.id}",
        scopes=scopes,
        store_key_value=True,
    )
    bot_row.api_key_id = key_row.id


async def _get_bot_api_permissions(db: AsyncSession, bot_row: BotRow) -> list[str] | None:
    """Read the scopes from a bot's linked API key."""
    if not bot_row.api_key_id:
        return None
    from app.db.models import ApiKey
    api_key = await db.get(ApiKey, bot_row.api_key_id)
    if not api_key:
        return None
    return api_key.scopes or []


# ---------------------------------------------------------------------------
# Memory hygiene
# ---------------------------------------------------------------------------

class MemoryHygieneStatusOut(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    only_if_active: bool = True
    has_custom_prompt: bool = False
    resolved_prompt: str = ""
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_task_status: Optional[str] = None
    last_task_id: Optional[str] = None
    model: Optional[str] = None
    model_provider_id: Optional[str] = None
    target_hour: int = -1


@router.get("/bots/{bot_id}/memory-hygiene", response_model=MemoryHygieneStatusOut)
async def admin_bot_memory_hygiene_status(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Get resolved memory hygiene config + last/next run times."""
    from app.db.models import Task as TaskRow
    from app.services.memory_hygiene import (
        resolve_enabled, resolve_interval, resolve_model,
        resolve_model_provider_id, resolve_only_if_active, resolve_prompt,
        resolve_target_hour,
    )

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    enabled = resolve_enabled(row)
    interval = resolve_interval(row)
    only_active = resolve_only_if_active(row)
    prompt = resolve_prompt(row)
    model = resolve_model(row)
    model_provider = resolve_model_provider_id(row)
    target_hour = resolve_target_hour(row)

    from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT
    has_custom = bool(prompt and prompt != DEFAULT_MEMORY_HYGIENE_PROMPT)

    # Find last hygiene task
    last_task = (await db.execute(
        select(TaskRow.id, TaskRow.status, TaskRow.completed_at)
        .where(TaskRow.bot_id == bot_id, TaskRow.task_type == "memory_hygiene")
        .order_by(TaskRow.created_at.desc())
        .limit(1)
    )).first()

    return MemoryHygieneStatusOut(
        enabled=enabled,
        interval_hours=interval,
        only_if_active=only_active,
        has_custom_prompt=has_custom,
        resolved_prompt=prompt,
        last_run_at=row.last_hygiene_run_at.isoformat() if row.last_hygiene_run_at else None,
        next_run_at=row.next_hygiene_run_at.isoformat() if row.next_hygiene_run_at else None,
        last_task_status=last_task.status if last_task else None,
        last_task_id=str(last_task.id) if last_task else None,
        model=model,
        model_provider_id=model_provider,
        target_hour=target_hour,
    )


@router.post("/bots/{bot_id}/memory-hygiene/trigger")
async def admin_bot_memory_hygiene_trigger(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:write")),
):
    """Manually trigger a memory hygiene run for this bot."""
    from app.services.memory_hygiene import create_hygiene_task

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    if row.memory_scheme != "workspace-files":
        raise HTTPException(status_code=400, detail="Memory hygiene requires workspace-files memory scheme")

    task_id = await create_hygiene_task(bot_id, db)
    return {"status": "ok", "task_id": str(task_id)}


# ---------------------------------------------------------------------------
# Memory hygiene run history
# ---------------------------------------------------------------------------

class HygieneRunOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    correlation_id: Optional[str] = None
    tool_calls: list[dict] = []
    total_tokens: int = 0
    iterations: int = 0
    duration_ms: Optional[int] = None


class HygieneRunsResponse(BaseModel):
    runs: list[HygieneRunOut] = []
    total: int = 0


@router.get("/bots/{bot_id}/memory-hygiene/runs", response_model=HygieneRunsResponse)
async def admin_bot_memory_hygiene_runs(
    bot_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Get recent memory hygiene run history with enriched stats."""
    from app.db.models import Task as TaskRow, ToolCall, TraceEvent
    from app.routers.api_v1_admin._helpers import build_tool_call_previews

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    # Count total runs
    total = (await db.execute(
        select(func.count())
        .select_from(TaskRow)
        .where(TaskRow.bot_id == bot_id, TaskRow.task_type == "memory_hygiene")
    )).scalar() or 0

    # Fetch recent runs
    tasks = (await db.execute(
        select(TaskRow)
        .where(TaskRow.bot_id == bot_id, TaskRow.task_type == "memory_hygiene")
        .order_by(TaskRow.created_at.desc())
        .limit(limit)
    )).scalars().all()

    runs_out: list[HygieneRunOut] = []
    for t in tasks:
        runs_out.append(HygieneRunOut(
            id=str(t.id),
            status=t.status,
            created_at=t.created_at,
            completed_at=t.completed_at,
            result=(t.result[:500] if t.result and len(t.result) > 500 else t.result),
            error=t.error,
            correlation_id=str(t.correlation_id) if t.correlation_id else None,
        ))

    # Enrich with tool calls and token stats via correlation_id
    correlation_ids = [t.correlation_id for t in tasks if t.correlation_id]
    if correlation_ids:
        tc_rows = (await db.execute(
            select(ToolCall)
            .where(ToolCall.correlation_id.in_(correlation_ids))
            .order_by(ToolCall.created_at)
        )).scalars().all()
        tc_by_corr: dict = {}
        for tc in tc_rows:
            tc_by_corr.setdefault(tc.correlation_id, []).append(tc)

        te_rows = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.correlation_id.in_(correlation_ids),
                TraceEvent.event_type == "token_usage",
            )
        )).scalars().all()

        stats_by_corr: dict = {}
        for te in te_rows:
            s = stats_by_corr.setdefault(te.correlation_id, {"tokens": 0, "iterations": 0})
            if te.data:
                s["tokens"] += te.data.get("total_tokens", 0)
                s["iterations"] = max(s["iterations"], te.data.get("iteration", 0))

        for run, task in zip(runs_out, tasks):
            if not task.correlation_id:
                continue
            tcs = tc_by_corr.get(task.correlation_id, [])
            if tcs:
                run.tool_calls = build_tool_call_previews(tcs)
            stats = stats_by_corr.get(task.correlation_id)
            if stats:
                run.total_tokens = stats["tokens"]
                run.iterations = stats["iterations"]
            if task.completed_at and task.created_at:
                run.duration_ms = int((task.completed_at - task.created_at).total_seconds() * 1000)

    return HygieneRunsResponse(runs=runs_out, total=total)


# ---------------------------------------------------------------------------
# Memory scheme
# ---------------------------------------------------------------------------

@router.post("/bots/{bot_id}/memory-scheme")
async def admin_bot_enable_memory_scheme(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:write")),
):
    """Enable the workspace-files memory scheme on an existing bot.

    Sets memory_scheme, bootstraps directory structure, and triggers reindex.
    """
    from app.agent.bots import reload_bots
    from app.services.memory_scheme import bootstrap_memory_scheme

    row = await db.get(BotRow, bot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")

    row.memory_scheme = "workspace-files"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    await reload_bots()
    bot = get_bot(bot_id)

    # Bootstrap memory directories
    memory_root = bootstrap_memory_scheme(bot)

    # Trigger filesystem reindex for the memory directory
    try:
        from app.services.memory_indexing import index_memory_for_bot
        await index_memory_for_bot(bot, force=True)
    except Exception:
        pass  # non-fatal; will be indexed on next natural cycle

    return {"status": "ok", "memory_scheme": "workspace-files", "memory_root": memory_root}


# ---------------------------------------------------------------------------
# Bot sandbox status + recreate
# ---------------------------------------------------------------------------

class SandboxStatusOut(BaseModel):
    exists: bool = False
    status: Optional[str] = None
    container_name: Optional[str] = None
    container_id: Optional[str] = None
    image_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


@router.get("/bots/{bot_id}/sandbox", response_model=SandboxStatusOut)
async def admin_bot_sandbox_status(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    """Get the status of a bot's local sandbox container."""
    from app.db.models import SandboxInstance

    instance = (await db.execute(
        select(SandboxInstance).where(
            SandboxInstance.scope_type == "bot",
            SandboxInstance.scope_key == bot_id,
        )
    )).scalar_one_or_none()

    if not instance:
        return SandboxStatusOut(exists=False)

    return SandboxStatusOut(
        exists=True,
        status=instance.status,
        container_name=instance.container_name,
        container_id=instance.container_id[:12] if instance.container_id else None,
        image_id=instance.image_id[:19] if instance.image_id else None,
        error_message=instance.error_message,
        created_at=instance.created_at,
        last_used_at=instance.last_used_at,
    )


@router.post("/bots/{bot_id}/sandbox/recreate")
async def admin_bot_sandbox_recreate(
    bot_id: str,
    _auth=Depends(require_scopes("bots:write")),
):
    """Recreate the bot's local sandbox container.

    Stops and removes the existing container. The next exec_command call
    will auto-create a fresh one with the latest config.
    """
    from app.services.sandbox import sandbox_service

    try:
        await sandbox_service.recreate_bot_local(bot_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok", "message": f"Sandbox for '{bot_id}' destroyed. Will be recreated on next use."}


