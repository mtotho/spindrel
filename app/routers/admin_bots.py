"""Admin bot CRUD routes."""
from __future__ import annotations
import logging
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from app.agent.bots import reload_bots
from app.agent.knowledge import list_knowledge_candidates_for_bot
from app.agent.persona import get_persona, write_persona
from app.config import settings
from app.agent.skills import re_embed_skill
from app.db.engine import async_session
from app.db.models import Bot as BotRow, SandboxProfile, Skill as SkillRow, ToolEmbedding
logger = logging.getLogger(__name__)
router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


async def _get_available_models() -> list[dict]:
    """Return model groups from all configured providers (for select optgroups)."""
    try:
        from app.services.providers import get_available_models_grouped
        return await get_available_models_grouped()
    except Exception:
        return []


async def _get_tool_options() -> dict:
    """Return available local tool names, MCP server names, client tool names, and tool_groups.

    tool_groups is a list of dicts:
      {"label": str, "tools": [{"name": str, "source_integration": str|None, "source_file": str|None}]}
    """
    from app.tools.mcp import _servers
    from app.tools.client_tools import _client_tools
    from sqlalchemy import select as sa_select

    async with async_session() as db:
        tool_rows = (await db.execute(
            sa_select(
                ToolEmbedding.tool_name,
                ToolEmbedding.server_name,
                ToolEmbedding.source_integration,
                ToolEmbedding.source_file,
            )
            .order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
        )).all()

    local_tools = sorted({r.tool_name for r in tool_rows if r.server_name is None})
    mcp_servers = sorted(_servers.keys())
    client_tools = sorted(_client_tools.keys())

    # Build tool_groups: ALL local tools grouped by Integration → Pack (source_file basename).
    # Tools with no source_integration go into the synthetic "core" integration.
    from collections import defaultdict
    integration_packs: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for r in tool_rows:
        if r.server_name is not None:
            continue  # MCP tools handled separately
        intg = r.source_integration or "core"
        pack = (r.source_file or "misc").replace(".py", "")
        entry = {"name": r.tool_name, "source_integration": r.source_integration, "source_file": r.source_file}
        integration_packs[intg][pack].append(entry)

    # core first, then other integrations alphabetically
    ordered_intgs = (["core"] if "core" in integration_packs else []) + sorted(
        k for k in integration_packs if k != "core"
    )
    tool_groups: list[dict] = []
    for intg_id in ordered_intgs:
        packs_dict = integration_packs[intg_id]
        tool_groups.append({
            "integration": intg_id,
            "is_core": intg_id == "core",
            "packs": [
                {"pack": pn, "tools": sorted(packs_dict[pn], key=lambda t: t["name"])}
                for pn in sorted(packs_dict)
            ],
            "total": sum(len(v) for v in packs_dict.values()),
        })

    return {
        "local_tools": local_tools,
        "mcp_servers": mcp_servers,
        "client_tools": client_tools,
        "tool_groups": tool_groups,
    }


@router.get("/bots/new", response_class=HTMLResponse)
async def admin_bot_new(request: Request):
    from types import SimpleNamespace
    from app.agent.bots import list_bots as _list_bots
    from app.services.harness import harness_service
    from sqlalchemy import select as sa_select
    async with async_session() as db:
        all_skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
        all_sandbox_profiles = list((await db.execute(select(SandboxProfile).where(SandboxProfile.enabled == True).order_by(SandboxProfile.name))).scalars().all())  # noqa: E712
        tool_names = (await db.execute(
            sa_select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
        )).scalars().all()
    from app.tools.packs import get_tool_packs
    packs = get_tool_packs()
    completions = (
        [{"value": f"skill:{s.id}", "label": f"skill:{s.id} — {s.name}"} for s in all_skills]
        + [{"value": f"tool:{t}", "label": f"tool:{t}"} for t in tool_names]
        + [{"value": f"tool-pack:{k}", "label": f"tool-pack:{k} — {len(v)} tools"} for k, v in sorted(packs.items())]
    )
    tool_options, model_groups = await asyncio.gather(_get_tool_options(), _get_available_models())
    empty_bot = SimpleNamespace(
        id="", name="", model="", system_prompt="",
        local_tools=[], mcp_servers=[], client_tools=[], pinned_tools=[],
        skills=[], docker_sandbox_profiles=[],
        tool_retrieval=True, tool_similarity_threshold=None,
        tool_result_config={},
        persona=False, context_compaction=True,
        compaction_interval=None, compaction_keep_turns=None,
        compaction_model=None, memory_knowledge_compaction_prompt=None,
        audio_input="transcribe",
        memory_config={}, knowledge_config={},
        filesystem_indexes=[], host_exec_config={"enabled": False},
        filesystem_access=[],
        display_name=None, avatar_url=None, integration_config={},
        knowledge_max_inject_chars=None, memory_max_inject_chars=None,
        delegation_config={},
        bot_sandbox={},
        model_provider_id=None,
        updated_at=None,
    )
    return templates.TemplateResponse("admin/bot_edit.html", {
        "request": request,
        "bot": empty_bot,
        "is_new": True,
        "all_skills": all_skills,
        "all_sandbox_profiles": all_sandbox_profiles,
        "model_groups": model_groups,
        "all_bots": _list_bots(),
        "all_harnesses": harness_service.list_harnesses(),
        "persona_content": "",
        "completions_json": json.dumps(completions),
        "knowledge_for_bot": [],
        "default_knowledge_similarity": settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
        **tool_options,
    })


