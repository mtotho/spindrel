import json
import logging

from app.agent.persona import write_persona, append_to_persona

from app.tools.registry import register

logger = logging.getLogger(__name__)

UPDATE_PERSONA_DESCRIPTION = (
    "Overwrites your persona layer — a concise, first-person document of self-knowledge "
    "you maintain across conversations. Update it when you notice a consistent preference, "
    "communication pattern, or internalized understanding worth keeping permanently. "
    "Keep it under 300 tokens. Write in first person as self-knowledge, not rules or instructions."
)

APPEND_TO_PERSONA_DESCRIPTION = (
    "Appends content to your persona layer — a concise, first-person document of self-knowledge "
    "you maintain across conversations. Append it when you notice a new preference, "
    "communication pattern, or internalized understanding. "
    "Review the existing persona layer before appending to ensure you don't add redundant information."
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
    if name == "append_to_persona":
        content = (args.get("content") or "").strip()
        if not content:
            return "No content provided; persona not appended."
        ok, err = await append_to_persona(bot_id, content)
        if ok:
            return "Persona appended."
        return f"Failed to append to persona: {err}" if err else "Failed to append to persona."
    return json.dumps({"error": f"Unknown persona tool: {name}"})



@register({
    "type": "function",
    "function": {
        "name": "append_to_persona",
        "description": APPEND_TO_PERSONA_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to append to the persona layer. Will be added to the end of the layer.",
                },
            },
            "required": ["content"],
        },
    },
})
async def append_to_persona_tool(content: str) -> str:
    raise NotImplementedError("append_to_persona must be called via call_persona_tool with bot_id injected")
        
