"""Ingestion pipeline integration setup manifest."""

SETUP = {
    "icon": "Rss",
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
}
