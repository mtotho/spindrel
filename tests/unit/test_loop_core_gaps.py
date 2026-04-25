"""Phase B.5 targeted sweep of loop.py core gaps (#4, #5, #30)."""
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.context_assembly import AssemblyResult
from app.agent.llm import AccumulatedMessage


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test-bot", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_tool_call(name="test_tool", args="{}", tc_id="tc_1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args
    return tc


def _mock_accumulated(content="Hello", tool_calls=None, completion_tokens=50):
    tc_list = None
    if tool_calls:
        tc_list = [
            {
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ]
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = completion_tokens
    usage.total_tokens = 100 + completion_tokens
    return AccumulatedMessage(content=content, tool_calls=tc_list, usage=usage)


def _make_stream_side_effects(*accumulated_messages):
    _msgs = list(accumulated_messages)
    _idx = {"n": 0}

    async def _stream(*args, **kwargs):
        idx = _idx["n"]
        _idx["n"] += 1
        yield _msgs[idx] if idx < len(_msgs) else _msgs[-1]

    return _stream


def _base_loop_settings(ms, *, pruning_enabled: bool = False) -> None:
    ms.AGENT_MAX_ITERATIONS = 5
    ms.AGENT_TRACE = False
    ms.TOOL_LOOP_DETECTION_ENABLED = False
    ms.TOOL_RESULT_SUMMARIZE_ENABLED = False
    ms.TOOL_RESULT_SUMMARIZE_THRESHOLD = 99_999
    ms.TOOL_RESULT_SUMMARIZE_MODEL = ""
    ms.TOOL_RESULT_SUMMARIZE_MAX_TOKENS = 500
    ms.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS = []
    ms.IN_LOOP_PRUNING_ENABLED = pruning_enabled
    ms.IN_LOOP_PRUNING_KEEP_ITERATIONS = 1
    ms.IN_LOOP_PRUNING_PRESSURE_THRESHOLD = 0.0
    ms.CONTEXT_PRUNING_MIN_LENGTH = 200
    ms.SKILL_CORRECTION_NUDGE_ENABLED = False
    ms.SKILL_REPEATED_LOOKUP_NUDGE_ENABLED = False
    ms.CONTEXT_BUDGET_RESERVE_RATIO = 0.15


# ─────────────────────────────────────────────────────────────────────────────
# #4 — activated-tool merging (run_agent_tool_loop lines 488-520)
# ─────────────────────────────────────────────────────────────────────────────

_INITIAL_SCHEMA = {"type": "function", "function": {"name": "get_tool_info"}}
_NEW_SCHEMA = {"type": "function", "function": {"name": "dynamic_lookup"}}


class TestActivatedToolMerging:
    """Verify tools activated mid-loop via get_tool_info appear in the next LLM call."""

    @pytest.mark.asyncio
    async def test_newly_activated_tool_merged_into_next_llm_call(self):
        """tools_param on iteration 2 includes a tool that was appended to current_activated_tools."""
        from app.agent.loop import run_agent_tool_loop
        from app.agent.context import current_activated_tools

        tc = _mock_tool_call("get_tool_info", '{"tool_name": "dynamic_lookup"}', "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Done")
        msgs = [acc_tool, acc_final]
        captured_tools: list[list] = []
        call_n = {"n": 0}

        async def _stream(model, messages, tools_param, tool_choice, **kw):
            captured_tools.append(list(tools_param) if tools_param else [])
            n = call_n["n"]
            call_n["n"] += 1
            yield msgs[n] if n < len(msgs) else msgs[-1]

        async def _activating_call(tool_name, args_str, **kw):
            lst = current_activated_tools.get()
            if lst is not None:
                lst.append(_NEW_SCHEMA)
            return '{"info": "schema for dynamic_lookup"}'

        bot = _make_bot()
        with patch("app.agent.loop._llm_call_stream", side_effect=_stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", side_effect=_activating_call), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms)
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "find dynamic_lookup"}],
                bot,
                pre_selected_tools=[_INITIAL_SCHEMA],
            ):
                pass

        assert len(captured_tools) == 2
        call0_names = {t["function"]["name"] for t in captured_tools[0]}
        call1_names = {t["function"]["name"] for t in captured_tools[1]}
        assert "dynamic_lookup" not in call0_names, "new tool must NOT be in the first LLM call"
        assert "dynamic_lookup" in call1_names, "new tool must be merged before the second LLM call"

    @pytest.mark.asyncio
    async def test_already_merged_tool_not_readded_in_later_iterations(self):
        """A tool merged in iter 1 is not duplicated in iter 2 even if _activated_list still holds it.

        The dedup compares against _existing_names (already in tools_param), not within
        _activated_list itself.  After dynamic_lookup is merged in iter 1, iter 2's merge
        finds it in _existing_names and skips re-adding it — exactly one copy persists.
        """
        from app.agent.loop import run_agent_tool_loop
        from app.agent.context import current_activated_tools

        # 3 iterations: iter 0 activates, iter 1 activates again, iter 2 returns text
        tc_0 = _mock_tool_call("get_tool_info", "{}", "tc_0")
        tc_1 = _mock_tool_call("get_tool_info", "{}", "tc_1")
        acc_0 = _mock_accumulated(content=None, tool_calls=[tc_0])
        acc_1 = _mock_accumulated(content=None, tool_calls=[tc_1])
        acc_final = _mock_accumulated("Done")
        msgs = [acc_0, acc_1, acc_final]
        captured_tools: list[list] = []
        call_n = {"n": 0}

        async def _stream(model, messages, tools_param, tool_choice, **kw):
            captured_tools.append(list(tools_param) if tools_param else [])
            n = call_n["n"]
            call_n["n"] += 1
            yield msgs[n] if n < len(msgs) else msgs[-1]

        async def _always_activate(tool_name, args_str, **kw):
            lst = current_activated_tools.get()
            if lst is not None:
                lst.append(_NEW_SCHEMA)  # appended every call; dedup must fire in iter 2
            return '{"info": "ok"}'

        bot = _make_bot()
        with patch("app.agent.loop._llm_call_stream", side_effect=_stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", side_effect=_always_activate), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms)
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "test"}],
                bot,
                pre_selected_tools=[_INITIAL_SCHEMA],
            ):
                pass

        assert len(captured_tools) == 3, "expected 3 LLM calls"
        # Iter 1 (second call): dynamic_lookup first merged here
        iter1_names = [t["function"]["name"] for t in captured_tools[1]]
        assert iter1_names.count("dynamic_lookup") == 1
        # Iter 2 (third call): dynamic_lookup is in _existing_names → not re-added, still exactly one
        iter2_names = [t["function"]["name"] for t in captured_tools[2]]
        assert iter2_names.count("dynamic_lookup") == 1, "dedup: existing tool must not be re-added"

    @pytest.mark.asyncio
    async def test_effective_allowed_expanded_for_dispatch(self):
        """After activation, the new tool is added to _effective_allowed so dispatch accepts it."""
        from app.agent.loop import run_agent_tool_loop
        from app.agent.context import current_activated_tools

        # Iter 0: activate dynamic_lookup via get_tool_info
        tc_info = _mock_tool_call("get_tool_info", "{}", "tc_1")
        # Iter 1: invoke dynamic_lookup (now in _effective_allowed)
        tc_dyn = _mock_tool_call("dynamic_lookup", "{}", "tc_2")
        acc_info = _mock_accumulated(content=None, tool_calls=[tc_info])
        acc_dyn = _mock_accumulated(content=None, tool_calls=[tc_dyn])
        acc_final = _mock_accumulated("Done")
        msgs = [acc_info, acc_dyn, acc_final]
        call_n = {"n": 0}

        async def _stream(*args, **kwargs):
            n = call_n["n"]
            call_n["n"] += 1
            yield msgs[n] if n < len(msgs) else msgs[-1]

        dispatched: list[str] = []

        async def _tool_call(tool_name, args_str, **kw):
            dispatched.append(tool_name)
            if tool_name == "get_tool_info":
                lst = current_activated_tools.get()
                if lst is not None:
                    lst.append(_NEW_SCHEMA)
            return '{"ok": true}'

        bot = _make_bot()
        with patch("app.agent.loop._llm_call_stream", side_effect=_stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", side_effect=_tool_call), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms)
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "test"}],
                bot,
                pre_selected_tools=[_INITIAL_SCHEMA],
                authorized_tool_names={"get_tool_info"},
            ):
                pass

        assert "get_tool_info" in dispatched
        assert "dynamic_lookup" in dispatched, "dynamic_lookup must be dispatched after _effective_allowed is expanded"


