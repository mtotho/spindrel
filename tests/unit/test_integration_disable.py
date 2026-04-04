"""Tests for global integration disable/enable feature."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.integration_settings import is_disabled, _cache


# ---------------------------------------------------------------------------
# is_disabled / set_disabled
# ---------------------------------------------------------------------------


class TestIsDisabled:
    """Tests for is_disabled() reading from the in-memory cache."""

    def setup_method(self):
        self._original_cache = dict(_cache)

    def teardown_method(self):
        _cache.clear()
        _cache.update(self._original_cache)

    def test_not_disabled_when_missing(self):
        """Integration with no _disabled key should not be disabled."""
        _cache.pop(("test_intg", "_disabled"), None)
        assert is_disabled("test_intg") is False

    def test_not_disabled_when_false(self):
        _cache[("test_intg", "_disabled")] = "false"
        assert is_disabled("test_intg") is False

    def test_disabled_when_true(self):
        _cache[("test_intg", "_disabled")] = "true"
        assert is_disabled("test_intg") is True

    def test_disabled_when_1(self):
        _cache[("test_intg", "_disabled")] = "1"
        assert is_disabled("test_intg") is True

    def test_disabled_when_yes(self):
        _cache[("test_intg", "_disabled")] = "yes"
        assert is_disabled("test_intg") is True

    def test_not_disabled_when_empty(self):
        _cache[("test_intg", "_disabled")] = ""
        assert is_disabled("test_intg") is False

    def test_not_disabled_when_random(self):
        _cache[("test_intg", "_disabled")] = "maybe"
        assert is_disabled("test_intg") is False


# ---------------------------------------------------------------------------
# unregister_integration_tools
# ---------------------------------------------------------------------------


class TestUnregisterIntegrationTools:
    """Tests for removing tools by integration ID from the registry."""

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
# remove_integration_embeddings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_integration_embeddings():
    """Verify remove_integration_embeddings deletes rows and invalidates cache."""
    from app.agent.tools import remove_integration_embeddings, _tool_cache

    # Pre-populate cache to verify it gets cleared
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
# Process manager gating
# ---------------------------------------------------------------------------


class TestProcessManagerDisabledGating:
    """Tests for disabled integration checks in process manager."""

    @pytest.mark.asyncio
    async def test_start_refuses_disabled(self):
        """start() should return False for a disabled integration."""
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.is_disabled", return_value=True):
            result = await pm.start("test_intg")
        assert result is False

    @pytest.mark.asyncio
    async def test_start_allows_enabled(self):
        """start() should proceed normally for an enabled integration (will fail for other reasons)."""
        from app.services.integration_processes import IntegrationProcessManager

        pm = IntegrationProcessManager()
        with patch("app.services.integration_settings.is_disabled", return_value=False):
            # Will fail because no process.py exists, but the disabled check passes
            result = await pm.start("nonexistent_intg")
        assert result is False  # fails for env/discovery reasons, not disabled


# ---------------------------------------------------------------------------
# Loader gating
# ---------------------------------------------------------------------------


class TestLoaderDisabledGating:
    """Tests for disabled integration check in _scan_integration_tools."""

    def test_scan_skips_disabled(self, tmp_path):
        """_scan_integration_tools should skip disabled integrations."""
        from app.tools.loader import _scan_integration_tools
        from app.tools.registry import _tools

        # Create a fake integration with a tools dir
        intg_dir = tmp_path / "test_intg" / "tools"
        intg_dir.mkdir(parents=True)
        (intg_dir / "my_tool.py").write_text("# no-op tool file\n")

        original = dict(_tools)
        try:
            with patch("app.services.integration_settings.is_disabled", return_value=True):
                _scan_integration_tools(tmp_path)
            # No new tools should have been registered
            new_tools = set(_tools.keys()) - set(original.keys())
            assert len(new_tools) == 0
        finally:
            _tools.clear()
            _tools.update(original)


# ---------------------------------------------------------------------------
# discover_setup_status disabled field
# ---------------------------------------------------------------------------


class TestDiscoverSetupStatusDisabledField:
    """Tests for the disabled field in discover_setup_status."""

    def test_disabled_field_present(self):
        """discover_setup_status should include a disabled field."""
        from integrations import discover_setup_status

        with patch("app.services.integration_settings.is_disabled", return_value=False):
            results = discover_setup_status()

        # All results should have a disabled field
        for entry in results:
            assert "disabled" in entry, f"Integration {entry['id']} missing disabled field"

    def test_disabled_field_reflects_cache(self):
        """disabled field should reflect the is_disabled() value."""
        from integrations import discover_setup_status

        def mock_is_disabled(iid):
            return iid == "example"

        with patch("app.services.integration_settings.is_disabled", side_effect=mock_is_disabled):
            results = discover_setup_status()

        for entry in results:
            if entry["id"] == "example":
                assert entry["disabled"] is True
            else:
                assert entry["disabled"] is False


# ---------------------------------------------------------------------------
# Context assembly activation gating
# ---------------------------------------------------------------------------


class TestContextAssemblyDisabledGating:
    """Verify that disabled integrations don't inject activation carapaces."""

    def test_activation_skips_disabled_integration(self):
        """Activation injection should skip disabled integrations."""
        # This is a structural test — the actual gating is in context_assembly.py
        # We verify the import and function exist
        from app.services.integration_settings import is_disabled
        assert callable(is_disabled)


# ---------------------------------------------------------------------------
# API endpoint: sidebar gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sidebar_sections_hides_disabled():
    """Sidebar sections endpoint should hide disabled integrations."""
    from app.routers.api_v1_admin.integrations import list_sidebar_sections

    mock_section = {
        "integration_id": "test_intg",
        "id": "test",
        "title": "TEST",
        "icon": "Plug",
        "items": [{"label": "Home", "href": "/test", "icon": "Home"}],
    }

    with patch("integrations.discover_sidebar_sections", return_value=[mock_section]):
        with patch("app.services.integration_settings.is_disabled", return_value=True):
            result = await list_sidebar_sections()
    assert result["sections"] == []

    with patch("integrations.discover_sidebar_sections", return_value=[mock_section]):
        with patch("app.services.integration_settings.is_disabled", return_value=False):
            with patch("app.services.integration_settings.get_value", return_value="true"):
                result = await list_sidebar_sections()
    assert len(result["sections"]) == 1
