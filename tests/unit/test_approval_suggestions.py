"""Unit tests for the approval suggestion engine."""
import pytest

from app.services.approval_suggestions import build_suggestions


class TestBroadestFirstOrdering:
    """Suggestions should be ordered broadest-first."""

    def test_first_two_are_broad(self):
        suggestions = build_suggestions("exec_command", {"command": "ls /home"})
        assert len(suggestions) >= 2
        # First: global (all bots)
        assert suggestions[0].scope == "global"
        assert suggestions[0].conditions == {}
        # Second: bot-scoped always
        assert suggestions[1].scope == "bot"
        assert suggestions[1].conditions == {}

    def test_narrow_after_broad(self):
        suggestions = build_suggestions("exec_command", {"command": "ls -la /home/user"})
        for s in suggestions[2:]:
            assert s.conditions, f"Expected conditions on narrow suggestion: {s.label}"


class TestExecCommandSuggestions:
    def test_ls_command(self):
        suggestions = build_suggestions("exec_command", {"command": "ls /home"})
        labels = [s.label for s in suggestions]
        # Should have: global, always, ls *, ls in /home/*, exact match
        assert any("ls *" in l or "ls " in l for l in labels), f"Expected prefix match in {labels}"
        assert any("exec_command" in l and "always" in l for l in labels), f"Expected tool-always in {labels}"

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
        assert any("exec_command" in l and "always" in l for l in labels)

    def test_broad_tool_always_in_first_two(self):
        suggestions = build_suggestions("exec_command", {"command": "cat /etc/passwd"})
        # The first two should be the broad options
        assert suggestions[0].conditions == {}
        assert suggestions[1].conditions == {}
        assert "exec_command" in suggestions[1].tool_name


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
    def test_unknown_tool_gets_global_and_bot(self):
        suggestions = build_suggestions("web_search", {"query": "hello"})
        assert len(suggestions) == 2
        assert suggestions[0].scope == "global"
        assert suggestions[0].conditions == {}
        assert suggestions[1].scope == "bot"
        assert suggestions[1].conditions == {}

    def test_unknown_tool_with_path_arg(self):
        suggestions = build_suggestions("custom_tool", {"file": "/data/input.csv"})
        labels = [s.label for s in suggestions]
        assert any("/data/" in l for l in labels)

    def test_empty_arguments(self):
        suggestions = build_suggestions("some_tool", {})
        assert len(suggestions) == 2  # global + bot-scoped
        assert suggestions[0].scope == "global"
        assert suggestions[1].scope == "bot"


class TestScopeField:
    def test_all_have_scope(self):
        suggestions = build_suggestions("write_file", {"path": "/tmp/test.txt"})
        for s in suggestions:
            assert s.scope in ("bot", "global"), f"Invalid scope: {s.scope}"

    def test_first_is_global(self):
        suggestions = build_suggestions("exec_command", {"command": "ls"})
        assert suggestions[0].scope == "global"

    def test_narrow_are_bot_scoped(self):
        suggestions = build_suggestions("exec_command", {"command": "ls -la"})
        for s in suggestions[2:]:
            assert s.scope == "bot", f"Narrow suggestions should be bot-scoped: {s.label}"


class TestConditions:
    def test_exact_match_has_pattern(self):
        suggestions = build_suggestions("exec_command", {"command": "ls"})
        exact = [s for s in suggestions if s.conditions.get("arguments", {}).get("command", {}).get("pattern", "").endswith("$")]
        assert len(exact) >= 1, "Should have an exact match condition"

    def test_prefix_match_has_prefix_pattern(self):
        suggestions = build_suggestions("exec_command", {"command": "git status"})
        git_star = [s for s in suggestions if "git *" in s.label]
        assert len(git_star) >= 1, f"Should have a 'git *' suggestion, got: {[s.label for s in suggestions]}"
        pattern = git_star[0].conditions["arguments"]["command"]["pattern"]
        assert pattern.startswith("^git")

    def test_long_command_skips_exact(self):
        long_cmd = "find /very/long/path -name '*.txt' -exec grep -l 'pattern' {} \\; | sort | uniq -c | sort -rn"
        suggestions = build_suggestions("exec_command", {"command": long_cmd})
        exact = [s for s in suggestions if s.conditions.get("arguments", {}).get("command", {}).get("pattern", "").endswith("$")]
        assert len(exact) == 0, "Should not suggest exact match for long commands"
