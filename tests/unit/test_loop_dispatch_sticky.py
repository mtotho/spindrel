"""Verify re-fetched tool results via `read_conversation_history(section="tool:...")`
are marked sticky at dispatch time, preventing the prune → re-fetch → prune loop
seen on long hygiene runs.
"""
from __future__ import annotations

import json

import pytest

from app.agent.loop_dispatch import _is_skill_get, _is_tool_id_refetch


class TestIsToolIdRefetch:
    def test_detects_tool_prefix_in_json_args(self):
        args = json.dumps({"section": "tool:e813c552-56d1-4a3c-ae40-4b8062b2c0f8"})
        assert _is_tool_id_refetch(args) is True

    def test_detects_tool_prefix_in_dict_args(self):
        assert _is_tool_id_refetch({"section": "tool:abc"}) is True

    def test_uppercase_prefix_still_matches(self):
        assert _is_tool_id_refetch({"section": "TOOL:abc"}) is True

    def test_whitespace_tolerated(self):
        assert _is_tool_id_refetch({"section": "  tool:abc  "}) is True

    def test_rejects_index_section(self):
        assert _is_tool_id_refetch({"section": "index"}) is False

    def test_rejects_section_number(self):
        assert _is_tool_id_refetch({"section": "3"}) is False

    def test_rejects_recent(self):
        assert _is_tool_id_refetch({"section": "recent"}) is False

    def test_handles_missing_section(self):
        assert _is_tool_id_refetch({"channel_id": "xyz"}) is False

    def test_handles_non_string_section(self):
        assert _is_tool_id_refetch({"section": 42}) is False

    def test_handles_malformed_json_string(self):
        assert _is_tool_id_refetch("{not json") is False

    def test_handles_empty_string(self):
        assert _is_tool_id_refetch("") is False

    def test_handles_none(self):
        assert _is_tool_id_refetch(None) is False


class TestIsSkillGet:
    """Sticky detection for manage_bot_skill(action="get") — same read-only
    reference-material semantics as the already-sticky `get_skill` tool.
    """

    def test_detects_get_in_dict_args(self):
        assert _is_skill_get({"action": "get", "name": "foo"}) is True

    def test_detects_get_in_json_string_args(self):
        args = json.dumps({"action": "get", "names": ["a", "b"]})
        assert _is_skill_get(args) is True

    def test_case_tolerated(self):
        assert _is_skill_get({"action": "GET"}) is True

    def test_whitespace_tolerated(self):
        assert _is_skill_get({"action": "  get  "}) is True

    def test_rejects_list_action(self):
        assert _is_skill_get({"action": "list"}) is False

    def test_rejects_update_action(self):
        assert _is_skill_get({"action": "update", "name": "x"}) is False

    def test_rejects_upsert_action(self):
        assert _is_skill_get({"action": "upsert"}) is False

    def test_handles_missing_action(self):
        assert _is_skill_get({"name": "foo"}) is False

    def test_handles_non_string_action(self):
        assert _is_skill_get({"action": 1}) is False

    def test_handles_malformed_json_string(self):
        assert _is_skill_get("{not json") is False

    def test_handles_empty_string(self):
        assert _is_skill_get("") is False

    def test_handles_none(self):
        assert _is_skill_get(None) is False
