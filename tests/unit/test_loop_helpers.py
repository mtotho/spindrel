"""Unit tests for pure helpers in app.agent.loop."""
from app.agent.loop import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES


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