@router.post("/bots", response_class=HTMLResponse)
async def admin_bot_create(
    request: Request,
    id: str = Form(...),
    name: str = Form(...),
    model: str = Form(...),
    system_prompt: str = Form(""),
    local_tools: list[str] = Form(default=[]),
    mcp_servers: list[str] = Form(default=[]),
    client_tools: list[str] = Form(default=[]),
    pinned_tools: list[str] = Form(default=[]),
    skills: list[str] = Form(default=[]),
    tool_retrieval: str = Form("true"),
    tool_similarity_threshold: str = Form(""),
    persona: str = Form("false"),
    context_compaction: str = Form("true"),
    compaction_interval: str = Form(""),
    compaction_keep_turns: str = Form(""),
    compaction_model: str = Form(""),
    memory_enabled: str = Form("false"),
    memory_cross_channel: str = Form("false"),
    memory_similarity_threshold: str = Form(""),
    memory_prompt: str = Form(""),
    knowledge_enabled: str = Form("false"),
    display_name: str = Form(""),
    avatar_url: str = Form(""),
    integration_config_json: str = Form(default="{}"),
    filesystem_indexes_json: str = Form("[]"),
    audio_input: str = Form("transcribe"),
    memory_knowledge_compaction_prompt: str = Form(""),
    docker_sandbox_profiles: list[str] = Form(default=[]),
    host_exec_config_json: str = Form(default='{"enabled": false}'),
    filesystem_access_json: str = Form(default="[]"),
    tool_result_config_json: str = Form(default="{}"),
    knowledge_max_inject_chars: str = Form(""),
    memory_max_inject_chars: str = Form(""),
    delegation_config_json: str = Form(default="{}"),
    model_provider_id: str = Form(""),
    bot_sandbox_json: str = Form(default="{}"),
):
    bot_id = id.strip()
    if not bot_id or not name.strip() or not model.strip():
        return HTMLResponse("<div class='text-red-400 p-4'>id, name, and model are required.</div>", status_code=422)

    def _float_or_none(s: str) -> float | None:
        try:
            return float(s.strip()) if s.strip() else None
        except ValueError:
            return None

    def _int_or_none(s: str) -> int | None:
        try:
            return int(s.strip()) if s.strip() else None
        except ValueError:
            return None

    try:
        fs_indexes = json.loads(filesystem_indexes_json or "[]")
    except json.JSONDecodeError:
        fs_indexes = []

    try:
        host_exec_config = json.loads(host_exec_config_json or '{"enabled": false}')
    except json.JSONDecodeError:
        host_exec_config = {"enabled": False}

    try:
        filesystem_access = json.loads(filesystem_access_json or "[]")
    except json.JSONDecodeError:
        filesystem_access = []

    try:
        tool_result_config = json.loads(tool_result_config_json or "{}")
    except json.JSONDecodeError:
        tool_result_config = {}

    try:
        delegation_config = json.loads(delegation_config_json or "{}")
    except json.JSONDecodeError:
        delegation_config = {}

    try:
        bot_sandbox = json.loads(bot_sandbox_json or "{}")
    except json.JSONDecodeError:
        bot_sandbox = {}

    mem_sim = _float_or_none(memory_similarity_threshold) or 0.45

    now = datetime.now(timezone.utc)
    row = BotRow(
        id=bot_id,
        name=name.strip(),
        model=model.strip(),
        system_prompt=system_prompt,
        local_tools=local_tools,
        mcp_servers=mcp_servers,
        client_tools=client_tools,
        pinned_tools=pinned_tools,
        skills=skills,
        docker_sandbox_profiles=docker_sandbox_profiles,
        tool_retrieval=(tool_retrieval.lower() == "true"),
        tool_similarity_threshold=_float_or_none(tool_similarity_threshold),
        persona=(persona.lower() == "true"),
        context_compaction=(context_compaction.lower() == "true"),
        compaction_interval=_int_or_none(compaction_interval),
        compaction_keep_turns=_int_or_none(compaction_keep_turns),
        compaction_model=compaction_model.strip() or None,
        memory_knowledge_compaction_prompt=memory_knowledge_compaction_prompt.strip() or None,
        audio_input=audio_input.strip() or "transcribe",
        memory_config={
            "enabled": memory_enabled.lower() == "true",
            "cross_channel": memory_cross_channel.lower() == "true",
            "similarity_threshold": mem_sim,
            "prompt": memory_prompt.strip() or None,
        },
        knowledge_config={
            "enabled": knowledge_enabled.lower() == "true",
        },
        filesystem_indexes=fs_indexes,
        host_exec_config=host_exec_config,
        filesystem_access=filesystem_access,
        display_name=display_name.strip() or None,
        avatar_url=avatar_url.strip() or None,
        integration_config=json.loads(integration_config_json or "{}"),
        tool_result_config=tool_result_config,
        knowledge_max_inject_chars=_int_or_none(knowledge_max_inject_chars),
        memory_max_inject_chars=_int_or_none(memory_max_inject_chars),
        delegation_config=delegation_config,
        bot_sandbox=bot_sandbox,
        model_provider_id=model_provider_id.strip() or None,
        created_at=now,
        updated_at=now,
    )

    async with async_session() as db:
        db.add(row)
        try:
            await db.commit()
        except Exception as exc:
            return HTMLResponse(f"<div class='text-red-400 p-4'>Error: {exc}</div>", status_code=400)

    await reload_bots()
    return RedirectResponse(f"/admin/bots/{bot_id}", status_code=303)


