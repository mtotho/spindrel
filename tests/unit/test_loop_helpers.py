"""Unit tests for pure helpers in app.agent.loop."""
from app.agent.loop import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES, _sanitize_messages


class TestClassifySysMsg:
    def test_all_known_prefixes(self):
        for prefix, expected_label in _SYS_MSG_PREFIXES:
            content = prefix + " some extra content"
            assert _CLASSIFY_SYS_MSG(content) == expected_label, (
                f"Failed for prefix {prefix!r}: expected {expected_label!r}"
            )

    def test_unknown_prefix(self):
        assert _CLASSIFY_SYS_MSG("Something unknown here") == "sys:system_prompt"

    def test_exact_prefix_match(self):
        assert _CLASSIFY_SYS_MSG("Current time: 2024-01-01") == "sys:datetime"

    def test_memory(self):
        assert _CLASSIFY_SYS_MSG("Relevant memories from past conversations...") == "sys:memory"

    def test_tool_index(self):
        assert _CLASSIFY_SYS_MSG("Available tools (not yet loaded — use get_tool_info") == "sys:tool_index"


class TestSanitizeMessages:
    """_sanitize_messages must return the SAME list object so callers
    holding a reference to the original list see appended messages."""

    def test_returns_same_list_object(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _sanitize_messages(msgs)
        assert result is msgs, "must return the same list, not a copy"

    def test_fixes_null_content_in_place(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None},
            {"role": "tool"},
        ]
        original_id = id(msgs)
        result = _sanitize_messages(msgs)
        assert id(result) == original_id
        assert result[0]["content"] == "hello"
        assert result[1]["content"] == ""
        assert result[2]["content"] == ""

    def test_appends_visible_to_original_reference(self):
        """Simulates the persist_turn bug: caller holds original ref,
        _sanitize_messages must not break the chain."""
        original = [{"role": "system", "content": "prompt"}]
        # Simulate what run_agent_tool_loop does:
        messages = _sanitize_messages(original)
        messages.append({"role": "assistant", "content": "response"})
        # The original reference must see the appended message
        assert len(original) == 2
        assert original[-1]["role"] == "assistant"
