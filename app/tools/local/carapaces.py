"""Local tool: manage_carapace — create, update, list, and inspect carapaces."""

import json
import logging
from datetime import datetime, timezone

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_carapace",
        "description": (
            "Create, update, list, or inspect carapaces (composable skill+tool bundles). "
            "A carapace bundles skills, tools, pinned tools, and behavioral instructions "
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
                    "description": "Carapace ID (required for create, update, get).",
                },
                "name": {
                    "type": "string",
                    "description": "Display name (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the carapace.",
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
                    "description": "Comma-separated carapace IDs to compose with.",
                },
                "system_prompt_fragment": {
                    "type": "string",
                    "description": "Behavioral instructions injected when this carapace is active.",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for categorization.",
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_carapace(
    action: str,
    id: str = "",
    name: str = "",
    description: str = "",
    skills: str = "",
    local_tools: str = "",
    pinned_tools: str = "",
    mcp_tools: str = "",
    includes: str = "",
    system_prompt_fragment: str = "",
    tags: str = "",
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
                skills=_parse_skills(skills),
                local_tools=_csv(local_tools),
                mcp_tools=_csv(mcp_tools),
                pinned_tools=_csv(pinned_tools),
                system_prompt_fragment=system_prompt_fragment or None,
                includes=_csv(includes),
                tags=_csv(tags),
                source_type="tool",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()

        from app.agent.carapaces import reload_carapaces
        await reload_carapaces()
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

            if name is not None and name != "":
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
            if tags is not None:
                row.tags = _csv(tags)
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        from app.agent.carapaces import reload_carapaces
        await reload_carapaces()
        return json.dumps({"ok": True, "id": id, "message": f"Carapace '{id}' updated."})

    return json.dumps({"error": f"Unknown action: {action}. Use create, update, list, or get."})
