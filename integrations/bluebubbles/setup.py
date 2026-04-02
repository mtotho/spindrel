"""BlueBubbles integration setup manifest."""

SETUP = {
    "icon": "MessageCircle",
    "env_vars": [
        {"key": "BLUEBUBBLES_SERVER_URL", "required": True, "description": "BlueBubbles server URL (e.g. http://192.168.1.50:1234)"},
        {"key": "BLUEBUBBLES_PASSWORD", "required": True, "description": "BlueBubbles server password", "secret": True},
        {"key": "AGENT_API_KEY", "required": True, "description": "API key for the agent server", "secret": True},
        {"key": "AGENT_BASE_URL", "required": False, "description": "Agent server URL (default: http://localhost:8000)"},
        {"key": "BB_DEFAULT_BOT", "required": False, "description": "Default bot ID for Socket.IO client (default: default). Not used by webhook path."},
        {"key": "BB_WAKE_WORDS", "required": False, "description": "Extra wake words (comma-separated). Added on top of automatic bot name/id wake words."},
        {"key": "BB_WEBHOOK_TOKEN", "required": False, "description": "Shared secret for webhook auth (?token=). If empty, webhook is unauthenticated.", "secret": True},
        {"key": "BB_SEND_METHOD", "required": False, "description": "iMessage send method: 'apple-script' (default, reliable) or 'private-api' (requires Private API helper)"},
    ],
    "api_permissions": "slack_integration",
    "webhook": {
        "path": "/integrations/bluebubbles/webhook",
        "description": "BlueBubbles new-message webhook receiver (optional ?token=BB_WEBHOOK_TOKEN auth)",
    },
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
        "config_fields": [
            {"key": "extra_wake_words", "type": "string", "label": "Extra Wake Words", "description": "Comma-separated additional wake words for this chat", "default": ""},
            {"key": "use_bot_wake_word", "type": "boolean", "label": "Use Bot Name as Wake Word", "description": "Automatically use the channel bot's name and ID as wake words", "default": True},
        ],
    },
}