# ─────────────────────────────────────────────────────────────────────────────
# #5 — in-loop pruning (run_agent_tool_loop lines 528-563)
# ─────────────────────────────────────────────────────────────────────────────

def _prior_iter_messages():
    """Message list that looks like a prior iteration already completed."""
    return [
        {"role": "user", "content": "do multi-step work"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "tc_0", "type": "function",
                "function": {"name": "old_tool", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "tc_0",
            "content": "X" * 300,  # large result, above CONTEXT_PRUNING_MIN_LENGTH=200
        },
    ]


class TestInLoopPruning:
    """Verify the in-loop pruning gate (iteration > 0) and context_pruning event."""

    @staticmethod
    async def _fake_dispatch_iteration_tool_calls(*, accumulated_tool_calls, state, compaction, **kwargs):
        for tc in accumulated_tool_calls:
            state.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": "X" * 300,
            })
            yield {
                "type": "tool_result",
                "tool": tc["function"]["name"],
                "result": '{"ok": true}',
                "tool_call_id": tc["id"],
            }

    @pytest.mark.asyncio
    async def test_pruning_event_emitted_when_enabled(self):
        """context_pruning with scope=in_loop is emitted when IN_LOOP_PRUNING_ENABLED=True."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("step_tool", "{}", "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()
        events = []
        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.dispatch_iteration_tool_calls", self._fake_dispatch_iteration_tool_calls), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms, pruning_enabled=True)
            async for evt in run_agent_tool_loop(
                _prior_iter_messages(),
                bot,
                pre_selected_tools=[{"type": "function", "function": {"name": "step_tool"}}],
            ):
                events.append(evt)

        pruning = [e for e in events if e.get("type") == "context_pruning"]
        assert len(pruning) >= 1, "expected at least one context_pruning event"
        assert pruning[0]["scope"] == "in_loop"
        assert pruning[0]["pruned_count"] > 0

    @pytest.mark.asyncio
    async def test_no_pruning_event_when_disabled(self):
        """No context_pruning event when IN_LOOP_PRUNING_ENABLED=False."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("step_tool", "{}", "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()
        events = []
        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.dispatch_iteration_tool_calls", self._fake_dispatch_iteration_tool_calls), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms, pruning_enabled=False)
            async for evt in run_agent_tool_loop(
                _prior_iter_messages(),
                bot,
                pre_selected_tools=[{"type": "function", "function": {"name": "step_tool"}}],
            ):
                events.append(evt)

        pruning = [e for e in events if e.get("type") == "context_pruning"]
        assert len(pruning) == 0

    @pytest.mark.asyncio
    async def test_pruning_not_fired_on_first_iteration(self):
        """iteration > 0 guard: single-iteration run never emits context_pruning."""
        from app.agent.loop import run_agent_tool_loop

        acc_final = _mock_accumulated("Immediate answer")

        bot = _make_bot()
        events = []
        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms, pruning_enabled=True)
            async for evt in run_agent_tool_loop(
                _prior_iter_messages(),
                bot,
                pre_selected_tools=[{"type": "function", "function": {"name": "step_tool"}}],
            ):
                events.append(evt)

        pruning = [e for e in events if e.get("type") == "context_pruning"]
        assert len(pruning) == 0, "single-iteration run must not emit context_pruning"


