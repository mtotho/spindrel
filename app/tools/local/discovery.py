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
            "Look up a tool by name and activate it for this turn. Returns the full "
            "OpenAI function schema AND adds the tool to your callable tools for the "
            "next iteration, so you can invoke it immediately after. Use this when you "
            "see a tool listed in the 'available tools (not yet loaded)' index."
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
    """Return the full OpenAI function schema for a tool and activate it for the next loop iteration.

    The agent loop reads `current_activated_tools` at the top of each iteration and
    merges any entries into `tools_param`, so a tool looked up via get_tool_info
    becomes callable on the very next LLM call (not just described to the model).
    """
    schema_for_activation: dict | None = None
    response_json: str

    entry = _tools.get(tool_name)
    if entry is not None:
        schema_for_activation = entry["schema"]
        response_json = json.dumps(schema_for_activation, indent=2)
    else:
        # Also check tool_embeddings DB for MCP tools
        from app.db.engine import async_session
        from app.db.models import ToolEmbedding
        from sqlalchemy import select
        async with async_session() as db:
            row = (await db.execute(
                select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_name)
            )).scalar_one_or_none()
        if row is None:
            return json.dumps({"error": f"Tool {tool_name!r} not found."})
        schema_for_activation = row.schema_ if isinstance(row.schema_, dict) else None
        response_json = json.dumps({
            "tool_name": tool_name,
            "server_name": row.server_name,
            "schema": row.schema_,
        }, indent=2)

    # Activate the tool for the next loop iteration. The agent loop owns the
    # actual tools_param rebuild and authorization set expansion; we just
    # append the schema so it picks it up.
    if schema_for_activation is not None:
        try:
            from app.agent.context import current_activated_tools
            _active = current_activated_tools.get()
            if _active is not None:
                _existing = {
                    (t.get("function") or {}).get("name")
                    for t in _active
                    if isinstance(t, dict)
                }
                fn_name = (schema_for_activation.get("function") or {}).get("name")
                if fn_name and fn_name not in _existing:
                    _active.append(schema_for_activation)
                    logger.info("get_tool_info: activated %r for next iteration", fn_name)
        except Exception:
            logger.exception("get_tool_info: failed to activate %r", tool_name)

    return response_json
