"""Unit tests for integration hot-reload and scaffolding."""
import json
import os
import shutil
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLoadedIds:
    """Tests for _loaded_ids tracking in discover_integrations()."""

    def test_loaded_ids_populated_by_discover(self):
        """discover_integrations() should populate _loaded_ids with all candidate IDs."""
        import integrations
        # Save and reset
        original = integrations._loaded_ids.copy()
        integrations._loaded_ids.clear()
        try:
            integrations.discover_integrations()
            assert len(integrations._loaded_ids) > 0
            # Should include known in-repo integrations
            assert "example" in integrations._loaded_ids
        finally:
            integrations._loaded_ids = original

    def test_no_new_integrations(self):
        """load_new_integrations returns empty when all are already loaded."""
        import integrations
        original = integrations._loaded_ids.copy()
        # Ensure all are loaded first
        integrations.discover_integrations()
        try:
            app = MagicMock()
            result = integrations.load_new_integrations(app)
            assert result == []
            app.include_router.assert_not_called()
        finally:
            integrations._loaded_ids = original

    def test_discovers_new_integration(self, tmp_path):
        """A new integration directory in INTEGRATION_DIRS gets discovered."""
        import integrations

        # Create a minimal integration
        new_int = tmp_path / "test_hot_reload"
        new_int.mkdir()
        (new_int / "__init__.py").write_text("")
        (new_int / "router.py").write_text(textwrap.dedent("""\
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/ping")
            async def ping():
                return {"ok": True}
        """))

        original_ids = integrations._loaded_ids.copy()
        # Ensure all existing integrations are loaded
        integrations.discover_integrations()

        try:
            # Patch INTEGRATION_DIRS to include our tmp_path
            with patch.object(integrations, "_all_integration_dirs", return_value=[
                integrations._INTEGRATIONS_DIR,
                integrations._PACKAGES_DIR,
                tmp_path,
            ]):
                app = MagicMock()
                result = integrations.load_new_integrations(app)

                assert len(result) == 1
                assert result[0][0] == "test_hot_reload"
                assert result[0][1] == new_int
                app.include_router.assert_called_once()
                assert "test_hot_reload" in integrations._loaded_ids
        finally:
            integrations._loaded_ids = original_ids


