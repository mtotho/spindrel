"""GitHub integration setup manifest."""

SETUP = {
    "env_vars": [
        {"key": "GITHUB_TOKEN", "required": True, "description": "PAT with repo scope"},
        {"key": "GITHUB_WEBHOOK_SECRET", "required": True, "description": "Webhook signature secret"},
        {"key": "GITHUB_BOT_LOGIN", "required": False, "description": "GitHub username of the bot/PAT owner (to ignore its own comments)"},
    ],
    "webhook": {
        "path": "/integrations/github/webhook",
        "description": "GitHub webhook receiver (push, PR, issue events)",
    },
    "instructions_url": None,
}
