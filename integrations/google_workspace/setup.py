"""Google Workspace integration setup manifest."""

SETUP = {
    "icon": "Cloud",
    "env_vars": [
        {
            "key": "GWS_CLIENT_ID",
            "required": True,
            "secret": False,
            "description": "Google OAuth Client ID — create at console.cloud.google.com/apis/credentials (Web application type)",
        },
        {
            "key": "GWS_CLIENT_SECRET",
            "required": True,
            "secret": True,
            "description": "Google OAuth Client Secret — from the same OAuth client ID",
        },
        {
            "key": "GWS_TIMEOUT",
            "required": False,
            "secret": False,
            "description": "CLI command timeout in seconds (default: 60)",
            "default": "60",
        },
    ],
    "npm_dependencies": [
        {"package": "@googleworkspace/cli", "binary_name": "gws"},
    ],
    "oauth": {
        "auth_start": "/integrations/google_workspace/auth/start",
        "status": "/integrations/google_workspace/auth/status",
        "disconnect": "/integrations/google_workspace/auth/disconnect",
        "scope_services": [
            "drive", "gmail", "calendar", "sheets", "docs", "slides",
            "tasks", "people", "chat", "forms", "keep", "meet",
        ],
    },
    "activation": {
        "carapaces": ["google-workspace"],
        "requires_workspace": False,
        "description": "Google Workspace — Drive, Gmail, Calendar, Sheets, Docs, and more",
        "config_fields": [
            {
                "key": "allowed_services",
                "type": "multiselect",
                "label": "Enabled Services",
                "description": "Which Google services this channel can access",
                "options": [
                    {"value": "drive", "label": "Google Drive"},
                    {"value": "gmail", "label": "Gmail"},
                    {"value": "calendar", "label": "Google Calendar"},
                    {"value": "sheets", "label": "Google Sheets"},
                    {"value": "docs", "label": "Google Docs"},
                    {"value": "slides", "label": "Google Slides"},
                    {"value": "tasks", "label": "Google Tasks"},
                    {"value": "people", "label": "Google Contacts"},
                    {"value": "chat", "label": "Google Chat"},
                    {"value": "forms", "label": "Google Forms"},
                    {"value": "keep", "label": "Google Keep"},
                    {"value": "meet", "label": "Google Meet"},
                ],
                "default": ["drive", "gmail", "calendar"],
            },
            {
                "key": "drive_root_folder",
                "type": "string",
                "label": "Drive Root Folder",
                "description": "Folder ID to scope Drive operations to (paste from Drive URL). Leave empty for full Drive access.",
            },
        ],
    },
    "webhook": None,
    "instructions_url": None,
    "binding": {
        "client_id_prefix": "gws:",
        "client_id_placeholder": "gws:default",
        "client_id_description": "Google Workspace account identifier",
        "config_fields": [],
    },
}
