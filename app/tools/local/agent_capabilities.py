"""Agent-first capability manifest and readiness tools."""
from __future__ import annotations

import json

from app.agent.context import current_bot_id, current_channel_id, current_session_id
from app.db.engine import async_session
from app.services.agent_capabilities import build_agent_capability_manifest
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "list_agent_capabilities",
        "description": (
            "Return the machine-readable manifest for what this agent can do now: "
            "API scopes/endpoints, tool working set, skill working set, Project "
            "context, runtime context budget, assigned work, agent status, harness status, widget authoring tools, and readiness findings. "
            "Use this before broad configuration, API, Project, widget, or harness work; publish_execution_receipt records outcomes after approved fixes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_schemas": {
                    "type": "boolean",
                    "description": "Include tool input and return schemas for key tools. Defaults false to keep output compact.",
                },
                "include_endpoints": {
                    "type": "boolean",
                    "description": "Include scoped API endpoint details. Defaults true.",
                },
                "max_tools": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum key tool details to include. Defaults 80.",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "context": {"type": "object"},
            "api": {"type": "object"},
            "tool_error_contract": {"type": "object"},
            "tools": {"type": "object"},
            "skills": {"type": "object"},
            "project": {"type": "object"},
            "runtime_context": {"type": "object"},
            "work_state": {"type": "object"},
            "agent_status": {"type": "object"},
            "activity_log": {"type": "object"},
            "coding_run": {"type": "object"},
            "harness": {"type": "object"},
            "widgets": {"type": "object"},
        "doctor": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["schema_version", "context", "api", "tools", "skills", "doctor"],
})
async def list_agent_capabilities(
    include_schemas: bool = False,
    include_endpoints: bool = True,
    max_tools: int = 80,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    async with async_session() as db:
        manifest = await build_agent_capability_manifest(
            db,
            bot_id=bot_id,
            channel_id=current_channel_id.get(),
            session_id=current_session_id.get(),
            include_schemas=include_schemas,
            include_endpoints=include_endpoints,
            max_tools=max(1, min(int(max_tools or 80), 500)),
        )
    return json.dumps(manifest, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "get_agent_context_snapshot",
        "description": (
            "Return the current agent runtime context budget and recommendation only. "
            "Use this before long-running, tool-heavy, summarization, or handoff decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "context": {"type": "object"},
        "runtime_context": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["context", "runtime_context"],
})
async def get_agent_context_snapshot() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    async with async_session() as db:
        manifest = await build_agent_capability_manifest(
            db,
            bot_id=bot_id,
            channel_id=current_channel_id.get(),
            session_id=current_session_id.get(),
            include_schemas=False,
            include_endpoints=False,
            max_tools=20,
        )
    return json.dumps(
        {
            "context": manifest["context"],
            "runtime_context": manifest["runtime_context"],
        },
        ensure_ascii=False,
    )


@register({
    "type": "function",
    "function": {
        "name": "get_agent_work_snapshot",
        "description": (
            "Return this agent's assigned Mission Control work: active missions, assigned Attention Items, "
            "recent updates, and the next recommended work action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum missions and Attention Items to return. Defaults 10.",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "context": {"type": "object"},
        "work_state": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["context", "work_state"],
})
async def get_agent_work_snapshot(max_items: int = 10) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    channel_id = current_channel_id.get()
    session_id = current_session_id.get()
    async with async_session() as db:
        from app.services.agent_work_snapshot import build_agent_work_snapshot

        work_state = await build_agent_work_snapshot(
            db,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            max_items=max(1, min(int(max_items or 10), 50)),
        )
    return json.dumps(
        {
            "context": {
                "bot_id": bot_id,
                "channel_id": str(channel_id) if channel_id else None,
                "session_id": str(session_id) if session_id else None,
            },
            "work_state": work_state,
        },
        ensure_ascii=False,
    )


@register({
    "type": "function",
    "function": {
        "name": "get_agent_activity_log",
        "description": (
            "Return this agent's recent replayable activity across tool calls, Attention, Mission updates, "
            "Project run receipts, widget receipts, and execution receipts. Use this to reconstruct what happened before "
            "continuing work, summarizing progress, or debugging a failure."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["tool_call", "attention", "mission_update", "project_receipt", "widget_receipt", "execution_receipt"],
                    "description": "Optional activity kind filter.",
                },
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum activity items to return. Defaults 20.",
                },
                "current_session_only": {
                    "type": "boolean",
                    "description": "When true, restrict replay to the current session. Defaults false so handoffs can see recent channel work.",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "context": {"type": "object"},
        "items": {"type": "array", "items": {"type": "object"}},
        "supported_kinds": {"type": "array", "items": {"type": "string"}},
        "error": {"type": "string"},
    },
    "required": ["context", "items", "supported_kinds"],
})
async def get_agent_activity_log(
    kind: str | None = None,
    max_items: int = 20,
    current_session_only: bool = False,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    channel_id = current_channel_id.get()
    session_id = current_session_id.get() if current_session_only else None
    async with async_session() as db:
        from app.services.agent_activity import AGENT_ACTIVITY_KINDS, list_agent_activity

        items = await list_agent_activity(
            db,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            kind=kind,
            limit=max(1, min(int(max_items or 20), 100)),
        )
    return json.dumps(
        {
            "context": {
                "bot_id": bot_id,
                "channel_id": str(channel_id) if channel_id else None,
                "session_id": str(session_id) if session_id else None,
            },
            "supported_kinds": list(AGENT_ACTIVITY_KINDS),
            "items": items,
        },
        ensure_ascii=False,
    )


@register({
    "type": "function",
    "function": {
        "name": "get_agent_status_snapshot",
        "description": (
            "Return this agent's current runtime status: idle, scheduled, working, stale/blocked, or failed. "
            "Use this before waiting on autonomous work, diagnosing a stuck run, or deciding whether a heartbeat needs review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_runs": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum recent task/heartbeat runs to return. Defaults 10.",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "context": {"type": "object"},
        "agent_status": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["context", "agent_status"],
})
async def get_agent_status_snapshot(max_runs: int = 10) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    channel_id = current_channel_id.get()
    session_id = current_session_id.get()
    async with async_session() as db:
        from app.services.agent_status import build_agent_status_snapshot

        agent_status = await build_agent_status_snapshot(
            db,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            limit=max(1, min(int(max_runs or 10), 50)),
        )
    return json.dumps(
        {
            "context": {
                "bot_id": bot_id,
                "channel_id": str(channel_id) if channel_id else None,
                "session_id": str(session_id) if session_id else None,
            },
            "agent_status": agent_status,
        },
        ensure_ascii=False,
    )


@register({
    "type": "function",
    "function": {
        "name": "run_agent_doctor",
        "description": (
            "Run a read-only readiness check over this agent's capability manifest. "
            "Returns concrete findings and suggested next actions for missing API "
            "grants, Project readiness, harness workdir gaps, widget-authoring "
            "tool registration gaps, runtime context pressure, and empty working sets."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
        "properties": {
            "status": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "proposed_actions": {"type": "array", "items": {"type": "object"}},
            "context": {"type": "object"},
            "error": {"type": "string"},
        },
    "required": ["status", "findings"],
})
async def run_agent_doctor() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    async with async_session() as db:
        manifest = await build_agent_capability_manifest(
            db,
            bot_id=bot_id,
            channel_id=current_channel_id.get(),
            session_id=current_session_id.get(),
            include_schemas=False,
            include_endpoints=False,
            max_tools=40,
        )
    return json.dumps(
        {
            **manifest["doctor"],
            "context": manifest["context"],
        },
        ensure_ascii=False,
    )
