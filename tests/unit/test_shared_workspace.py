"""Unit tests for shared workspace service path management and helpers."""
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.services.shared_workspace import SharedWorkspaceService


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

    def test_passthrough_non_workspace_path(self):
        svc = SharedWorkspaceService()
        result = svc.translate_path("ws-123", "/some/other/path")
        assert result == "/some/other/path"


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

    def test_user_env_can_override_auto(self):
        """setdefault means user-provided env wins if already set."""
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.env = {"AGENT_SERVER_URL": "http://custom.com"}
        with patch("app.services.shared_workspace.settings") as mock_settings:
            mock_settings.SERVER_PUBLIC_URL = "http://localhost:8000"
            env = svc._build_env(ws)
        assert env["AGENT_SERVER_URL"] == "http://custom.com"


class TestListFiles:
    def test_list_files_returns_entries(self):
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                root = svc.ensure_host_dirs("ws-123")

                os.makedirs(os.path.join(root, "bots", "bot-a"))
                with open(os.path.join(root, "readme.txt"), "w") as f:
                    f.write("hello")

                entries = svc.list_files("ws-123", "/")

            names = [e["name"] for e in entries]
            assert "bots" in names
            assert "common" in names
            assert "readme.txt" in names

            readme = next(e for e in entries if e["name"] == "readme.txt")
            assert readme["is_dir"] is False
            assert readme["size"] == 5

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


class TestWriteProtection:
    def test_write_intent_detection(self):
        assert SharedWorkspaceService._command_has_write_intent("rm -rf /tmp")
        assert SharedWorkspaceService._command_has_write_intent("echo foo > file.txt")
        assert SharedWorkspaceService._command_has_write_intent("pip install requests")
        assert not SharedWorkspaceService._command_has_write_intent("ls -la")
        assert not SharedWorkspaceService._command_has_write_intent("cat file.txt")
        assert not SharedWorkspaceService._command_has_write_intent("python script.py")
