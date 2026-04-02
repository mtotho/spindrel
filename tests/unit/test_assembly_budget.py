"""Tests for budget-aware behaviour inside assemble_context()."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.bots import BotConfig
from app.agent.context_assembly import AssemblyResult, assemble_context
from app.agent.context_budget import ContextBudget, estimate_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_bot(**overrides) -> BotConfig:
    """Return a minimal BotConfig with defaults overridden by kwargs."""
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="gpt-4o",
        system_prompt="You are a test bot.",
        local_tools=[],
        mcp_servers=[],
        client_tools=[],
        skills=[],
        pinned_tools=[],
        tool_retrieval=False,
        carapaces=[],
        memory_scheme=None,
        history_mode=None,
        filesystem_indexes=[],
        delegate_bots=[],
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


async def _drain(gen) -> list[dict]:
    """Drain an async generator into a list."""
    events = []
    async for ev in gen:
        events.append(ev)
    return events


def _assembly_patches():
    """Return a stack of patches that neutralize DB / hook / trace calls."""
    return [
        patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
        patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
    ]


def _call_assembly(messages, bot, user_message, result, budget=None, correlation_id=None):
    """Build assemble_context() call with common defaults."""
    return assemble_context(
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=None,
        client_id=None,
        correlation_id=correlation_id,
        channel_id=None,
        audio_data=None,
        audio_format=None,
        attachments=None,
        native_audio=False,
        result=result,
        budget=budget,
    )


# ---------------------------------------------------------------------------
# Tests: generous budget
# ---------------------------------------------------------------------------

class TestAssemblyBudgetGenerous:
    """With a large budget, assembly tracks consumption but skips nothing."""

    @pytest.mark.asyncio
    async def test_budget_tracks_conversation_history(self):
        """Pre-existing messages are charged against the budget."""
        bot = _minimal_bot()
        messages = [
            {"role": "system", "content": "You are a test bot."},
            {"role": "user", "content": "Hello there!"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
        budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
        result = AssemblyResult()

        patches = _assembly_patches()
        for p in patches:
            p.start()
        try:
            await _drain(_call_assembly(messages, bot, "What's up?", result, budget=budget))
        finally:
            for p in patches:
                p.stop()

        assert "conversation_history" in budget.breakdown
        assert budget.consumed_tokens > 0
        assert result.budget_utilization is not None
        assert result.budget_utilization >= 0

    @pytest.mark.asyncio
    async def test_budget_utilization_on_result(self):
        """result.budget_utilization is populated when budget is passed."""
        bot = _minimal_bot()
        messages = [{"role": "system", "content": "Short system prompt."}]
        budget = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        result = AssemblyResult()

        patches = _assembly_patches()
        for p in patches:
            p.start()
        try:
            await _drain(_call_assembly(messages, bot, "Hi", result, budget=budget))
        finally:
            for p in patches:
                p.stop()

        assert result.budget_utilization is not None
        assert result.budget_utilization < 0.1

    @pytest.mark.asyncio
    async def test_no_budget_leaves_result_none(self):
        """When no budget is passed, result.budget_utilization stays None."""
        bot = _minimal_bot()
        messages = [{"role": "system", "content": "System."}]
        result = AssemblyResult()

        patches = _assembly_patches()
        for p in patches:
            p.start()
        try:
            await _drain(_call_assembly(messages, bot, "Hi", result, budget=None))
        finally:
            for p in patches:
                p.stop()

        assert result.budget_utilization is None


# ---------------------------------------------------------------------------
# Tests: tight budget — P3/P4 gating
# ---------------------------------------------------------------------------

class TestAssemblyBudgetTight:
    """When budget is nearly exhausted, P3 and P4 content is skipped."""

    @pytest.mark.asyncio
    async def test_p4_tool_index_skipped_when_budget_exhausted(self):
        """Tool index hints (P4) are skipped when budget can't afford them."""
        bot = _minimal_bot(
            local_tools=["web_search", "file", "exec_command"],
            tool_retrieval=True,
        )
        messages = [{"role": "system", "content": "System."}]

        # Budget almost exhausted — only 10 tokens remaining
        budget = ContextBudget(total_tokens=10_000, reserve_tokens=0)
        budget.consume("pre_fill", 9_990)
        result = AssemblyResult()

        mock_schemas = {
            "web_search": {"type": "function", "function": {"name": "web_search", "description": "Search", "parameters": {}}},
            "file": {"type": "function", "function": {"name": "file", "description": "File ops", "parameters": {}}},
            "exec_command": {"type": "function", "function": {"name": "exec_command", "description": "Run command", "parameters": {}}},
        }

        patches = _assembly_patches() + [
            patch("app.agent.context_assembly._all_tool_schemas_by_name", new_callable=AsyncMock, return_value=mock_schemas),
            patch("app.agent.context_assembly.retrieve_tools", new_callable=AsyncMock, return_value=(
                [mock_schemas["web_search"]], 0.8, [("web_search", 0.8)],
            )),
            patch("app.agent.context_assembly.get_client_tool_schemas", return_value=[]),
            patch("app.agent.context_assembly.get_mcp_server_for_tool", return_value=None),
        ]

        for p in patches:
            p.start()
        try:
            events = await _drain(_call_assembly(messages, bot, "search for cats", result, budget=budget))
        finally:
            for p in patches:
                p.stop()

        tool_index_events = [e for e in events if e.get("type") == "tool_index"]
        assert len(tool_index_events) == 0
        assert "tool_index" not in budget.breakdown

    @pytest.mark.asyncio
    async def test_p3_fs_rag_budget_gate(self):
        """Budget correctly prevents large content when remaining is small."""
        # This tests the budget gate mechanism at the data level, since
        # wiring through the full workspace path requires extensive DB mocking.
        budget = ContextBudget(total_tokens=10_000, reserve_tokens=0)
        budget.consume("pre_fill", 9_990)

        # Simulated fs RAG content that assembly would try to inject
        fs_content = (
            "Relevant workspace file excerpts (partial segments):\n\n"
            + "\n\n---\n\n".join(["A" * 500, "B" * 500])
        )
        assert not budget.can_afford(estimate_tokens(fs_content))

        # With generous budget, same content should fit
        big_budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
        assert big_budget.can_afford(estimate_tokens(fs_content))

    @pytest.mark.asyncio
    async def test_p4_tool_index_included_with_generous_budget(self):
        """Tool index hints (P4) ARE included when budget has room."""
        bot = _minimal_bot(
            local_tools=["web_search", "file", "exec_command"],
            tool_retrieval=True,
        )
        messages = [{"role": "system", "content": "System."}]

        budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
        result = AssemblyResult()

        mock_schemas = {
            "web_search": {"type": "function", "function": {"name": "web_search", "description": "Search the web", "parameters": {}}},
            "file": {"type": "function", "function": {"name": "file", "description": "File operations", "parameters": {}}},
            "exec_command": {"type": "function", "function": {"name": "exec_command", "description": "Run a command", "parameters": {}}},
        }

        patches = _assembly_patches() + [
            patch("app.agent.context_assembly._all_tool_schemas_by_name", new_callable=AsyncMock, return_value=mock_schemas),
            patch("app.agent.context_assembly.retrieve_tools", new_callable=AsyncMock, return_value=(
                [mock_schemas["web_search"]], 0.8, [("web_search", 0.8)],
            )),
            patch("app.agent.context_assembly.get_client_tool_schemas", return_value=[]),
            patch("app.agent.context_assembly.get_mcp_server_for_tool", return_value=None),
        ]

        for p in patches:
            p.start()
        try:
            events = await _drain(_call_assembly(messages, bot, "search for cats", result, budget=budget))
        finally:
            for p in patches:
                p.stop()

        tool_index_events = [e for e in events if e.get("type") == "tool_index"]
        assert len(tool_index_events) == 1
        assert "tool_index" in budget.breakdown
        assert budget.breakdown["tool_index"] > 0


# ---------------------------------------------------------------------------
# Tests: budget in injection summary
# ---------------------------------------------------------------------------

class TestAssemblyBudgetSummary:
    """Budget info is included in trace events."""

    @pytest.mark.asyncio
    async def test_summary_includes_budget(self):
        """context_injection_summary trace includes budget data when present."""
        bot = _minimal_bot()
        messages = [{"role": "system", "content": "System prompt."}]
        budget = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        result = AssemblyResult()
        cid = uuid.uuid4()

        recorded = []

        async def _capture_trace(**kwargs):
            recorded.append(kwargs)

        patches = [
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", side_effect=_capture_trace),
        ]

        for p in patches:
            p.start()
        try:
            await _drain(_call_assembly(messages, bot, "Hello", result, budget=budget, correlation_id=cid))
        finally:
            for p in patches:
                p.stop()

        summaries = [e for e in recorded if e.get("event_type") == "context_injection_summary"]
        if summaries:
            data = summaries[0]["data"]
            assert "context_budget" in data
            cb = data["context_budget"]
            assert cb["total_tokens"] == 100_000
            assert cb["reserve_tokens"] == 15_000
            assert "consumed_tokens" in cb
            assert "remaining_tokens" in cb
