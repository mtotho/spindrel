"""Unit tests for app.agent.context_pruning and tool result hard cap."""

import copy
import json

import pytest

from app.agent.context_pruning import (
    STICKY_TOOL_NAMES,
    prune_in_loop_tool_results,
    prune_tool_results,
)


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
    def test_prunes_all_tool_results(self):
        """All tool results from previous turns should be pruned."""
        messages = [
            _make_system_msg("system prompt"),
            # Turn 1
            _make_user_msg("turn 1"),
            _make_assistant_msg("thinking", [_make_tool_call("tc1", "web_search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("answer 1"),
            # Turn 2
            _make_user_msg("turn 2"),
            _make_assistant_msg("thinking", [_make_tool_call("tc2", "read_file")]),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("answer 2"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 2
        assert stats["chars_saved"] > 0
        assert stats["turns_pruned"] == 2

        # Both tool results replaced with markers
        assert messages[3]["content"].startswith("[Tool result pruned")
        assert "web_search" in messages[3]["content"]
        assert messages[7]["content"].startswith("[Tool result pruned")
        assert "read_file" in messages[7]["content"]

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
        stats = prune_tool_results(messages, min_content_length=200)

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
        prune_tool_results(messages, min_content_length=10)

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
        prune_tool_results(messages, min_content_length=10)
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
        prune_tool_results(messages, min_content_length=10)
        assert messages[1]["content"] == long_reply


class TestToolCallArgumentPruning:
    def test_prunes_large_assistant_tool_call_arguments(self):
        """Large historical tool-call args should be compacted even when result is small."""
        large_args = json.dumps({"query": "x" * 1000})
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [{
                "id": "tc1",
                "type": "function",
                "function": {"name": "web_search", "arguments": large_args},
            }]),
            _make_tool_result("tc1", "OK"),
            _make_assistant_msg("a1"),
        ]

        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert stats["tool_call_args_pruned"] == 1
        assert stats["tool_call_arg_chars_saved"] > 0
        compacted = messages[1]["tool_calls"][0]
        assert compacted["id"] == "tc1"
        assert compacted["function"]["name"] == "web_search"
        marker = json.loads(compacted["function"]["arguments"])
        assert marker["_spindrel_pruned_tool_args"] is True
        assert marker["tool"] == "web_search"
        assert marker["original_chars"] == len(large_args)

    def test_already_pruned_tool_call_arguments_are_idempotent(self):
        marker = json.dumps({
            "_spindrel_pruned_tool_args": True,
            "tool": "web_search",
            "original_chars": 1200,
            "note": "Historical tool-call arguments were compacted for context replay.",
        })
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [{
                "id": "tc1",
                "type": "function",
                "function": {"name": "web_search", "arguments": marker},
            }]),
            _make_tool_result("tc1", "OK"),
        ]

        stats = prune_tool_results(messages, min_content_length=50)

        assert stats["tool_call_args_pruned"] == 0
        assert messages[1]["tool_calls"][0]["function"]["arguments"] == marker


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_messages(self):
        stats = prune_tool_results([])
        assert stats == {
            "pruned_count": 0,
            "chars_saved": 0,
            "turns_pruned": 0,
            "tool_call_args_pruned": 0,
            "tool_call_arg_chars_saved": 0,
        }

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
        stats = prune_tool_results(messages)
        assert stats["pruned_count"] == 0
        assert messages == original

    def test_single_turn_tool_result_is_pruned(self):
        """Even a single-turn tool result is pruned (no turn protection)."""
        messages = [
            _make_user_msg("hello"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(1000)),
            _make_assistant_msg("found it"),
        ]
        stats = prune_tool_results(messages)
        assert stats["pruned_count"] == 1


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
        stats = prune_tool_results(messages, min_content_length=200)
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
        stats = prune_tool_results(messages, min_content_length=200)

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
        stats = prune_tool_results(messages, min_content_length=200)
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
        prune_tool_results(messages, min_content_length=200)
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
        prune_tool_results(messages, min_content_length=200)
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
        stats = prune_tool_results(messages, min_content_length=200)

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
        stats = prune_tool_results(messages, min_content_length=200)

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
        prune_tool_results(messages, min_content_length=200)

        assert messages[2]["_tool_record_id"] == record_id

    def test_recent_turns_with_record_id_still_pruned(self):
        """Kept turns with _tool_record_id should still be pruned (retrievable)."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        original_content = _long_content(500)
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            {**_make_tool_result("tc1", original_content), "_tool_record_id": record_id},
            _make_assistant_msg("a1"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 1
        assert "read_conversation_history" in messages[2]["content"]
        assert record_id in messages[2]["content"]

    def test_recent_turns_without_record_id_get_dead_marker(self):
        """Tool results without _tool_record_id are pruned with dead marker."""
        original_content = _long_content(500)
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", original_content),
            _make_assistant_msg("a1"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 1
        assert messages[2]["content"].startswith("[Tool result pruned")
        assert "read_conversation_history" not in messages[2]["content"]

    def test_sticky_tool_result_not_pruned(self):
        """Tool results with _no_prune=True should never be pruned, regardless of size."""
        skill_content = "# How to deploy\n\n" + ("step " * 200)
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "get_skill")]),
            {**_make_tool_result("tc1", skill_content), "_no_prune": True},
            _make_assistant_msg("following the skill"),
            _make_user_msg("q2"),
            _make_assistant_msg("done"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 0
        # Skill content unchanged
        assert messages[2]["content"] == skill_content
        assert messages[2]["_no_prune"] is True

    def test_sticky_flag_with_record_id_still_skipped(self):
        """Sticky flag wins even when a record_id is present."""
        skill_content = "skill body " * 100
        messages = [
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "get_skill")]),
            {
                **_make_tool_result("tc1", skill_content),
                "_no_prune": True,
                "_tool_record_id": "abc12345-1234-1234-1234-123456789abc",
            },
            _make_assistant_msg("done"),
            _make_user_msg("q2"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert messages[2]["content"] == skill_content

    def test_mixed_sticky_and_normal_tool_results(self):
        """Sticky tool results stay; non-sticky tool results in same conversation are pruned."""
        skill_content = "# Runbook\n\n" + ("instructions " * 100)
        normal_content = _long_content(500)
        messages = [
            # Turn 1: skill fetch (sticky)
            _make_user_msg("q1"),
            _make_assistant_msg("", [_make_tool_call("tc1", "get_skill")]),
            {**_make_tool_result("tc1", skill_content), "_no_prune": True},
            _make_assistant_msg("ok"),
            # Turn 2: regular tool call (not sticky)
            _make_user_msg("q2"),
            _make_assistant_msg("", [_make_tool_call("tc2", "web_search")]),
            _make_tool_result("tc2", normal_content),
            _make_assistant_msg("done"),
            # Turn 3 (recent)
            _make_user_msg("q3"),
            _make_assistant_msg("final"),
        ]
        stats = prune_tool_results(messages, min_content_length=200)

        # Only the non-sticky one is pruned
        assert stats["pruned_count"] == 1
        assert stats["turns_pruned"] == 1
        # Skill content untouched
        assert messages[2]["content"] == skill_content
        # web_search result replaced with marker
        assert messages[6]["content"].startswith("[Tool result pruned")
        assert "web_search" in messages[6]["content"]

    def test_sticky_tool_names_constant_includes_skill_tools(self):
        """The exported constant must include both skill tool names."""
        assert "get_skill" in STICKY_TOOL_NAMES
        assert "get_skill_list" in STICKY_TOOL_NAMES

    def test_sticky_tool_names_includes_memory_file(self):
        """get_memory_file is sticky so hygiene runs don't re-fetch MEMORY.md."""
        assert "get_memory_file" in STICKY_TOOL_NAMES

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
        stats = prune_tool_results(messages, min_content_length=200)

        assert stats["pruned_count"] == 2
        # Turn 1: retrieval pointer
        assert "read_conversation_history" in messages[2]["content"]
        assert record_id in messages[2]["content"]
        # Turn 2: dead marker
        assert messages[6]["content"].startswith("[Tool result pruned")
        assert "read_conversation_history" not in messages[6]["content"]


# ---------------------------------------------------------------------------
# In-loop pruning (between iterations within a single turn)
# ---------------------------------------------------------------------------

def _build_iter_turn(num_iterations: int, content_size: int = 500) -> list[dict]:
    """Build a single-turn message list with N iterations of tool calls.

    Layout:
        user
        assistant(tool_calls=[tc_iter1])
        tool(tc_iter1)
        assistant(tool_calls=[tc_iter2])
        tool(tc_iter2)
        ...
    """
    msgs: list[dict] = [_make_user_msg("do everything")]
    for i in range(1, num_iterations + 1):
        tc_id = f"tc{i}"
        msgs.append(_make_assistant_msg("", [_make_tool_call(tc_id, f"tool_{i}")]))
        msgs.append(_make_tool_result(tc_id, _long_content(content_size)))
    return msgs


class TestInLoopPruning:
    def test_prunes_older_iterations_keeps_latest(self):
        """With keep_iterations=1, all iterations except the latest get pruned."""
        messages = _build_iter_turn(num_iterations=4)
        # Layout: user | (asst, tool) x4   → indexes 0 | 1,2 | 3,4 | 5,6 | 7,8
        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert stats["pruned_count"] == 3  # iterations 1, 2, 3 pruned; 4 kept
        assert stats["iterations_pruned"] == 3
        # Iter 1, 2, 3 tool results pruned
        assert "older iteration" in messages[2]["content"]
        assert "older iteration" in messages[4]["content"]
        assert "older iteration" in messages[6]["content"]
        # Iter 4 (latest) verbatim
        assert messages[8]["content"] == _long_content(500)

    def test_prunes_older_iteration_tool_call_arguments_keeps_latest(self):
        """Oversized args from older iterations are compacted; latest iteration stays verbatim."""
        old_args = json.dumps({"payload": "x" * 1000})
        latest_args = json.dumps({"payload": "y" * 1000})
        messages = [
            _make_user_msg("q"),
            _make_assistant_msg("", [{
                "id": "tc1",
                "type": "function",
                "function": {"name": "old_tool", "arguments": old_args},
            }]),
            _make_tool_result("tc1", "OK"),
            _make_assistant_msg("", [{
                "id": "tc2",
                "type": "function",
                "function": {"name": "latest_tool", "arguments": latest_args},
            }]),
            _make_tool_result("tc2", "OK"),
        ]

        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert stats["tool_call_args_pruned"] == 1
        old_marker = json.loads(messages[1]["tool_calls"][0]["function"]["arguments"])
        assert old_marker["_spindrel_pruned_tool_args"] is True
        assert messages[3]["tool_calls"][0]["function"]["arguments"] == latest_args

    def test_keep_iterations_two(self):
        """With keep_iterations=2, the last two iterations are protected."""
        messages = _build_iter_turn(num_iterations=4)
        stats = prune_in_loop_tool_results(messages, keep_iterations=2, min_content_length=200)

        assert stats["pruned_count"] == 2  # iter 1 + 2 pruned
        # Iter 3 + 4 verbatim
        assert messages[6]["content"] == _long_content(500)
        assert messages[8]["content"] == _long_content(500)

    def test_no_pruning_when_only_one_iteration(self):
        """A single iteration's results must never be pruned (LLM still consuming them)."""
        messages = _build_iter_turn(num_iterations=1)
        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert stats["pruned_count"] == 0
        assert messages[2]["content"] == _long_content(500)

    def test_keep_iterations_clamped_to_minimum_one(self):
        """keep_iterations=0 is clamped to 1 — never prune the most recent iteration."""
        messages = _build_iter_turn(num_iterations=2)
        stats = prune_in_loop_tool_results(messages, keep_iterations=0, min_content_length=200)

        # Acts like keep_iterations=1: iter 1 pruned, iter 2 kept
        assert stats["pruned_count"] == 1
        assert "older iteration" in messages[2]["content"]
        assert messages[4]["content"] == _long_content(500)

    def test_idempotent_after_first_prune(self):
        """Running prune twice should not double-prune (markers are short, below threshold)."""
        messages = _build_iter_turn(num_iterations=3)
        stats1 = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)
        stats2 = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert stats1["pruned_count"] == 2
        assert stats2["pruned_count"] == 0  # nothing left to prune

    def test_short_results_skipped(self):
        """Tool results below min_content_length are not pruned."""
        messages = [
            _make_user_msg("q"),
            _make_assistant_msg("", [_make_tool_call("tc1", "echo")]),
            _make_tool_result("tc1", "ok"),
            _make_assistant_msg("", [_make_tool_call("tc2", "search")]),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("", [_make_tool_call("tc3", "save")]),
            _make_tool_result("tc3", "saved"),
        ]
        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        # Only tc2 (long content from older iteration) gets pruned
        assert stats["pruned_count"] == 1
        assert messages[2]["content"] == "ok"
        assert "older iteration" in messages[4]["content"]
        assert messages[6]["content"] == "saved"

    def test_sticky_tool_results_protected(self):
        """_no_prune=True is honored — sticky skill results stay verbatim across iterations."""
        skill_content = "# Runbook\n\n" + ("step " * 200)
        messages = [
            _make_user_msg("q"),
            _make_assistant_msg("", [_make_tool_call("tc1", "get_skill")]),
            {**_make_tool_result("tc1", skill_content), "_no_prune": True},
            _make_assistant_msg("", [_make_tool_call("tc2", "search")]),
            _make_tool_result("tc2", _long_content(500)),
            _make_assistant_msg("", [_make_tool_call("tc3", "fetch")]),
            _make_tool_result("tc3", _long_content(500)),
        ]
        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        # Skill (iter 1) preserved despite being old; iter 2 pruned; iter 3 kept (latest)
        assert stats["pruned_count"] == 1
        assert messages[2]["content"] == skill_content
        assert "older iteration" in messages[4]["content"]
        assert messages[6]["content"] == _long_content(500)

    def test_user_and_assistant_text_untouched(self):
        """Only tool results are mutated."""
        messages = [
            _make_user_msg("important question " * 50),
            _make_assistant_msg("thinking out loud " * 50, [_make_tool_call("tc1", "search")]),
            _make_tool_result("tc1", _long_content(500)),
            _make_assistant_msg("more thinking " * 50, [_make_tool_call("tc2", "fetch")]),
            _make_tool_result("tc2", _long_content(500)),
        ]
        original_user = messages[0]["content"]
        original_asst1 = messages[1]["content"]
        original_asst2 = messages[3]["content"]
        prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert messages[0]["content"] == original_user
        assert messages[1]["content"] == original_asst1
        assert messages[3]["content"] == original_asst2

    def test_record_id_produces_retrieval_pointer(self):
        """When _tool_record_id is present, the marker contains a retrieval pointer."""
        record_id = "abc12345-1234-1234-1234-123456789abc"
        messages = [
            _make_user_msg("q"),
            _make_assistant_msg("", [_make_tool_call("tc1", "web_search")]),
            {**_make_tool_result("tc1", _long_content(500)), "_tool_record_id": record_id},
            _make_assistant_msg("", [_make_tool_call("tc2", "fetch")]),
            _make_tool_result("tc2", _long_content(500)),
        ]
        prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        assert "read_conversation_history" in messages[2]["content"]
        assert record_id in messages[2]["content"]
        assert "web_search" in messages[2]["content"]

    def test_empty_messages(self):
        stats = prune_in_loop_tool_results([], keep_iterations=1)
        assert stats == {
            "pruned_count": 0,
            "chars_saved": 0,
            "iterations_pruned": 0,
            "tool_call_args_pruned": 0,
            "tool_call_arg_chars_saved": 0,
        }

    def test_no_tool_calls_at_all(self):
        """A turn with no tool calls is a no-op."""
        messages = [
            _make_user_msg("hi"),
            _make_assistant_msg("hello"),
        ]
        original = copy.deepcopy(messages)
        stats = prune_in_loop_tool_results(messages, keep_iterations=1)
        assert stats["pruned_count"] == 0
        assert messages == original

    def test_multiple_tool_calls_same_iteration(self):
        """Parallel tool calls in one iteration share that iteration's protection."""
        messages = [
            _make_user_msg("q"),
            # Iteration 1: two parallel tool calls
            _make_assistant_msg("", [
                _make_tool_call("tc1a", "search"),
                _make_tool_call("tc1b", "fetch"),
            ]),
            _make_tool_result("tc1a", _long_content(500)),
            _make_tool_result("tc1b", _long_content(500)),
            # Iteration 2: single tool call
            _make_assistant_msg("", [_make_tool_call("tc2", "save")]),
            _make_tool_result("tc2", _long_content(500)),
        ]
        stats = prune_in_loop_tool_results(messages, keep_iterations=1, min_content_length=200)

        # Both iter 1 results pruned; iter 2 kept
        assert stats["pruned_count"] == 2
        assert "older iteration" in messages[2]["content"]
        assert "older iteration" in messages[3]["content"]
        assert messages[5]["content"] == _long_content(500)
