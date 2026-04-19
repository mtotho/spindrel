"""Tests for the bot knowledge-base convention: auto-created folder + prefix helpers."""
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.workspace import WorkspaceService


def _shared_bot(bot_id="my-bot", ws_id="ws-1"):
    return SimpleNamespace(id=bot_id, shared_workspace_id=ws_id)


def _standalone_bot(bot_id="solo-bot"):
    return SimpleNamespace(id=bot_id, shared_workspace_id=None)


class TestBotKnowledgeBaseDir:
    def test_standalone_bot_gets_knowledge_base_on_ensure(self):
        """ensure_host_dir creates knowledge-base/ for a standalone bot."""
        svc = WorkspaceService()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmp
                bot = _standalone_bot("solo-1")
                root = svc.ensure_host_dir("solo-1", bot=bot)
            assert os.path.isdir(root)
            assert os.path.isdir(os.path.join(root, "knowledge-base"))

    def test_shared_bot_gets_knowledge_base_in_bot_subdir(self):
        """For shared-workspace bots, KB sits under bots/<id>/knowledge-base/."""
        from app.services.shared_workspace import SharedWorkspaceService
        sw = SharedWorkspaceService()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.paths.settings") as mock_paths:
                mock_paths.WORKSPACE_LOCAL_DIR = ""
                mock_paths.WORKSPACE_BASE_DIR = tmp
                sw.ensure_host_dirs("ws-1")
                bot_dir = sw.ensure_bot_dir("ws-1", "dev-bot")
            assert os.path.isdir(os.path.join(bot_dir, "knowledge-base"))


class TestBotKnowledgeBaseIndexPrefix:
    def test_standalone_prefix_is_knowledge_base(self):
        svc = WorkspaceService()
        bot = _standalone_bot("solo")
        assert svc.get_bot_knowledge_base_index_prefix(bot) == "knowledge-base"

    def test_shared_prefix_includes_bots_subdir(self):
        """Shared-workspace bots store under bots/<id>/knowledge-base/ relative to shared root."""
        svc = WorkspaceService()
        bot = _shared_bot("dev-bot", "ws-1")
        assert svc.get_bot_knowledge_base_index_prefix(bot) == "bots/dev-bot/knowledge-base"

    def test_get_bot_knowledge_base_root_for_standalone(self):
        svc = WorkspaceService()
        bot = _standalone_bot("solo")
        with patch("app.services.paths.settings") as mock_paths:
            mock_paths.WORKSPACE_LOCAL_DIR = ""
            mock_paths.WORKSPACE_BASE_DIR = "/tmp/bases"
            root = svc.get_bot_knowledge_base_root(bot)
        assert root == "/tmp/bases/solo/knowledge-base"
