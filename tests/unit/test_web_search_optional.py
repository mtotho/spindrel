"""Tests that web_search uses the correct backend based on WEB_SEARCH_ENABLED."""
import importlib
from unittest.mock import patch

import pytest


def _reload_web_search_module(enabled: bool):
    """Re-import web_search.py with a patched WEB_SEARCH_ENABLED value.

    Returns the registry's _tools dict after reload so we can inspect
    which tools got registered and with which function.
    """
    from app.tools import registry

    # Clear any previously registered tools from this module
    for name in ["web_search", "fetch_url"]:
        registry._tools.pop(name, None)

    with patch("app.config.settings.WEB_SEARCH_ENABLED", enabled):
        import app.tools.local.web_search as mod
        importlib.reload(mod)

    return registry._tools


class TestWebSearchBackendSelection:
    def test_searxng_backend_when_enabled(self):
        tools = _reload_web_search_module(enabled=True)
        assert "web_search" in tools
        func = tools["web_search"]["function"]
        assert func.__name__ == "_web_search_searxng"

    def test_ddgs_backend_when_disabled(self):
        tools = _reload_web_search_module(enabled=False)
        assert "web_search" in tools
        func = tools["web_search"]["function"]
        assert func.__name__ == "_web_search_ddgs"

    def test_fetch_url_always_registered(self):
        for enabled in (True, False):
            tools = _reload_web_search_module(enabled=enabled)
            assert "fetch_url" in tools

    def test_ssrf_helpers_importable_regardless(self):
        """_check_ssrf and _BLOCKED_NETWORKS must stay importable for test_security.py."""
        from app.tools.local.web_search import _check_ssrf, _BLOCKED_NETWORKS

        assert callable(_check_ssrf)
        assert len(_BLOCKED_NETWORKS) > 0
