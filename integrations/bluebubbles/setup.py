"""BlueBubbles integration setup manifest."""

SETUP = {
    "env_vars": [
        {"key": "BLUEBUBBLES_SERVER_URL", "required": True, "description": "BlueBubbles server URL (e.g. http://192.168.1.50:1234)"},
        {"key": "BLUEBUBBLES_PASSWORD", "required": True, "description": "BlueBubbles server password", "secret": True},
        {"key": "AGENT_API_KEY", "required": True, "description": "API key for the agent server", "secret": True},
        {"key": "AGENT_BASE_URL", "required": False, "description": "Agent server URL (default: http://localhost:8000)"},
        {"key": "BB_DEFAULT_BOT", "required": False, "description": "Default bot ID (default: default)"},
    ],
    "webhook": None,
    "instructions_url": None,
    "python_dependencies": [
        {"package": "python-socketio", "import_name": "socketio"},
        {"package": "aiohttp", "import_name": "aiohttp"},
    ],
    "binding": {
        "client_id_prefix": "bb:",
        "client_id_placeholder": "bb:iMessage;-;+15551234567",
        "client_id_description": "BlueBubbles chat GUID (e.g. iMessage;-;+15551234567 for 1:1, iMessage;+;chat123 for group)",
        "display_name_placeholder": "+1 (555) 123-4567",
    },
}