class TestContextWindowGuard:
    @pytest.mark.asyncio
    async def test_oversized_prompt_returns_controlled_error_without_llm_call(self):
        """The loop should block locally instead of sending an over-window request."""
        from app.agent.loop import run_agent_tool_loop

        llm = AsyncMock()
        bot = _make_bot(model="gpt-4")
        events = []
        huge_args = '{"payload":"' + ("x" * 40_000) + '"}'
        messages = [
            {"role": "user", "content": "old"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "tc_big",
                    "type": "function",
                    "function": {"name": "big_tool", "arguments": huge_args},
                }],
            },
            {"role": "tool", "tool_call_id": "tc_big", "content": "OK"},
        ]

        with patch("app.agent.loop._llm_call_stream", llm), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.services.providers.resolve_provider_for_model", return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock), \
             patch("app.agent.loop.settings") as ms:
            _base_loop_settings(ms)
            async for evt in run_agent_tool_loop(messages, bot):
                events.append(evt)

        assert llm.await_count == 0
        assert any(e.get("code") == "context_window_exceeded" for e in events)
        response = [e for e in events if e.get("type") == "response"][-1]
        assert "too large" in response["text"]

    def test_image_payload_does_not_trigger_false_context_overflow(self):
        """Regression: base64 image data must not be char-counted as prompt text.

        The pre-LLM guard used to call ``message_prompt_chars`` and divide by 3.5,
        which stringified multimodal parts whole and counted the base64 blob as
        prompt text — a ~200KB image became ~71K "tokens", so any channel with a
        few image uploads tripped ``context_window_exceeded`` before the LLM was
        ever called. Real tokenizers count each image as ~512 tokens.
        """
        from app.agent.loop_helpers import _check_prompt_budget_guard

        bot = _make_bot(model="gpt-4o")
        # Ten ~250KB base64 images — representative of a chat history with
        # repeated screenshot uploads. Raw char count ~2.5MB ≈ 714K "tokens"
        # by the chars/3.5 heuristic; real tokenization counts ~512/image
        # ≈ 5K tokens total, well under a 128K-window budget.
        fake_b64 = "A" * 250_000
        messages = [{"role": "system", "content": "short system prompt"}]
        for i in range(10):
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"screenshot {i}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{fake_b64}"},
                    },
                ],
            })
            messages.append({"role": "assistant", "content": f"looked at {i}"})

        with patch("app.agent.loop_helpers.logger"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.context_budget.get_model_context_window", return_value=128_000), \
             patch("app.config.settings") as ms:
            ms.CONTEXT_BUDGET_RESERVE_RATIO = 0.15
            gate = _check_prompt_budget_guard(
                messages=messages,
                tools_param=None,
                model="gpt-4o",
                effective_provider_id="openai",
                iteration=0,
                correlation_id=None,
                session_id=None,
                bot=bot,
                client_id=None,
                turn_start=0,
                embedded_client_actions=[],
                compaction=False,
            )

        assert gate.should_return is False, (
            "A single 200KB image must not trip the context-window guard — real "
            "tokenization counts it as ~512 tokens, not ~71K. Messages left "
            f"in state: {len(messages)}"
        )
        assert not any(
            e.get("code") == "context_window_exceeded" for e in gate.events
        ), "No context_window_exceeded event should fire for a single image."

    # NOTE: end-to-end tests for profile-level keep_iterations would live here,
    # but the harness used by TestInLoopPruning in this file has a pre-existing
    # circular-import issue (ToolResultEnvelope in app.tools.local.machine_control)
    # that prevents the loop tests from running under unit-test conditions.
    # Coverage is provided by two focused unit tests instead:
    # - tests/unit/test_context_profiles.py::test_task_none_overrides_keep_iterations
    #   confirms the task_none profile carries keep_iterations_override=8.
    # - tests/unit/test_context_pruning.py::TestInLoopPruning::*
    #   confirms prune_in_loop_tool_results honours its keep_iterations arg.
    # The loop wiring (profile → keep_iterations → prune_in_loop_tool_results)
    # is three lines in app/agent/loop.py and is visually auditable.


# ─────────────────────────────────────────────────────────────────────────────
# #30 — run_stream delegation_post ordering (lines 1519-1759)
# ─────────────────────────────────────────────────────────────────────────────

async def _noop_assemble_context(*args, **kwargs):
    return
    yield  # noqa: unreachable — makes this an async generator function


class TestDelegationPostOrdering:
    """Verify outermost run_stream emits delegation_post events before the response."""

    @pytest.mark.asyncio
    async def test_outermost_emits_delegation_post_before_response(self):
        """delegation_post appears before response in the outermost run_stream event stream."""
        from app.agent.loop import run_stream
        from app.agent.context import current_pending_delegation_posts

        async def _mock_loop(*args, **kwargs):
            posts = current_pending_delegation_posts.get()
            if posts is not None:
                posts.append({
                    "bot_id": "helper_bot",
                    "text": "helper says hi",
                    "reply_in_thread": False,
                    "client_actions": [],
                })
            yield {"type": "response", "text": "parent done", "client_actions": []}

        bot = _make_bot()
        events = []
        with patch("app.agent.loop.assemble_context", _noop_assemble_context), \
             patch("app.agent.loop.run_agent_tool_loop", _mock_loop), \
             patch("app.services.usage_limits.check_usage_limits", new_callable=AsyncMock), \
             patch("app.services.reranking.rerank_rag_context", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.set_agent_context"), \
             patch("app.agent.embeddings.clear_embed_cache"), \
             patch("app.agent.loop.settings") as ms:
            ms.CONTEXT_BUDGET_ENABLED = False
            async for evt in run_stream(
                [{"role": "user", "content": "hi"}],
                bot,
                user_message="hi",
            ):
                events.append(evt)

        types = [e["type"] for e in events]
        assert "delegation_post" in types, "delegation_post must be emitted"
        assert "response" in types, "response must be emitted"
        dp_idx = types.index("delegation_post")
        resp_idx = types.index("response")
        assert dp_idx < resp_idx, "delegation_post must precede response"

    @pytest.mark.asyncio
    async def test_nested_run_stream_passes_response_through_directly(self):
        """Nested run_stream (non-outermost) yields response directly without buffering."""
        from app.agent.loop import run_stream
        from app.agent.context import current_pending_delegation_posts

        # Pre-set delegation_posts so _is_outermost_stream = False
        outer_posts: list = []
        token = current_pending_delegation_posts.set(outer_posts)

        async def _mock_loop(*args, **kwargs):
            yield {"type": "response", "text": "nested done", "client_actions": []}

        bot = _make_bot()
        events = []
        try:
            with patch("app.agent.loop.assemble_context", _noop_assemble_context), \
                 patch("app.agent.loop.run_agent_tool_loop", _mock_loop), \
                 patch("app.services.usage_limits.check_usage_limits", new_callable=AsyncMock), \
                 patch("app.services.reranking.rerank_rag_context", new_callable=AsyncMock, return_value=None), \
                 patch("app.agent.loop.set_agent_context"), \
                 patch("app.agent.embeddings.clear_embed_cache"), \
                 patch("app.agent.loop.settings") as ms:
                ms.CONTEXT_BUDGET_ENABLED = False
                async for evt in run_stream(
                    [{"role": "user", "content": "nested call"}],
                    bot,
                    user_message="nested call",
                ):
                    events.append(evt)
        finally:
            current_pending_delegation_posts.reset(token)

        # Nested path emits response directly — no delegation_post wrapper
        types = [e["type"] for e in events]
        assert "response" in types
        assert "delegation_post" not in types, "nested run_stream must not emit delegation_post"

    @pytest.mark.asyncio
    async def test_no_delegation_post_when_queue_empty(self):
        """When run_agent_tool_loop adds nothing to delegation_posts, no delegation_post event."""
        from app.agent.loop import run_stream

        async def _mock_loop(*args, **kwargs):
            # does NOT append to delegation_posts
            yield {"type": "response", "text": "all done", "client_actions": []}

        bot = _make_bot()
        events = []
        with patch("app.agent.loop.assemble_context", _noop_assemble_context), \
             patch("app.agent.loop.run_agent_tool_loop", _mock_loop), \
             patch("app.services.usage_limits.check_usage_limits", new_callable=AsyncMock), \
             patch("app.services.reranking.rerank_rag_context", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.set_agent_context"), \
             patch("app.agent.embeddings.clear_embed_cache"), \
             patch("app.agent.loop.settings") as ms:
            ms.CONTEXT_BUDGET_ENABLED = False
            async for evt in run_stream(
                [{"role": "user", "content": "hi"}],
                bot,
                user_message="hi",
            ):
                events.append(evt)

        types = [e["type"] for e in events]
        assert "response" in types
        assert "delegation_post" not in types
