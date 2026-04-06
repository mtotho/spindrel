"""Gmail integration manifest."""

SETUP = {
    "icon": "Mail",
    "env_vars": [
        {
            "key": "GMAIL_EMAIL",
            "required": True,
            "description": "Gmail email address for IMAP login",
        },
        {
            "key": "GMAIL_APP_PASSWORD",
            "required": True,
            "description": "Gmail app password (not your regular password — generate at myaccount.google.com/apppasswords)",
            "secret": True,
        },
        {
            "key": "GMAIL_IMAP_HOST",
            "required": False,
            "description": "IMAP server hostname",
            "default": "imap.gmail.com",
        },
        {
            "key": "GMAIL_IMAP_PORT",
            "required": False,
            "description": "IMAP server port",
            "default": "993",
        },
        {
            "key": "GMAIL_POLL_INTERVAL",
            "required": False,
            "description": "Seconds between poll cycles",
            "default": "60",
        },
        {
            "key": "GMAIL_MAX_PER_POLL",
            "required": False,
            "description": "Maximum emails to fetch per poll cycle",
            "default": "25",
        },
        {
            "key": "GMAIL_FOLDERS",
            "required": False,
            "description": "Comma-separated IMAP folders to poll",
            "default": "INBOX",
        },
        {
            "key": "GMAIL_INITIAL_FETCH",
            "required": False,
            "description": (
                "What to do on first poll when no cursor exists. "
                '"new" (default) = skip existing mail, only process future emails. '
                '"recent:N" = fetch last N days (e.g. "recent:7"). '
                '"all" = fetch everything (original behavior).'
            ),
            "default": "new",
        },
        {
            "key": "AGENT_BASE_URL",
            "required": False,
            "description": "Agent server base URL",
            "default": "http://localhost:8000",
        },
        {
            "key": "INGESTION_CLASSIFIER_MODEL",
            "required": False,
            "description": "Model for email safety classification",
            "default": "gpt-4o-mini",
            "type": "model_selection",
        },
    ],
    "api_permissions": "slack_integration",
    "webhook": None,
    "instructions_url": None,
    "activation": {
        "carapaces": ["gmail-feeds"],
        "requires_workspace": True,
        "description": "Email ingestion and digest management via Gmail IMAP",

    },
    "binding": {
        "client_id_prefix": "gmail:",
        "client_id_placeholder": "gmail:user@gmail.com",
        "client_id_description": "Gmail address for this channel (e.g. gmail:user@gmail.com)",
        "display_name_placeholder": "user@gmail.com",
        "auto_client_id": "gmail:{GMAIL_EMAIL}",
    },
}
