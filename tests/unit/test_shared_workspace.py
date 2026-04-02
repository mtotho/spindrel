"""Unit tests for shared workspace service path management and helpers."""
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.services.shared_workspace import SharedWorkspaceService, _slug


class TestSlug:
    def test_simple_name(self):
        assert _slug("my-workspace") == "my-workspace"

    def test_spaces_to_dashes(self):
        assert _slug("My Workspace Name") == "my-workspace-name"

    def test_special_chars(self):
        assert _slug("test@workspace#1") == "test-workspace-1"

    def test_truncates_at_32(self):
        result = _slug("a" * 50)
        assert len(result) <= 32

    def test_strips_leading_trailing_dashes(self):
        assert _slug("--hello--") == "hello"

    def test_empty_string(self):
        assert _slug("") == ""


class TestGetHostRoot:
    def test_returns_path_under_base_dir(self):
        svc = SharedWorkspaceService()
        ws_id = "abc-123"
        with patch("app.services.paths.settings") as mock_paths:
            mock_paths.WORKSPACE_LOCAL_DIR = ""
            mock_paths.WORKSPACE_BASE_DIR = "/tmp/test-workspaces"
            root = svc.get_host_root(ws_id)
        assert root == "/tmp/test-workspaces/shared/abc-123"


class TestEnsureHostDirs:
    def test_creates_directories(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                root = svc.ensure_host_dirs("test-ws-id")

            assert os.path.isdir(os.path.join(root, "bots"))
            assert os.path.isdir(os.path.join(root, "common"))
            assert os.path.isdir(os.path.join(root, "users"))
            assert os.path.isdir(os.path.join(root, "integrations"))

    def test_idempotent(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                root1 = svc.ensure_host_dirs("test-ws-id")
                root2 = svc.ensure_host_dirs("test-ws-id")
            assert root1 == root2


class TestEnsureBotDir:
    def test_creates_bot_directory(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                svc.ensure_host_dirs("ws-123")
                svc.ensure_bot_dir("ws-123", "my-bot")

            bot_dir = os.path.join(tmpdir, "shared", "ws-123", "bots", "my-bot")
            assert os.path.isdir(bot_dir)


class TestGetBotCwd:
    def test_member_gets_scoped_cwd(self):
        svc = SharedWorkspaceService()
        cwd = svc.get_bot_cwd("bot-1", "member", None)
        assert cwd == "/workspace/bots/bot-1"

    def test_orchestrator_gets_scoped_cwd(self):
        """Orchestrators now get the same scoped cwd as members."""
        svc = SharedWorkspaceService()
        cwd = svc.get_bot_cwd("orch-bot", "orchestrator", None)
        assert cwd == "/workspace/bots/orch-bot"

    def test_cwd_override(self):
        svc = SharedWorkspaceService()
        cwd = svc.get_bot_cwd("bot-1", "member", "/workspace/custom")
        assert cwd == "/workspace/custom"


class TestTranslatePath:
    def test_translate_absolute_path(self):
        svc = SharedWorkspaceService()
        with patch("app.services.paths.settings") as mock_paths:
            mock_paths.WORKSPACE_LOCAL_DIR = ""
            mock_paths.WORKSPACE_BASE_DIR = "/home/user/.agent-workspaces"
            result = svc.translate_path("ws-123", "/workspace/bots/my-bot/file.txt")
        expected = "/home/user/.agent-workspaces/shared/ws-123/bots/my-bot/file.txt"
        assert result == expected

    def test_translate_root_path(self):
        svc = SharedWorkspaceService()
        with patch("app.services.paths.settings") as mock_paths:
            mock_paths.WORKSPACE_LOCAL_DIR = ""
            mock_paths.WORKSPACE_BASE_DIR = "/home/user/.agent-workspaces"
            result = svc.translate_path("ws-123", "/workspace")
        expected = "/home/user/.agent-workspaces/shared/ws-123"
        assert result == expected


class TestContainerName:
    def test_container_name_format(self):
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.id = "12345678-1234-1234-1234-123456789abc"
        ws.name = "My Workspace"
        name = svc._container_name(ws)
        assert name.startswith("agent-ws-my-workspace-")
        assert "12345678" in name


class TestBuildEnv:
    def test_includes_auto_injected_vars(self):
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.env = {"CUSTOM": "value"}
        with patch("app.services.shared_workspace.settings") as mock_settings:
            mock_settings.SERVER_PUBLIC_URL = "http://localhost:8000"
            env = svc._build_env(ws)
        assert env["CUSTOM"] == "value"
        assert env["AGENT_SERVER_URL"] == "http://localhost:8000"
        # Master API_KEY must NOT be injected (per-bot scoped keys are used at exec time)
        assert "AGENT_SERVER_API_KEY" not in env

    def test_user_env_can_override_auto(self):
        """setdefault means user-provided env wins if already set."""
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.env = {"AGENT_SERVER_URL": "http://custom.com"}
        with patch("app.services.shared_workspace.settings") as mock_settings:
            mock_settings.SERVER_PUBLIC_URL = "http://localhost:8000"
            env = svc._build_env(ws)
        # User-provided wins with setdefault
        assert env["AGENT_SERVER_URL"] == "http://custom.com"


class TestListFiles:
    def test_list_files_returns_entries(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                root = svc.ensure_host_dirs("ws-123")

                # Create some files
                os.makedirs(os.path.join(root, "bots", "bot-a"))
                with open(os.path.join(root, "readme.txt"), "w") as f:
                    f.write("hello")

                entries = svc.list_files("ws-123", "/")

            names = [e["name"] for e in entries]
            assert "bots" in names
            assert "common" in names
            assert "readme.txt" in names

            # Check file entry has size
            readme = next(e for e in entries if e["name"] == "readme.txt")
            assert readme["is_dir"] is False
            assert readme["size"] == 5

            # Check dir entry
            bots_entry = next(e for e in entries if e["name"] == "bots")
            assert bots_entry["is_dir"] is True

    def test_list_files_subdirectory(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                root = svc.ensure_host_dirs("ws-123")

                os.makedirs(os.path.join(root, "bots", "bot-a"))
                with open(os.path.join(root, "bots", "bot-a", "main.py"), "w") as f:
                    f.write("print('hi')")

                entries = svc.list_files("ws-123", "/bots/bot-a")

            assert len(entries) == 1
            assert entries[0]["name"] == "main.py"

    def test_list_files_empty_directory(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                svc.ensure_host_dirs("ws-123")
                entries = svc.list_files("ws-123", "/users")

            assert entries == []
