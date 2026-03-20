"""Admin bot CRUD routes."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.agent.bots import reload_bots
from app.config import settings
from app.agent.skills import re_embed_skill
from app.db.engine import async_session
from app.db.models import Bot as BotRow, SandboxProfile, Skill as SkillRow, ToolEmbedding

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


async def _get_litellm_models() -> list[str]:
    """Fetch available models from LiteLLM proxy. Returns empty list on failure."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        base_url=settings.LITELLM_BASE_URL,
        api_key=settings.LITELLM_API_KEY or "dummy",
        max_retries=0,
        timeout=5.0,
    )
    try:
        models = await client.models.list()
        return sorted(m.id for m in models.data)
    except Exception:
        return []


async def _get_tool_options() -> dict:
    """Return available local tool names, MCP server names, and client tool names."""
    from app.tools.mcp import _servers
    from app.tools.client_tools import _client_tools
    from sqlalchemy import select as sa_select

    async with async_session() as db:
        tool_rows = (await db.execute(
            sa_select(ToolEmbedding.tool_name, ToolEmbedding.server_name)
            .order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
        )).all()

    local_tools = sorted({r.tool_name for r in tool_rows if r.server_name is None})
    mcp_servers = sorted(_servers.keys())
    client_tools = sorted(_client_tools.keys())
    return {"local_tools": local_tools, "mcp_servers": mcp_servers, "client_tools": client_tools}


@router.get("/bots/new", response_class=HTMLResponse)
async def admin_bot_new(request: Request):
    async with async_session() as db:
        all_skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
        all_sandbox_profiles = list((await db.execute(select(SandboxProfile).order_by(SandboxProfile.name))).scalars().all())
    tool_options, litellm_models = await asyncio.gather(_get_tool_options(), _get_litellm_models())
    return templates.TemplateResponse("admin/bot_new.html", {
        "request": request,
        "all_skills": all_skills,
        "all_sandbox_profiles": all_sandbox_profiles,
        "litellm_models": litellm_models,
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
    memory_cross_session: str = Form("false"),
    memory_similarity_threshold: str = Form(""),
    knowledge_enabled: str = Form("false"),
    knowledge_similarity_threshold: str = Form(""),
    slack_display_name: str = Form(""),
    slack_icon_emoji: str = Form(""),
    slack_icon_url: str = Form(""),
    filesystem_indexes_json: str = Form("[]"),
    audio_input: str = Form("transcribe"),
    memory_knowledge_compaction_prompt: str = Form(""),
    docker_sandbox_profiles: list[str] = Form(default=[]),
    host_exec_config_json: str = Form(default='{"enabled": false}'),
    filesystem_access_json: str = Form(default="[]"),
    tool_result_config_json: str = Form(default="{}"),
    knowledge_max_inject_chars: str = Form(""),
    memory_max_inject_chars: str = Form(""),
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

    mem_sim = _float_or_none(memory_similarity_threshold) or 0.45
    know_sim = _float_or_none(knowledge_similarity_threshold) or 0.45

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
            "cross_session": memory_cross_session.lower() == "true",
            "similarity_threshold": mem_sim,
        },
        knowledge_config={
            "enabled": knowledge_enabled.lower() == "true",
            "similarity_threshold": know_sim,
        },
        filesystem_indexes=fs_indexes,
        host_exec_config=host_exec_config,
        filesystem_access=filesystem_access,
        slack_display_name=slack_display_name.strip() or None,
        slack_icon_emoji=slack_icon_emoji.strip() or None,
        slack_icon_url=slack_icon_url.strip() or None,
        tool_result_config=tool_result_config,
        knowledge_max_inject_chars=_int_or_none(knowledge_max_inject_chars),
        memory_max_inject_chars=_int_or_none(memory_max_inject_chars),
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


@router.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
async def admin_bot_edit(request: Request, bot_id: str):
    async with async_session() as db:
        row = await db.get(BotRow, bot_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bot not found")
        all_skills = (await db.execute(select(SkillRow).order_by(SkillRow.name))).scalars().all()
        all_sandbox_profiles = list((await db.execute(select(SandboxProfile).order_by(SandboxProfile.name))).scalars().all())
    tool_options, litellm_models = await asyncio.gather(_get_tool_options(), _get_litellm_models())
    return templates.TemplateResponse("admin/bot_edit.html", {
        "request": request,
        "bot": row,
        "all_skills": all_skills,
        "all_sandbox_profiles": all_sandbox_profiles,
        "litellm_models": litellm_models,
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
    context_compaction: str = Form("true"),
    compaction_interval: str = Form(""),
    compaction_keep_turns: str = Form(""),
    compaction_model: str = Form(""),
    memory_enabled: str = Form("false"),
    memory_cross_session: str = Form("false"),
    memory_similarity_threshold: str = Form(""),
    knowledge_enabled: str = Form("false"),
    knowledge_similarity_threshold: str = Form(""),
    slack_display_name: str = Form(""),
    slack_icon_emoji: str = Form(""),
    slack_icon_url: str = Form(""),
    filesystem_indexes_json: str = Form("[]"),
    audio_input: str = Form("transcribe"),
    memory_knowledge_compaction_prompt: str = Form(""),
    docker_sandbox_profiles: list[str] = Form(default=[]),
    host_exec_config_json: str = Form(default='{"enabled": false}'),
    filesystem_access_json: str = Form(default="[]"),
    tool_result_config_json: str = Form(default="{}"),
    knowledge_max_inject_chars: str = Form(""),
    memory_max_inject_chars: str = Form(""),
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

    mem_sim = _float_or_none(memory_similarity_threshold) or 0.45
    know_sim = _float_or_none(knowledge_similarity_threshold) or 0.45

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
            "cross_session": memory_cross_session.lower() == "true",
            "similarity_threshold": mem_sim,
        }
        row.knowledge_config = {
            "enabled": knowledge_enabled.lower() == "true",
            "similarity_threshold": know_sim,
        }
        row.filesystem_indexes = fs_indexes
        row.host_exec_config = host_exec_config
        row.filesystem_access = filesystem_access
        row.slack_display_name = slack_display_name.strip() or None
        row.slack_icon_emoji = slack_icon_emoji.strip() or None
        row.slack_icon_url = slack_icon_url.strip() or None
        row.tool_result_config = tool_result_config
        row.knowledge_max_inject_chars = _int_or_none(knowledge_max_inject_chars)
        row.memory_max_inject_chars = _int_or_none(memory_max_inject_chars)
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    await reload_bots()

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
