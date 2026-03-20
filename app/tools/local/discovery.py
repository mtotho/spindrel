"""Tool discovery tool — let agents look up full schemas for available tools."""
import json
import logging

from app.tools.registry import _tools, register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_tool_info",
        "description": (
            "Get the full description and parameters schema for any available tool by name. "
            "Use this when you see a tool listed in the 'available tools (not yet loaded)' index "
            "but don't have its full schema yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The exact name of the tool to look up.",
                },
            },
            "required": ["tool_name"],
        },
    },
})
async def get_tool_info(tool_name: str) -> str:
    """Return the full OpenAI function schema for a registered local tool."""
    entry = _tools.get(tool_name)
    if entry is None:
        # Also check tool_embeddings DB for MCP tools
        from app.db.engine import async_session
        from app.db.models import ToolEmbedding
        from sqlalchemy import select
        async with async_session() as db:
            row = (await db.execute(
                select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_name)
            )).scalar_one_or_none()
        if row:
            return json.dumps({
                "tool_name": tool_name,
                "server_name": row.server_name,
                "schema": row.schema_,
            }, indent=2)
        return json.dumps({"error": f"Tool {tool_name!r} not found."})

    schema = entry["schema"]
    return json.dumps(schema, indent=2)
