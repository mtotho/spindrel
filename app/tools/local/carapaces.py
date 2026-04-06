"""Local tool: manage_capability — create, update, list, and inspect capabilities."""

import json
import logging
from datetime import datetime, timezone

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_capability",
        "description": (
            "Create, update, list, or inspect capabilities (composable skill+tool bundles). "
            "A capability bundles skills, tools, pinned tools, and behavioral instructions "
            "into a reusable configuration that can be applied to any bot or sub-agent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "list", "get"],
                    "description": "The action to perform.",
                },
                "id": {
                    "type": "string",
                    "description": "Capability ID (required for create, update, get).",
                },
                "name": {
                    "type": "string",
                    "description": "Display name (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the capability.",
                },
                "skills": {
                    "type": "string",
                    "description": 'JSON array of skill configs, e.g. \'[{"id": "testing", "mode": "pinned"}]\'.',
                },
                "local_tools": {
                    "type": "string",
                    "description": "Comma-separated tool names, e.g. 'exec_command,file,web_search'.",
                },
                "pinned_tools": {
                    "type": "string",
                    "description": "Comma-separated pinned tool names.",
                },
                "mcp_tools": {
                    "type": "string",
                    "description": "Comma-separated MCP server names.",
                },
                "includes": {
                    "type": "string",
                    "description": "Comma-separated capability IDs to compose with.",
                },
                "system_prompt_fragment": {
                    "type": "string",
                    "description": "Behavioral instructions injected when this capability is active.",
                },
                "delegates": {
                    "type": "string",
                    "description": (
                        'JSON array of delegate configs, e.g. '
                        '\'[{"id": "qa", "type": "carapace", "description": "Run QA", "model_tier": "standard"}]\'. '
                        'Each entry has id, type (carapace or bot), description, and optional model_tier (free/fast/standard/capable/frontier).'
                    ),
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for categorization.",
                },
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane")
async def manage_capability(
    action: str,
    id: str = "",
    name: str = "",
    description: str | None = None,
    skills: str | None = None,
    local_tools: str | None = None,
    pinned_tools: str | None = None,
    mcp_tools: str | None = None,
    includes: str | None = None,
    delegates: str | None = None,
    system_prompt_fragment: str | None = None,
    tags: str | None = None,
) -> str:
    from app.db.engine import async_session
    from app.db.models import Carapace as CarapaceRow
    from sqlalchemy import select

    def _csv(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()] if s else []

    def _parse_skills(s: str) -> list:
        if not s:
            return []
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Treat as comma-separated skill IDs
            return [{"id": x.strip(), "mode": "on_demand"} for x in s.split(",") if x.strip()]

    def _parse_delegates(s: str) -> list:
        if not s:
            return []
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Treat as comma-separated carapace IDs
            return [{"id": x.strip(), "type": "carapace"} for x in s.split(",") if x.strip()]

    if action == "list":
        from app.agent.carapaces import list_carapaces
        items = list_carapaces()
        if not items:
            return json.dumps({"carapaces": [], "message": "No carapaces found."})
        summary = []
        for c in items:
            summary.append({
                "id": c["id"],
                "name": c["name"],
                "description": c.get("description"),
                "tags": c.get("tags", []),
                "includes": c.get("includes", []),
                "tool_count": len(c.get("local_tools", [])),
                "skill_count": len(c.get("skills", [])),
            })
        return json.dumps({"carapaces": summary})

    if action == "get":
        if not id:
            return json.dumps({"error": "id is required for get action."})
        from app.agent.carapaces import get_carapace
        c = get_carapace(id)
        if c is None:
            return json.dumps({"error": f"Carapace '{id}' not found."})
        return json.dumps(c)

    if action == "create":
        if not id or not name:
            return json.dumps({"error": "id and name are required for create action."})
        # Tool-created carapaces cannot specify tools or delegates (privilege escalation guard)
        if _csv(local_tools or "") or _csv(pinned_tools or "") or _csv(mcp_tools or ""):
            return json.dumps({"error": "Tool-created carapaces cannot specify local_tools, pinned_tools, or mcp_tools. Use the admin UI."})
        if _parse_delegates(delegates or ""):
            return json.dumps({"error": "Tool-created carapaces cannot specify delegates. Use the admin UI."})
        cid = id.strip().lower().replace(" ", "-")

        async with async_session() as db:
            existing = await db.get(CarapaceRow, cid)
            if existing:
                return json.dumps({"error": f"Carapace '{cid}' already exists."})

            now = datetime.now(timezone.utc)
            row = CarapaceRow(
                id=cid,
                name=name.strip(),
                description=description or None,
                skills=_parse_skills(skills or ""),
                local_tools=[],
                mcp_tools=[],
                pinned_tools=[],
                system_prompt_fragment=system_prompt_fragment or None,
                includes=_csv(includes or ""),
                delegates=[],
                tags=_csv(tags or ""),
                source_type="tool",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()

        from app.agent.carapaces import reload_carapaces
        await reload_carapaces()
        try:
            from app.agent.capability_rag import reindex_capability
            await reindex_capability(cid)
        except Exception:
            pass
        return json.dumps({"ok": True, "id": cid, "message": f"Carapace '{cid}' created."})

    if action == "update":
        if not id:
            return json.dumps({"error": "id is required for update action."})

        async with async_session() as db:
            row = await db.get(CarapaceRow, id)
            if not row:
                return json.dumps({"error": f"Carapace '{id}' not found."})
            if row.source_type in ("file", "integration"):
                return json.dumps({"error": "Cannot edit a file-managed carapace."})

            # Tool-created carapaces cannot modify tools or delegates (privilege escalation guard)
            if row.source_type == "tool":
                if local_tools is not None and _csv(local_tools):
                    return json.dumps({"error": "Tool-created carapaces cannot specify local_tools. Use the admin UI."})
                if pinned_tools is not None and _csv(pinned_tools):
                    return json.dumps({"error": "Tool-created carapaces cannot specify pinned_tools. Use the admin UI."})
                if mcp_tools is not None and _csv(mcp_tools):
                    return json.dumps({"error": "Tool-created carapaces cannot specify mcp_tools. Use the admin UI."})
                if delegates is not None and _parse_delegates(delegates):
                    return json.dumps({"error": "Tool-created carapaces cannot specify delegates. Use the admin UI."})

            if name:
                row.name = name.strip()
            if description is not None:
                row.description = description or None
            if skills is not None:
                row.skills = _parse_skills(skills)
            if local_tools is not None:
                row.local_tools = _csv(local_tools)
            if mcp_tools is not None:
                row.mcp_tools = _csv(mcp_tools)
            if pinned_tools is not None:
                row.pinned_tools = _csv(pinned_tools)
            if system_prompt_fragment is not None:
                row.system_prompt_fragment = system_prompt_fragment or None
            if includes is not None:
                row.includes = _csv(includes)
            if delegates is not None:
                row.delegates = _parse_delegates(delegates)
            if tags is not None:
                row.tags = _csv(tags)
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        from app.agent.carapaces import reload_carapaces
        await reload_carapaces()
        try:
            from app.agent.capability_rag import reindex_capability
            await reindex_capability(id)
        except Exception:
            pass
        return json.dumps({"ok": True, "id": id, "message": f"Carapace '{id}' updated."})

    return json.dumps({"error": f"Unknown action: {action}. Use create, update, list, or get."})
