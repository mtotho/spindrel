import json

from app.tools.registry import register

CLIENT_ACTIONS = {
    "new_session": "Start a fresh conversation session, clearing all history.",
    "switch_bot": "Switch to a different bot/assistant. Requires 'bot_id' in params.",
    "switch_session": "Switch to an existing session by UUID. Requires 'session_id' in params.",
    "toggle_tts": "Toggle text-to-speech output on or off.",
    "list_sessions": "Display all conversation sessions to the user.",
    "list_bots": "Display all available bots/assistants to the user.",
    "show_history": "Display the conversation history. You should then summarize the conversation in one sentence.",
}

_TOOL_RESULTS = {
    "show_history": "Conversation history has been displayed to the user. "
                    "Provide a brief one-sentence summary of what was discussed so far.",
    "list_sessions": "Sessions have been displayed to the user.",
    "list_bots": "Available bots have been displayed to the user.",
}

_DESCRIPTIONS = "\n".join(f"- {k}: {v}" for k, v in CLIENT_ACTIONS.items())


@register({
    "type": "function",
    "function": {
        "name": "client_action",
        "description": (
            "Request an action on the user's client device. "
            "Use this when the user asks to perform a client-side operation "
            "like starting a new session, switching bots, listing sessions, "
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
        return json.dumps({"error": f"Unknown action: {action}"})
    result = _TOOL_RESULTS.get(action, f"Action '{action}' executed on client.")
    return json.dumps({"status": "ok", "action": action, "params": params or {}, "result": result})
