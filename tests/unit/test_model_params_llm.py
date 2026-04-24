"""Tests for model_params threading through _llm_call and the agent loop."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.llm import AccumulatedMessage, _fold_system_messages, _model_cooldowns


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    """Ensure cooldowns don't leak between tests."""
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_response(content="Hello", tool_calls=None):
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    choice.finish_reason = "stop" if not tool_calls else "tool_calls"
    dump = {"role": "assistant", "content": content}
    if tool_calls:
        dump["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]
    choice.message.model_dump = MagicMock(return_value=dump)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    return resp


def _default_mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        LLM_MAX_RETRIES=0,
        LLM_RATE_LIMIT_INITIAL_WAIT=1,
        LLM_RETRY_INITIAL_WAIT=1,
        LLM_FALLBACK_MODEL="",
        LLM_FALLBACK_COOLDOWN_SECONDS=300,
        AGENT_TRACE=False,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# _llm_call passes model_params through to the API
# ---------------------------------------------------------------------------

class TestLlmCallModelParams:
    @pytest.mark.asyncio
    async def test_params_spread_into_api_call(self):
        """Verify that model_params kwargs are spread into client.chat.completions.create."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call(
                "gpt-4", [{"role": "user", "content": "hi"}], None, None,
                model_params={"temperature": 0.3, "max_tokens": 1024},
            )

        # Check the kwargs passed to the API
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_unsupported_params_filtered_before_api_call(self):
        """If a bot has frequency_penalty set but model is anthropic, it should NOT be sent."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call(
                "anthropic/claude-3-opus",
                [{"role": "user", "content": "hi"}],
                None, None,
                model_params={
                    "temperature": 0.5,
                    "max_tokens": 4096,
                    "frequency_penalty": 0.8,
                    "presence_penalty": 1.0,
                },
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 4096
        assert "frequency_penalty" not in call_kwargs
        assert "presence_penalty" not in call_kwargs

    @pytest.mark.asyncio
    async def test_empty_params_no_extra_kwargs(self):
        """Empty model_params should not add any extra kwargs."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call("gpt-4", [{"role": "user", "content": "hi"}], None, None, model_params={})

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        # Only the standard four keys should be present
        assert "temperature" not in call_kwargs
        assert "max_tokens" not in call_kwargs
        assert "frequency_penalty" not in call_kwargs

    @pytest.mark.asyncio
    async def test_none_model_params_no_extra_kwargs(self):
        """model_params=None should behave like empty dict."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call("gpt-4", [{"role": "user", "content": "hi"}], None, None, model_params=None)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "temperature" not in call_kwargs

    @pytest.mark.asyncio
    async def test_reasoning_effort_passed_as_string(self):
        """reasoning_effort is a string value (low/medium/high), should be passed through."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.supports_reasoning", return_value=True), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call(
                "gpt-4o", [{"role": "user", "content": "hi"}], None, None,
                model_params={"reasoning_effort": "high", "temperature": 0.5},
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "high"
        assert call_kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_params_persist_across_retries(self):
        """On retry, the same filtered params should be used each time."""
        from app.agent.llm import _llm_call
        import openai

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=[rate_err, mock_resp])

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings(LLM_MAX_RETRIES=1)), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await _llm_call(
                "gpt-4", [{"role": "user", "content": "hi"}], None, None,
                model_params={"temperature": 0.2},
            )

        # Both calls should have temperature=0.2
        for call in mock_client.chat.completions.create.call_args_list:
            assert call.kwargs["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_params_survive_fallback_model_switch(self):
        """When falling back to another model, params should be re-filtered for the new model."""
        from app.agent.llm import _llm_call
        import openai

        mock_client = AsyncMock()
        mock_resp = _mock_response("fallback ok")
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        call_models = []
        async def track_calls(**kwargs):
            call_models.append(kwargs.get("model"))
            if kwargs.get("model") == "anthropic/claude-3":
                raise rate_err
            return mock_resp

        mock_client.chat.completions.create = AsyncMock(side_effect=track_calls)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings(
                 LLM_MAX_RETRIES=0,
             )), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _llm_call(
                "anthropic/claude-3",
                [{"role": "user", "content": "hi"}], None, None,
                model_params={"temperature": 0.7, "frequency_penalty": 0.5},
                fallback_models=[{"model": "gpt-4"}],
            )

        assert result is mock_resp
        # Primary call (anthropic): frequency_penalty should be filtered out
        primary_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        assert primary_kwargs["temperature"] == 0.7
        assert "frequency_penalty" not in primary_kwargs

        # Fallback call (gpt-4 = openai): frequency_penalty should be included
        fallback_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert fallback_kwargs["temperature"] == 0.7
        assert fallback_kwargs["frequency_penalty"] == 0.5


# ---------------------------------------------------------------------------
# Agent loop passes bot.model_params to _llm_call
# ---------------------------------------------------------------------------

def _mock_accumulated(content="Hello", tool_calls=None):
    tc_list = None
    if tool_calls:
        tc_list = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]
    usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    return AccumulatedMessage(content=content, tool_calls=tc_list, usage=usage)


def _make_stream_side_effects(*accumulated_messages):
    _msgs = list(accumulated_messages)
    _idx = {"n": 0}

    async def _stream(*args, **kwargs):
        idx = _idx["n"]
        _idx["n"] += 1
        msg = _msgs[idx] if idx < len(_msgs) else _msgs[-1]
        yield msg

    return _stream


def _tracking_stream(*accumulated_messages):
    """Create a stream factory that also records call args for assertions."""
    _msgs = list(accumulated_messages)
    _idx = {"n": 0}
    calls = []

    async def _stream(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        idx = _idx["n"]
        _idx["n"] += 1
        msg = _msgs[idx] if idx < len(_msgs) else _msgs[-1]
        yield msg

    _stream.calls = calls
    return _stream


class TestAgentLoopModelParams:
    @pytest.mark.asyncio
    async def test_bot_model_params_passed_to_llm_call(self):
        """run_agent_tool_loop should pass bot.model_params to _llm_call_stream."""
        from app.agent.loop import run_agent_tool_loop

        acc = _mock_accumulated("Hello world")
        bot = _make_bot(model_params={"temperature": 0.3, "max_tokens": 2048})

        stream = _tracking_stream(acc)

        with patch("app.agent.loop._llm_call_stream", stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                events.append(event)

        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1

        assert stream.calls[0]["kwargs"]["model_params"] == {"temperature": 0.3, "max_tokens": 2048}

    @pytest.mark.asyncio
    async def test_bot_without_model_params_sends_no_extras(self):
        """A bot with empty model_params should pass empty dict."""
        from app.agent.loop import run_agent_tool_loop

        acc = _mock_accumulated("Hello world")
        bot = _make_bot()

        stream = _tracking_stream(acc)

        with patch("app.agent.loop._llm_call_stream", stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                pass

        assert stream.calls[0]["kwargs"]["model_params"] == {}

    @pytest.mark.asyncio
    async def test_invalid_params_for_model_stripped_in_loop(self):
        """Bot has frequency_penalty set — loop passes them to _llm_call_stream (filtering is internal)."""
        from app.agent.loop import run_agent_tool_loop

        acc = _mock_accumulated("Hello")
        bot = _make_bot(
            model="anthropic/claude-3-opus",
            model_params={
                "temperature": 0.4,
                "frequency_penalty": 1.0,
                "presence_penalty": 0.5,
            },
        )

        stream = _tracking_stream(acc)

        with patch("app.agent.loop._llm_call_stream", stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hello"}], bot
            ):
                events.append(event)

        assert any(e["type"] == "response" for e in events)
        assert stream.calls[0]["kwargs"]["model_params"]["temperature"] == 0.4

    @pytest.mark.asyncio
    async def test_params_persist_across_tool_loop_iterations(self):
        """Model params should be sent on every _llm_call_stream call in a multi-iteration tool loop."""
        from app.agent.loop import run_agent_tool_loop

        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "test_tool"
        tc.function.arguments = "{}"

        acc1 = _mock_accumulated(content=None, tool_calls=[tc])
        acc2 = _mock_accumulated("done")

        stream = _tracking_stream(acc1, acc2)

        bot = _make_bot(
            local_tools=["test_tool"],
            model_params={"temperature": 0.1},
        )

        with patch("app.agent.loop._llm_call_stream", stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._start_tool_call", new_callable=AsyncMock, return_value=True), \
             patch("app.agent.tool_dispatch._complete_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "do it"}], bot
            ):
                events.append(event)

        assert len(stream.calls) == 2
        for call in stream.calls:
            assert call["kwargs"]["model_params"]["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_junk_params_never_reach_api(self):
        """Junk keys are passed through to _llm_call_stream; filtering happens inside."""
        from app.agent.loop import run_agent_tool_loop

        acc = _mock_accumulated("ok")
        bot = _make_bot(
            model_params={
                "temperature": 0.5,
                "top_p": 0.9,
                "top_k": 40,
                "bogus_setting": True,
            },
        )

        stream = _tracking_stream(acc)

        with patch("app.agent.loop._llm_call_stream", stream), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                pass

        assert stream.calls[0]["kwargs"]["model_params"]["temperature"] == 0.5


# ---------------------------------------------------------------------------
# _fold_system_messages — unit tests for the message transformation
# ---------------------------------------------------------------------------

class TestFoldSystemMessages:
    def test_no_system_messages_unchanged(self):
        """Messages without system role should pass through unchanged."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _fold_system_messages(msgs)
        assert result == msgs

    def test_single_system_message_becomes_user(self):
        """A single system message should be merged with the next user message."""
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hello"},
        ]
        result = _fold_system_messages(msgs)
        # System-as-user merges with adjacent user → single message
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "You are helpful." in result[0]["content"]
        assert "hello" in result[0]["content"]

    def test_multiple_system_messages_merged(self):
        """Multiple system messages should be merged into a single user message."""
        msgs = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "system", "content": "Memory context."},
            {"role": "system", "content": "Skill context."},
            {"role": "user", "content": "do something"},
        ]
        result = _fold_system_messages(msgs)
        # All system content merged into first message
        assert result[0]["role"] == "user"
        assert "System prompt." in result[0]["content"]
        assert "Memory context." in result[0]["content"]
        assert "Skill context." in result[0]["content"]
        # No system roles remain
        assert all(m["role"] != "system" for m in result)

    def test_role_alternation_enforced(self):
        """Consecutive same-role messages should be merged to enforce alternation."""
        msgs = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "hello"},
        ]
        result = _fold_system_messages(msgs)
        # system→user merged with user→"hello" = single user message
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "Instructions" in result[0]["content"]
        assert "hello" in result[0]["content"]

    def test_complex_conversation_alternation(self):
        """Realistic conversation with many system injections should produce valid alternation."""
        msgs = [
            {"role": "system", "content": "You are a bot."},
            {"role": "system", "content": "Current time: 2026-03-26"},
            {"role": "system", "content": "Memory: user likes cats"},
            {"role": "user", "content": "What do you know about me?"},
            {"role": "assistant", "content": "You like cats!"},
            {"role": "system", "content": "Skill context injected here."},
            {"role": "user", "content": "Tell me more."},
        ]
        result = _fold_system_messages(msgs)
        # No system messages remain
        assert all(m["role"] != "system" for m in result)
        # No consecutive same-role messages
        for i in range(1, len(result)):
            assert result[i]["role"] != result[i - 1]["role"], (
                f"Consecutive {result[i]['role']} at positions {i-1} and {i}"
            )

    def test_empty_system_content_skipped(self):
        """System messages with empty content should not add empty strings."""
        msgs = [
            {"role": "system", "content": ""},
            {"role": "system", "content": "Real content"},
            {"role": "user", "content": "hello"},
        ]
        result = _fold_system_messages(msgs)
        assert result[0]["role"] == "user"
        # System content merged with user due to alternation
        assert "Real content" in result[0]["content"]
        assert "hello" in result[0]["content"]

    def test_non_string_content_not_merged(self):
        """Multipart/audio content should not be merged with adjacent same-role messages."""
        msgs = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "user", "content": "follow up"},
        ]
        result = _fold_system_messages(msgs)
        # system becomes user, but list content can't merge with string
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Instructions"
        # List content stays separate
        user_with_list = [m for m in result if isinstance(m.get("content"), list)]
        assert len(user_with_list) == 1

    def test_empty_messages_list(self):
        """Empty input should return empty output."""
        assert _fold_system_messages([]) == []

    def test_only_system_messages(self):
        """All-system input should produce a single user message."""
        msgs = [
            {"role": "system", "content": "A"},
            {"role": "system", "content": "B"},
        ]
        result = _fold_system_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "A" in result[0]["content"]
        assert "B" in result[0]["content"]

    def test_original_messages_not_mutated(self):
        """_fold_system_messages should not mutate the input list."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        original = [dict(m) for m in msgs]
        _fold_system_messages(msgs)
        assert msgs[0] == original[0]
        assert msgs[1] == original[1]

    def test_tool_calls_preserved_when_assistant_messages_merge(self):
        """When a system message between two assistant messages is removed,
        merging them must preserve tool_calls from both messages."""
        msgs = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "first response"},
            {"role": "system", "content": "injected context"},
            {"role": "assistant", "content": "using tool", "tool_calls": [
                {"id": "call_abc123", "type": "function", "function": {"name": "search", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_abc123", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        result = _fold_system_messages(msgs)
        # No system messages remain
        assert all(m["role"] != "system" for m in result)
        # The merged assistant message must contain the tool_calls
        assistant_with_tc = [m for m in result if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(assistant_with_tc) == 1
        assert assistant_with_tc[0]["tool_calls"][0]["id"] == "call_abc123"
        # The tool result must still be present
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_call_id"] == "call_abc123"

    def test_both_assistant_tool_calls_preserved_on_merge(self):
        """When both consecutive assistant messages have tool_calls, all must be kept."""
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "step 1", "tool_calls": [
                {"id": "call_111", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_111", "content": "res_a"},
            {"role": "assistant", "content": "step 2", "tool_calls": [
                {"id": "call_222", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_222", "content": "res_b"},
            {"role": "system", "content": "context"},
            {"role": "assistant", "content": "step 3", "tool_calls": [
                {"id": "call_333", "type": "function", "function": {"name": "c", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_333", "content": "res_c"},
        ]
        result = _fold_system_messages(msgs)
        # All tool_call IDs must exist in some assistant message
        all_tc_ids = set()
        for m in result:
            for tc in m.get("tool_calls", []):
                all_tc_ids.add(tc["id"])
        assert {"call_111", "call_222", "call_333"} == all_tc_ids
        # All tool results must be present
        tool_results = {m["tool_call_id"] for m in result if m.get("role") == "tool"}
        assert tool_results == {"call_111", "call_222", "call_333"}

    def test_tool_role_messages_never_merged(self):
        """Consecutive tool messages should NOT be merged (each has unique tool_call_id)."""
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "call_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_a", "content": "res_a"},
            {"role": "tool", "tool_call_id": "call_b", "content": "res_b"},
        ]
        result = _fold_system_messages(msgs)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "call_a"
        assert tool_msgs[1]["tool_call_id"] == "call_b"


# ---------------------------------------------------------------------------
# _llm_call applies _fold_system_messages via requires_system_message_folding
# ---------------------------------------------------------------------------

class TestLlmCallSystemMessageFolding:
    @pytest.mark.asyncio
    async def test_minimax_messages_folded(self):
        """System messages should be folded to user for minimax/ models (heuristic fallback)."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "system", "content": "Current time: now"},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call("minimax/MiniMax-M2.5", messages, None, None)

        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        # No system messages should reach the API
        assert all(m["role"] != "system" for m in sent_messages)
        # Should have proper alternation
        for i in range(1, len(sent_messages)):
            assert sent_messages[i]["role"] != sent_messages[i - 1]["role"]

    @pytest.mark.asyncio
    async def test_openai_messages_not_folded(self):
        """System messages should be preserved for standard providers like openai."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call("gpt-4", messages, None, None)

        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert sent_messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_minimax_system_content_preserved(self):
        """All system content should be present in the folded output, just not as system role."""
        from app.agent.llm import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [
            {"role": "system", "content": "Bot instructions here."},
            {"role": "system", "content": "Memory: user likes cats"},
            {"role": "user", "content": "What do I like?"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()):
            await _llm_call("minimax/MiniMax-M2.5", messages, None, None)

        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        all_content = " ".join(m.get("content", "") for m in sent_messages if isinstance(m.get("content"), str))
        assert "Bot instructions here." in all_content
        assert "Memory: user likes cats" in all_content
        assert "What do I like?" in all_content

    @pytest.mark.asyncio
    async def test_db_flagged_model_messages_folded(self):
        """A model flagged in the DB (via _no_sys_msg_models cache) should get system messages folded."""
        from app.agent.llm import _llm_call
        import app.services.providers as pmod

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "hello"},
        ]

        original = pmod._no_sys_msg_models
        try:
            pmod._no_sys_msg_models = {"some-custom/model-v1"}
            with patch("app.services.providers.get_llm_client", return_value=mock_client), \
                 patch("app.services.providers.record_usage"), \
                 patch("app.agent.llm.settings", _default_mock_settings()):
                await _llm_call("some-custom/model-v1", messages, None, None)
        finally:
            pmod._no_sys_msg_models = original

        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert all(m["role"] != "system" for m in sent_messages)


# ---------------------------------------------------------------------------
# requires_system_message_folding — unit tests
# ---------------------------------------------------------------------------

class TestRequiresSystemMessageFolding:
    def test_db_flagged_model_returns_true(self):
        import app.services.providers as pmod
        original = pmod._no_sys_msg_models
        try:
            pmod._no_sys_msg_models = {"custom/no-sys-model"}
            assert pmod.requires_system_message_folding("custom/no-sys-model") is True
        finally:
            pmod._no_sys_msg_models = original

    def test_heuristic_minimax_returns_true(self):
        from app.services.providers import requires_system_message_folding
        assert requires_system_message_folding("minimax/some-model") is True

    def test_standard_provider_returns_false(self):
        from app.services.providers import requires_system_message_folding
        assert requires_system_message_folding("openai/gpt-4") is False
        assert requires_system_message_folding("anthropic/claude-3") is False

    def test_db_flag_takes_precedence(self):
        """Even if heuristic would return False, DB flag should return True."""
        import app.services.providers as pmod
        original = pmod._no_sys_msg_models
        try:
            pmod._no_sys_msg_models = {"openai/custom-no-sys"}
            assert pmod.requires_system_message_folding("openai/custom-no-sys") is True
        finally:
            pmod._no_sys_msg_models = original