@router.get("/bots/{bot_id}/model-cost-badge", response_class=HTMLResponse)
async def admin_bot_model_cost_badge(bot_id: str):
    """HTMX lazy-load: return a small badge with model cost info for the bots list."""
    try:
        async with async_session() as db:
            row = await db.get(BotRow, bot_id)
        if not row:
            return HTMLResponse("<span class='text-xs text-gray-600'>—</span>")
        from app.services.providers import get_cached_model_info
        info = get_cached_model_info(row.model, row.model_provider_id)
        if not info:
            return HTMLResponse("<span class='text-xs text-gray-600'>—</span>")
        parts = []
        ctx = info.get("max_tokens")
        if ctx:
            parts.append(f"{ctx // 1000}k ctx")
        inp = info.get("input_cost_per_1m")
        out = info.get("output_cost_per_1m")
        if inp or out:
            parts.append(f"{inp or '?'}/{out or '?'} /1M")
        if not parts:
            return HTMLResponse("<span class='text-xs text-gray-600'>—</span>")
        title = f"ctx: {ctx // 1000}k tokens · in: {inp}/1M · out: {out}/1M" if ctx and inp else ""
        html = f"<span class='text-xs text-gray-500 font-mono' title='{title}'>{' · '.join(parts)}</span>"
        return HTMLResponse(html)
    except Exception:
        return HTMLResponse("<span class='text-xs text-gray-600'>—</span>")


@router.get("/bots/{bot_id}/context-estimate-badge", response_class=HTMLResponse)
async def admin_bot_context_estimate_badge(bot_id: str):
    """HTMX lazy-load: return a small badge with the estimated token count for this bot."""
    try:
        from app.services.context_estimate import estimate_bot_context
        result = await estimate_bot_context(draft={}, bot_id=bot_id)
        tokens = result.approx_tokens
        if tokens >= 1000:
            label = f"~{tokens // 1000}k ctx"
        else:
            label = f"~{tokens} ctx"
        return HTMLResponse(
            f"<span class='text-xs text-gray-500 font-mono' title='{result.total_chars:,} chars'>{label}</span>"
        )
    except Exception:
        return HTMLResponse("<span class='text-xs text-gray-600'>—</span>")


