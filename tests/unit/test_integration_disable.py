"""Tests for the integration lifecycle-status model.

Covers the three-state ``available | needs_setup | enabled`` system on
``IntegrationSetting._status``. Legacy ``is_disabled`` / ``set_disabled``
helpers have been retired; this file pins their replacement.
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
    """``get_status`` reads from the in-memory cache."""

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

    def test_round_trip_needs_setup(self):
        _cache[("test_intg", STATUS_KEY)] = "needs_setup"
        assert get_status("test_intg") == "needs_setup"

    def test_round_trip_enabled(self):
        _cache[("test_intg", STATUS_KEY)] = "enabled"
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

    def test_is_active_false_for_needs_setup(self):
        _cache[("test_intg", STATUS_KEY)] = "needs_setup"
        with patch(
            "app.services.integration_settings.is_configured", return_value=True
        ):
            assert is_active("test_intg") is False


# ---------------------------------------------------------------------------
# Auto-promote / auto-demote
# ---------------------------------------------------------------------------


class TestStatusReconciliation:
    def setup_method(self):
        self._original_cache = dict(_cache)

    def teardown_method(self):
        _cache.clear()
        _cache.update(self._original_cache)

    @pytest.mark.asyncio
    async def test_promotes_needs_setup_to_enabled_when_configured(self):
        from app.services.integration_settings import _reconcile_status

        _cache[("test_intg", STATUS_KEY)] = "needs_setup"
        with (
            patch(
                "app.services.integration_settings.is_configured", return_value=True
            ),
            patch(
                "app.services.integration_settings.set_status",
                new=AsyncMock(),
            ) as set_mock,
        ):
            await _reconcile_status("test_intg")
        set_mock.assert_awaited_once_with("test_intg", "enabled")

    @pytest.mark.asyncio
    async def test_demotes_enabled_to_needs_setup_when_unconfigured(self):
        from app.services.integration_settings import _reconcile_status

        _cache[("test_intg", STATUS_KEY)] = "enabled"
        with (
            patch(
                "app.services.integration_settings.is_configured", return_value=False
            ),
            patch(
                "app.services.integration_settings.set_status",
                new=AsyncMock(),
            ) as set_mock,
        ):
            await _reconcile_status("test_intg")
        set_mock.assert_awaited_once_with("test_intg", "needs_setup")

    @pytest.mark.asyncio
    async def test_available_is_never_auto_flipped(self):
        from app.services.integration_settings import _reconcile_status

        _cache[("test_intg", STATUS_KEY)] = "available"
        with (
            patch(
                "app.services.integration_settings.is_configured", return_value=True
            ),
            patch(
                "app.services.integration_settings.set_status",
                new=AsyncMock(),
            ) as set_mock,
        ):
            await _reconcile_status("test_intg")
        set_mock.assert_not_awaited()


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
# Process manager gating — only starts for status=enabled
# ---------------------------------------------------------------------------


class TestProcessManagerStatusGating:
    @pytest.mark.asyncio
    async def test_start_refuses_non_enabled(self):
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.get_status", return_value="needs_setup"):
            result = await pm.start("test_intg")
        assert result is False

    @pytest.mark.asyncio
    async def test_start_refuses_available(self):
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.get_status", return_value="available"):
            result = await pm.start("test_intg")
        assert result is False

    @pytest.mark.asyncio
    async def test_start_allows_enabled(self):
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.get_status", return_value="enabled"):
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
async def test_sidebar_sections_only_shows_enabled():
    from app.routers.api_v1_admin.integrations import list_sidebar_sections

    mock_section = {
        "integration_id": "test_intg",
        "id": "test",
        "title": "TEST",
        "icon": "Plug",
        "items": [{"label": "Home", "href": "/test", "icon": "Home"}],
    }

    with patch("integrations.discover_sidebar_sections", return_value=[mock_section]):
        with patch("app.services.integration_settings.get_status", return_value="needs_setup"):
            result = await list_sidebar_sections()
    assert result["sections"] == []

    with patch("integrations.discover_sidebar_sections", return_value=[mock_section]):
        with patch("app.services.integration_settings.get_status", return_value="available"):
            result = await list_sidebar_sections()
    assert result["sections"] == []

    with patch("integrations.discover_sidebar_sections", return_value=[mock_section]):
        with patch("app.services.integration_settings.get_status", return_value="enabled"):
            with patch("app.services.integration_settings.get_value", return_value="true"):
                result = await list_sidebar_sections()
    assert len(result["sections"]) == 1


def test_is_configured_stub_callable():
    """Simple sanity check that the public is_configured helper is still importable."""
    assert callable(is_configured)


# ---------------------------------------------------------------------------
# Add-button short-circuit: already-configured integrations skip needs_setup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_short_circuits_to_enabled_when_configured():
    """Clicking Add (target=needs_setup) on an integration with no required
    settings (is_configured True) should transition straight to enabled,
    not land on a 'Needs Setup' card with nothing to fill in.
    """
    from app.routers.api_v1_admin.integrations import (
        set_integration_status, StatusBody,
    )

    calls: list[tuple] = []

    async def fake_set_status(iid, status):
        calls.append(("set_status", iid, status))

    async def fake_stop(iid):
        calls.append(("stop", iid))

    async def fake_load_mcp():
        calls.append(("load_mcp",))

    async def fake_index():
        calls.append(("index",))

    async def fake_remove_embeddings(iid):
        calls.append(("remove_emb", iid))
        return 0

    with (
        patch("app.services.integration_settings.get_status", return_value="available"),
        patch("app.services.integration_settings.is_configured", return_value=True),
        patch("app.services.integration_settings.set_status", new=fake_set_status),
        patch("app.services.integration_processes.process_manager.stop", new=fake_stop),
        patch("app.services.mcp_servers.load_mcp_servers", new=fake_load_mcp),
        patch("app.agent.tools.index_local_tools", new=fake_index),
        patch("app.agent.tools.remove_integration_embeddings", new=fake_remove_embeddings),
        patch(
            "integrations._iter_integration_candidates",
            return_value=iter([]),
        ),
        patch("app.tools.loader.load_integration_tools", return_value=[]),
    ):
        result = await set_integration_status("excalidraw", StatusBody(status="needs_setup"))

    assert result["status"] == "enabled", (
        f"expected short-circuit to enabled, got {result['status']!r}"
    )
    assert ("set_status", "excalidraw", "enabled") in calls
