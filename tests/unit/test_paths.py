"""Unit tests for app.services.paths — workspace path translation."""
from unittest.mock import patch

import pytest

from app.services.paths import local_workspace_base, host_workspace_base, local_to_host, host_to_local, local_home_dir, host_home_dir


def _mock_settings_defaults(mock_settings):
    """Set sane defaults for all settings accessed by path helpers."""
    mock_settings.HOME_HOST_DIR = ""
    mock_settings.HOME_LOCAL_DIR = ""
    mock_settings.SPINDREL_HOME = ""


class TestNoTranslation:
    """When WORKSPACE_HOST_DIR and WORKSPACE_LOCAL_DIR are both empty (host-based dev)."""

    @patch("app.services.paths.settings")
    def test_local_workspace_base_falls_back(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = ""
        mock_settings.WORKSPACE_BASE_DIR = "/home/user/.agent-workspaces"
        assert local_workspace_base() == "/home/user/.agent-workspaces"

    @patch("app.services.paths.settings")
    def test_host_workspace_base_falls_back(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_HOST_DIR = ""
        mock_settings.WORKSPACE_BASE_DIR = "/home/user/.agent-workspaces"
        assert host_workspace_base() == "/home/user/.agent-workspaces"

    @patch("app.services.paths.settings")
    def test_local_to_host_noop(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = ""
        mock_settings.WORKSPACE_HOST_DIR = ""
        mock_settings.WORKSPACE_BASE_DIR = "/home/user/.agent-workspaces"
        path = "/home/user/.agent-workspaces/bot1"
        assert local_to_host(path) == path


class TestWithTranslation:
    """When both vars are set (server running inside Docker)."""

    @patch("app.services.paths.settings")
    def test_local_workspace_base(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        assert local_workspace_base() == "/workspace-data"

    @patch("app.services.paths.settings")
    def test_host_workspace_base(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        assert host_workspace_base() == "/home/user/.agent-workspaces"

    @patch("app.services.paths.settings")
    def test_translate_workspace_subpath(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        assert local_to_host("/workspace-data/bot1") == "/home/user/.agent-workspaces/bot1"

    @patch("app.services.paths.settings")
    def test_translate_exact_base(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        assert local_to_host("/workspace-data") == "/home/user/.agent-workspaces"

    @patch("app.services.paths.settings")
    def test_translate_nested_path(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        assert (
            local_to_host("/workspace-data/shared/ws1/bots/bot1")
            == "/home/user/.agent-workspaces/shared/ws1/bots/bot1"
        )

    @patch("app.services.paths.settings")
    def test_non_workspace_path_passes_through(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        assert local_to_host("/tmp/something") == "/tmp/something"

    @patch("app.services.paths.settings")
    def test_partial_prefix_not_matched(self, mock_settings):
        """Ensure /workspace-data-extra is NOT treated as a workspace path."""
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        assert local_to_host("/workspace-data-extra/foo") == "/workspace-data-extra/foo"


class TestHomeDirTranslation:
    """Path translation for the Spindrel home directory."""

    @patch("app.services.paths.settings")
    def test_host_to_local_home_path(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        mock_settings.HOME_HOST_DIR = "/home/user/spindrel-home"
        mock_settings.HOME_LOCAL_DIR = "/app/home"
        assert host_to_local("/home/user/spindrel-home/toths") == "/app/home/toths"

    @patch("app.services.paths.settings")
    def test_host_to_local_exact_home(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        mock_settings.HOME_HOST_DIR = "/home/user/spindrel-home"
        mock_settings.HOME_LOCAL_DIR = "/app/home"
        assert host_to_local("/home/user/spindrel-home") == "/app/home"

    @patch("app.services.paths.settings")
    def test_local_to_host_home_path(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.WORKSPACE_LOCAL_DIR = "/workspace-data"
        mock_settings.WORKSPACE_HOST_DIR = "/home/user/.agent-workspaces"
        mock_settings.WORKSPACE_BASE_DIR = "~/.agent-workspaces"
        mock_settings.HOME_HOST_DIR = "/home/user/spindrel-home"
        mock_settings.HOME_LOCAL_DIR = "/app/home"
        assert local_to_host("/app/home/toths") == "/home/user/spindrel-home/toths"

    @patch("app.services.paths.settings")
    def test_home_helpers(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.HOME_HOST_DIR = "/home/user/spindrel-home"
        mock_settings.HOME_LOCAL_DIR = "/app/home"
        assert local_home_dir() == "/app/home"
        assert host_home_dir() == "/home/user/spindrel-home"

    @patch("app.services.paths.settings")
    def test_home_helpers_host_mode(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        mock_settings.SPINDREL_HOME = "/home/user/spindrel-home"
        assert local_home_dir() == "/home/user/spindrel-home"
        assert host_home_dir() == "/home/user/spindrel-home"

    @patch("app.services.paths.settings")
    def test_no_home_configured(self, mock_settings):
        _mock_settings_defaults(mock_settings)
        assert local_home_dir() is None
        assert host_home_dir() is None
