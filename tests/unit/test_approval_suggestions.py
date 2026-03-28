"""Unit tests for the approval suggestion engine."""
import pytest

from app.services.approval_suggestions import build_suggestions


class TestExecCommandSuggestions:
    def test_ls_command(self):
        suggestions = build_suggestions("exec_command", {"command": "ls /home"})
        labels = [s.label for s in suggestions]
        # Should have: exact match, ls *, ls in /home/*, allow tool always
        assert any("ls /home" in l for l in labels), f"Expected exact match in {labels}"
        assert any("ls *" in l or "ls " in l for l in labels), f"Expected prefix match in {labels}"
        assert any("exec_command always" in l for l in labels), f"Expected tool-always in {labels}"

    def test_rm_rf(self):
        suggestions = build_suggestions("exec_command", {"command": "rm -rf /tmp/stuff"})
        labels = [s.label for s in suggestions]
        assert any("rm" in l for l in labels)
        # Should suggest path-based too
        assert any("/tmp/" in l for l in labels), f"Expected path suggestion in {labels}"

    def test_simple_command_no_args(self):
        suggestions = build_suggestions("exec_command", {"command": "whoami"})
        labels = [s.label for s in suggestions]
        assert any("whoami" in l for l in labels)
        assert any("exec_command always" in l for l in labels)

    def test_always_has_tool_always(self):
        suggestions = build_suggestions("exec_command", {"command": "cat /etc/passwd"})
        last = suggestions[-1]
        assert last.conditions == {}
        assert "exec_command" in last.tool_name
        assert "always" in last.label.lower()


class TestPathSuggestions:
    def test_write_file(self):
        suggestions = build_suggestions("write_file", {"path": "/home/user/docs/report.txt"})
        labels = [s.label for s in suggestions]
        assert any("/home/user/docs/report.txt" in l for l in labels)
        assert any("/home/user/docs/" in l for l in labels)

    def test_read_file(self):
        suggestions = build_suggestions("read_file", {"path": "/etc/config.yaml"})
        labels = [s.label for s in suggestions]
        assert any("/etc/" in l for l in labels)


class TestGenericTool:
    def test_unknown_tool_gets_tool_always(self):
        suggestions = build_suggestions("web_search", {"query": "hello"})
        assert len(suggestions) >= 1
        assert suggestions[-1].tool_name == "web_search"
        assert suggestions[-1].conditions == {}

    def test_unknown_tool_with_path_arg(self):
        suggestions = build_suggestions("custom_tool", {"file": "/data/input.csv"})
        labels = [s.label for s in suggestions]
        assert any("/data/" in l for l in labels)

    def test_empty_arguments(self):
        suggestions = build_suggestions("some_tool", {})
        assert len(suggestions) == 1
        assert "some_tool always" in suggestions[0].label.lower()


class TestConditions:
    def test_exact_match_has_pattern(self):
        suggestions = build_suggestions("exec_command", {"command": "ls"})
        exact = [s for s in suggestions if "conditions" in dir(s) and s.conditions.get("arguments", {}).get("command", {}).get("pattern", "").endswith("$")]
        assert len(exact) >= 1, "Should have an exact match condition"

    def test_prefix_match_has_prefix_pattern(self):
        suggestions = build_suggestions("exec_command", {"command": "git status"})
        # Should have a "Allow git *" suggestion that matches any git subcommand
        git_star = [s for s in suggestions if "git *" in s.label]
        assert len(git_star) >= 1, f"Should have a 'git *' suggestion, got: {[s.label for s in suggestions]}"
        # Its condition should be a regex starting with ^git
        pattern = git_star[0].conditions["arguments"]["command"]["pattern"]
        assert pattern.startswith("^git")
