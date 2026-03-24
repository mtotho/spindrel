"""Tests for app.tools.local.compression_history — get_message_detail tool."""
import json
import uuid

import pytest

from app.agent.context import current_session_id, set_compression_history
from app.tools.local.compression_history import get_message_detail, _format_detail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SESSION_ID = uuid.uuid4()


def _history() -> list[dict]:
    return [
        {"role": "user", "content": "How do I configure webhooks?"},
        {"role": "assistant", "content": "You can set it up in settings."},
        {"role": "user", "content": "What about authentication?"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "tc1", "type": "function",
            "function": {"name": "search_docs", "arguments": '{"q": "webhook auth"}'},
        }]},
        {"role": "tool", "tool_call_id": "tc1", "content": "Found: webhook auth uses Bearer tokens."},
        {"role": "assistant", "content": "Webhook auth uses Bearer tokens. Here's how..."},
        {"role": "user", "content": "Can you show me a code example?"},
        {"role": "assistant", "content": "Sure, here's a Python example:\n```python\nimport requests\n```"},
    ]


@pytest.fixture(autouse=True)
def _reset_context():
    """Set session_id ContextVar and clean up compression history."""
    token = current_session_id.set(TEST_SESSION_ID)
    yield
    set_compression_history(TEST_SESSION_ID, None)
    current_session_id.reset(token)


# ---------------------------------------------------------------------------
# _format_detail
# ---------------------------------------------------------------------------

class TestFormatDetail:
    def test_user_message(self):
        msg = {"role": "user", "content": "Hello world"}
        result = _format_detail(0, msg)
        assert "[msg:0] user:" in result
        assert "Hello world" in result

    def test_assistant_with_tool_calls(self):
        msg = {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "web_search", "arguments": '{"q": "test"}'}}],
        }
        result = _format_detail(3, msg)
        assert "[msg:3] assistant:" in result
        assert "web_search" in result

    def test_tool_message_includes_call_id(self):
        msg = {"role": "tool", "tool_call_id": "tc_abc", "content": "Result data"}
        result = _format_detail(5, msg)
        assert "tc_abc" in result
        assert "Result data" in result


# ---------------------------------------------------------------------------
# get_message_detail — no context
# ---------------------------------------------------------------------------

class TestGetMessageDetailNoContext:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_history(self):
        result = await get_message_detail(start_index=0)
        data = json.loads(result)
        assert "error" in data
        assert "not active" in data["error"]


# ---------------------------------------------------------------------------
# get_message_detail — index-based retrieval
# ---------------------------------------------------------------------------

class TestGetMessageDetailByIndex:
    @pytest.fixture(autouse=True)
    def _set_history(self):
        set_compression_history(TEST_SESSION_ID, _history())
        yield
        set_compression_history(TEST_SESSION_ID, None)

    @pytest.mark.asyncio
    async def test_single_message(self):
        result = await get_message_detail(start_index=0)
        assert "[msg:0]" in result
        assert "webhooks" in result

    @pytest.mark.asyncio
    async def test_range_of_messages(self):
        result = await get_message_detail(start_index=0, end_index=2)
        assert "[msg:0]" in result
        assert "[msg:1]" in result
        assert "[msg:2]" in result

    @pytest.mark.asyncio
    async def test_end_index_defaults_to_start(self):
        result = await get_message_detail(start_index=5)
        assert "[msg:5]" in result
        assert "[msg:4]" not in result
        assert "[msg:6]" not in result

    @pytest.mark.asyncio
    async def test_clamps_to_valid_range(self):
        result = await get_message_detail(start_index=-5, end_index=100)
        assert "[msg:0]" in result

    @pytest.mark.asyncio
    async def test_max_20_messages(self):
        big_history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        set_compression_history(TEST_SESSION_ID, big_history)
        result = await get_message_detail(start_index=0, end_index=49)
        assert "[msg:19]" in result
        assert "[msg:20]" not in result

    @pytest.mark.asyncio
    async def test_out_of_range_returns_error(self):
        result = await get_message_detail(start_index=100, end_index=105)
        data = json.loads(result)
        assert "error" in data
        assert "out of range" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_no_params_returns_error(self):
        result = await get_message_detail()
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# get_message_detail — keyword search
# ---------------------------------------------------------------------------

class TestGetMessageDetailByQuery:
    @pytest.fixture(autouse=True)
    def _set_history(self):
        set_compression_history(TEST_SESSION_ID, _history())
        yield
        set_compression_history(TEST_SESSION_ID, None)

    @pytest.mark.asyncio
    async def test_keyword_match(self):
        result = await get_message_detail(query="Bearer")
        assert "[msg:4]" in result or "[msg:5]" in result
        assert "Bearer" in result

    @pytest.mark.asyncio
    async def test_keyword_case_insensitive(self):
        result = await get_message_detail(query="bearer")
        assert "Bearer" in result

    @pytest.mark.asyncio
    async def test_keyword_no_match(self):
        result = await get_message_detail(query="nonexistent_xyz")
        data = json.loads(result)
        assert "No messages matching" in data["result"]

    @pytest.mark.asyncio
    async def test_keyword_matches_tool_call_name(self):
        result = await get_message_detail(query="search_docs")
        assert "search_docs" in result

    @pytest.mark.asyncio
    async def test_keyword_max_20_results(self):
        big_history = [{"role": "user", "content": f"matching word {i}"} for i in range(50)]
        set_compression_history(TEST_SESSION_ID, big_history)
        result = await get_message_detail(query="matching")
        import re
        matches = re.findall(r"\[msg:\d+\]", result)
        assert len(matches) <= 20
