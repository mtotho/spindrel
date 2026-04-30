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
            "context, harness status, widget authoring tools, and readiness findings. "
            "Use this before broad configuration, API, Project, widget, or harness work."
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
        "tools": {"type": "object"},
        "skills": {"type": "object"},
        "project": {"type": "object"},
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
        "name": "run_agent_doctor",
        "description": (
            "Run a read-only readiness check over this agent's capability manifest. "
            "Returns concrete findings and suggested next actions for missing API "
            "grants, Project readiness, harness workdir gaps, widget-authoring "
            "tool registration gaps, and empty working sets."
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