@router.post("/bots/{bot_id}/estimate-context")
async def admin_bot_context_estimate(bot_id: str, body: dict | None = Body(default=None)):
    """JSON: draft bot fields from the edit form; returns heuristic per-turn context breakdown."""
    from app.services.context_estimate import estimate_bot_context

    draft = body if isinstance(body, dict) else {}
    result = await estimate_bot_context(draft=draft, bot_id=bot_id)
    tot = max(result.total_chars, 1)
    lines_out = [
        {
            "label": row.label,
            "chars": row.chars,
            "pct": round(100.0 * row.chars / tot, 1),
            "hint": row.hint,
        }
        for row in sorted(result.lines, key=lambda r: -r.chars)
    ]
    return JSONResponse({
        "lines": lines_out,
        "total_chars": result.total_chars,
        "approx_tokens": result.approx_tokens,
        "disclaimer": result.disclaimer,
    })


@router.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
async def admin_bot_edit(request: Request, bot_id: str):
    from app.agent.bots import list_bots as _list_bots
    from app.services.harness import harness_service
    from sqlalchemy import select as sa_select
    async with async_session() as db:
        row = await db.get(BotRow, bot_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bot not found")
        all_skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
        all_sandbox_profiles = list((await db.execute(select(SandboxProfile).where(SandboxProfile.enabled == True).order_by(SandboxProfile.name))).scalars().all())  # noqa: E712
        tool_names = (await db.execute(
            sa_select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
        )).scalars().all()
    from app.tools.packs import get_tool_packs
    packs = get_tool_packs()
    completions = (
        [{"value": f"skill:{s.id}", "label": f"skill:{s.id} — {s.name}"} for s in all_skills]
        + [{"value": f"tool:{t}", "label": f"tool:{t}"} for t in tool_names]
        + [
            {"value": f"tool-pack:{k}", "label": f"tool-pack:{k} — {len(v)} tools"}
            for k, v in sorted(packs.items())
        ]
    )
    tool_options, model_groups, persona_content, knowledge_for_bot = await asyncio.gather(
        _get_tool_options(),
        _get_available_models(),
        get_persona(bot_id),
        list_knowledge_candidates_for_bot(bot_id),
    )
    return templates.TemplateResponse("admin/bot_edit.html", {
        "request": request,
        "bot": row,
        "all_skills": all_skills,
        "all_sandbox_profiles": all_sandbox_profiles,
        "model_groups": model_groups,
        "all_bots": [b for b in _list_bots() if b.id != bot_id],
        "all_harnesses": harness_service.list_harnesses(),
        "persona_content": persona_content or "",
        "completions_json": json.dumps(completions),
        "knowledge_for_bot": knowledge_for_bot,
        "default_knowledge_similarity": settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
        **tool_options,
    })


@router.post("/bots/{bot_id}", response_class=HTMLResponse)
async def admin_bot_update(
    request: Request,
    bot_id: str,
    name: str = Form(...),
    model: str = Form(...),
    system_prompt: str = Form(""),
    local_tools: list[str] = Form(default=[]),
    mcp_servers: list[str] = Form(default=[]),
    client_tools: list[str] = Form(default=[]),
    pinned_tools: list[str] = Form(default=[]),
    skills: list[str] = Form(default=[]),
    tool_retrieval: str = Form("true"),
    tool_similarity_threshold: str = Form(""),
    persona: str = Form("false"),
    persona_content: str = Form(""),
    context_compaction: str = Form("true"),
    compaction_interval: str = Form(""),
    compaction_keep_turns: str = Form(""),
    compaction_model: str = Form(""),
    memory_enabled: str = Form("false"),
    memory_cross_channel: str = Form("false"),
    memory_similarity_threshold: str = Form(""),
    memory_prompt: str = Form(""),
    knowledge_enabled: str = Form("false"),
    display_name: str = Form(""),
    avatar_url: str = Form(""),
    integration_config_json: str = Form(default="{}"),
    filesystem_indexes_json: str = Form("[]"),
    audio_input: str = Form("transcribe"),
    memory_knowledge_compaction_prompt: str = Form(""),
    docker_sandbox_profiles: list[str] = Form(default=[]),
    host_exec_config_json: str = Form(default='{"enabled": false}'),
    filesystem_access_json: str = Form(default="[]"),
    tool_result_config_json: str = Form(default="{}"),
    knowledge_max_inject_chars: str = Form(""),
    memory_max_inject_chars: str = Form(""),
    delegation_config_json: str = Form(default="{}"),
    model_provider_id: str = Form(""),
    bot_sandbox_json: str = Form(default="{}"),
):
    def _float_or_none(s: str) -> float | None:
        try:
            return float(s.strip()) if s.strip() else None
        except ValueError:
            return None

    def _int_or_none(s: str) -> int | None:
        try:
            return int(s.strip()) if s.strip() else None
        except ValueError:
            return None

    try:
        fs_indexes = json.loads(filesystem_indexes_json or "[]")
    except json.JSONDecodeError:
        fs_indexes = []

    try:
        host_exec_config = json.loads(host_exec_config_json or '{"enabled": false}')
    except json.JSONDecodeError:
        host_exec_config = {"enabled": False}

    try:
        filesystem_access = json.loads(filesystem_access_json or "[]")
    except json.JSONDecodeError:
        filesystem_access = []

    try:
        tool_result_config = json.loads(tool_result_config_json or "{}")
    except json.JSONDecodeError:
        tool_result_config = {}

    try:
        delegation_config = json.loads(delegation_config_json or "{}")
    except json.JSONDecodeError:
        delegation_config = {}

    try:
        bot_sandbox = json.loads(bot_sandbox_json or "{}")
    except json.JSONDecodeError:
        bot_sandbox = {}

    mem_sim = _float_or_none(memory_similarity_threshold) or 0.45

    async with async_session() as db:
        row = await db.get(BotRow, bot_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bot not found")

        old_skills = set(row.skills or [])
        new_skills = set(skills)

        row.name = name.strip()
        row.model = model.strip()
        row.system_prompt = system_prompt
        row.local_tools = local_tools
        row.mcp_servers = mcp_servers
        row.client_tools = client_tools
        row.pinned_tools = pinned_tools
        row.skills = skills
        row.docker_sandbox_profiles = docker_sandbox_profiles
        row.tool_retrieval = (tool_retrieval.lower() == "true")
        row.tool_similarity_threshold = _float_or_none(tool_similarity_threshold)
        row.persona = (persona.lower() == "true")
        row.context_compaction = (context_compaction.lower() == "true")
        row.compaction_interval = _int_or_none(compaction_interval)
        row.compaction_keep_turns = _int_or_none(compaction_keep_turns)
        row.compaction_model = compaction_model.strip() or None
        row.memory_knowledge_compaction_prompt = memory_knowledge_compaction_prompt.strip() or None
        row.audio_input = audio_input.strip() or "transcribe"
        row.memory_config = {
            "enabled": memory_enabled.lower() == "true",
            "cross_channel": memory_cross_channel.lower() == "true",
            "similarity_threshold": mem_sim,
            "prompt": memory_prompt.strip() or None,
        }
        row.knowledge_config = {
            "enabled": knowledge_enabled.lower() == "true",
        }
        row.filesystem_indexes = fs_indexes
        row.host_exec_config = host_exec_config
        row.filesystem_access = filesystem_access
        row.display_name = display_name.strip() or None
        row.avatar_url = avatar_url.strip() or None
        row.integration_config = json.loads(integration_config_json or "{}")
        row.tool_result_config = tool_result_config
        row.knowledge_max_inject_chars = _int_or_none(knowledge_max_inject_chars)
        row.memory_max_inject_chars = _int_or_none(memory_max_inject_chars)
        row.delegation_config = delegation_config
        row.bot_sandbox = bot_sandbox
        row.model_provider_id = model_provider_id.strip() or None
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    await reload_bots()

    if persona_content.strip():
        await write_persona(bot_id, persona_content.strip())

    # Re-embed any newly added skills
    added_skills = new_skills - old_skills
    for skill_id in added_skills:
        await re_embed_skill(skill_id)

    return RedirectResponse(f"/admin/bots/{bot_id}/edit?saved=1", status_code=303)


@router.delete("/bots/{bot_id}", response_class=HTMLResponse)
async def admin_bot_delete(bot_id: str):
    async with async_session() as db:
        row = await db.get(BotRow, bot_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bot not found")
        await db.delete(row)
        await db.commit()
    await reload_bots()
    return HTMLResponse("", status_code=200)