class TestScaffold:
    """Tests for the scaffold action in manage_integration tool."""

    def _get_scaffold_fn(self):
        from app.tools.local.admin_integrations import _scaffold_integration
        return _scaffold_integration

    def test_scaffold_creates_files(self, tmp_path):
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("my_test_integration", ["tools", "skills"])

        assert result["ok"] is True
        assert result["integration_id"] == "my_test_integration"

        int_dir = tmp_path / "my_test_integration"
        assert int_dir.is_dir()
        assert (int_dir / "__init__.py").exists()
        assert (int_dir / "setup.py").exists()
        assert (int_dir / "router.py").exists()
        assert (int_dir / "README.md").exists()
        assert (int_dir / "tools").is_dir()
        assert (int_dir / "tools" / "__init__.py").exists()
        assert (int_dir / "skills").is_dir()

    def test_scaffold_all_features(self, tmp_path):
        # Phase G removed "dispatcher" from the scaffold features —
        # new integrations declare a renderer.py instead, and the
        # scaffolder doesn't have a generator for that yet (out of
        # scope for Phase G; renderer-scaffolding can land later).
        scaffold = self._get_scaffold_fn()
        all_features = ["tools", "skills", "carapaces", "hooks", "process", "workflows"]
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("full_integration", all_features)

        assert result["ok"] is True
        int_dir = tmp_path / "full_integration"
        assert (int_dir / "tools").is_dir()
        assert (int_dir / "skills").is_dir()
        assert (int_dir / "carapaces").is_dir()
        assert (int_dir / "hooks.py").exists()
        assert (int_dir / "process.py").exists()
        assert (int_dir / "workflows").is_dir()

    def test_scaffold_no_features(self, tmp_path):
        """Scaffold with no features creates only base files."""
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("minimal_integration", [])

        assert result["ok"] is True
        int_dir = tmp_path / "minimal_integration"
        assert (int_dir / "__init__.py").exists()
        assert (int_dir / "setup.py").exists()
        assert (int_dir / "router.py").exists()
        assert (int_dir / "README.md").exists()
        # No optional dirs
        assert not (int_dir / "tools").exists()
        assert not (int_dir / "skills").exists()
        assert not (int_dir / "dispatcher.py").exists()

    def test_scaffold_rejects_existing(self, tmp_path):
        scaffold = self._get_scaffold_fn()
        # Create the dir first
        (tmp_path / "existing_int").mkdir()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("existing_int", [])

        assert "error" in result
        assert "already exists" in result["error"]

    def test_scaffold_validates_name(self, tmp_path):
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            # Uppercase
            result = scaffold("MyIntegration", [])
            assert "error" in result
            assert "Invalid" in result["error"]

            # Starts with number
            result = scaffold("1bad", [])
            assert "error" in result

            # Dashes
            result = scaffold("my-integration", [])
            assert "error" in result

            # Spaces
            result = scaffold("my integration", [])
            assert "error" in result

    def test_scaffold_valid_names(self, tmp_path):
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("my_integration", [])
            assert result["ok"] is True

            result = scaffold("simple", [])
            assert result["ok"] is True

            result = scaffold("x123", [])
            assert result["ok"] is True

    def test_scaffold_invalid_features(self, tmp_path):
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            result = scaffold("test_int", ["tools", "bogus_feature"])

        assert "error" in result
        assert "Unknown features" in result["error"]
        assert "bogus_feature" in result["error"]

    def test_scaffold_no_scaffold_dir(self):
        scaffold = self._get_scaffold_fn()
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=None):
            result = scaffold("test_int", [])

        assert "error" in result
        assert "No writable integration directory" in result["error"]

    def test_scaffold_all_python_files_are_valid(self, tmp_path):
        """All generated Python files should be syntactically valid."""
        scaffold = self._get_scaffold_fn()
        all_features = ["tools", "skills", "carapaces", "dispatcher", "hooks", "process", "workflows"]
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            scaffold("valid_py", all_features)

        int_dir = tmp_path / "valid_py"
        for py_file in int_dir.rglob("*.py"):
            code = py_file.read_text()
            if code.strip():
                compile(code, str(py_file.relative_to(int_dir)), "exec")


