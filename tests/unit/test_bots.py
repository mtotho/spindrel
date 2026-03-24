"""Unit tests for resolve_bot_id, get_bot, _bot_row_to_config in app.agent.bots."""
import pytest
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.agent import bots
from app.agent.bots import (
    BotConfig, MemoryConfig, KnowledgeConfig,
    resolve_bot_id, get_bot, _bot_row_to_config,
)


def _bot(id: str, name: str) -> BotConfig:
    return BotConfig(
        id=id, name=name, model="gpt-4", system_prompt="test",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    backup = bots._registry.copy()
    yield
    bots._registry.clear()
    bots._registry.update(backup)


class TestResolveBotId:
    def test_exact_id(self):
        bot = _bot("google_bot", "Google Bot")
        bots._registry["google_bot"] = bot
        assert resolve_bot_id("google_bot") is bot

    def test_case_insensitive_id(self):
        bot = _bot("Google_Bot", "Google Bot")
        bots._registry["Google_Bot"] = bot
        assert resolve_bot_id("google_bot") is bot

    def test_exact_name(self):
        bot = _bot("gb", "Google Bot")
        bots._registry["gb"] = bot
        assert resolve_bot_id("Google Bot") is bot

    def test_substring_of_id(self):
        bot = _bot("google_bot", "My Bot")
        bots._registry["google_bot"] = bot
        assert resolve_bot_id("google") is bot

    def test_substring_of_name(self):
        bot = _bot("gb", "Let Me Google That For You")
        bots._registry["gb"] = bot
        assert resolve_bot_id("google") is bot

    def test_word_overlap(self):
        bot = _bot("search", "Let Me Google That")
        bots._registry["search"] = bot
        assert resolve_bot_id("let me google") is bot

    def test_none_for_no_match(self):
        bots._registry["some_bot"] = _bot("some_bot", "Some Bot")
        assert resolve_bot_id("zzz_nonexistent_zzz") is None

    def test_none_for_empty_registry(self):
        bots._registry.clear()
        assert resolve_bot_id("anything") is None

    def test_none_for_empty_hint(self):
        bots._registry["a"] = _bot("a", "A")
        assert resolve_bot_id("") is None


# ---------------------------------------------------------------------------
# get_bot
# ---------------------------------------------------------------------------

class TestGetBot:
    def test_returns_bot_for_known_id(self):
        bot = _bot("known", "Known Bot")
        bots._registry["known"] = bot
        assert get_bot("known") is bot

    def test_raises_404_for_unknown_id(self):
        with pytest.raises(HTTPException) as exc_info:
            get_bot("nonexistent_bot_xyz")
        assert exc_info.value.status_code == 404
        assert "nonexistent_bot_xyz" in exc_info.value.detail


# ---------------------------------------------------------------------------
# _bot_row_to_config
# ---------------------------------------------------------------------------

def _make_bot_row(**overrides):
    """Create a mock BotRow with all fields set to sensible defaults."""
    row = MagicMock()
    row.id = overrides.get("id", "test_bot")
    row.name = overrides.get("name", "Test Bot")
    row.model = overrides.get("model", "gpt-4")
    row.system_prompt = overrides.get("system_prompt", "You are helpful.")
    row.mcp_servers = overrides.get("mcp_servers", ["server1"])
    row.local_tools = overrides.get("local_tools", ["web_search"])
    row.pinned_tools = overrides.get("pinned_tools", ["pinned_tool"])
    row.tool_retrieval = overrides.get("tool_retrieval", True)
    row.tool_similarity_threshold = overrides.get("tool_similarity_threshold", 0.35)
    row.client_tools = overrides.get("client_tools", ["shell_exec"])
    row.skills = overrides.get("skills", ["skill1", {"id": "skill2", "mode": "pinned"}])
    row.persona = overrides.get("persona", True)
    row.context_compaction = overrides.get("context_compaction", True)
    row.compaction_interval = overrides.get("compaction_interval", 10)
    row.compaction_keep_turns = overrides.get("compaction_keep_turns", 4)
    row.compaction_model = overrides.get("compaction_model", "gpt-3.5-turbo")
    row.memory_knowledge_compaction_prompt = overrides.get("memory_knowledge_compaction_prompt", None)
    row.audio_input = overrides.get("audio_input", "transcribe")
    row.memory_config = overrides.get("memory_config", {
        "enabled": True,
        "cross_channel": True,
        "cross_bot": False,
        "prompt": "Remember things.",
    })
    row.knowledge_config = overrides.get("knowledge_config", {"enabled": True})
    row.filesystem_indexes = overrides.get("filesystem_indexes", [])
    row.docker_sandbox_profiles = overrides.get("docker_sandbox_profiles", ["python-scratch"])
    row.host_exec_config = overrides.get("host_exec_config", {
        "enabled": True,
        "commands": [{"name": "git", "subcommands": ["status", "log"]}],
    })
    row.filesystem_access = overrides.get("filesystem_access", [
        {"path": "/tmp", "mode": "readwrite"},
    ])
    row.display_name = overrides.get("display_name", "Test Display")
    row.avatar_url = overrides.get("avatar_url", "https://example.com/avatar.png")
    row.integration_config = overrides.get("integration_config", {})
    row.tool_result_config = overrides.get("tool_result_config", {})
    row.knowledge_max_inject_chars = overrides.get("knowledge_max_inject_chars", 5000)
    row.memory_max_inject_chars = overrides.get("memory_max_inject_chars", 3000)
    row.delegation_config = overrides.get("delegation_config", {
        "delegate_bots": ["child_bot"],
        "harness_access": ["harness1"],
    })
    row.model_provider_id = overrides.get("model_provider_id", "provider1")
    row.bot_sandbox = overrides.get("bot_sandbox", {"enabled": True, "image": "node:20"})
    row.user_id = overrides.get("user_id", None)
    row._sw_workspace_id = overrides.get("_sw_workspace_id", None)
    row._sw_role = overrides.get("_sw_role", None)
    row._sw_cwd_override = overrides.get("_sw_cwd_override", None)
    return row


class TestBotRowToConfig:
    def test_basic_fields_mapped(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.id == "test_bot"
        assert config.name == "Test Bot"
        assert config.model == "gpt-4"
        assert config.system_prompt == "You are helpful."

    def test_memory_config_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.memory.enabled is True
        assert config.memory.cross_channel is True
        assert config.memory.prompt == "Remember things."

    def test_knowledge_config_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.knowledge.enabled is True

    def test_skills_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert len(config.skills) == 2
        assert config.skills[0].id == "skill1"
        assert config.skills[0].mode == "on_demand"
        assert config.skills[1].id == "skill2"
        assert config.skills[1].mode == "pinned"

    def test_host_exec_config_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.host_exec.enabled is True
        assert len(config.host_exec.commands) == 1
        assert config.host_exec.commands[0].name == "git"
        assert config.host_exec.commands[0].subcommands == ["status", "log"]

    def test_filesystem_access_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert len(config.filesystem_access) == 1
        assert config.filesystem_access[0].path == "/tmp"
        assert config.filesystem_access[0].mode == "readwrite"

    def test_delegation_config_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.delegate_bots == ["child_bot"]
        assert config.harness_access == ["harness1"]

    def test_bot_sandbox_parsed(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.bot_sandbox.enabled is True
        assert config.bot_sandbox.image == "node:20"

    def test_none_delegation_config(self):
        row = _make_bot_row(delegation_config=None)
        config = _bot_row_to_config(row)
        assert config.delegate_bots == []
        assert config.harness_access == []

    def test_empty_memory_config(self):
        row = _make_bot_row(memory_config={})
        config = _bot_row_to_config(row)
        assert config.memory.enabled is False
        assert config.memory.cross_channel is False

    def test_model_provider_id(self):
        row = _make_bot_row()
        config = _bot_row_to_config(row)
        assert config.model_provider_id == "provider1"

    def test_user_id_from_row(self):
        row = _make_bot_row()
        row.user_id = "user-uuid-123"
        config = _bot_row_to_config(row)
        assert config.user_id == "user-uuid-123"

    def test_user_id_none_by_default(self):
        row = _make_bot_row()
        row.user_id = None
        config = _bot_row_to_config(row)
        assert config.user_id is None

    def test_shared_workspace_fields_from_transient_attrs(self):
        import uuid as _uuid
        row = _make_bot_row()
        row.user_id = None
        ws_id = _uuid.uuid4()
        row._sw_workspace_id = ws_id
        row._sw_role = "orchestrator"
        row._sw_cwd_override = "/workspace/custom"
        config = _bot_row_to_config(row)
        assert config.shared_workspace_id == str(ws_id)
        assert config.shared_workspace_role == "orchestrator"
        assert config.shared_workspace_cwd == "/workspace/custom"

    def test_shared_workspace_fields_none_when_no_junction(self):
        row = _make_bot_row()
        row.user_id = None
        # Explicitly set to None (as load_bots does for bots not in a workspace)
        row._sw_workspace_id = None
        row._sw_role = None
        row._sw_cwd_override = None
        config = _bot_row_to_config(row)
        assert config.shared_workspace_id is None
        assert config.shared_workspace_role is None
        assert config.shared_workspace_cwd is None
