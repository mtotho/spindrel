import json
import logging

from app.agent.persona import write_persona
from app.tools.registry import register

logger = logging.getLogger(__name__)

UPDATE_PERSONA_DESCRIPTION = (
    "Overwrites your persona layer — a concise, first-person document of self-knowledge "
    "you maintain across conversations. Update it when you notice a consistent preference, "
    "communication pattern, or internalized understanding worth keeping permanently. "
    "Keep it under 300 tokens. Write in first person as self-knowledge, not rules or instructions."
)


@register({
    "type": "function",
    "function": {
        "name": "update_persona",
        "description": UPDATE_PERSONA_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full persona layer content. Replaces the existing layer entirely.",
                },
            },
            "required": ["content"],
        },
    },
})
async def update_persona_tool(content: str) -> str:
    raise NotImplementedError("update_persona must be called via call_persona_tool with bot_id injected")


async def call_persona_tool(name: str, arguments_json: str, bot_id: str) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "Invalid tool arguments."
    if name == "update_persona":
        content = (args.get("content") or "").strip()
        if not content:
            return "No content provided; persona not updated."
        ok, err = await write_persona(bot_id, content)
        if ok:
            return "Persona updated."
        return f"Failed to update persona: {err}" if err else "Failed to update persona."
    return json.dumps({"error": f"Unknown persona tool: {name}"})