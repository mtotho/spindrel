"""Discord integration setup manifest."""

SETUP = {
    "env_vars": [
        {"key": "DISCORD_TOKEN", "required": True, "description": "Bot token from Discord Developer Portal > Bot > Token", "secret": True},
        {"key": "AGENT_API_KEY", "required": True, "description": "API key for the agent server", "secret": True},
        {"key": "AGENT_BASE_URL", "required": False, "description": "Agent server URL (default: http://localhost:8000)"},
    ],
    "api_permissions": "slack_integration",
    "webhook": None,
    "instructions_url": None,
    "binding": {
        "client_id_prefix": "discord:",
        "client_id_placeholder": "discord:123456789012345678",
        "client_id_description": "Discord channel ID (enable Developer Mode, right-click channel > Copy Channel ID)",
        "display_name_placeholder": "#general",
    },
}
