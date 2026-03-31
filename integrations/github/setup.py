"""GitHub integration setup manifest."""

SETUP = {
    "icon": "Code2",
    "env_vars": [
        {"key": "GITHUB_TOKEN", "required": True, "description": "PAT with repo scope", "secret": True},
        {"key": "GITHUB_WEBHOOK_SECRET", "required": True, "description": "Webhook signature secret", "secret": True},
        {"key": "GITHUB_BOT_LOGIN", "required": False, "description": "GitHub username of the bot/PAT owner (to ignore its own comments)"},
    ],
    "api_permissions": ["chat", "bots:read", "channels:read", "channels:write", "sessions:read", "sessions:write"],
    "webhook": {
        "path": "/integrations/github/webhook",
        "description": "GitHub webhook receiver (push, PR, issue events)",
    },
    "instructions_url": None,
    "binding": {
        "client_id_prefix": "github:",
        "client_id_placeholder": "github:owner/repo",
        "client_id_description": "GitHub owner/repo (e.g. octocat/hello-world)",
        "display_name_placeholder": "octocat/hello-world",
        "event_types": [
            {"value": "pull_request", "label": "Pull requests"},
            {"value": "push", "label": "Pushes"},
            {"value": "issues", "label": "Issues"},
            {"value": "issue_comment", "label": "Issue/PR comments"},
            {"value": "pull_request_review", "label": "PR reviews"},
            {"value": "pull_request_review_comment", "label": "PR review comments"},
            {"value": "release", "label": "Releases"},
            {"value": "discussion", "label": "Discussions"},
            {"value": "discussion_comment", "label": "Discussion comments"},
        ],
    },
}
