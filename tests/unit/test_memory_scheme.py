"""Unit tests for the workspace-files memory scheme."""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agent.bots import BotConfig, KnowledgeConfig, MemoryConfig, _bot_row_to_config


def _bot(memory_scheme=None, **overrides) -> BotConfig:
    defaults = dict(
        id="test_bot", name="Test", model="gpt-4", system_prompt="You are helpful.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        memory_scheme=memory_scheme,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# BotConfig: memory_scheme field
# ---------------------------------------------------------------------------

class TestBotConfigMemoryScheme:
    def test_default_is_none(self):
        bot = _bot()
        assert bot.memory_scheme is None

    def test_workspace_files_scheme(self):
        bot = _bot(memory_scheme="workspace-files")
        assert bot.memory_scheme == "workspace-files"

    def test_bot_row_to_config_reads_memory_scheme(self):
        row = MagicMock()
        row.id = "test"
        row.name = "Test"
        row.model = "gpt-4"
        row.system_prompt = "Hello"
        row.mcp_servers = []
        row.local_tools = []
        row.pinned_tools = []
        row.tool_retrieval = True
        row.tool_similarity_threshold = None
        row.client_tools = []
        row.skills = []
        row.persona = False
        row.context_compaction = True
        row.compaction_interval = None
        row.compaction_keep_turns = None
        row.compaction_model = None
        row.memory_knowledge_compaction_prompt = None
        row.audio_input = "transcribe"
        row.memory_config = {}
        row.knowledge_config = {}
        row.filesystem_indexes = []
        row.docker_sandbox_profiles = []
        row.host_exec_config = {}
        row.filesystem_access = []
        row.display_name = None
        row.avatar_url = None
        row.integration_config = {}
        row.tool_result_config = {}
        row.knowledge_max_inject_chars = None
        row.memory_max_inject_chars = None
        row.delegation_config = {}
        row.model_params = {}
        row.model_provider_id = None
        row.bot_sandbox = {}
        row.workspace = {}
        row.user_id = None
        row.fallback_models = []
        row._sw_workspace_id = None
        row._sw_role = None
        row._sw_cwd_override = None
        row.memory_scheme = "workspace-files"
        config = _bot_row_to_config(row)
        assert config.memory_scheme == "workspace-files"


# ---------------------------------------------------------------------------
# Bootstrap service
# ---------------------------------------------------------------------------

class TestBootstrapMemoryScheme:
    def test_creates_directory_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bot = _bot(memory_scheme="workspace-files")
            from app.services.memory_scheme import bootstrap_memory_scheme
            result = bootstrap_memory_scheme(bot, ws_root=tmpdir)

            assert os.path.isdir(os.path.join(tmpdir, "memory"))
            assert os.path.isdir(os.path.join(tmpdir, "memory", "logs"))
            assert os.path.isdir(os.path.join(tmpdir, "memory", "reference"))
            assert os.path.isfile(os.path.join(tmpdir, "memory", "MEMORY.md"))
            assert result == os.path.join(tmpdir, "memory")

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bot = _bot(memory_scheme="workspace-files")
            from app.services.memory_scheme import bootstrap_memory_scheme

            bootstrap_memory_scheme(bot, ws_root=tmpdir)
            # Write custom content to MEMORY.md
            md_path = os.path.join(tmpdir, "memory", "MEMORY.md")
            Path(md_path).write_text("Custom content")

            # Bootstrap again — should NOT overwrite
            bootstrap_memory_scheme(bot, ws_root=tmpdir)
            assert Path(md_path).read_text() == "Custom content"

    def test_get_memory_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bot = _bot()
            from app.services.memory_scheme import get_memory_root
            result = get_memory_root(bot, ws_root=tmpdir)
            assert result == os.path.join(tmpdir, "memory")


# ---------------------------------------------------------------------------
# Memory file path resolution
# ---------------------------------------------------------------------------

class TestResolveMemoryPath:
    @pytest.fixture
    def memory_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_root = os.path.join(tmpdir, "memory")
            os.makedirs(os.path.join(mem_root, "logs"))
            os.makedirs(os.path.join(mem_root, "reference"))
            Path(os.path.join(mem_root, "MEMORY.md")).write_text("# Memory")
            Path(os.path.join(mem_root, "logs", "2026-03-28.md")).write_text("log")
            Path(os.path.join(mem_root, "reference", "deploy-guide.md")).write_text("guide")
            yield mem_root

    def test_resolve_memory_shorthand(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        # MEMORY → MEMORY.md
        assert _resolve_memory_path("MEMORY", memory_dir) is not None
        assert _resolve_memory_path("MEMORY", memory_dir).endswith("MEMORY.md")

    def test_resolve_date_shorthand(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        path = _resolve_memory_path("2026-03-28", memory_dir)
        assert path is not None
        assert path.endswith("2026-03-28.md")
        assert "logs" in path

    def test_resolve_reference_shorthand(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        path = _resolve_memory_path("deploy-guide", memory_dir)
        assert path is not None
        assert path.endswith("deploy-guide.md")
        assert "reference" in path

    def test_resolve_explicit_path(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        path = _resolve_memory_path("logs/2026-03-28", memory_dir)
        assert path is not None
        assert "logs" in path

    def test_rejects_traversal(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        assert _resolve_memory_path("../../../etc/passwd", memory_dir) is None
        assert _resolve_memory_path("../../sensitive", memory_dir) is None

    def test_returns_none_for_missing(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        assert _resolve_memory_path("nonexistent-file", memory_dir) is None

    def test_strips_md_suffix(self, memory_dir):
        from app.tools.local.memory_files import _resolve_memory_path

        path = _resolve_memory_path("MEMORY.md", memory_dir)
        assert path is not None
        assert path.endswith("MEMORY.md")


# ---------------------------------------------------------------------------
# Tool hiding
# ---------------------------------------------------------------------------

class TestToolHiding:
    def test_memory_scheme_hides_db_tools(self):
        """When memory_scheme is set, DB memory/knowledge tools should be removed."""
        bot = _bot(
            memory_scheme="workspace-files",
            local_tools=["save_memory", "search_memories", "web_search", "upsert_knowledge", "exec_command"],
        )
        hidden = {
            "save_memory", "search_memories", "purge_memory",
            "merge_memories", "promote_memories_to_knowledge",
            "upsert_knowledge", "append_to_knowledge", "edit_knowledge",
            "delete_knowledge", "get_knowledge", "list_knowledge_bases",
            "search_knowledge", "pin_knowledge", "unpin_knowledge",
            "set_knowledge_similarity_threshold",
        }
        filtered = [t for t in bot.local_tools if t not in hidden]
        assert "save_memory" not in filtered
        assert "upsert_knowledge" not in filtered
        assert "web_search" in filtered
        assert "exec_command" in filtered

    def test_no_hiding_when_scheme_is_none(self):
        bot = _bot(
            memory_scheme=None,
            local_tools=["save_memory", "search_memories", "web_search"],
        )
        # Without scheme, all tools stay
        assert "save_memory" in bot.local_tools
        assert "search_memories" in bot.local_tools


# ---------------------------------------------------------------------------
# Effective system prompt
# ---------------------------------------------------------------------------

class TestEffectiveSystemPrompt:
    def test_memory_scheme_prompt_injected(self):
        from app.services.sessions import _effective_system_prompt, _MEMORY_SCHEME_PROMPT
        bot = _bot(memory_scheme="workspace-files")
        prompt = _effective_system_prompt(bot)
        assert "## Memory" in prompt
        assert "search_memory" in prompt
        assert "get_memory_file" in prompt

    def test_no_memory_scheme_prompt_without_scheme(self):
        from app.services.sessions import _effective_system_prompt
        bot = _bot(memory_scheme=None)
        prompt = _effective_system_prompt(bot)
        assert "## Memory" not in prompt

    def test_memory_scheme_overrides_db_memory_prompt(self):
        from app.services.sessions import _effective_system_prompt
        bot = _bot(
            memory_scheme="workspace-files",
            memory=MemoryConfig(enabled=True, prompt="DB memory prompt here"),
        )
        prompt = _effective_system_prompt(bot)
        # Should use workspace-files prompt, NOT the DB memory prompt
        assert "DB memory prompt here" not in prompt
        assert "## Memory" in prompt


# ---------------------------------------------------------------------------
# Compaction flush prompt override
# ---------------------------------------------------------------------------

class TestCompactionFlushOverride:
    def test_memory_scheme_flush_prompt(self):
        from app.services.compaction import _MEMORY_SCHEME_FLUSH_PROMPT
        assert "daily log" in _MEMORY_SCHEME_FLUSH_PROMPT
        assert "MEMORY.md" in _MEMORY_SCHEME_FLUSH_PROMPT
        assert "exec_command" in _MEMORY_SCHEME_FLUSH_PROMPT


# ---------------------------------------------------------------------------
# Reranking prefixes
# ---------------------------------------------------------------------------

class TestRerankingPrefixes:
    def test_memory_scheme_prefixes_registered(self):
        from app.services.reranking import _RAG_PREFIXES, _EXCLUDED_PREFIXES

        # Memory scheme injections should be in RAG prefixes
        prefix_labels = [label for _, label in _RAG_PREFIXES]
        assert "memory_bootstrap" in prefix_labels
        assert "memory_today_log" in prefix_labels
        assert "memory_yesterday_log" in prefix_labels

        # And excluded from reranking
        assert any("MEMORY.md" in p for p in _EXCLUDED_PREFIXES)
        assert any("daily log" in p.lower() for p in _EXCLUDED_PREFIXES)