class TestReloadAction:
    """Tests for the reload action via manage_integration tool."""

    @pytest.mark.asyncio
    async def test_reload_returns_empty_when_no_new(self):
        """Reload with no new integrations returns informative message."""
        from app.tools.local.admin_integrations import _reload_integrations

        mock_app = MagicMock()
        with patch("integrations.load_new_integrations", return_value=[]):
            result = await _reload_integrations(app=mock_app)

        assert result["ok"] is True
        assert result["loaded"] == []
        assert "No new integrations" in result["message"]

    @pytest.mark.asyncio
    async def test_reload_loads_new_integration(self, tmp_path):
        """Reload with a new integration returns its info."""
        from app.tools.local.admin_integrations import _reload_integrations

        # Create minimal integration dir
        int_dir = tmp_path / "new_int"
        int_dir.mkdir()
        (int_dir / "router.py").write_text("")
        tools_dir = int_dir / "tools"
        tools_dir.mkdir()

        mock_app = MagicMock()

        with patch("integrations.load_new_integrations", return_value=[("new_int", int_dir)]), \
             patch("app.tools.loader.load_integration_tools", return_value=["new_int_tool"]), \
             patch("app.agent.tools.index_local_tools", new_callable=AsyncMock), \
             patch("app.services.file_sync.sync_all_files", new_callable=AsyncMock), \
             patch("app.agent.skills.load_skills", new_callable=AsyncMock), \
             patch("app.agent.carapaces.load_carapaces", new_callable=AsyncMock), \
             patch("app.services.workflows.load_workflows", new_callable=AsyncMock), \
             patch("integrations.discover_sidebar_sections"), \
             patch("integrations.discover_activation_manifests"):
            result = await _reload_integrations(app=mock_app)

        assert result["ok"] is True
        assert len(result["loaded"]) == 1
        assert result["loaded"][0]["id"] == "new_int"
        assert "router" in result["loaded"][0]["capabilities"]
        assert "tools" in result["loaded"][0]["capabilities"]
        assert result["new_tools"] == ["new_int_tool"]

    @pytest.mark.asyncio
    async def test_reload_app_none_resolves_from_main(self):
        """When app=None, reload resolves app from app.main."""
        from app.tools.local.admin_integrations import _reload_integrations

        mock_app = MagicMock()
        with patch("integrations.load_new_integrations", return_value=[]) as mock_load, \
             patch("app.tools.local.admin_integrations.app", mock_app, create=True), \
             patch.dict("sys.modules", {"app.main": MagicMock(app=mock_app)}):
            result = await _reload_integrations(app=None)

        assert result["ok"] is True
        mock_load.assert_called_once_with(mock_app)

    @pytest.mark.asyncio
    async def test_reload_partial_failure_continues(self, tmp_path):
        """If one reload step fails, others still run."""
        from app.tools.local.admin_integrations import _reload_integrations

        mock_app = MagicMock()
        # Create a real dir so Path.exists()/is_dir() work naturally
        int_dir = tmp_path / "fake_int"
        int_dir.mkdir()

        with patch("integrations.load_new_integrations", return_value=[("fake", int_dir)]), \
             patch("app.tools.loader.load_integration_tools", return_value=[]), \
             patch("app.agent.tools.index_local_tools", new_callable=AsyncMock, side_effect=Exception("index boom")), \
             patch("app.services.file_sync.sync_all_files", new_callable=AsyncMock) as mock_sync, \
             patch("app.agent.skills.load_skills", new_callable=AsyncMock) as mock_skills, \
             patch("app.agent.carapaces.load_carapaces", new_callable=AsyncMock), \
             patch("app.services.workflows.load_workflows", new_callable=AsyncMock), \
             patch("integrations.discover_sidebar_sections"), \
             patch("integrations.discover_activation_manifests"):
            result = await _reload_integrations(app=mock_app)

        # Should report the error but still continue
        assert result["ok"] is False
        assert len(result["errors"]) == 1
        assert "index boom" in result["errors"][0]
        # Subsequent steps should have been called
        mock_sync.assert_called_once()
        mock_skills.assert_called_once()


class TestScaffoldYaml:
    """Tests for YAML validity in scaffolded files."""

    def test_scaffolded_carapace_yaml_is_valid(self, tmp_path):
        import yaml
        from app.tools.local.admin_integrations import _scaffold_integration
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            _scaffold_integration("yaml_test", ["carapaces"])

        carapace_file = tmp_path / "yaml_test" / "carapaces" / "yaml_test.yaml"
        data = yaml.safe_load(carapace_file.read_text())
        assert data["id"] == "yaml_test"
        assert isinstance(data.get("skills"), type(None)) or isinstance(data.get("skills"), list)

    def test_scaffolded_workflow_yaml_is_valid(self, tmp_path):
        import yaml
        from app.tools.local.admin_integrations import _scaffold_integration
        with patch("app.tools.local.admin_integrations._get_scaffold_dir", return_value=tmp_path):
            _scaffold_integration("yaml_test2", ["workflows"])

        wf_file = tmp_path / "yaml_test2" / "workflows" / "yaml_test2-example.yaml"
        data = yaml.safe_load(wf_file.read_text())
        assert data["id"] == "yaml_test2-example"
        assert "steps" in data


class TestLoadIntegrationTools:
    """Tests for the targeted tool loader."""

    def test_no_tools_dir(self, tmp_path):
        from app.tools.loader import load_integration_tools
        result = load_integration_tools(tmp_path)
        assert result == []

    def test_empty_tools_dir(self, tmp_path):
        from app.tools.loader import load_integration_tools
        (tmp_path / "tools").mkdir()
        result = load_integration_tools(tmp_path)
        assert result == []

    def test_skips_underscore_files(self, tmp_path):
        from app.tools.loader import load_integration_tools
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").write_text("")
        (tools_dir / "_private.py").write_text("x = 1")
        result = load_integration_tools(tmp_path)
        assert result == []
