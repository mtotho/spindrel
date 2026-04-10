"""Web Search integration setup manifest."""


def is_stack_enabled() -> bool:
    """Whether the SearXNG/Playwright containers should run.

    Only true when the integration is in ``searxng`` mode AND
    ``WEB_SEARCH_CONTAINERS`` is truthy.  Instances using ``ddgs`` or
    ``disabled`` mode never start the stack — this prevents e2e/test
    instances (which use ``ddgs``) from racing production for the
    shared host-level container_name.
    """
    from integrations.web_search.config import settings as _ws_settings
    if _ws_settings.WEB_SEARCH_MODE != "searxng":
        return False
    return _ws_settings.WEB_SEARCH_CONTAINERS


SETUP = {
    "version": "1.0",
    "icon": "Search",
    "env_vars": [
        {
            "key": "WEB_SEARCH_MODE",
            "required": False,
            "description": "Search backend: searxng (self-hosted, private), ddgs (DuckDuckGo, lightweight), or disabled",
            "default": "searxng",
            "options": ["searxng", "ddgs", "disabled"],
        },
        {
            "key": "WEB_SEARCH_CONTAINERS",
            "required": False,
            "description": "Start built-in SearXNG + Playwright containers (only needed in searxng mode with no external instance)",
            "default": "true",
        },
        {
            "key": "SEARXNG_URL",
            "required": False,
            "description": "URL of the SearXNG instance (only used in searxng mode). Default auto-detects Docker vs local.",
        },
        {
            "key": "PLAYWRIGHT_WS_URL",
            "required": False,
            "description": "Playwright/Chromium WebSocket URL for JS-rendered page fetching. Default auto-detects Docker vs local.",
        },
    ],
    "webhook": None,
    "instructions_url": None,
    "docker_compose": {
        "file": "docker-compose.yml",
        "project_name": "spindrel-web-search",
        "enabled_setting": "WEB_SEARCH_CONTAINERS",
        "connect_networks": ["agent-server_default"],
        "config_files": ["config/searxng/settings.yml"],
        "description": "SearXNG + Playwright for private web search",
    },
}
