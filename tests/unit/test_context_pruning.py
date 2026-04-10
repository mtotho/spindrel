"""Unit tests for app.agent.context_pruning and tool result hard cap."""

import copy

import pytest

from app.agent.context_pruning import prune_tool_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_msg(text: str = "hello") -> dict:
    return {"role": "user", "content": text}


def _make_assistant_msg(text: str = "Sure!", tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _make_tool_call(tc_id: str, name: str) -> dict:
    return {"id": tc_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


def _make_tool_result(tc_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


def _make_system_msg(text: str) -> dict:
    return {"role": "system", "content": text}


def _long_content(n: int = 500) -> str:
    return "x" * n


# ---------------------------------------------------------------------------
# Basic pruning
# ---------------------------------------------------------------------------

class TestBasicPruning:
    def test_prunes_old_turns_keeps_recent(self):
        """Tool results in old turns should be pruned; recent kept intact."""
        messages = [
            _make_system_msg("system prompt"),
            # Turn 1 (old)
            _make_user_msg("turn 1"),
            _make_assistant_msg("thinking", [_make_tool_call("tc1", "web_search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("answer 1"),
            # Turn 2 (recent, keep_full_turns=1)
            _make_user_msg("turn 2"),
            _make_assistant_msg("thinking", [_make_tool_call("tc2", "read_file")]),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("answer 2"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 1
        assert stats["chars_saved"] > 0
        assert stats["turns_pruned"] == 1

        # Old tool result is replaced with marker
        assert messages[3]["content"].startswith("[Tool result pruned")
        assert "web_search" in messages[3]["content"]
        assert "500 chars" in messages[3]["content"]

        # Recent tool result is intact
        assert messages[7]["content"] == _long_content(500)

    def test_short_results_not_pruned(self):
        """Tool results below min_content_length should never be pruned."""
        messages = [
            _make_user_msg("turn 1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "do_thing")]),
            _make_tool_result("tc1", "OK"),
            _make_assistant_msg("done"),
            _make_user_msg("turn 2"),
            _make_assistant_msg("answer"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert messages[2]["content"] == "OK"

    def test_user_messages_never_touched(self):
        """User messages should never be modified."""
        messages = [
            _make_user_msg("important question " * 50),
            _make_assistant_msg("answer"),
            _make_user_msg("follow up"),
            _make_assistant_msg("done"),
        ]
        original = copy.deepcopy(messages)
        prune_tool_results(messages, keep_full_turns=1, min_content_length=10)

        for orig, cur in zip(original, messages):
            if orig["role"] == "user":
                assert orig["content"] == cur["content"]

    def test_system_messages_never_touched(self):
        """System messages should never be modified."""
        sys_content = "System prompt " * 100
        messages = [
            _make_system_msg(sys_content),
            _make_user_msg("hello"),
            _make_assistant_msg("done"),
        ]
        prune_tool_results(messages, keep_full_turns=1, min_content_length=10)
        assert messages[0]["content"] == sys_content

    def test_assistant_text_never_touched(self):
        """Assistant messages should never be modified."""
        long_reply = "Very detailed answer " * 100
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg(long_reply),
            _make_user_msg("q2"),
            _make_assistant_msg("done"),
        ]
        prune_tool_results(messages, keep_full_turns=1, min_content_length=10)
        assert messages[1]["content"] == long_reply


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_messages(self):
        stats = prune_tool_results([], keep_full_turns=3)
        assert stats == {"pruned_count": 0, "chars_saved": 0, "turns_pruned": 0}

    def test_no_tool_calls(self):
        """Conversation with no tool calls should be unmodified."""
        messages = [
            _make_system_msg("prompt"),
            _make_user_msg("hello"),
            _make_assistant_msg("hi there!"),
            _make_user_msg("bye"),
            _make_assistant_msg("goodbye"),
        ]
        original = copy.deepcopy(messages)
        stats = prune_tool_results(messages, keep_full_turns=1)
        assert stats["pruned_count"] == 0
        assert messages == original

    def test_single_turn(self):
        """Single turn should never be pruned (it's always 'recent')."""
        messages = [
            _make_user_msg("hello"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(1000)),
            _make_assistant_msg("found it"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1)
        assert stats["pruned_count"] == 0

    def test_keep_turns_zero_prunes_all(self):
        """With keep_full_turns=0, all tool results should be pruned."""
        messages = [
            _make_user_msg("hello"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("found it"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=0, min_content_length=200)
        assert stats["pruned_count"] == 1

    def test_keep_turns_exceeds_total(self):
        """If keep_full_turns > total turns, nothing should be pruned."""
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("a1"),
            _make_user_msg("q2"),
            _make_assistant_msg("a2"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=10, min_content_length=200)
        assert stats["pruned_count"] == 0


# ---------------------------------------------------------------------------
# Conversation markers
# ---------------------------------------------------------------------------

class TestConversationMarkers:
    def test_begin_end_markers(self):
        """Pruning should only apply within BEGIN/END markers."""
        messages = [
            _make_system_msg("system"),
            _make_system_msg("--- BEGIN RECENT CONVERSATION HISTORY ---"),
            # Turn 1 (old)
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("a1"),
            # Turn 2 (recent)
            _make_user_msg("q2"),
            _make_assistant_msg("a2"),
            _make_system_msg("--- END RECENT CONVERSATION HISTORY ---"),
            # Post-marker system messages (should not be touched)
            _make_system_msg("injected context " * 100),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)
        assert stats["pruned_count"] == 1
        assert messages[4]["content"].startswith("[Tool result pruned")
        # System messages outside the region are untouched
        assert messages[9]["content"].startswith("injected context")


# ---------------------------------------------------------------------------
# Stats accuracy
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_accuracy(self):
        """Stats should accurately reflect what was pruned."""
        content_500 = _long_content(500)
        content_300 = _long_content(300)
        messages = [
            # Turn 1
            _make_user_msg("q1"),
            _make_assistant_msg("", [
                _make_tool_call("tc1", "tool_a"),
                _make_tool_call("tc2", "tool_b"),
            ]),
            _make_tool_result("tc1", content_500),
            _make_tool_result("tc2", content_300),
            _make_assistant_msg("a1"),
            # Turn 2
            _make_user_msg("q2"),
            _make_assistant_msg("", [_make_tool_call("tc3", "tool_c")]),
            _make_tool_result("tc3", _long_content(400)),
            _make_assistant_msg("a2"),
            # Turn 3 (recent)
            _make_user_msg("q3"),
            _make_assistant_msg("a3"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 3  # tc1, tc2, tc3
        assert stats["turns_pruned"] == 2  # turn 1 and turn 2

        # chars_saved = sum of (original_length - marker_length)
        marker_1 = f"[Tool result pruned — tool_a: 500 chars]"
        marker_2 = f"[Tool result pruned — tool_b: 300 chars]"
        marker_3 = f"[Tool result pruned — tool_c: 400 chars]"
        expected_saved = (500 - len(marker_1)) + (300 - len(marker_2)) + (400 - len(marker_3))
        assert stats["chars_saved"] == expected_saved

    def test_multiple_tool_calls_per_turn(self):
        """Multiple tool results in the same turn should all be pruned."""
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [
                _make_tool_call("tc1", "search"),
                _make_tool_call("tc2", "read"),
            ]),
            _make_tool_result("tc1", _long_content(500)),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("done"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)
        assert stats["pruned_count"] == 2
        assert stats["turns_pruned"] == 1


# ---------------------------------------------------------------------------
# Tool name resolution
# ---------------------------------------------------------------------------

class TestToolNameMap:
    def test_unknown_tool_name(self):
        """Tool results without matching assistant tool_call should show 'unknown'."""
        messages = [
            _make_user_msg("q1"),
            # Assistant with no tool_calls array
            _make_assistant_msg("thinking"),
            _make_tool_result("orphan_tc", _long_content(500)),
            _make_assistant_msg("done"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        prune_tool_results(messages, keep_full_turns=1, min_content_length=200)
        assert "unknown" in messages[2]["content"]

    def test_tool_call_id_preserved(self):
        """The tool_call_id field should never be modified."""
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("done"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        prune_tool_results(messages, keep_full_turns=1, min_content_length=200)
        assert messages[2]["tool_call_id"] == "tc1"
        assert messages[2]["role"] == "tool"


# ---------------------------------------------------------------------------
# Retrieval pointers
# ---------------------------------------------------------------------------

class TestRetrievalPointers:
    def test_record_id_produces_retrieval_pointer(self):
        """Tool results with _tool_record_id should get a retrieval pointer."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "web_search")]),
            {**_make_tool_result("tc1", _long_content(500)), "_tool_record_id": record_id},
            _make_assistant_msg("a1"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 1
        assert "read_conversation_history" in messages[2]["content"]
        assert record_id in messages[2]["content"]
        assert "web_search" in messages[2]["content"]
        assert "500" in messages[2]["content"]

    def test_no_record_id_produces_dead_marker(self):
        """Tool results without _tool_record_id should get the old dead marker."""
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "web_search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("a1"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 1
        assert messages[2]["content"].startswith("[Tool result pruned")
        assert "read_conversation_history" not in messages[2]["content"]

    def test_record_id_preserved_after_pruning(self):
        """_tool_record_id key should survive pruning (stays on the message dict)."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            {**_make_tool_result("tc1", _long_content(500)), "_tool_record_id": record_id},
            _make_assistant_msg("a1"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert messages[2]["_tool_record_id"] == record_id

    def test_recent_turns_untouched_with_record_id(self):
        """Kept turns should not be pruned even if they have _tool_record_id."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        original_content = _long_content(500)
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            {**_make_tool_result("tc1", original_content), "_tool_record_id": record_id},
            _make_assistant_msg("a1"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert messages[2]["content"] == original_content

    def test_mixed_record_id_and_no_record_id(self):
        """Messages with and without record IDs should get appropriate markers."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        messages = [
            # Turn 1: has record_id
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            {**_make_tool_result("tc1", _long_content(500)), "_tool_record_id": record_id},
            _make_assistant_msg("a1"),
            # Turn 2: no record_id
            _make_user_msg("q2"),
            _make_assistant_msg("", [_make_tool_call("tc2", "legacy_tool")]),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("a2"),
            # Turn 3: recent (kept)
            _make_user_msg("q3"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, keep_full_turns=1, min_content_length=200)

        assert stats["pruned_count"] == 2
        # Turn 1: retrieval pointer
        assert "read_conversation_history" in messages[2]["content"]
        assert record_id in messages[2]["content"]
        # Turn 2: dead marker
        assert messages[6]["content"].startswith("[Tool result pruned")
        assert "read_conversation_history" not in messages[6]["content"]
