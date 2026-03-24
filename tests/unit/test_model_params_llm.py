"""Tests for model_params threading through _llm_call and the agent loop."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
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
                 LLM_FALLBACK_MODEL="gpt-4",
             )), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _llm_call(
                "anthropic/claude-3",
                [{"role": "user", "content": "hi"}], None, None,
                model_params={"temperature": 0.7, "frequency_penalty": 0.5},
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

class TestAgentLoopModelParams:
    @pytest.mark.asyncio
    async def test_bot_model_params_passed_to_llm_call(self):
        """run_agent_tool_loop should pass bot.model_params to _llm_call."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("Hello world")
        )
        bot = _make_bot(model_params={"temperature": 0.3, "max_tokens": 2048})

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "response"

        # Check that the API call included our model params
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_bot_without_model_params_sends_no_extras(self):
        """A bot with empty model_params should not inject extra kwargs."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("Hello world")
        )
        bot = _make_bot()  # default: model_params={}

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                pass

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "temperature" not in call_kwargs
        assert "max_tokens" not in call_kwargs

    @pytest.mark.asyncio
    async def test_invalid_params_for_model_stripped_in_loop(self):
        """Bot has frequency_penalty set but model is anthropic — should be stripped before LLM call."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("Hello")
        )
        bot = _make_bot(
            model="anthropic/claude-3-opus",
            model_params={
                "temperature": 0.4,
                "frequency_penalty": 1.0,  # not supported by anthropic
                "presence_penalty": 0.5,   # not supported by anthropic
            },
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hello"}], bot
            ):
                events.append(event)

        # Should still get a response (no crash)
        assert any(e["type"] == "response" for e in events)

        # Verify the unsupported params were stripped
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.4
        assert "frequency_penalty" not in call_kwargs
        assert "presence_penalty" not in call_kwargs

    @pytest.mark.asyncio
    async def test_params_persist_across_tool_loop_iterations(self):
        """Model params should be sent on every LLM call in a multi-iteration tool loop."""
        from app.agent.loop import run_agent_tool_loop

        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "test_tool"
        tc.function.arguments = "{}"

        resp1 = _mock_response(content=None, tool_calls=[tc])
        resp2 = _mock_response("done")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        bot = _make_bot(
            local_tools=["test_tool"],
            model_params={"temperature": 0.1},
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "do it"}], bot
            ):
                events.append(event)

        # Should have 2 LLM calls (tool call + final response)
        assert mock_client.chat.completions.create.await_count == 2
        # Both should have temperature=0.1
        for call in mock_client.chat.completions.create.call_args_list:
            assert call.kwargs["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_junk_params_never_reach_api(self):
        """If someone puts garbage keys in model_params, they should be silently stripped."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("ok")
        )
        bot = _make_bot(
            model_params={
                "temperature": 0.5,
                "top_p": 0.9,            # excluded by design
                "top_k": 40,             # excluded by design
                "bogus_setting": True,   # total garbage
            },
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            async for _ in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                pass

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert "top_p" not in call_kwargs
        assert "top_k" not in call_kwargs
        assert "bogus_setting" not in call_kwargs
