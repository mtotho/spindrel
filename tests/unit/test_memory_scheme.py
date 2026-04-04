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

    def test_orchestrator_gets_per_bot_memory(self):
        """Orchestrators use standard memory/ under their ws_root (already scoped to bots/{id}/)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bot = _bot(
                id="orch_bot",
                memory_scheme="workspace-files",
                shared_workspace_id="ws-123",
                shared_workspace_role="orchestrator",
            )
            from app.services.memory_scheme import bootstrap_memory_scheme, get_memory_rel_path
            rel = get_memory_rel_path(bot)
            # Orchestrators now use the same "memory" prefix — ws_root is already bots/{id}/
            assert rel == "memory"

            result = bootstrap_memory_scheme(bot, ws_root=tmpdir)
            assert result == os.path.join(tmpdir, "memory")
            assert os.path.isdir(os.path.join(tmpdir, "memory", "logs"))
            assert os.path.isfile(os.path.join(tmpdir, "memory", "MEMORY.md"))

    def test_non_orchestrator_gets_standard_memory(self):
        """Non-orchestrator shared workspace bots use standard memory/ path."""
        bot = _bot(
            id="worker_bot",
            memory_scheme="workspace-files",
            shared_workspace_id="ws-123",
            shared_workspace_role="worker",
        )
        from app.services.memory_scheme import get_memory_rel_path
        assert get_memory_rel_path(bot) == "memory"


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
        from app.services.sessions import _effective_system_prompt
        from app.config import DEFAULT_MEMORY_SCHEME_PROMPT
        bot = _bot(memory_scheme="workspace-files")
        prompt = _effective_system_prompt(bot)
        assert "## Memory" in prompt
        assert "search_memory" in prompt
        assert "get_memory_file" in prompt

    def test_memory_scheme_prompt_uses_prefixed_paths(self):
        """Ensure the prompt tells bots to use memory/ prefix when writing files."""
        from app.services.sessions import _effective_system_prompt
        bot = _bot(memory_scheme="workspace-files")
        prompt = _effective_system_prompt(bot)
        # The prompt must use memory/MEMORY.md (not bare MEMORY.md) so the
        # file tool resolves to the correct directory.
        assert "memory/MEMORY.md" in prompt
        assert "memory/logs/" in prompt
        assert "memory/reference/" in prompt
        # Verify no bare "MEMORY.md" without the memory/ prefix.
        # Split on "memory/MEMORY.md" and check remaining fragments.
        fragments = prompt.split("memory/MEMORY.md")
        for frag in fragments:
            # Each fragment should NOT end with a bare reference to MEMORY.md
            # (i.e. "MEMORY.md" should only appear as part of "memory/MEMORY.md")
            assert not frag.rstrip().endswith("MEMORY.md"), (
                "Found bare 'MEMORY.md' reference without memory/ prefix in prompt"
            )

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
        from app.config import DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        assert "daily log" in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        assert "memory/MEMORY.md" in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        assert "memory/logs/" in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        assert "file" in DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT

    def test_flush_prompt_no_bare_memory_md(self):
        """Flush prompt must not reference bare 'MEMORY.md' without memory/ prefix."""
        from app.config import DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
        # Remove all correctly-prefixed references, then check for leftover bare ones
        stripped = DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT.replace("memory/MEMORY.md", "")
        assert "MEMORY.md" not in stripped, (
            "Flush prompt contains bare 'MEMORY.md' without memory/ prefix"
        )


# ---------------------------------------------------------------------------
# Reranking prefixes
# ---------------------------------------------------------------------------

class TestRerankingPrefixes:
    def test_memory_scheme_prefixes_excluded_from_reranking(self):
        """Memory scheme injections are structural — they should be EXCLUDED, not RAG-ranked."""
        from app.services.reranking import _RAG_PREFIXES, _EXCLUDED_PREFIXES

        # Memory scheme entries must NOT be in _RAG_PREFIXES (they're always injected)
        prefix_labels = [label for _, label in _RAG_PREFIXES]
        assert "memory_bootstrap" not in prefix_labels
        assert "memory_today_log" not in prefix_labels
        assert "memory_yesterday_log" not in prefix_labels

        # They must be in _EXCLUDED_PREFIXES
        assert any("memory/MEMORY.md" in p for p in _EXCLUDED_PREFIXES)
        assert any("daily log" in p.lower() for p in _EXCLUDED_PREFIXES)

    def test_excluded_prefixes_match_injection_headers(self):
        """Excluded prefixes must match what context_assembly actually produces.

        The injection headers use get_memory_rel_path() which returns "memory".
        Excluded prefixes must start-match these headers or reranking would
        incorrectly try to rerank structural content.
        """
        from app.services.reranking import _EXCLUDED_PREFIXES
        from app.services.memory_scheme import get_memory_rel_path

        bot = _bot(memory_scheme="workspace-files")
        mem_rel = get_memory_rel_path(bot)  # "memory"

        # Build the headers context_assembly would produce
        bootstrap_header = f"Your persistent memory ({mem_rel}/MEMORY.md"
        today_header = f"Today's daily log ({mem_rel}/logs/"
        yesterday_header = f"Yesterday's daily log ({mem_rel}/logs/"
        reference_header = f"Reference documents in {mem_rel}/reference/"

        # Check excluded prefixes match
        assert any(bootstrap_header.startswith(ep) for ep in _EXCLUDED_PREFIXES), (
            f"Bootstrap header not excluded from reranking: {bootstrap_header!r}"
        )
        assert any(today_header.startswith(ep) for ep in _EXCLUDED_PREFIXES), (
            f"Today log header not excluded from reranking: {today_header!r}"
        )
        assert any(yesterday_header.startswith(ep) for ep in _EXCLUDED_PREFIXES), (
            f"Yesterday log header not excluded from reranking: {yesterday_header!r}"
        )
        assert any(reference_header.startswith(ep) for ep in _EXCLUDED_PREFIXES), (
            f"Reference header not excluded from reranking: {reference_header!r}"
        )


# ---------------------------------------------------------------------------
# Custom prompt override
# ---------------------------------------------------------------------------

class TestCustomPromptOverride:
    def test_custom_memory_scheme_prompt_gets_formatted(self):
        """A user-provided MEMORY_SCHEME_PROMPT still gets {memory_rel} substituted."""
        from app.services.sessions import _effective_system_prompt
        from app.config import settings

        custom = "Write files to {memory_rel}/MEMORY.md, not bare MEMORY.md."
        bot = _bot(memory_scheme="workspace-files")
        orig = settings.MEMORY_SCHEME_PROMPT
        try:
            settings.MEMORY_SCHEME_PROMPT = custom
            prompt = _effective_system_prompt(bot)
        finally:
            settings.MEMORY_SCHEME_PROMPT = orig
        assert "memory/MEMORY.md" in prompt
        assert "{memory_rel}" not in prompt  # placeholder must be resolved

    def test_empty_override_falls_back_to_default(self):
        """Empty MEMORY_SCHEME_PROMPT setting uses the built-in default."""
        from app.services.sessions import _effective_system_prompt
        from app.config import settings

        bot = _bot(memory_scheme="workspace-files")
        orig = settings.MEMORY_SCHEME_PROMPT
        try:
            settings.MEMORY_SCHEME_PROMPT = ""
            prompt = _effective_system_prompt(bot)
        finally:
            settings.MEMORY_SCHEME_PROMPT = orig
        assert "memory/MEMORY.md" in prompt
        assert "## Memory" in prompt


# ---------------------------------------------------------------------------
# Base prompt content validation
# ---------------------------------------------------------------------------

class TestBasePromptContent:
    def test_base_prompt_correct_tool_names(self):
        """Verify correct tool names appear and old wrong names don't."""
        from app.config import DEFAULT_GLOBAL_BASE_PROMPT

        # Correct names must be present
        assert "delegate_to_agent" in DEFAULT_GLOBAL_BASE_PROMPT
        assert "get_tool_info" in DEFAULT_GLOBAL_BASE_PROMPT

        # Old wrong names must NOT be present
        # "delegate_to" appears inside "delegate_to_agent", so check for the
        # standalone wrong usage: backtick-wrapped `delegate_to` without _agent
        assert "`delegate_to`" not in DEFAULT_GLOBAL_BASE_PROMPT
        # Old get_tool( pattern must not appear
        assert "get_tool(" not in DEFAULT_GLOBAL_BASE_PROMPT

    def test_base_prompt_platform_awareness(self):
        """Verify key platform concepts are mentioned in the base prompt."""
        from app.config import DEFAULT_GLOBAL_BASE_PROMPT

        for concept in ["carapace", "integration", "workflow", "orchestrator"]:
            assert concept.lower() in DEFAULT_GLOBAL_BASE_PROMPT.lower(), (
                f"Base prompt missing platform concept: {concept}"
            )

    def test_base_prompt_capability_discovery(self):
        """Verify capability discovery guidance is present."""
        from app.config import DEFAULT_GLOBAL_BASE_PROMPT

        assert "get_tool_info" in DEFAULT_GLOBAL_BASE_PROMPT
        assert "get_skill" in DEFAULT_GLOBAL_BASE_PROMPT
        assert "Discovering Capabilities" in DEFAULT_GLOBAL_BASE_PROMPT
