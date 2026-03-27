"""Unit tests for tool policy evaluation logic."""
import pytest

from app.services.tool_policies import _match_conditions, _match_tool_name


class TestMatchToolName:
    def test_exact_match(self):
        assert _match_tool_name("exec_command", "exec_command") is True

    def test_exact_no_match(self):
        assert _match_tool_name("exec_command", "web_search") is False

    def test_wildcard_all(self):
        assert _match_tool_name("*", "anything") is True
        assert _match_tool_name("*", "exec_command") is True

    def test_glob_prefix(self):
        assert _match_tool_name("exec_*", "exec_command") is True
        assert _match_tool_name("exec_*", "web_search") is False

    def test_glob_question_mark(self):
        assert _match_tool_name("exec_?ommand", "exec_command") is True
        assert _match_tool_name("exec_?ommand", "exec_xommand") is True
        assert _match_tool_name("exec_?ommand", "exec_xyommand") is False


class TestMatchConditions:
    def test_empty_conditions_always_match(self):
        assert _match_conditions(None, {"command": "ls"}) is True
        assert _match_conditions({}, {"command": "ls"}) is True
        assert _match_conditions({"arguments": {}}, {"command": "ls"}) is True

    def test_pattern_match(self):
        conditions = {"arguments": {"command": {"pattern": "^rm "}}}
        assert _match_conditions(conditions, {"command": "rm -rf /"}) is True
        assert _match_conditions(conditions, {"command": "ls -la"}) is False

    def test_pattern_match_partial(self):
        conditions = {"arguments": {"command": {"pattern": "sudo"}}}
        assert _match_conditions(conditions, {"command": "sudo rm -rf /"}) is True
        assert _match_conditions(conditions, {"command": "ls sudo"}) is True

    def test_prefix_match(self):
        conditions = {"arguments": {"path": {"prefix": "/etc/"}}}
        assert _match_conditions(conditions, {"path": "/etc/passwd"}) is True
        assert _match_conditions(conditions, {"path": "/home/user"}) is False

    def test_in_match(self):
        conditions = {"arguments": {"mode": {"in": ["delete", "force"]}}}
        assert _match_conditions(conditions, {"mode": "delete"}) is True
        assert _match_conditions(conditions, {"mode": "force"}) is True
        assert _match_conditions(conditions, {"mode": "safe"}) is False

    def test_missing_argument_returns_false(self):
        conditions = {"arguments": {"command": {"pattern": ".*"}}}
        assert _match_conditions(conditions, {}) is False
        assert _match_conditions(conditions, {"other": "value"}) is False

    def test_multiple_argument_matchers(self):
        conditions = {
            "arguments": {
                "command": {"pattern": "^rm"},
                "path": {"prefix": "/etc/"},
            }
        }
        assert _match_conditions(conditions, {"command": "rm file", "path": "/etc/hosts"}) is True
        assert _match_conditions(conditions, {"command": "rm file", "path": "/home/user"}) is False
        assert _match_conditions(conditions, {"command": "ls", "path": "/etc/hosts"}) is False

    def test_invalid_regex_returns_false(self):
        conditions = {"arguments": {"command": {"pattern": "[invalid"}}}
        assert _match_conditions(conditions, {"command": "test"}) is False

    def test_non_string_argument_coerced(self):
        conditions = {"arguments": {"count": {"pattern": "^5$"}}}
        assert _match_conditions(conditions, {"count": 5}) is True
        assert _match_conditions(conditions, {"count": 10}) is False
