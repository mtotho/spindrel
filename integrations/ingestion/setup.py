"""Ingestion pipeline integration setup manifest."""

SETUP = {
    "icon": "Rss",
    "env_vars": [
        {
            "key": "INGESTION_CLASSIFIER_MODEL",
            "required": False,
            "type": "model_selection",
            "description": "LLM model for content classification",
            "default": "gpt-4o-mini",
        },
        {
            "key": "INGESTION_QUARANTINE_RETENTION_DAYS",
            "required": False,
            "description": "Days to keep quarantined items before cleanup",
            "default": "90",
        },
        {
            "key": "INGESTION_MAX_BODY_BYTES",
            "required": False,
            "description": "Maximum content size in bytes for classification",
            "default": "50000",
        },
        {
            "key": "INGESTION_CLASSIFIER_MAX_RETRIES",
            "required": False,
            "description": "Retry attempts on transient classifier errors",
            "default": "3",
        },
    ],
    "sidebar_section": {
        "id": "content-feeds",
        "title": "CONTENT FEEDS",
        "icon": "Rss",
        "items": [
            {"label": "Dashboard", "href": "/integration/ingestion", "icon": "Rss"},
        ],
    },
    "web_ui": {
        "static_dir": "dashboard/dist",
    },
    "webhook": None,
    "chat_hud": [
        {
            "id": "feed-status",
            "style": "status_strip",
            "endpoint": "/hud/status",
            "poll_interval": 60,
            "label": "Feed Health",
            "icon": "Rss",
        },
    ],
    "chat_hud_presets": {
        "default": {"label": "Feed Status Strip", "widgets": ["feed-status"]},
        "none": {"label": "No HUD", "widgets": []},
    },
}
