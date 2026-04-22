"""Unit tests for pure helpers in app.agent.loop."""
from app.agent.context import task_creation_count
from app.agent.loop import (
    _CLASSIFY_SYS_MSG,
    _EMPTY_RESPONSE_GENERIC_FALLBACK,
    _SYS_MSG_PREFIXES,
    _append_transcript_text_entry,
    _append_transcript_tool_entry,
    _collapse_final_assistant_tool_turn,
    _sanitize_messages,
    _synthesize_empty_response_fallback,
)


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


class TestTaskCreationCountContextVar:
    """task_creation_count must be accessible and trackable for pending_tasks events."""

    def test_defaults_to_zero(self):
        assert task_creation_count.get(0) == 0

    def test_increment_and_read(self):
        token = task_creation_count.set(0)
        try:
            task_creation_count.set(task_creation_count.get() + 1)
            task_creation_count.set(task_creation_count.get() + 1)
            assert task_creation_count.get() == 2
        finally:
            task_creation_count.reset(token)


class TestTranscriptEntryHelpers:
    def test_append_text_merges_adjacent_entries(self):
        entries = [{"id": "text:1", "kind": "text", "text": "Hello"}]

        _append_transcript_text_entry(entries, " world")

        assert entries == [{"id": "text:1", "kind": "text", "text": "Hello world"}]

    def test_append_tool_then_text_creates_distinct_entries(self):
        entries: list[dict] = []

        _append_transcript_tool_entry(entries, "call-1")
        _append_transcript_text_entry(entries, "Done.")

        assert entries == [
            {"id": "tool:call-1", "kind": "tool_call", "toolCallId": "call-1"},
            {"id": "text:2", "kind": "text", "text": "Done."},
        ]

    def test_collapse_final_assistant_tool_turn_hides_intermediate_rows_and_merges_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": "First file edit.",
                "tool_calls": [
                    {"id": "call-1", "function": {"name": "file", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "Edited file"},
            {
                "role": "assistant",
                "content": "Done.",
                "_transcript_entries": [
                    {"id": "text:1", "kind": "text", "text": "First file edit."},
                    {"id": "tool:call-1", "kind": "tool_call", "toolCallId": "call-1"},
                    {"id": "text:2", "kind": "text", "text": "Done."},
                ],
            },
        ]

        _collapse_final_assistant_tool_turn(messages)

        assert messages[0]["_hidden"] is True
        assert messages[2]["tool_calls"] == [
            {"id": "call-1", "function": {"name": "file", "arguments": "{}"}},
        ]

    def test_pending_tasks_event_emitted_when_count_positive(self):
        """Simulate the logic in run_stream: emit pending_tasks when count > 0."""
        token = task_creation_count.set(3)
        try:
            pending = task_creation_count.get(0)
            events = []
            if pending > 0:
                events.append({"type": "pending_tasks", "count": pending})
            assert len(events) == 1
            assert events[0] == {"type": "pending_tasks", "count": 3}
        finally:
            task_creation_count.reset(token)

    def test_no_event_when_count_zero(self):
        """No pending_tasks event when no tasks were created."""
        token = task_creation_count.set(0)
        try:
            pending = task_creation_count.get(0)
            events = []
            if pending > 0:
                events.append({"type": "pending_tasks", "count": pending})
            assert len(events) == 0
        finally:
            task_creation_count.reset(token)


class TestSynthesizeEmptyResponseFallback:
    """When the LLM returns 0 tokens twice in a row, the loop must surface
    completed tool work instead of discarding it behind the generic
    "I had trouble generating a response" fallback.

    Regression for the delegation_basic e2e failure (2026-04-11): a parent
    bot delegated to e2e-tools, the lite model returned 0 tokens twice on
    the post-delegation iteration, and the user saw the generic fallback
    instead of any signal that the delegation actually happened.
    """

    def test_no_tool_calls_returns_generic_fallback(self):
        """When nothing was attempted, the generic fallback is still right."""
        result = _synthesize_empty_response_fallback([], [])
        assert result == _EMPTY_RESPONSE_GENERIC_FALLBACK

    def test_surfaces_tool_name_when_no_result_text(self):
        """Tool was called but tool result message has no text content —
        still surface the tool name so the user knows work happened."""
        messages = [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "do_thing"}}]},
            {"role": "tool", "tool_call_id": "1", "content": ""},
        ]
        result = _synthesize_empty_response_fallback(["do_thing"], messages)
        assert "do_thing" in result
        assert result != _EMPTY_RESPONSE_GENERIC_FALLBACK

    def test_surfaces_tool_name_and_last_result_text(self):
        """The most recent non-empty tool result must appear in the fallback,
        not just the tool name."""
        messages = [
            {"role": "user", "content": "delegate it"},
            {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "delegate_to_agent"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "Delegation task created: abc-123"},
        ]
        result = _synthesize_empty_response_fallback(["delegate_to_agent"], messages)
        assert "delegate_to_agent" in result
        assert "Delegation task created: abc-123" in result

    def test_delegation_basic_keywords_present(self):
        """The synthesized fallback must contain at least one keyword the
        delegation_basic e2e scenario asserts on (`task`/`delegat`/`e2e-tools`).
        This pins the contract that delegation_basic relies on."""
        messages = [
            {"role": "user", "content": "Delegate to the e2e-tools bot"},
            {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "delegate_to_agent"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "Delegation task created: f3c42dee-dbeb-452d-8563-e22bed6ebbc8"},
        ]
        result = _synthesize_empty_response_fallback(["delegate_to_agent"], messages)
        assert any(kw in result.lower() for kw in ("task", "delegat", "e2e-tools"))

    def test_dedupes_tool_names_preserving_order(self):
        """If a tool was called multiple times, list it once."""
        messages = [
            {"role": "tool", "tool_call_id": "3", "content": "result 3"},
        ]
        result = _synthesize_empty_response_fallback(
            ["search", "search", "fetch", "search"], messages
        )
        # Only the first occurrence of each name, in order
        assert result.count("search") == 1
        assert result.count("fetch") == 1
        assert result.index("search") < result.index("fetch")

    def test_picks_most_recent_tool_result(self):
        """When multiple tool result messages exist, use the LAST one."""
        messages = [
            {"role": "tool", "tool_call_id": "1", "content": "OLD result"},
            {"role": "assistant", "content": "intermediate"},
            {"role": "tool", "tool_call_id": "2", "content": "NEWEST result"},
        ]
        result = _synthesize_empty_response_fallback(["a", "b"], messages)
        assert "NEWEST result" in result
        assert "OLD result" not in result

    def test_handles_list_content_parts(self):
        """Some providers return tool content as a list of `{type, text}` parts."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "1",
                "content": [
                    {"type": "text", "text": "first chunk"},
                    {"type": "text", "text": "second chunk"},
                ],
            },
        ]
        result = _synthesize_empty_response_fallback(["my_tool"], messages)
        assert "first chunk" in result
        assert "second chunk" in result

    def test_truncates_long_tool_results(self):
        """Tool result text must be capped so a 50KB JSON dump doesn't
        become the user-facing response."""
        long_text = "x" * 5000
        messages = [
            {"role": "tool", "tool_call_id": "1", "content": long_text},
        ]
        result = _synthesize_empty_response_fallback(["my_tool"], messages)
        # 500-char cap on the tool text portion; result has framing too
        assert len(result) < 1000
        assert "x" * 500 in result
        assert "x" * 1000 not in result

    def test_ignores_non_tool_messages_when_searching_for_result(self):
        """User and assistant messages must not be mistaken for tool results."""
        messages = [
            {"role": "user", "content": "USER MESSAGE TEXT"},
            {"role": "assistant", "content": "ASSISTANT TEXT"},
            {"role": "tool", "tool_call_id": "1", "content": "real tool result"},
        ]
        result = _synthesize_empty_response_fallback(["my_tool"], messages)
        assert "real tool result" in result
        assert "USER MESSAGE TEXT" not in result
        assert "ASSISTANT TEXT" not in result
