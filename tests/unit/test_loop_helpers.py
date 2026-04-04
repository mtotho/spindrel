"""Unit tests for pure helpers in app.agent.loop."""
from app.agent.context import task_creation_count
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
