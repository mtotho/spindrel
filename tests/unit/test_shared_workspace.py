"""Unit tests for shared workspace service path management and helpers."""
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.agent.context import current_allowed_secrets
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

    def test_creates_knowledge_base_subdir(self):
        """Every shared-workspace bot gets bots/<id>/knowledge-base/ by convention."""
        svc = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmpdir
                svc.ensure_host_dirs("ws-123")
                bot_dir = svc.ensure_bot_dir("ws-123", "my-bot")

            kb_dir = os.path.join(bot_dir, "knowledge-base")
            assert os.path.isdir(kb_dir)


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
            mock_settings.SERVER_INTERNAL_URL = "http://localhost:8000"
            env = svc._build_env(ws)
        assert env["CUSTOM"] == "value"
        assert env["AGENT_SERVER_URL"] == "http://localhost:8000"

    def test_user_env_can_override_auto(self):
        """setdefault means user-provided env wins if already set."""
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.env = {"AGENT_SERVER_URL": "http://custom.com"}
        with patch("app.services.shared_workspace.settings") as mock_settings:
            mock_settings.SERVER_INTERNAL_URL = "http://localhost:8000"
            env = svc._build_env(ws)
        assert env["AGENT_SERVER_URL"] == "http://custom.com"

    def test_uses_internal_not_public_url(self):
        """Subprocess runs in-container — must use localhost, not host.docker.internal.

        Regression guard: SERVER_PUBLIC_URL ('host.docker.internal:8000' by
        default) only resolves in sidecar containers that sandbox.py launches
        with --add-host. The agent-server container has no such alias, so
        shared_workspace subprocesses (run_script, exec_command) would fail DNS.
        """
        svc = SharedWorkspaceService()
        ws = MagicMock()
        ws.env = {}
        with patch("app.services.shared_workspace.settings") as mock_settings:
            mock_settings.SERVER_INTERNAL_URL = "http://localhost:8000"
            mock_settings.SERVER_PUBLIC_URL = "http://host.docker.internal:8000"
            env = svc._build_env(ws)
        assert env["AGENT_SERVER_URL"] == "http://localhost:8000"

    def test_secret_values_are_not_ambient(self):
        svc = SharedWorkspaceService()
        env = {}

        with patch("app.services.secret_values.get_env_dict") as get_env:
            svc._inject_allowed_secret_values(env)

        get_env.assert_not_called()
        assert env == {}

    def test_injects_only_currently_allowed_secret_values(self):
        svc = SharedWorkspaceService()
        env = {}
        token = current_allowed_secrets.set(["GITHUB_TOKEN"])
        try:
            with patch(
                "app.services.secret_values.get_env_dict",
                return_value={
                    "GITHUB_TOKEN": "ghp_secret",
                    "NPM_TOKEN": "npm_secret",
                    "INVALID-NAME": "bad",
                },
            ):
                svc._inject_allowed_secret_values(env)
        finally:
            current_allowed_secrets.reset(token)

        assert env == {"GITHUB_TOKEN": "ghp_secret"}

    def test_empty_allowed_secret_list_injects_nothing(self):
        svc = SharedWorkspaceService()
        env = {}
        token = current_allowed_secrets.set([])
        try:
            with patch("app.services.secret_values.get_env_dict") as get_env:
                svc._inject_allowed_secret_values(env)
        finally:
            current_allowed_secrets.reset(token)

        get_env.assert_not_called()
        assert env == {}


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
