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
    ChannelIntegration,
    ChannelSkillEnrollment,
    Project,
    Session,
    Skill,
)
from app.services import api_keys as _api_keys_mod
from app.services.api_keys import SCOPE_PRESETS, has_scope
from app.services.tool_error_contract import tool_error_contract
from app.tools.registry import _tools as _local_tools


CORE_AGENT_TOOLS = (
    "list_agent_capabilities",
    "run_agent_doctor",
    "get_agent_context_snapshot",
    "get_agent_work_snapshot",
    "get_agent_activity_log",
    "get_agent_status_snapshot",
    "get_tool_info",
    "get_skill",
    "list_api_endpoints",
    "call_api",
    "publish_project_run_receipt",
)

PROJECT_CODING_RUN_TOOLS = (
    "file",
    "exec_command",
    "run_e2e_tests",
    "publish_project_run_receipt",
)

WIDGET_AUTHORING_TOOLS = (
    "prepare_widget_authoring",
    "file",
    "widget_library_list",
    "preview_widget",
    "check_html_widget_authoring",
    "check_widget_authoring",
    "emit_html_widget",
    "pin_widget",
    "check_widget",
    "publish_widget_authoring_receipt",
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
    "widgets/authoring_runs",
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


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _runtime_context_recommendation(percent_full: float | None) -> str:
    if percent_full is None:
        return "unknown"
    if percent_full >= 90:
        return "handoff"
    if percent_full >= 75:
        return "summarize"
    return "continue"


def _runtime_context_from_budget(
    budget: dict[str, Any] | None,
    *,
    channel_id: str | None,
    session_id: str | None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    budget = budget or {}
    tokens_used = _int_or_none(budget.get("consumed_tokens"))
    total_tokens = _int_or_none(budget.get("total_tokens"))
    utilization = _float_or_none(budget.get("utilization"))
    if utilization is None and total_tokens and tokens_used is not None and total_tokens > 0:
        utilization = tokens_used / total_tokens
    percent_full = round(utilization * 100, 1) if utilization is not None else None
    tokens_remaining = None
    if tokens_used is not None and total_tokens is not None:
        tokens_remaining = max(0, total_tokens - tokens_used)

    source = str(budget.get("source") or "none")
    available = source != "none" and any(
        value is not None
        for value in (tokens_used, total_tokens, percent_full)
    )
    reason = unavailable_reason
    if reason is None and not available:
        reason = "No context budget has been recorded yet."

    recommendation = _runtime_context_recommendation(percent_full if available else None)
    return {
        "available": available,
        "channel_id": channel_id,
        "session_id": session_id,
        "recommendation": recommendation,
        "reason": reason,
        "budget": {
            "tokens_used": tokens_used,
            "tokens_remaining": tokens_remaining,
            "total_tokens": total_tokens,
            "percent_full": percent_full,
            "source": source,
            "context_profile": budget.get("context_profile"),
        },
        "details": {
            "context_origin": budget.get("context_origin"),
            "current_prompt_tokens": _int_or_none(budget.get("current_prompt_tokens")),
            "cached_prompt_tokens": _int_or_none(budget.get("cached_prompt_tokens")),
            "completion_tokens": _int_or_none(budget.get("completion_tokens")),
            "live_history_turns": _int_or_none(budget.get("live_history_turns")),
            "mandatory_static_injections": list(budget.get("mandatory_static_injections") or []),
            "optional_static_injections": list(budget.get("optional_static_injections") or []),
        },
    }


async def runtime_context_payload(
    db: AsyncSession,
    channel: Channel | None,
    *,
    session_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    resolved_session_id = str(session_id) if session_id is not None else None
    if channel is None:
        return _runtime_context_from_budget(
            None,
            channel_id=None,
            session_id=resolved_session_id,
            unavailable_reason="No channel context available.",
        )

    from app.services.context_breakdown import fetch_latest_context_budget

    budget = await fetch_latest_context_budget(
        channel.id,
        db,
        session_id=resolved_session_id,
    )
    return _runtime_context_from_budget(
        budget,
        channel_id=str(channel.id),
        session_id=resolved_session_id,
    )


async def work_state_payload(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
    max_items: int = 10,
) -> dict[str, Any]:
    from app.services.agent_work_snapshot import build_agent_work_snapshot

    return await build_agent_work_snapshot(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        max_items=max_items,
    )


async def activity_log_payload(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    from app.services.agent_activity import agent_activity_summary

    return await agent_activity_summary(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        limit=20,
    )


async def agent_status_payload(
    db: AsyncSession,
    *,
    bot_id: str | None,
    channel_id: str | uuid.UUID | None = None,
    session_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    from app.services.agent_status import build_agent_status_snapshot

    return await build_agent_status_snapshot(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        limit=10,
    )


def _integration_href(integration_id: str) -> str:
    return f"/admin/integrations/{integration_id}"


def _channel_settings_href(manifest: dict[str, Any], tab: str) -> str | None:
    channel_id = manifest.get("context", {}).get("channel_id")
    if not channel_id:
        return None
    return f"/channels/{channel_id}/settings#{tab}"


def _dependency_gaps(entry: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "python": [
            dep["package"]
            for dep in entry.get("python_dependencies", []) or []
            if not dep.get("installed")
        ],
        "npm": [
            dep["package"]
            for dep in entry.get("npm_dependencies", []) or []
            if not dep.get("installed")
        ],
        "system": [
            dep.get("apt_package") or dep.get("binary")
            for dep in entry.get("system_dependencies", []) or []
            if not dep.get("installed")
        ],
    }


def _has_dependency_gaps(gaps: dict[str, list[str]]) -> bool:
    return any(gaps.get(kind) for kind in ("python", "npm", "system"))


def _process_payload(entry: dict[str, Any]) -> dict[str, Any]:
    process_status = entry.get("process_status") or {}
    return {
        "declared": bool(entry.get("has_process")),
        "running": process_status.get("status") == "running",
        "exit_code": process_status.get("exit_code"),
        "restart_count": process_status.get("restart_count"),
    }


def _global_integration_entry(entry: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    integration_id = str(entry.get("id") or "")
    missing_settings = [
        env["key"]
        for env in entry.get("env_vars", []) or []
        if env.get("required") and not env.get("is_set")
    ]
    dependency_gaps = _dependency_gaps(entry)
    manifest = manifest or {}
    return {
        "id": integration_id,
        "name": entry.get("name") or integration_id,
        "lifecycle_status": entry.get("lifecycle_status", "available"),
        "status": entry.get("status", "not_configured"),
        "missing_required_settings": missing_settings,
        "dependency_gaps": dependency_gaps,
        "process": _process_payload(entry),
        "webhook_declared": bool(entry.get("webhook")),
        "oauth_declared": bool(entry.get("oauth")),
        "api_permissions_declared": bool(entry.get("api_permissions")),
        "capabilities": list(manifest.get("capabilities") or []),
        "rich_tool_results": bool(manifest.get("tool_result_rendering")),
        "href": _integration_href(integration_id),
    }


def _value_present(value: Any) -> bool:
    return value is not None and value != ""


def _missing_activation_config_fields(option: dict[str, Any]) -> list[str]:
    config = option.get("activation_config") or {}
    missing: list[str] = []
    for field in option.get("config_fields", []) or []:
        if not field.get("required"):
            continue
        key = field.get("key")
        if not key:
            continue
        if _value_present(config.get(key)) or _value_present(field.get("default")):
            continue
        missing.append(str(key))
    return missing


def _binding_entry(row: ChannelIntegration, href: str | None) -> dict[str, Any]:
    client_id = row.client_id or ""
    return {
        "id": str(row.id),
        "integration_type": row.integration_type,
        "client_id": client_id,
        "display_name": row.display_name,
        "activated": bool(row.activated),
        "stub_binding": client_id.startswith("mc-activated:"),
        "dispatch_config_keys": sorted((row.dispatch_config or {}).keys()),
        "href": href,
    }


def _channel_integration_payload(
    *,
    channel_id: str,
    bindings: list[ChannelIntegration],
    activation_options: list[dict[str, Any]],
    binding_href: str | None,
    activation_href: str | None,
) -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        "bindings": [_binding_entry(row, binding_href) for row in bindings],
        "activation_options": [
            {
                "integration_type": option["integration_type"],
                "activated": bool(option.get("activated")),
                "tools": list(option.get("tools") or []),
                "includes": list(option.get("includes") or []),
                "requires_workspace": bool(option.get("requires_workspace")),
                "missing_config_fields": _missing_activation_config_fields(option),
                "href": activation_href,
            }
            for option in activation_options
        ],
    }


def _integration_summary(
    global_entries: list[dict[str, Any]],
    channel_payload: dict[str, Any] | None,
) -> dict[str, int]:
    enabled = [entry for entry in global_entries if entry.get("lifecycle_status") == "enabled"]
    bindings = (channel_payload or {}).get("bindings") or []
    activations = (channel_payload or {}).get("activation_options") or []
    return {
        "enabled_count": len(enabled),
        "needs_setup_count": sum(1 for entry in enabled if entry.get("missing_required_settings")),
        "dependency_gap_count": sum(1 for entry in enabled if _has_dependency_gaps(entry["dependency_gaps"])),
        "process_gap_count": sum(
            1
            for entry in enabled
            if entry.get("process", {}).get("declared")
            and not entry.get("process", {}).get("running")
            and not entry.get("missing_required_settings")
        ),
        "channel_binding_count": len(bindings),
        "channel_activation_count": sum(1 for option in activations if option.get("activated")),
        "channel_stub_binding_count": sum(1 for binding in bindings if binding.get("stub_binding")),
    }


async def _integration_payload(db: AsyncSession, channel: Channel | None) -> dict[str, Any]:
    from app.services.channel_integrations import list_activation_options
    from app.services.integration_catalog import discover_setup_status
    from app.services.integration_manifests import get_all_manifests

    manifests = get_all_manifests()
    global_entries = [
        _global_integration_entry(entry, manifests.get(str(entry.get("id") or "")))
        for entry in discover_setup_status()
    ]
    channel_payload: dict[str, Any] | None = None
    if channel is not None:
        bindings = list((await db.execute(
            select(ChannelIntegration)
            .where(ChannelIntegration.channel_id == channel.id)
            .order_by(ChannelIntegration.created_at)
        )).scalars().all())
        activation_options = await list_activation_options(db, channel_id=channel.id)
        channel_payload = _channel_integration_payload(
            channel_id=str(channel.id),
            bindings=bindings,
            activation_options=activation_options,
            binding_href=f"/channels/{channel.id}/settings#channel",
            activation_href=f"/channels/{channel.id}/settings#agent",
        )

    return {
        "summary": _integration_summary(global_entries, channel_payload),
        "global": global_entries,
        "channel": channel_payload,
    }


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
    coding_run = manifest.get("coding_run") or {}
    if project.get("attached") and coding_run.get("missing_tools"):
        findings.append({
            "severity": "warning",
            "code": "project_coding_run_tools_missing",
            "message": f"Missing Project coding-run tools: {', '.join(coding_run.get('missing_tools') or [])}.",
            "next_action": "Restart/reload local tools and verify coding-run helper modules import cleanly.",
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
    runtime_context = manifest.get("runtime_context") or {}
    recommendation = runtime_context.get("recommendation")
    budget = runtime_context.get("budget") or {}
    percent_full = budget.get("percent_full")
    percent_text = f"{percent_full}% full" if percent_full is not None else "near its limit"
    if recommendation == "summarize":
        findings.append({
            "severity": "warning",
            "code": "context_should_summarize",
            "message": f"Runtime context is {percent_text}; summarize or compact before starting a broad task.",
            "next_action": "Create a concise state summary or trigger compaction before taking on more scope.",
        })
    elif recommendation == "handoff":
        findings.append({
            "severity": "error",
            "code": "context_should_handoff",
            "message": f"Runtime context is {percent_text}; hand off or compact before continuing substantial work.",
            "next_action": "Produce a handoff summary or compact the session before more tool-heavy work.",
        })
    agent_status = manifest.get("agent_status") or {}
    current_status = agent_status.get("current") or {}
    heartbeat_status = agent_status.get("heartbeat") or {}
    recent_runs = agent_status.get("recent_runs") or []
    latest_run = recent_runs[0] if recent_runs else {}
    if current_status.get("stale"):
        findings.append({
            "severity": "error",
            "code": "agent_status_stale_run",
            "message": "The current agent run appears stale and may need operator review.",
            "next_action": "Open the run trace or heartbeat/task history and decide whether to cancel, retry, or investigate.",
        })
    if latest_run.get("status") in {"failed", "error"}:
        findings.append({
            "severity": "warning",
            "code": "agent_last_run_failed",
            "message": "The latest autonomous agent run failed.",
            "next_action": "Review the latest run error and retry only after the blocker is understood.",
        })
    if latest_run.get("repetition_detected") or heartbeat_status.get("repetition_detected"):
        findings.append({
            "severity": "warning",
            "code": "heartbeat_repetition_detected",
            "message": "The latest heartbeat was flagged as repetitive.",
            "next_action": "Review the heartbeat prompt, prior result context, and assigned tools before the next run.",
        })
    if (
        agent_status.get("available")
        and manifest.get("context", {}).get("channel_id")
        and not heartbeat_status.get("configured")
        and not current_status
        and agent_status.get("state") == "idle"
    ):
        findings.append({
            "severity": "info",
            "code": "heartbeat_not_configured",
            "message": "This channel has no heartbeat configured for autonomous status check-ins.",
            "next_action": "Open channel automation settings if this agent should report on a schedule.",
        })
    integrations = manifest.get("integrations") or {}
    for entry in integrations.get("global") or []:
        if entry.get("lifecycle_status") != "enabled":
            continue
        integration_id = entry.get("id")
        if entry.get("missing_required_settings"):
            findings.append({
                "severity": "warning",
                "code": f"integration_settings_missing:{integration_id}",
                "message": f"{entry.get('name') or integration_id} is enabled but missing required settings.",
                "next_action": "Open the integration settings and fill the missing required values.",
            })
        if _has_dependency_gaps(entry.get("dependency_gaps") or {}):
            findings.append({
                "severity": "warning",
                "code": f"integration_dependencies_missing:{integration_id}",
                "message": f"{entry.get('name') or integration_id} is missing required dependencies.",
                "next_action": "Open the integration page and install the missing dependencies.",
            })
        process = entry.get("process") or {}
        if (
            process.get("declared")
            and not process.get("running")
            and not entry.get("missing_required_settings")
        ):
            findings.append({
                "severity": "warning",
                "code": f"integration_process_not_running:{integration_id}",
                "message": f"{entry.get('name') or integration_id} has a background process that is not running.",
                "next_action": "Open the integration page and review the process state.",
            })
    channel_integrations = integrations.get("channel") or {}
    for binding in channel_integrations.get("bindings") or []:
        if binding.get("stub_binding"):
            integration_type = binding.get("integration_type")
            findings.append({
                "severity": "info",
                "code": f"channel_integration_stub_binding:{integration_type}",
                "message": f"{integration_type} is activated with a placeholder channel binding.",
                "next_action": "Open channel settings and bind it to a real external channel or conversation.",
            })
    for option in channel_integrations.get("activation_options") or []:
        if option.get("activated") and option.get("missing_config_fields"):
            integration_type = option.get("integration_type")
            findings.append({
                "severity": "warning",
                "code": f"channel_integration_activation_config_missing:{integration_type}",
                "message": f"{integration_type} activation is missing required channel config.",
                "next_action": "Open channel agent settings and fill the required activation fields.",
            })
    return findings


def _deduped(values: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _bot_settings_href(manifest: dict[str, Any], group: str = "access") -> str | None:
    bot_id = manifest.get("context", {}).get("bot_id")
    if bot_id:
        return f"/admin/bots/{bot_id}#{group}"
    channel_id = manifest.get("context", {}).get("channel_id")
    if channel_id:
        return f"/channels/{channel_id}/settings#agent"
    return None


def _project_settings_href(manifest: dict[str, Any]) -> str:
    project = manifest.get("project") or {}
    if project.get("id"):
        return f"/admin/projects/{project['id']}#Settings"
    return "/admin/projects"


def _doctor_proposed_actions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    findings = manifest.get("doctor", {}).get("findings") or []
    finding_codes = {finding.get("code") for finding in findings if isinstance(finding, dict)}
    context = manifest.get("context") or {}
    bot_id = context.get("bot_id")

    if bot_id and "missing_api_scopes" in finding_codes:
        workspace_scopes = list(SCOPE_PRESETS["workspace_bot"]["scopes"])
        actions.append({
            "id": f"{bot_id}:missing_api_scopes:workspace_bot",
            "finding_code": "missing_api_scopes",
            "kind": "permission",
            "title": "Grant workspace API access",
            "description": "Enable this bot to inspect and update workspace state through the existing API tools.",
            "impact": "Adds the workspace_bot API scope preset. The bot can use call_api only within those grants.",
            "required_actor_scopes": ["bots:write"],
            "grants_scopes": workspace_scopes,
            "apply": {
                "type": "bot_patch",
                "patch": {"api_permissions": workspace_scopes},
            },
        })

    if bot_id and "empty_tool_working_set" in finding_codes:
        core_tools = list(manifest.get("tools", {}).get("recommended_core") or [])
        if not core_tools:
            core_tools = [name for name in CORE_AGENT_TOOLS if name in _local_tools]
        configured = list(manifest.get("tools", {}).get("configured") or [])
        pinned = list(manifest.get("tools", {}).get("pinned") or [])
        actions.append({
            "id": f"{bot_id}:empty_tool_working_set:core_tools",
            "finding_code": "empty_tool_working_set",
            "kind": "tool_setup",
            "title": "Add core agent tools",
            "description": "Give the bot the basic discovery and API tools it needs to understand its own capabilities.",
            "impact": "Adds core tools to local and pinned tools without removing existing tools.",
            "required_actor_scopes": ["bots:write"],
            "grants_scopes": [],
            "apply": {
                "type": "bot_patch",
                "patch": {
                    "local_tools": _deduped([*configured, *core_tools]),
                    "pinned_tools": _deduped([*pinned, *core_tools]),
                },
            },
        })

    if bot_id and "harness_without_workdir" in finding_codes:
        href = _bot_settings_href(manifest, "identity")
        if href:
            actions.append({
                "id": f"{bot_id}:harness_without_workdir:settings",
                "finding_code": "harness_without_workdir",
                "kind": "configuration",
                "title": "Open harness settings",
                "description": "Attach the channel to a Project or set a harness workspace path.",
                "impact": "Navigation only. No configuration changes are applied automatically.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": href},
            })

    if bot_id and "project_runtime_not_ready" in finding_codes:
        actions.append({
            "id": f"{bot_id}:project_runtime_not_ready:settings",
            "finding_code": "project_runtime_not_ready",
            "kind": "configuration",
            "title": "Open Project settings",
            "description": "Review missing secrets or invalid runtime environment keys for the attached Project.",
            "impact": "Navigation only. Secret values and runtime variables are never inferred automatically.",
            "required_actor_scopes": [],
            "grants_scopes": [],
            "apply": {"type": "navigate", "href": _project_settings_href(manifest)},
        })

    integrations = manifest.get("integrations") or {}
    for entry in integrations.get("global") or []:
        integration_id = entry.get("id")
        href = entry.get("href") or (f"/admin/integrations/{integration_id}" if integration_id else None)
        if not integration_id or not href:
            continue
        if f"integration_settings_missing:{integration_id}" in finding_codes:
            actions.append({
                "id": f"integration:{integration_id}:settings",
                "finding_code": f"integration_settings_missing:{integration_id}",
                "kind": "integration_setup",
                "title": f"Open {entry.get('name') or integration_id} settings",
                "description": "Fill required integration settings.",
                "impact": "Navigation only. No secrets or settings are changed automatically.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": href},
            })
        if f"integration_dependencies_missing:{integration_id}" in finding_codes:
            actions.append({
                "id": f"integration:{integration_id}:dependencies",
                "finding_code": f"integration_dependencies_missing:{integration_id}",
                "kind": "integration_setup",
                "title": f"Open {entry.get('name') or integration_id} dependencies",
                "description": "Install or review missing integration dependencies.",
                "impact": "Navigation only. Dependency installers remain explicit admin actions.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": href},
            })
        if f"integration_process_not_running:{integration_id}" in finding_codes:
            actions.append({
                "id": f"integration:{integration_id}:process",
                "finding_code": f"integration_process_not_running:{integration_id}",
                "kind": "integration_setup",
                "title": f"Open {entry.get('name') or integration_id} process",
                "description": "Review the integration background process.",
                "impact": "Navigation only. The process is not started automatically.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": href},
            })

    binding_href = _channel_settings_href(manifest, "channel")
    activation_href = _channel_settings_href(manifest, "agent")
    channel_integrations = integrations.get("channel") or {}
    for binding in channel_integrations.get("bindings") or []:
        integration_type = binding.get("integration_type")
        if (
            integration_type
            and binding_href
            and f"channel_integration_stub_binding:{integration_type}" in finding_codes
        ):
            actions.append({
                "id": f"channel-integration:{integration_type}:binding",
                "finding_code": f"channel_integration_stub_binding:{integration_type}",
                "kind": "integration_binding",
                "title": f"Bind {integration_type} to a real destination",
                "description": "Replace the activation placeholder with a real external channel or conversation.",
                "impact": "Navigation only. Bindings are changed only from Channel settings.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": binding_href},
            })
    for option in channel_integrations.get("activation_options") or []:
        integration_type = option.get("integration_type")
        if (
            integration_type
            and activation_href
            and f"channel_integration_activation_config_missing:{integration_type}" in finding_codes
        ):
            actions.append({
                "id": f"channel-integration:{integration_type}:activation-config",
                "finding_code": f"channel_integration_activation_config_missing:{integration_type}",
                "kind": "integration_activation",
                "title": f"Configure {integration_type} activation",
                "description": "Fill required channel activation fields.",
                "impact": "Navigation only. Activation config is edited from Channel settings.",
                "required_actor_scopes": [],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": activation_href},
            })

    if "heartbeat_not_configured" in finding_codes:
        href = _channel_settings_href(manifest, "automation")
        if href:
            actions.append({
                "id": f"{context.get('channel_id')}:heartbeat_not_configured:automation",
                "finding_code": "heartbeat_not_configured",
                "kind": "agent_status",
                "title": "Open heartbeat settings",
                "description": "Configure a channel heartbeat if this bot should check in autonomously.",
                "impact": "Navigation only. Heartbeat settings are not changed automatically.",
                "required_actor_scopes": ["channels.heartbeat:write"],
                "grants_scopes": [],
                "apply": {"type": "navigate", "href": href},
            })

    return actions


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
            "publish_widget_authoring_receipt",
            "inspect_widget_pin_if_health_fails",
        ],
        "readiness": readiness,
        "findings": findings,
    }


def _coding_run_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    available_tools = [name for name in PROJECT_CODING_RUN_TOOLS if name in _local_tools]
    missing_tools = [name for name in PROJECT_CODING_RUN_TOOLS if name not in _local_tools]
    project = manifest.get("project") or {}
    runtime = project.get("runtime_env") or {}
    readiness = "ready"
    if not project.get("attached"):
        readiness = "needs_project"
    elif missing_tools:
        readiness = "blocked"
    elif runtime and not runtime.get("ready", True):
        readiness = "runtime_needs_attention"
    return {
        "readiness": readiness,
        "fresh_instances": "available",
        "run_receipts": "available" if "publish_project_run_receipt" in _local_tools else "missing",
        "required_tools": list(PROJECT_CODING_RUN_TOOLS),
        "available_tools": available_tools,
        "missing_tools": missing_tools,
        "default_flow": [
            "start Project coding run",
            "bind fresh Project instance",
            "edit and test in Project root",
            "capture screenshots when UI changes",
            "publish_project_run_receipt",
        ],
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
        "tool_error_contract": tool_error_contract(),
        "tools": await _tool_payload(db, bot, include_schemas=include_schemas, max_tools=max_tools),
        "skills": await _skill_payload(db, bot, channel),
        "project": await _project_payload(db, channel),
        "harness": {
            "runtime": bot.harness_runtime if bot else None,
            "workdir": bot.harness_workdir if bot else None,
            "bridge_status": "native" if bot and bot.harness_runtime else "not_configured",
        },
    }
    manifest["coding_run"] = _coding_run_payload(manifest)
    manifest["widgets"] = _widget_payload(manifest)
    manifest["integrations"] = await _integration_payload(db, channel)
    manifest["runtime_context"] = await runtime_context_payload(
        db,
        channel,
        session_id=manifest["context"].get("session_id"),
    )
    manifest["work_state"] = await work_state_payload(
        db,
        bot_id=manifest["context"].get("bot_id"),
        channel_id=manifest["context"].get("channel_id"),
        session_id=manifest["context"].get("session_id"),
    )
    manifest["agent_status"] = await agent_status_payload(
        db,
        bot_id=manifest["context"].get("bot_id"),
        channel_id=manifest["context"].get("channel_id"),
        session_id=manifest["context"].get("session_id"),
    )
    manifest["activity_log"] = await activity_log_payload(
        db,
        bot_id=manifest["context"].get("bot_id"),
        channel_id=manifest["context"].get("channel_id"),
        session_id=manifest["context"].get("session_id"),
    )
    manifest["doctor"] = {
        "status": "ok",
        "findings": _doctor_findings(manifest),
        "proposed_actions": [],
    }
    if any(f["severity"] == "error" for f in manifest["doctor"]["findings"]):
        manifest["doctor"]["status"] = "error"
    elif manifest["doctor"]["findings"]:
        manifest["doctor"]["status"] = "needs_attention"
    manifest["doctor"]["proposed_actions"] = _doctor_proposed_actions(manifest)
    return manifest
