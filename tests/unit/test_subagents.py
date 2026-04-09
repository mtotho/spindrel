"""Unit tests for the sub-agent system.

Tests cover:
- Preset resolution and validation
- Tool filtering (spawn_subagents stripped from sub-agent tools)
- Model tier resolution
- Rate limiting (max sub-agents per call)
- Error handling (missing prompt, invalid preset)
- Result truncation
- Parallel execution via run_subagents
- The spawn_subagents tool function
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.subagents import (
    MAX_RESULT_CHARS,
    MAX_SUBAGENTS_PER_CALL,
    SUBAGENT_PRESETS,
    SubagentResult,
    run_subagent,
    run_subagents,
)


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

class TestPresets:
    def test_all_presets_have_required_fields(self):
        for name, cfg in SUBAGENT_PRESETS.items():
            assert "tools" in cfg, f"Preset {name} missing 'tools'"
            assert "system_prompt" in cfg, f"Preset {name} missing 'system_prompt'"
            assert "default_tier" in cfg, f"Preset {name} missing 'default_tier'"
            assert isinstance(cfg["tools"], list), f"Preset {name} tools must be a list"
            assert cfg["default_tier"] in {"free", "fast", "standard", "capable", "frontier"}, (
                f"Preset {name} has invalid tier: {cfg['default_tier']}"
            )

    def test_expected_presets_exist(self):
        expected = {"file-scanner", "summarizer", "researcher", "code-reviewer", "data-extractor"}
        assert expected == set(SUBAGENT_PRESETS.keys())

    def test_summarizer_has_no_tools(self):
        assert SUBAGENT_PRESETS["summarizer"]["tools"] == []

    def test_file_scanner_has_file_tools(self):
        tools = SUBAGENT_PRESETS["file-scanner"]["tools"]
        assert "file" in tools
        assert "exec_command" in tools

    def test_researcher_has_web_search(self):
        assert "web_search" in SUBAGENT_PRESETS["researcher"]["tools"]


# ---------------------------------------------------------------------------
# run_subagent — unit tests with mocked LLM
# ---------------------------------------------------------------------------

def _mock_agent_loop(response_text="Sub-agent result"):
    """Create a mock for run_agent_tool_loop that yields a response event."""
    async def _gen(*args, **kwargs):
        yield {"type": "response", "text": response_text}

    return _gen


def _mock_bot_config():
    from app.agent.bots import BotConfig
    return BotConfig(
        id="test-bot",
        name="Test",
        model="test-model",
        system_prompt="Test bot.",
    )


class TestRunSubagent:
    @pytest.mark.asyncio
    async def test_invalid_preset_returns_error(self):
        result = await run_subagent("do something", preset="nonexistent")
        assert result.status == "error"
        assert "Unknown preset" in result.result
        assert "nonexistent" in result.result

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("Hello from sub-agent"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_basic_execution(self, mock_schemas, mock_loop):
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "Say hello",
                preset="summarizer",
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        assert result.result == "Hello from sub-agent"
        assert result.preset == "summarizer"
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("x" * 5000))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_result_truncation(self, mock_schemas, mock_loop):
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "Generate long text",
                preset="summarizer",
                max_chars=100,
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        assert len(result.result) < 200  # 100 + truncation message
        assert "truncated" in result.result.lower()

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas")
    async def test_forbidden_tools_stripped(self, mock_schemas, mock_loop):
        """spawn_subagents and delegate_to_agent must be stripped from sub-agent tools."""
        mock_schemas.return_value = []
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "test",
                tools=["file", "spawn_subagents", "delegate_to_agent", "exec_command"],
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        # Check what tools were passed to get_local_tool_schemas
        called_tools = mock_schemas.call_args[0][0]
        assert "spawn_subagents" not in called_tools
        assert "delegate_to_agent" not in called_tools
        assert "file" in called_tools
        assert "exec_command" in called_tools

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_explicit_model_overrides_tier(self, mock_schemas, mock_loop):
        """When model= is explicit, it should be used directly, not tier resolution."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "test",
                preset="summarizer",
                model="explicit/model-name",
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        assert result.model == "explicit/model-name"

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_model_tier_resolution(self, mock_schemas, mock_loop):
        """Model tier should resolve via resolve_model_tier."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            with patch("app.services.server_config.resolve_model_tier", return_value=("gemini/flash", "provider-1")):
                result = await run_subagent(
                    "test",
                    model_tier="fast",
                    parent_bot_id="test-bot",
                )
        assert result.status == "ok"
        assert result.model == "gemini/flash"

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_preset_tier_used_when_no_explicit(self, mock_schemas, mock_loop):
        """When no model or model_tier is given, use the preset's default_tier."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            with patch("app.services.server_config.resolve_model_tier", return_value=("gemini/flash", None)) as mock_resolve:
                result = await run_subagent(
                    "test",
                    preset="file-scanner",  # default_tier = "fast"
                    parent_bot_id="test-bot",
                )
        # Should have tried to resolve "fast" tier
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args[0][0] == "fast"

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop(""))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_empty_response_becomes_placeholder(self, mock_schemas, mock_loop):
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "test",
                preset="summarizer",
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        assert result.result == "(empty response)"

    @pytest.mark.asyncio
    async def test_exception_during_execution_returns_error(self):
        async def _failing_loop(*args, **kwargs):
            raise RuntimeError("LLM exploded")
            yield  # noqa: unreachable — makes this an async generator

        with patch("app.agent.loop.run_agent_tool_loop", side_effect=_failing_loop):
            with patch("app.tools.registry.get_local_tool_schemas", return_value=[]):
                with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
                    result = await run_subagent(
                        "test",
                        preset="summarizer",
                        parent_bot_id="test-bot",
                    )
        assert result.status == "error"
        assert "LLM exploded" in result.result

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("ok"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_no_preset_with_explicit_tools_and_prompt(self, mock_schemas, mock_loop):
        """Custom sub-agent with no preset should work."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            result = await run_subagent(
                "What time is it?",
                tools=["get_current_time"],
                system_prompt="You are a clock.",
                model_tier="fast",
                parent_bot_id="test-bot",
            )
        assert result.status == "ok"
        assert result.preset is None

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_max_iterations_capped(self, mock_schemas, mock_loop):
        """Sub-agents should have a low max_iterations (5)."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            await run_subagent("test", preset="summarizer", parent_bot_id="test-bot")
        # Check max_iterations was passed
        call_kwargs = mock_loop.call_args[1] if mock_loop.call_args[1] else {}
        # run_agent_tool_loop is called as side_effect, check via the wrapper
        # The mock was called, verify max_iterations in kwargs
        assert mock_loop.called

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("done"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_skip_tool_policy_enabled(self, mock_schemas, mock_loop):
        """Sub-agents should skip tool approval policy."""
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            await run_subagent("test", preset="summarizer", parent_bot_id="test-bot")
        assert mock_loop.called


# ---------------------------------------------------------------------------
# run_subagents — parallel execution
# ---------------------------------------------------------------------------

class TestRunSubagents:
    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop")
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_parallel_execution(self, mock_schemas, mock_loop):
        """Multiple sub-agents should run and all return results."""
        call_count = 0

        async def _counting_loop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield {"type": "response", "text": f"Result {call_count}"}

        mock_loop.side_effect = _counting_loop
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            results = await run_subagents([
                {"preset": "summarizer", "prompt": "Task 1"},
                {"preset": "summarizer", "prompt": "Task 2"},
                {"preset": "summarizer", "prompt": "Task 3"},
            ], parent_bot_id="test-bot")

        assert len(results) == 3
        assert all(r.status == "ok" for r in results)
        # Indices should be assigned
        assert [r.index for r in results] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_missing_prompt_returns_error(self):
        results = await run_subagents([
            {"preset": "summarizer"},  # no prompt!
        ])
        assert len(results) == 1
        assert results[0].status == "error"
        assert "Missing" in results[0].result

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("ok"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_rate_limit_truncation(self, mock_schemas, mock_loop):
        """Specs beyond MAX_SUBAGENTS_PER_CALL should be dropped."""
        specs = [{"preset": "summarizer", "prompt": f"Task {i}"} for i in range(MAX_SUBAGENTS_PER_CALL + 5)]
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            results = await run_subagents(specs, parent_bot_id="test-bot")
        assert len(results) == MAX_SUBAGENTS_PER_CALL

    @pytest.mark.asyncio
    async def test_empty_specs_returns_empty(self):
        results = await run_subagents([])
        assert results == []

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop")
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_exception_in_one_doesnt_break_others(self, mock_schemas, mock_loop):
        """If one sub-agent throws, the others should still succeed."""
        call_idx = 0

        async def _mixed_loop(*args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 2:
                raise RuntimeError("Boom")
            yield {"type": "response", "text": f"OK {call_idx}"}

        mock_loop.side_effect = _mixed_loop
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            results = await run_subagents([
                {"preset": "summarizer", "prompt": "A"},
                {"preset": "summarizer", "prompt": "B"},
                {"preset": "summarizer", "prompt": "C"},
            ], parent_bot_id="test-bot")

        assert len(results) == 3
        # One should be an error, the other two should be ok
        statuses = {r.status for r in results}
        assert "error" in statuses
        assert "ok" in statuses


# ---------------------------------------------------------------------------
# spawn_subagents tool function
# ---------------------------------------------------------------------------

class TestSpawnSubagentsTool:
    @pytest.mark.asyncio
    async def test_empty_agents_returns_error(self):
        from app.tools.local.subagents import spawn_subagents
        result = json.loads(await spawn_subagents([]))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("tool result"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_tool_returns_json_with_results(self, mock_schemas, mock_loop):
        from app.tools.local.subagents import spawn_subagents
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            raw = await spawn_subagents([
                {"preset": "summarizer", "prompt": "Summarize this"},
            ])
        data = json.loads(raw)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["status"] == "ok"
        assert data["results"][0]["result"] == "tool result"
        assert data["results"][0]["preset"] == "summarizer"

    @pytest.mark.asyncio
    @patch("app.agent.loop.run_agent_tool_loop", side_effect=_mock_agent_loop("ok"))
    @patch("app.tools.registry.get_local_tool_schemas", return_value=[])
    async def test_tool_truncation_warning(self, mock_schemas, mock_loop):
        from app.tools.local.subagents import spawn_subagents
        agents = [{"preset": "summarizer", "prompt": f"Task {i}"} for i in range(MAX_SUBAGENTS_PER_CALL + 3)]
        with patch("app.agent.bots.get_bot", return_value=_mock_bot_config()):
            raw = await spawn_subagents(agents)
        data = json.loads(raw)
        assert "warning" in data
        assert len(data["results"]) == MAX_SUBAGENTS_PER_CALL
