"""Unit tests for carapace resolution, cycle detection, and merge logic."""
import pytest

from app.agent.bots import SkillConfig
from app.agent.carapaces import (
    ResolvedCarapace,
    _registry,
    resolve_carapaces,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure a clean registry for each test."""
    _registry.clear()
    yield
    _registry.clear()


def _make_carapace(
    id: str,
    *,
    skills=None,
    local_tools=None,
    mcp_tools=None,
    pinned_tools=None,
    system_prompt_fragment=None,
    includes=None,
):
    return {
        "id": id,
        "name": id,
        "description": None,
        "skills": skills or [],
        "local_tools": local_tools or [],
        "mcp_tools": mcp_tools or [],
        "pinned_tools": pinned_tools or [],
        "system_prompt_fragment": system_prompt_fragment,
        "includes": includes or [],
        "tags": [],
        "source_path": None,
        "source_type": "manual",
        "content_hash": None,
    }


class TestResolveCarapaces:
    def test_empty_ids(self):
        result = resolve_carapaces([])
        assert result.skills == []
        assert result.local_tools == []
        assert result.system_prompt_fragments == []

    def test_single_carapace(self):
        _registry["qa"] = _make_carapace(
            "qa",
            skills=[{"id": "testing", "mode": "pinned"}],
            local_tools=["exec_command", "file"],
            pinned_tools=["exec_command"],
            system_prompt_fragment="Be a QA expert.",
        )
        result = resolve_carapaces(["qa"])
        assert len(result.skills) == 1
        assert result.skills[0].id == "testing"
        assert result.skills[0].mode == "pinned"
        assert result.local_tools == ["exec_command", "file"]
        assert result.pinned_tools == ["exec_command"]
        assert result.system_prompt_fragments == ["Be a QA expert."]

    def test_multiple_carapaces_deduplicate(self):
        _registry["a"] = _make_carapace(
            "a",
            local_tools=["exec_command", "file"],
            skills=[{"id": "s1", "mode": "pinned"}],
        )
        _registry["b"] = _make_carapace(
            "b",
            local_tools=["file", "web_search"],
            skills=[{"id": "s1", "mode": "on_demand"}, {"id": "s2", "mode": "pinned"}],
        )
        result = resolve_carapaces(["a", "b"])
        # exec_command, file from a; web_search from b (file deduped)
        assert result.local_tools == ["exec_command", "file", "web_search"]
        # s1 from a (first seen); s2 from b
        assert [s.id for s in result.skills] == ["s1", "s2"]
        assert result.skills[0].mode == "pinned"  # from a, first seen

    def test_composition_via_includes(self):
        _registry["base"] = _make_carapace(
            "base",
            local_tools=["file"],
            system_prompt_fragment="Base instructions.",
        )
        _registry["qa"] = _make_carapace(
            "qa",
            includes=["base"],
            local_tools=["exec_command"],
            system_prompt_fragment="QA instructions.",
        )
        result = resolve_carapaces(["qa"])
        # base tools come first (depth-first), then qa
        assert result.local_tools == ["file", "exec_command"]
        # fragments: base first (from includes), then qa
        assert result.system_prompt_fragments == ["Base instructions.", "QA instructions."]

    def test_cycle_detection(self):
        _registry["a"] = _make_carapace("a", includes=["b"], local_tools=["t1"])
        _registry["b"] = _make_carapace("b", includes=["a"], local_tools=["t2"])
        # Should not infinite loop
        result = resolve_carapaces(["a"])
        # a includes b, b tries to include a but cycle detected
        assert "t2" in result.local_tools
        assert "t1" in result.local_tools

    def test_max_depth(self):
        # Chain: a -> b -> c -> d -> e -> f -> g (depth > 5)
        prev = None
        for i, name in enumerate(reversed("abcdefg")):
            includes = [prev] if prev else []
            _registry[name] = _make_carapace(name, includes=includes, local_tools=[f"t{name}"])
            prev = name
        result = resolve_carapaces(["a"], max_depth=3)
        # Should stop at depth 3, not resolve all 7
        assert len(result.local_tools) <= 4  # a + 3 levels of includes

    def test_missing_carapace(self):
        result = resolve_carapaces(["nonexistent"])
        assert result.skills == []
        assert result.local_tools == []

    def test_skill_string_entry(self):
        _registry["c"] = _make_carapace("c", skills=["my-skill"])
        result = resolve_carapaces(["c"])
        assert len(result.skills) == 1
        assert result.skills[0].id == "my-skill"
        assert result.skills[0].mode == "on_demand"

    def test_mcp_tools(self):
        _registry["c"] = _make_carapace("c", mcp_tools=["homeassistant", "github"])
        result = resolve_carapaces(["c"])
        assert result.mcp_tools == ["homeassistant", "github"]

    def test_empty_fragment_ignored(self):
        _registry["c"] = _make_carapace("c", system_prompt_fragment="   ")
        result = resolve_carapaces(["c"])
        assert result.system_prompt_fragments == []

    def test_diamond_includes(self):
        """A includes B and C; both B and C include D. D should only appear once."""
        _registry["d"] = _make_carapace("d", local_tools=["t_d"], system_prompt_fragment="D")
        _registry["b"] = _make_carapace("b", includes=["d"], local_tools=["t_b"])
        _registry["c"] = _make_carapace("c", includes=["d"], local_tools=["t_c"])
        _registry["a"] = _make_carapace("a", includes=["b", "c"])
        result = resolve_carapaces(["a"])
        # t_d should appear once (from b's include of d)
        assert result.local_tools.count("t_d") == 1
        assert "t_b" in result.local_tools
        assert "t_c" in result.local_tools
        # D's fragment should appear once (from b's resolution)
        assert result.system_prompt_fragments.count("D") == 1
