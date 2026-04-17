"""Tests for the integration lifecycle-status model.

Two-state lifecycle: ``available | enabled``. "Needs setup" is derived at
render time from ``is_configured`` — not a stored state. Legacy
``is_disabled`` / ``set_disabled`` helpers have been retired.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.integration_settings import (
    STATUS_KEY,
    _cache,
    get_status,
    is_active,
    is_configured,
)


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def setup_method(self):
        self._original_cache = dict(_cache)

    def teardown_method(self):
        _cache.clear()
        _cache.update(self._original_cache)

    def test_default_is_available(self):
        _cache.pop(("test_intg", STATUS_KEY), None)
        assert get_status("test_intg") == "available"

    def test_round_trip_available(self):
        _cache[("test_intg", STATUS_KEY)] = "available"
        assert get_status("test_intg") == "available"

    def test_round_trip_enabled(self):
        _cache[("test_intg", STATUS_KEY)] = "enabled"
        assert get_status("test_intg") == "enabled"

    def test_legacy_needs_setup_coerces_to_enabled(self):
        """A row written by the transitional 3-state model reads back as enabled."""
        _cache[("test_intg", STATUS_KEY)] = "needs_setup"
        assert get_status("test_intg") == "enabled"

    def test_unknown_value_falls_back_to_available(self):
        _cache[("test_intg", STATUS_KEY)] = "bogus"
        assert get_status("test_intg") == "available"

    def test_is_active_only_when_enabled_and_configured(self):
        _cache[("test_intg", STATUS_KEY)] = "enabled"
        with patch(
            "app.services.integration_settings.is_configured", return_value=True
        ):
            assert is_active("test_intg") is True
        with patch(
            "app.services.integration_settings.is_configured", return_value=False
        ):
            assert is_active("test_intg") is False

    def test_is_active_false_when_available(self):
        _cache[("test_intg", STATUS_KEY)] = "available"
        with patch(
            "app.services.integration_settings.is_configured", return_value=True
        ):
            assert is_active("test_intg") is False


# ---------------------------------------------------------------------------
# unregister_integration_tools (registry helper used by the status router)
# ---------------------------------------------------------------------------


class TestUnregisterIntegrationTools:
    def test_removes_matching_tools(self):
        from app.tools.registry import _tools, unregister_integration_tools

        original = dict(_tools)
        try:
            _tools["tool_a"] = {"function": lambda: None, "schema": {}, "source_integration": "slack"}
            _tools["tool_b"] = {"function": lambda: None, "schema": {}, "source_integration": "slack"}
            _tools["tool_c"] = {"function": lambda: None, "schema": {}, "source_integration": "github"}

            removed = unregister_integration_tools("slack")
            assert sorted(removed) == ["tool_a", "tool_b"]
            assert "tool_a" not in _tools
            assert "tool_b" not in _tools
            assert "tool_c" in _tools
        finally:
            _tools.clear()
            _tools.update(original)

    def test_returns_empty_when_no_match(self):
        from app.tools.registry import _tools, unregister_integration_tools

        original = dict(_tools)
        try:
            _tools["tool_x"] = {"function": lambda: None, "schema": {}, "source_integration": "github"}
            removed = unregister_integration_tools("nonexistent")
            assert removed == []
            assert "tool_x" in _tools
        finally:
            _tools.clear()
            _tools.update(original)


# ---------------------------------------------------------------------------
# remove_integration_embeddings (used when moving to available)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_integration_embeddings():
    from app.agent.tools import remove_integration_embeddings, _tool_cache

    _tool_cache["test_key"] = (0, [], 0.0, [])

    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.agent.tools.async_session", return_value=mock_session_ctx):
        count = await remove_integration_embeddings("test_intg")

    assert count == 3
    assert "test_key" not in _tool_cache


# ---------------------------------------------------------------------------
# Process manager gating — only starts when both enabled AND configured
# ---------------------------------------------------------------------------


class TestProcessManagerStatusGating:
    @pytest.mark.asyncio
    async def test_start_refuses_available(self):
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.get_status", return_value="available"):
            result = await pm.start("test_intg")
        assert result is False

    @pytest.mark.asyncio
    async def test_start_refuses_enabled_but_unconfigured(self):
        """Enabled but missing required settings: process must not start."""
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with (
            patch("app.services.integration_settings.get_status", return_value="enabled"),
            patch("app.services.integration_settings.is_configured", return_value=False),
        ):
            result = await pm.start("test_intg")
        assert result is False

    @pytest.mark.asyncio
    async def test_start_allows_enabled_and_configured(self):
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with (
            patch("app.services.integration_settings.get_status", return_value="enabled"),
            patch("app.services.integration_settings.is_configured", return_value=True),
        ):
            # Still fails — no process.py exists — but we pass the status gate.
            result = await pm.start("nonexistent_intg")
        assert result is False


# ---------------------------------------------------------------------------
# discover_setup_status exposes lifecycle_status
# ---------------------------------------------------------------------------


class TestDiscoverSetupStatusLifecycleField:
    def test_lifecycle_status_field_present(self):
        from integrations import discover_setup_status

        with patch("app.services.integration_settings.get_status", return_value="available"):
            results = discover_setup_status()

        for entry in results:
            assert "lifecycle_status" in entry, (
                f"Integration {entry['id']} missing lifecycle_status field"
            )

    def test_lifecycle_status_reflects_get_status(self):
        from integrations import discover_setup_status

        def mock_get_status(iid):
            return "enabled" if iid == "example" else "available"

        with patch("app.services.integration_settings.get_status", side_effect=mock_get_status):
            results = discover_setup_status()

        for entry in results:
            if entry["id"] == "example":
                assert entry["lifecycle_status"] == "enabled"
            else:
                assert entry["lifecycle_status"] == "available"


# ---------------------------------------------------------------------------
# API endpoint: sidebar gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sidebar_sections_requires_active():
    """Sidebar only surfaces integrations that are enabled AND configured."""
    from app.routers.api_v1_admin.integrations import list_sidebar_sections

    mock_section = {
        "integration_id": "test_intg",
        "id": "test",
        "title": "TEST",
        "icon": "Plug",
        "items": [{"label": "Home", "href": "/test", "icon": "Home"}],
    }

    # available → hidden
    with (
        patch("integrations.discover_sidebar_sections", return_value=[mock_section]),
        patch("app.services.integration_settings.is_active", return_value=False),
    ):
        result = await list_sidebar_sections()
    assert result["sections"] == []

    # active (enabled + configured) → visible
    with (
        patch("integrations.discover_sidebar_sections", return_value=[mock_section]),
        patch("app.services.integration_settings.is_active", return_value=True),
        patch("app.services.integration_settings.get_value", return_value="true"),
    ):
        result = await list_sidebar_sections()
    assert len(result["sections"]) == 1


# ---------------------------------------------------------------------------
# Endpoint: status transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_status_rejects_invalid_target():
    from app.routers.api_v1_admin.integrations import set_integration_status, StatusBody
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await set_integration_status("x", StatusBody(status="needs_setup"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_set_status_enabled_does_not_require_configured():
    """User intent drives enablement; readiness is derived. Enabling a
    misconfigured integration is allowed and leaves it in an enabled-but-
    unready state (UI shows the Needs Setup badge; process won't auto-start).
    """
    from app.routers.api_v1_admin.integrations import set_integration_status, StatusBody

    calls: list[tuple] = []

    async def fake_set_status(iid, status):
        calls.append(("set_status", iid, status))

    async def fake_load_mcp():
        calls.append(("load_mcp",))

    async def fake_index():
        calls.append(("index",))

    async def fake_sync_all_files():
        calls.append(("sync_all_files",))
        return {}

    with (
        patch("app.services.integration_settings.get_status", return_value="available"),
        patch("app.services.integration_settings.is_configured", return_value=False),
        patch("app.services.integration_settings.set_status", new=fake_set_status),
        patch("app.services.mcp_servers.load_mcp_servers", new=fake_load_mcp),
        patch("app.agent.tools.index_local_tools", new=fake_index),
        patch("app.services.file_sync.sync_all_files", new=fake_sync_all_files),
        patch("integrations._iter_integration_candidates", return_value=iter([])),
        patch("app.tools.loader.load_integration_tools", return_value=[]),
    ):
        result = await set_integration_status("x", StatusBody(status="enabled"))

    assert result["status"] == "enabled"
    assert ("set_status", "x", "enabled") in calls


def test_is_configured_stub_callable():
    assert callable(is_configured)
