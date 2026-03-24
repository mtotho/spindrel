"""Tests for context compression integration in app.agent.loop.run_stream().

These test the message restoration contract: after run_stream() with compression
active, messages = original full history + new turn messages.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.context import current_compression_history
from app.agent.context_assembly import AssemblyResult


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        compression_config={},
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


async def _fake_assemble_context(**kw):
    """Async generator that yields nothing and populates result."""
    return
    yield  # pragma: no cover


def _patch_stack():
    """Return patch context managers for run_stream dependencies."""
    # assemble_context is an async generator yielding events
    async def fake_assemble(*a, **kw):
        return
        yield  # async generator that yields nothing

    return {
        "assemble": patch("app.agent.loop.assemble_context", fake_assemble),
        "tool_schemas": patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
        "trace": patch("app.agent.loop._record_trace_event", new_callable=AsyncMock),
        # compress_context is imported inside run_stream from app.services.compression
        "compress": patch("app.services.compression.compress_context"),
        # run_agent_tool_loop needs to be patched
        "loop": patch("app.agent.loop.run_agent_tool_loop"),
    }


# ---------------------------------------------------------------------------
# Message restoration after compression
# ---------------------------------------------------------------------------

class TestCompressionMessageRestoration:

    @pytest.mark.asyncio
    async def test_messages_restored_after_compressed_run(self):
        """After run_stream with compression active, messages = original + new turn."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        original_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "msg1 " + "x" * 300},
            {"role": "assistant", "content": "resp1 " + "y" * 300},
            {"role": "user", "content": "Current question"},
        ]
        messages = list(original_messages)
        original_len = len(messages)

        compressed_msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "system", "content": "[Compressed summary]"},
            {"role": "user", "content": "Current question"},
        ]
        drilldown = [{"role": "user", "content": "msg1"}, {"role": "assistant", "content": "resp1"}]

        async def fake_tool_loop(msgs, *a, **kw):
            msgs.append({"role": "assistant", "content": "Compressed response"})
            yield {"type": "response", "content": "Compressed response"}

        p = _patch_stack()

        with p["assemble"], p["tool_schemas"], p["trace"], p["compress"] as mock_compress, p["loop"] as mock_loop:
            mock_compress.return_value = (compressed_msgs, drilldown)
            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(messages, bot, "Current question", session_id=uuid.uuid4()):
                events.append(event)

        # Original messages preserved + new assistant message appended
        assert len(messages) == original_len + 1
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "Compressed response"
        for i, orig in enumerate(original_messages):
            assert messages[i]["content"] == orig["content"]

    @pytest.mark.asyncio
    async def test_context_compressed_event_emitted(self):
        """run_stream should yield a context_compressed event."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "msg " + "x" * 500},
            {"role": "assistant", "content": "resp " + "y" * 500},
            {"role": "user", "content": "question"},
        ]

        compressed_msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "system", "content": "[Summary]"},
            {"role": "user", "content": "question"},
        ]

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with p["assemble"], p["tool_schemas"], p["trace"], p["compress"] as mock_compress, p["loop"] as mock_loop:
            mock_compress.return_value = (compressed_msgs, [])
            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(messages, bot, "question", session_id=uuid.uuid4()):
                events.append(event)

        event_types = [e.get("type") for e in events]
        assert "context_compressed" in event_types
        comp_event = next(e for e in events if e.get("type") == "context_compressed")
        assert "original_chars" in comp_event
        assert "compressed_chars" in comp_event
        assert comp_event["compressed_chars"] < comp_event["original_chars"]

    @pytest.mark.asyncio
    async def test_no_compression_passes_through(self):
        """When compress_context returns None, messages pass through unchanged."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "short question"},
        ]
        original_len = len(messages)

        async def fake_tool_loop(msgs, *a, **kw):
            msgs.append({"role": "assistant", "content": "reply"})
            yield {"type": "response", "content": "reply"}

        p = _patch_stack()
        with p["assemble"], p["tool_schemas"], p["trace"], p["compress"] as mock_compress, p["loop"] as mock_loop:
            mock_compress.return_value = None
            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(messages, bot, "short question", session_id=uuid.uuid4()):
                events.append(event)

        event_types = [e.get("type") for e in events]
        assert "context_compressed" not in event_types
        assert len(messages) == original_len + 1
        assert messages[-1]["content"] == "reply"

    @pytest.mark.asyncio
    async def test_compressed_messages_passed_to_tool_loop(self):
        """run_agent_tool_loop receives the compressed messages, not originals."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "msg1 " + "x" * 300},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "question"},
        ]

        compressed_msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "system", "content": "[Summary]"},
            {"role": "user", "content": "question"},
        ]

        received_msgs = []

        async def fake_tool_loop(msgs, *a, **kw):
            received_msgs.extend(msgs)
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with p["assemble"], p["tool_schemas"], p["trace"], p["compress"] as mock_compress, p["loop"] as mock_loop:
            mock_compress.return_value = (compressed_msgs, [])
            mock_loop.side_effect = fake_tool_loop

            async for _ in run_stream(messages, bot, "question", session_id=uuid.uuid4()):
                pass

        # The tool loop should receive the compressed messages
        assert len(received_msgs) == 3
        assert received_msgs[1]["content"] == "[Summary]"


# ---------------------------------------------------------------------------
# ContextVar lifecycle
# ---------------------------------------------------------------------------

class TestCompressionContextVar:
    @pytest.mark.asyncio
    async def test_contextvar_cleared_after_run(self):
        """current_compression_history should be None after run_stream completes."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "question"},
        ]

        compressed_msgs = [
            {"role": "system", "content": "prompt"},
            {"role": "system", "content": "[Summary]"},
            {"role": "user", "content": "question"},
        ]
        drilldown = [{"role": "user", "content": "old msg"}]

        async def fake_tool_loop(msgs, *a, **kw):
            # During the loop, the ContextVar should be set
            assert current_compression_history.get() is not None
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with p["assemble"], p["tool_schemas"], p["trace"], p["compress"] as mock_compress, p["loop"] as mock_loop:
            mock_compress.return_value = (compressed_msgs, drilldown)
            mock_loop.side_effect = fake_tool_loop

            async for _ in run_stream(messages, bot, "question", session_id=uuid.uuid4()):
                pass

        # After completion, ContextVar should be cleared
        assert current_compression_history.get() is None
