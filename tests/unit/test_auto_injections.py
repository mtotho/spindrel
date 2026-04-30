"""Tests for apply_auto_injections — the single source of truth for
runtime tool injection based on bot config.

Verifies that each auto-injection rule fires correctly and that
the combined result includes all expected tools.
"""
from app.agent.bots import BotConfig, SkillConfig
from app.agent.channel_overrides import EffectiveTools, apply_auto_injections


def _bot(**kwargs) -> BotConfig:
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="gpt-4",
        system_prompt="",
        local_tools=["get_current_time"],
        mcp_servers=[],
        client_tools=[],
        pinned_tools=[],
        skills=[],
        memory_scheme="workspace-files",
        history_mode="file",
        tool_retrieval=False,
    )
    defaults.update(kwargs)
    return BotConfig(**defaults)


def _eff(**kwargs) -> EffectiveTools:
    defaults = dict(
        local_tools=["get_current_time"],
        mcp_servers=[],
        client_tools=[],
        pinned_tools=[],
        skills=[],
    )
    defaults.update(kwargs)
    return EffectiveTools(**defaults)


class TestMemorySchemeInjection:
    """memory_scheme=workspace-files injects memory tools and hides knowledge tools."""

    def test_injects_memory_tools(self):
        bot = _bot(memory_scheme="workspace-files")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        for tool in ("search_memory", "get_memory_file", "memory", "manage_bot_skill"):
            assert tool in result.local_tools, f"Missing memory tool: {tool}"
            assert tool in result.pinned_tools, f"Missing from pinned: {tool}"

    def test_hides_knowledge_tools(self):
        bot = _bot(memory_scheme="workspace-files")
        eff = _eff(local_tools=["get_current_time", "upsert_knowledge", "search_knowledge"])
        result = apply_auto_injections(eff, bot)

        assert "upsert_knowledge" not in result.local_tools
        assert "search_knowledge" not in result.local_tools
        assert "get_current_time" in result.local_tools

    def test_no_injection_without_workspace_files(self):
        bot = _bot(memory_scheme=None)
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "search_memory" not in result.local_tools
        assert "file" not in result.local_tools

    def test_no_duplicates_if_already_present(self):
        bot = _bot(memory_scheme="workspace-files")
        eff = _eff(local_tools=["file", "get_current_time"])
        result = apply_auto_injections(eff, bot)

        assert result.local_tools.count("file") == 1


class TestToolRetrievalInjection:
    """tool_retrieval=true injects get_tool_info."""

    def test_injects_get_tool_info(self):
        bot = _bot(tool_retrieval=True)
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "get_tool_info" in result.local_tools
        assert "get_tool_info" in result.pinned_tools

    def test_no_injection_when_false(self):
        bot = _bot(tool_retrieval=False)
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "get_tool_info" not in result.local_tools


class TestSkillToolInjection:
    """get_skill and get_skill_list are always injected (skills are shared docs)."""

    def test_injects_skill_tools_with_skills(self):
        bot = _bot(skills=[])
        eff = _eff(skills=[SkillConfig(id="testing", mode="on_demand")])
        result = apply_auto_injections(eff, bot)

        assert "get_skill" in result.local_tools
        assert "get_skill_list" in result.local_tools

    def test_injects_skill_tools_without_skills(self):
        bot = _bot()
        eff = _eff(skills=[])
        result = apply_auto_injections(eff, bot)

        assert "get_skill" in result.local_tools
        assert "get_skill_list" in result.local_tools


class TestAgentReadinessInjection:
    """Agent self-inspection tools are always injected."""

    def test_injects_capability_manifest_and_doctor_tools(self):
        bot = _bot(memory_scheme=None, history_mode="standard")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "list_agent_capabilities" in result.local_tools
        assert "list_agent_capabilities" in result.pinned_tools
        assert "run_agent_doctor" in result.local_tools
        assert "run_agent_doctor" in result.pinned_tools


class TestChannelAwarenessInjection:
    """Channel history + sub-session tools are always injected."""

    def test_injects_list_channels(self):
        bot = _bot(memory_scheme=None, history_mode="standard")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "list_channels" in result.local_tools
        assert "list_channels" in result.pinned_tools

    def test_injects_read_history(self):
        bot = _bot(history_mode="file")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "read_conversation_history" in result.local_tools
        assert "read_conversation_history" in result.pinned_tools

    def test_injects_read_history_even_for_standard_mode(self):
        bot = _bot(history_mode="standard")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "read_conversation_history" in result.local_tools
        assert "read_conversation_history" in result.pinned_tools

    def test_injects_sub_session_tools(self):
        bot = _bot(memory_scheme=None, history_mode="standard")
        eff = _eff()
        result = apply_auto_injections(eff, bot)

        assert "list_sub_sessions" in result.local_tools
        assert "list_sub_sessions" in result.pinned_tools
        assert "read_sub_session" in result.local_tools
        assert "read_sub_session" in result.pinned_tools

class TestCombinedInjections:
    """All injections apply together for a fully configured bot."""

    def test_full_bot_gets_all_tools(self):
        bot = _bot(
            memory_scheme="workspace-files",
            tool_retrieval=True,
            history_mode="file",
        )
        eff = _eff(skills=[SkillConfig(id="testing", mode="pinned")])
        result = apply_auto_injections(eff, bot)

        expected = {
            # declared
            "get_current_time",
            # memory scheme
            "search_memory", "get_memory_file", "memory", "manage_bot_skill",
            # tool retrieval
            "get_tool_info",
            # skills
            "get_skill", "get_skill_list",
            # agent readiness
            "list_agent_capabilities", "run_agent_doctor",
            # channel awareness
            "list_channels", "read_conversation_history",
            "list_sub_sessions", "read_sub_session",
        }
        actual = set(result.local_tools)
        missing = expected - actual
        assert not missing, f"Missing auto-injected tools: {missing}"

    def test_pinned_includes_all_injected(self):
        bot = _bot(
            memory_scheme="workspace-files",
            tool_retrieval=True,
            history_mode="file",
        )
        eff = _eff(skills=[SkillConfig(id="testing", mode="pinned")])
        result = apply_auto_injections(eff, bot)

        # Every injected tool should also be pinned
        for tool in result.local_tools:
            if tool == "get_current_time":
                continue  # declared, not auto-injected
            assert tool in result.pinned_tools, (
                f"Auto-injected tool '{tool}' should be pinned"
            )

    def test_preserves_existing_tools(self):
        bot = _bot(memory_scheme="workspace-files")
        eff = _eff(
            local_tools=["get_current_time", "custom_tool"],
            pinned_tools=["custom_tool"],
        )
        result = apply_auto_injections(eff, bot)

        assert "custom_tool" in result.local_tools
        assert "custom_tool" in result.pinned_tools
        assert "get_current_time" in result.local_tools
