"""Agent-facing capability manifest and readiness checks.

The manifest is the machine-readable version of "what can this agent do
right now?"  It intentionally composes existing primitives instead of adding a
new capability runtime: scoped API keys, tool enrollment, skill enrollment,
Projects, widgets, and harness metadata remain the source systems.
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ApiKey,
    Bot,
    BotSkillEnrollment,
    BotToolEnrollment,
    Channel,
    ChannelSkillEnrollment,
    Project,
    Session,
    Skill,
)
from app.services import api_keys as _api_keys_mod
from app.services.api_keys import has_scope
from app.tools.registry import _tools as _local_tools


CORE_AGENT_TOOLS = (
    "list_agent_capabilities",
    "run_agent_doctor",
    "get_tool_info",
    "get_skill",
    "list_api_endpoints",
    "call_api",
)

WIDGET_AUTHORING_TOOLS = (
    "prepare_widget_authoring",
    "widget_library_list",
    "preview_widget",
    "check_html_widget_authoring",
    "check_widget_authoring",
    "emit_html_widget",
    "pin_widget",
    "check_widget",
    "check_dashboard_widgets",
    "inspect_widget_pin",
    "describe_dashboard",
    "assess_widget_usefulness",
    "invoke_widget_action",
)

WIDGET_AUTHORING_SKILLS = (
    "widgets",
    "widgets/html",
    "widgets/sdk",
    "widgets/styling",
    "widgets/errors",
    "widgets/channel_dashboards",
)

TOOL_PROFILE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("api", ("api", "endpoint", "http")),
    ("project", ("project", "workspace", "file", "exec", "terminal")),
    ("widgets", ("widget", "dashboard", "pin", "html")),
    ("messaging", ("message", "chat", "channel", "respond", "send")),
    ("planning", ("plan", "question", "replan", "progress")),
    ("diagnostics", ("health", "log", "trace", "error", "doctor", "inspect")),
    ("automation", ("task", "pipeline", "cron", "heartbeat", "standing_order")),
)


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _profile_for_tool(name: str, description: str | None = None) -> str:
    haystack = f"{name} {description or ''}".lower()
    for profile, needles in TOOL_PROFILE_KEYWORDS:
        if any(needle in haystack for needle in needles):
            return profile
    return "general"


def _tool_signature(
    name: str,
    entry: dict[str, Any],
    *,
    include_schemas: bool,
    enrolled: set[str],
    pinned: set[str],
    configured: set[str],
) -> dict[str, Any]:
    schema = entry.get("schema") or {}
    fn = schema.get("function") or {}
    description = fn.get("description")
    payload: dict[str, Any] = {
        "name": name,
        "profile": _profile_for_tool(name, description),
        "description": description,
        "safety_tier": entry.get("safety_tier", "readonly"),
        "execution_policy": entry.get("execution_policy", "normal"),
        "source_integration": entry.get("source_integration"),
        "source_file": entry.get("source_file"),
        "requires_bot_context": bool(entry.get("requires_bot_context")),
        "requires_channel_context": bool(entry.get("requires_channel_context")),
        "enrolled": name in enrolled,
        "pinned": name in pinned,
        "configured": name in configured,
        "has_return_schema": bool(entry.get("returns")),
    }
    if include_schemas:
        payload["input_schema"] = fn.get("parameters")
        payload["returns_schema"] = entry.get("returns")
    return payload


def filter_endpoints_for_scopes(scopes: list[str] | None) -> list[dict[str, Any]]:
    """Return catalog endpoints visible to the given scopes.

    ``None`` means admin/user discovery, so everything is visible. An empty
    list means a scoped caller with no grants.
    """
    if scopes is None:
        return list(_api_keys_mod.ENDPOINT_CATALOG)
    endpoints: list[dict[str, Any]] = []
    for endpoint in _api_keys_mod.ENDPOINT_CATALOG:
        scope = endpoint.get("scope")
        if scope is None or has_scope(scopes, scope):
            endpoints.append(endpoint)
    return endpoints


async def _resolve_context(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None,
    session_id: str | uuid.UUID | None,
) -> tuple[Bot | None, Channel | None, Session | None]:
    session: Session | None = None
    channel: Channel | None = None
    bot: Bot | None = None

    session_uuid = _uuid_or_none(session_id)
    if session_uuid is not None:
        session = await db.get(Session, session_uuid)
        if session is not None:
            bot_id = bot_id or session.bot_id
            channel_id = channel_id or session.channel_id or session.parent_channel_id

    channel_uuid = _uuid_or_none(channel_id)
    if channel_uuid is not None:
        channel = await db.get(Channel, channel_uuid)
        if channel is not None:
            bot_id = bot_id or channel.bot_id

    if bot_id:
        bot = await db.get(Bot, bot_id)

    return bot, channel, session


async def _scopes_for_bot(db: AsyncSession, bot: Bot | None) -> list[str]:
    if bot is None or bot.api_key_id is None:
        return []
    key = await db.get(ApiKey, bot.api_key_id)
    if key is None or not key.is_active:
        return []
    return list(key.scopes or [])


async def _tool_payload(
    db: AsyncSession,
    bot: Bot | None,
    *,
    include_schemas: bool,
    max_tools: int,
) -> dict[str, Any]:
    bot_id = bot.id if bot is not None else None
    enrolled_rows: list[BotToolEnrollment] = []
    if bot_id:
        enrolled_rows = list((await db.execute(
            select(BotToolEnrollment).where(BotToolEnrollment.bot_id == bot_id)
        )).scalars().all())

    enrolled = {row.tool_name for row in enrolled_rows}
    pinned = {str(name) for name in (getattr(bot, "pinned_tools", None) or []) if name}
    configured = {str(name) for name in (getattr(bot, "local_tools", None) or []) if name}
    core = {name for name in CORE_AGENT_TOOLS if name in _local_tools}
    important = sorted((enrolled | pinned | configured | core) & set(_local_tools))

    details = [
        _tool_signature(
            name,
            _local_tools[name],
            include_schemas=include_schemas,
            enrolled=enrolled,
            pinned=pinned,
            configured=configured,
        )
        for name in important[:max_tools]
    ]
    profile_counts = Counter(
        _profile_for_tool(
            name,
            ((_local_tools[name].get("schema") or {}).get("function") or {}).get("description"),
        )
        for name in _local_tools
    )
    safety_counts = Counter(str(entry.get("safety_tier", "readonly")) for entry in _local_tools.values())

    return {
        "catalog_count": len(_local_tools),
        "working_set_count": len(enrolled | pinned | configured),
        "configured": sorted(configured),
        "pinned": sorted(pinned),
        "enrolled": [
            {
                "name": row.tool_name,
                "source": row.source,
                "enrolled_at": row.enrolled_at.isoformat() if row.enrolled_at else None,
                "fetch_count": row.fetch_count,
            }
            for row in sorted(enrolled_rows, key=lambda r: r.tool_name)
        ],
        "profiles": dict(sorted(profile_counts.items())),
        "safety_tiers": dict(sorted(safety_counts.items())),
        "recommended_core": sorted(core),
        "details": details,
        "details_truncated": len(important) > max_tools,
    }


async def _skill_payload(
    db: AsyncSession,
    bot: Bot | None,
    channel: Channel | None,
) -> dict[str, Any]:
    bot_rows: list[BotSkillEnrollment] = []
    channel_rows: list[ChannelSkillEnrollment] = []
    if bot is not None:
        bot_rows = list((await db.execute(
            select(BotSkillEnrollment).where(BotSkillEnrollment.bot_id == bot.id)
        )).scalars().all())
    if channel is not None:
        channel_rows = list((await db.execute(
            select(ChannelSkillEnrollment).where(ChannelSkillEnrollment.channel_id == channel.id)
        )).scalars().all())

    skill_ids = sorted({row.skill_id for row in bot_rows} | {row.skill_id for row in channel_rows})
    rows_by_id: dict[str, Skill] = {}
    if skill_ids:
        skill_rows = (await db.execute(
            select(Skill).where(Skill.id.in_(skill_ids))
        )).scalars().all()
        rows_by_id = {row.id: row for row in skill_rows}

    def _entry(skill_id: str, source: str, scope: str, enrolled_at: Any) -> dict[str, Any]:
        row = rows_by_id.get(skill_id)
        return {
            "id": skill_id,
            "name": row.name if row is not None else skill_id,
            "description": row.description if row is not None else None,
            "category": row.category if row is not None else None,
            "source": source,
            "scope": scope,
            "enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
        }

    return {
        "bot_enrolled": [
            _entry(row.skill_id, row.source, "bot", row.enrolled_at)
            for row in sorted(bot_rows, key=lambda r: r.skill_id)
        ],
        "channel_enrolled": [
            _entry(row.skill_id, row.source, "channel", row.enrolled_at)
            for row in sorted(channel_rows, key=lambda r: r.skill_id)
        ],
        "working_set_count": len(skill_ids),
        "loader": {
            "tool": "get_skill",
            "auto_inject_default": False,
            "portable_folder_bundles": "planned",
        },
    }


async def _project_payload(db: AsyncSession, channel: Channel | None) -> dict[str, Any]:
    if channel is None or channel.project_id is None:
        return {"attached": False}
    project = await db.get(Project, channel.project_id)
    if project is None:
        return {"attached": False, "project_id": str(channel.project_id), "missing": True}
    payload: dict[str, Any] = {
        "attached": True,
        "id": str(project.id),
        "name": project.name,
        "slug": project.slug,
        "root_path": project.root_path,
        "prompt_file_path": project.prompt_file_path,
    }
    try:
        from app.services.project_runtime import load_project_runtime_environment
        runtime = await load_project_runtime_environment(db, project)
        payload["runtime_env"] = runtime.safe_payload()
    except Exception as exc:  # pragma: no cover - defensive; doctor reports this.
        payload["runtime_env"] = {"ready": False, "error": str(exc)}
    return payload


def _doctor_findings(manifest: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not manifest["context"].get("bot_id"):
        findings.append({
            "severity": "error",
            "code": "missing_bot_context",
            "message": "No bot context was resolved, so bot-scoped tools cannot reason about their own grants.",
            "next_action": "Pass bot_id or run from an agent turn.",
        })
    if not manifest["api"].get("scopes"):
        findings.append({
            "severity": "warning",
            "code": "missing_api_scopes",
            "message": "The bot has no scoped API key grants, so call_api/list_api_endpoints cannot operate.",
            "next_action": "Assign an API key preset such as workspace_bot or a narrower custom scope set.",
        })
    if manifest["tools"].get("catalog_count", 0) and not manifest["tools"].get("working_set_count"):
        findings.append({
            "severity": "info",
            "code": "empty_tool_working_set",
            "message": "No tools are enrolled yet; the agent will rely on retrieval and get_tool_info.",
            "next_action": "Let the agent fetch tools as needed or pin core tools for this bot.",
        })
    project = manifest.get("project") or {}
    runtime = project.get("runtime_env") or {}
    if project.get("attached") and runtime and not runtime.get("ready", True):
        findings.append({
            "severity": "warning",
            "code": "project_runtime_not_ready",
            "message": "The attached Project runtime environment has missing, invalid, or reserved variables.",
            "next_action": "Open Project settings and bind the missing secrets or adjust the Blueprint env keys.",
        })
    if manifest["harness"].get("runtime") and not manifest["project"].get("attached") and not manifest["harness"].get("workdir"):
        findings.append({
            "severity": "warning",
            "code": "harness_without_workdir",
            "message": "The bot uses an external harness but has no Project or harness workdir.",
            "next_action": "Attach the channel to a Project or configure harness_workdir.",
        })
    widgets = manifest.get("widgets") or {}
    if widgets.get("missing_authoring_tools"):
        findings.append({
            "severity": "warning",
            "code": "widget_authoring_tools_missing",
            "message": "Some widget authoring tools are missing from the local registry.",
            "next_action": "Restart/reload local tools and verify the widget authoring modules import cleanly.",
        })
    return findings


def _widget_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    skill_rows = (manifest.get("skills", {}).get("bot_enrolled") or []) + (
        manifest.get("skills", {}).get("channel_enrolled") or []
    )
    enrolled_skills = {
        row.get("id")
        for row in skill_rows
        if isinstance(row, dict) and row.get("id")
    }
    available_tools = [name for name in WIDGET_AUTHORING_TOOLS if name in _local_tools]
    missing_tools = [name for name in WIDGET_AUTHORING_TOOLS if name not in _local_tools]
    available_skills = [skill for skill in WIDGET_AUTHORING_SKILLS if skill in enrolled_skills]
    missing_skills = [skill for skill in WIDGET_AUTHORING_SKILLS if skill not in enrolled_skills]
    findings: list[dict[str, str]] = []
    if missing_tools:
        findings.append({
            "severity": "warning",
            "code": "missing_widget_authoring_tools",
            "message": f"Missing widget authoring tools: {', '.join(missing_tools)}.",
            "next_action": "Verify local tool import/registration before asking the bot to author widgets.",
        })
    if missing_skills:
        findings.append({
            "severity": "info",
            "code": "widget_skills_not_enrolled",
            "message": f"Widget skills not in the current working set: {', '.join(missing_skills)}.",
            "next_action": "Call prepare_widget_authoring or get_skill('widgets') when starting widget work.",
        })

    readiness = "ready"
    if missing_tools:
        readiness = "blocked"
    elif missing_skills:
        readiness = "needs_skills"

    return {
        "authoring_tools": available_tools,
        "required_authoring_tools": list(WIDGET_AUTHORING_TOOLS),
        "missing_authoring_tools": missing_tools,
        "recommended_skills": list(WIDGET_AUTHORING_SKILLS),
        "available_skills": available_skills,
        "missing_skills": missing_skills,
        "health_loop": "available" if "check_widget" in _local_tools else "missing",
        "html_authoring_check": "available" if "check_html_widget_authoring" in _local_tools else "missing",
        "tool_widget_authoring_check": "available" if "check_widget_authoring" in _local_tools else "missing",
        "authoring_flow": [
            "prepare_widget_authoring",
            "widget_library_list",
            "file",
            "check_html_widget_authoring",
            "emit_html_widget_or_pin_widget",
            "check_widget",
            "inspect_widget_pin_if_health_fails",
        ],
        "readiness": readiness,
        "findings": findings,
    }


async def build_agent_capability_manifest(
    db: AsyncSession,
    *,
    bot_id: str | None = None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    scopes: list[str] | None = None,
    include_schemas: bool = False,
    include_endpoints: bool = True,
    max_tools: int = 80,
) -> dict[str, Any]:
    """Build the agent-first manifest for a bot/channel/session context."""
    bot, channel, session = await _resolve_context(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
    )
    effective_scopes = list(scopes) if scopes is not None else await _scopes_for_bot(db, bot)
    endpoints = filter_endpoints_for_scopes(effective_scopes if effective_scopes else [])

    manifest: dict[str, Any] = {
        "schema_version": "agent-capabilities.v1",
        "context": {
            "bot_id": bot.id if bot else bot_id,
            "bot_name": bot.name if bot else None,
            "channel_id": str(channel.id) if channel else (str(channel_id) if channel_id else None),
            "channel_name": channel.name if channel else None,
            "session_id": str(session.id) if session else (str(session_id) if session_id else None),
        },
        "api": {
            "scopes": effective_scopes,
            "endpoint_count": len(endpoints),
            "endpoints": endpoints if include_endpoints else [],
            "catalog_detail": "request/response schemas are included when FastAPI OpenAPI exposes them",
        },
        "tools": await _tool_payload(db, bot, include_schemas=include_schemas, max_tools=max_tools),
        "skills": await _skill_payload(db, bot, channel),
        "project": await _project_payload(db, channel),
        "harness": {
            "runtime": bot.harness_runtime if bot else None,
            "workdir": bot.harness_workdir if bot else None,
            "bridge_status": "native" if bot and bot.harness_runtime else "not_configured",
        },
    }
    manifest["widgets"] = _widget_payload(manifest)
    manifest["doctor"] = {
        "status": "ok",
        "findings": _doctor_findings(manifest),
    }
    if any(f["severity"] == "error" for f in manifest["doctor"]["findings"]):
        manifest["doctor"]["status"] = "error"
    elif manifest["doctor"]["findings"]:
        manifest["doctor"]["status"] = "needs_attention"
    return manifest
