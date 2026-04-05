"""Unit tests for pure helpers in app.services.context_estimate."""
import json

from app.services.context_estimate import (
    _clamp,
    _memory_knowledge_hit_factor,
    _parse_skill_entries,
    _rag_retrieval_factor,
    _schema_json_chars,
)


# ---------------------------------------------------------------------------
# _schema_json_chars
# ---------------------------------------------------------------------------

class TestSchemaJsonChars:
    def test_basic(self):
        schema = {"type": "function", "function": {"name": "test"}}
        expected = len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False))
        assert _schema_json_chars(schema) == expected

    def test_empty(self):
        assert _schema_json_chars({}) == 2  # "{}"


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------

class TestClamp:
    def test_within_range(self):
        assert _clamp(5.0, 0.0, 10.0) == 5.0

    def test_below_lo(self):
        assert _clamp(-1.0, 0.0, 10.0) == 0.0

    def test_above_hi(self):
        assert _clamp(15.0, 0.0, 10.0) == 10.0

    def test_at_lo(self):
        assert _clamp(0.0, 0.0, 10.0) == 0.0

    def test_at_hi(self):
        assert _clamp(10.0, 0.0, 10.0) == 10.0


# ---------------------------------------------------------------------------
# _parse_skill_entries
# ---------------------------------------------------------------------------

class TestParseSkillEntries:
    def test_strings_are_on_demand(self):
        pinned, on_demand = _parse_skill_entries(["skill1", "skill2"])
        assert len(on_demand) == 2
        assert on_demand[0]["id"] == "skill1"
        assert pinned == []

    def test_pinned_dict(self):
        pinned, on_demand = _parse_skill_entries([{"id": "s1", "mode": "pinned"}])
        assert len(pinned) == 1
        assert pinned[0]["mode"] == "pinned"

    def test_rag_dict_falls_to_on_demand(self):
        """Legacy rag mode entries should land in on_demand bucket."""
        pinned, on_demand = _parse_skill_entries([{"id": "s1", "mode": "rag"}])
        assert len(on_demand) == 1
        assert pinned == []

    def test_default_mode_on_demand(self):
        pinned, on_demand = _parse_skill_entries([{"id": "s1"}])
        assert len(on_demand) == 1

    def test_non_string_non_dict(self):
        pinned, on_demand = _parse_skill_entries([42])
        assert len(on_demand) == 1
        assert on_demand[0]["id"] == "42"


# ---------------------------------------------------------------------------
# _rag_retrieval_factor
# ---------------------------------------------------------------------------

class TestRagRetrievalFactor:
    def test_in_range(self):
        f = _rag_retrieval_factor(0.35)
        assert 0.15 <= f <= 0.92

    def test_high_threshold_lower_factor(self):
        f_high = _rag_retrieval_factor(0.8)
        f_low = _rag_retrieval_factor(0.2)
        assert f_high < f_low


# ---------------------------------------------------------------------------
# _memory_knowledge_hit_factor
# ---------------------------------------------------------------------------

class TestMemoryKnowledgeHitFactor:
    def test_in_range(self):
        f = _memory_knowledge_hit_factor(0.45)
        assert 0.22 <= f <= 0.95

    def test_high_threshold_lower_factor(self):
        f_high = _memory_knowledge_hit_factor(0.8)
        f_low = _memory_knowledge_hit_factor(0.2)
        assert f_high < f_low
