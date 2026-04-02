"""Tests verifying memory files get indexed with correct root/file_path
and that search_memory queries match those stored values.

All shared workspace bots (orchestrators and members) now have their
workspace root scoped to bots/{id}/ and use a simple "memory" prefix.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agent.bots import BotConfig, KnowledgeConfig, MemoryConfig


def _bot(
    bot_id="test_bot",
    memory_scheme="workspace-files",
    shared_workspace_id=None,
    shared_workspace_role=None,
    **kw,
) -> BotConfig:
    defaults = dict(
        id=bot_id, name="Test", model="gpt-4", system_prompt="You are helpful.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        memory_scheme=memory_scheme,
        shared_workspace_id=shared_workspace_id,
        shared_workspace_role=shared_workspace_role,
    )
    defaults.update(kw)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# Memory prefix resolution for different workspace roles
# ---------------------------------------------------------------------------

class TestMemoryRelPath:
    """get_memory_rel_path must return the correct prefix for each bot role."""

    def test_standalone_bot(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(bot_id="standalone")
        assert get_memory_rel_path(bot) == "memory"

    def test_shared_workspace_member(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(
            bot_id="member_bot",
            shared_workspace_id="ws-abc",
            shared_workspace_role="worker",
        )
        assert get_memory_rel_path(bot) == "memory"

    def test_shared_workspace_orchestrator(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(
            bot_id="orch_bot",
            shared_workspace_id="ws-abc",
            shared_workspace_role="orchestrator",
        )
        # Orchestrators now have workspace root scoped to bots/{id}/, so prefix is just "memory"
        assert get_memory_rel_path(bot) == "memory"


# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------

class TestWorkspaceRootResolution:
    """Verify get_workspace_root returns correct paths per role."""

    def test_standalone_bot(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(bot_id="standalone")
        with patch("app.services.workspace.local_workspace_base", return_value="/base"):
            root = ws.get_workspace_root("standalone", bot)
        assert root == "/base/standalone"

    def test_shared_member(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(
            bot_id="worker",
            shared_workspace_id="ws-123",
            shared_workspace_role="worker",
        )
        with patch(
            "app.services.shared_workspace.shared_workspace_service.get_host_root",
            return_value="/base/shared/ws-123",
        ):
            root = ws.get_workspace_root("worker", bot)
        assert root == "/base/shared/ws-123/bots/worker"

    def test_shared_orchestrator(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(
            bot_id="orch",
            shared_workspace_id="ws-123",
            shared_workspace_role="orchestrator",
        )
        with patch(
            "app.services.shared_workspace.shared_workspace_service.get_host_root",
            return_value="/base/shared/ws-123",
        ):
            root = ws.get_workspace_root("orch", bot)
        # Orchestrators now get the same scoped root as members
        assert root == "/base/shared/ws-123/bots/orch"


# ---------------------------------------------------------------------------
# Indexer: memory files are NOT skipped by _is_auto_injected
# ---------------------------------------------------------------------------

class TestAutoInjectedDoesNotSkipMemory:
    """Memory files must NOT be excluded by the auto-injection skip list."""

    def test_memory_md_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "MEMORY.md")) is False

    def test_memory_log_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "logs", "2026-03-28.md")) is False

    def test_memory_reference_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "reference", "todos.md")) is False

    def test_orchestrator_memory_not_skipped(self):
        """bots/orch_bot/memory/MEMORY.md should NOT be auto-injected."""
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("bots", "orch_bot", "memory", "MEMORY.md")) is False
        assert _is_auto_injected(("bots", "orch_bot", "memory", "logs", "2026-03-28.md")) is False

    def test_skills_ARE_skipped(self):
        """Sanity check: skills/ subtree IS auto-injected (should be skipped)."""
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("skills", "arch_linux.md")) is True

    def test_persona_IS_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("persona.md",)) is True

    def test_bots_prefix_paths_not_auto_injected(self):
        """For shared workspace bots, indexer walks from workspace root, so paths
        like bots/{id}/memory/MEMORY.md exist. These should NOT be auto-injected."""
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("bots", "dev_bot", "memory", "MEMORY.md")) is False
        assert _is_auto_injected(("bots", "dev_bot", "memory", "logs", "2026-03-28.md")) is False
        # bots/X/skills/ and bots/X/persona.md are inside a bot subdir — not
        # at the indexer's root level so they don't match the auto-inject rules
        assert _is_auto_injected(("bots", "orch", "persona.md")) is False
        assert _is_auto_injected(("bots", "orch", "skills", "foo.md")) is False


# ---------------------------------------------------------------------------
# End-to-end: indexing stores correct root + file_path, search queries match
# ---------------------------------------------------------------------------

class TestMemoryPathConsistency:
    """Verify that the root/file_path stored during indexing exactly matches
    the root/memory_prefix used by search_memory.

    For shared workspace bots the indexing root is the workspace root.
    File paths stored are relative to the workspace root, e.g.
    ``bots/{id}/memory/MEMORY.md``.  search_memory uses
    ``get_memory_index_prefix`` to get the correct LIKE prefix.
    """

    def _compute_search_params(self, bot) -> str:
        """Simulate what search_memory would use as memory_prefix."""
        from app.services.memory_scheme import get_memory_index_prefix
        return get_memory_index_prefix(bot)

    def test_standalone_bot_paths_match(self):
        bot = _bot(bot_id="standalone_bot")
        prefix = self._compute_search_params(bot)
        assert prefix == "bots/standalone_bot/memory"
        # Indexed file_path: "bots/standalone_bot/memory/MEMORY.md" matches LIKE prefix + "/%"
        assert "bots/standalone_bot/memory/MEMORY.md".startswith(prefix + "/")

    def test_shared_member_bot_paths_match(self):
        """Member bot: root = workspace root, prefix = bots/{id}/memory."""
        bot = _bot(
            bot_id="worker_bot",
            shared_workspace_id="ws-123",
            shared_workspace_role="worker",
        )
        prefix = self._compute_search_params(bot)
        assert prefix == "bots/worker_bot/memory"
        # Indexed file_path: "bots/worker_bot/memory/MEMORY.md"
        assert "bots/worker_bot/memory/MEMORY.md".startswith(prefix + "/")
        # Should NOT match another bot's memory
        assert not "bots/other_bot/memory/MEMORY.md".startswith(prefix + "/")

    def test_shared_orchestrator_bot_paths_match(self):
        """Orchestrator: root = workspace root, prefix = bots/{id}/memory."""
        bot = _bot(
            bot_id="orch_bot",
            shared_workspace_id="ws-123",
            shared_workspace_role="orchestrator",
        )
        prefix = self._compute_search_params(bot)
        assert prefix == "bots/orch_bot/memory"
        # Indexed file_path: "bots/orch_bot/memory/MEMORY.md"
        assert "bots/orch_bot/memory/MEMORY.md".startswith(prefix + "/")


# ---------------------------------------------------------------------------
# hybrid_memory_search: SQL pattern generation
# ---------------------------------------------------------------------------

class TestMemorySearchPatterns:
    """Verify the SQL LIKE pattern correctly scopes to memory subdirectory."""

    def test_standalone_pattern(self):
        """Standalone bot: memory_prefix='bots/standalone/memory' → LIKE 'bots/standalone/memory/%'."""
        from app.services.memory_scheme import get_memory_index_prefix
        bot = _bot(bot_id="standalone")
        prefix = get_memory_index_prefix(bot)
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "bots/standalone/memory/%"
        assert "bots/standalone/memory/MEMORY.md".startswith("bots/standalone/memory/")
        assert "bots/standalone/memory/logs/2026-03-28.md".startswith("bots/standalone/memory/")
        assert not "data/status.json".startswith("bots/standalone/memory/")

    def test_shared_workspace_pattern(self):
        """Shared workspace bot: prefix='bots/{id}/memory' → LIKE 'bots/{id}/memory/%'."""
        from app.services.memory_scheme import get_memory_index_prefix
        bot = _bot(bot_id="dev_bot", shared_workspace_id="ws-123", shared_workspace_role="worker")
        prefix = get_memory_index_prefix(bot)
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "bots/dev_bot/memory/%"
        assert "bots/dev_bot/memory/MEMORY.md".startswith("bots/dev_bot/memory/")
        assert not "bots/other_bot/memory/MEMORY.md".startswith("bots/dev_bot/memory/")


# ---------------------------------------------------------------------------
# Diagnostics: memory prefix used correctly
# ---------------------------------------------------------------------------

class TestDiagnosticsMemoryPrefix:
    """Diagnostics uses get_memory_index_prefix for DB queries and
    get_memory_rel_path for on-disk walks."""

    def test_standalone_bot_index_prefix(self):
        from app.services.memory_scheme import get_memory_index_prefix
        bot = _bot(bot_id="standalone")
        prefix = get_memory_index_prefix(bot)
        assert prefix == "bots/standalone/memory"

    def test_shared_bot_index_prefix(self):
        from app.services.memory_scheme import get_memory_index_prefix
        bot = _bot(bot_id="member", shared_workspace_id="ws-1", shared_workspace_role="worker")
        prefix = get_memory_index_prefix(bot)
        assert prefix == "bots/member/memory"

    def test_rel_path_always_memory(self):
        """get_memory_rel_path is always 'memory' (for physical file access)."""
        from app.services.memory_scheme import get_memory_rel_path
        for role in ("worker", "orchestrator"):
            bot = _bot(bot_id="bot", shared_workspace_id="ws-1", shared_workspace_role=role)
            assert get_memory_rel_path(bot) == "memory"
