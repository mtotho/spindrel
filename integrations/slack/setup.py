"""Slack integration setup manifest."""

SETUP = {
    "env_vars": [
        {"key": "SLACK_BOT_TOKEN", "required": True, "description": "Bot token (xoxb-...) — needs chat:write, reactions:write, channels:read scopes", "secret": True},
        {"key": "SLACK_APP_TOKEN", "required": True, "description": "App-level token (xapp-...) for Socket Mode", "secret": True},
        {"key": "AGENT_API_KEY", "required": True, "description": "API key for the agent server", "secret": True},
        {"key": "AGENT_BASE_URL", "required": False, "description": "Agent server URL (default: http://localhost:8000)"},
    ],
    "webhook": None,
    "instructions_url": None,
    "binding": {
        "client_id_prefix": "slack:",
        "client_id_placeholder": "slack:C01ABC123",
        "client_id_description": "Slack channel ID (starts with C)",
        "display_name_placeholder": "#general",
    },
}
