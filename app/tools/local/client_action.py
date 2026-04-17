import json

from sqlalchemy import select

from app.tools.registry import register

CLIENT_ACTIONS = {
    "new_session": "Start a fresh conversation, clearing the current chat.",
    "switch_bot": "Switch to a different bot/assistant. Requires 'bot_id' in params.",
    "switch_session": "Switch to a previous conversation by UUID. Requires 'session_id' in params.",
    "toggle_tts": "Toggle text-to-speech output on or off.",
    "list_sessions": "List previous conversations and display them. If the user wants to switch "
                     "to a specific conversation, follow up with switch_session using the "
                     "session_id from the results.",
    "list_bots": "Display all available bots/assistants to the user.",
    "show_history": "Display the conversation history. You should then summarize "
                    "the conversation based on context.",
}

_TOOL_RESULTS = {
    "show_history": "Conversation history has been displayed to the user. "
                    "Provide a brief summary of what was discussed so far based on "
                    "the conversation summary and recent messages in your context.",
    "list_bots": "Available bots have been displayed to the user.",
}

_DESCRIPTIONS = "\n".join(f"- {k}: {v}" for k, v in CLIENT_ACTIONS.items())


async def _list_sessions_result() -> str:
    from app.db.engine import async_session
    from app.db.models import Session

    async with async_session() as db:
        result = await db.execute(
            select(Session).order_by(Session.last_active.desc())
        )
        sessions = result.scalars().all()

    entries = []
    for s in sessions:
        entries.append({
            "id": str(s.id),
            "bot_id": s.bot_id,
            "title": s.title,
            "last_active": s.last_active.isoformat() if s.last_active else None,
        })

    return json.dumps({
        "status": "ok",
        "action": "list_sessions",
        "params": {},
        "result": "Conversations displayed to user. Data below for your reference.",
        "sessions": entries,
    }, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "client_action",
        "description": (
            "Request an action on the user's client device. "
            "Use this when the user asks to perform a client-side operation "
            "like starting a fresh conversation, switching bots, listing past conversations, "
            "or showing conversation history. "
            f"Available actions:\n{_DESCRIPTIONS}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(CLIENT_ACTIONS.keys()),
                    "description": "The client-side action to perform.",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Optional parameters for the action. "
                        "switch_bot requires {\"bot_id\": \"...\"}, "
                        "switch_session requires {\"session_id\": \"...\"}."
                    ),
                },
            },
            "required": ["action"],
        },
    },
})
async def client_action(action: str, params: dict | None = None) -> str:
    if action not in CLIENT_ACTIONS:
        return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)

    if action == "list_sessions":
        return await _list_sessions_result()

    result = _TOOL_RESULTS.get(action, f"Action '{action}' executed on client.")
    return json.dumps({"status": "ok", "action": action, "params": params or {}, "result": result}, ensure_ascii=False)
