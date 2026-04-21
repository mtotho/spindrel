"""Unit tests for enforce_turn_aggregate_cap.

Guards the second-layer defense that runs after per-tool TOOL_RESULT_HARD_CAP —
N parallel tools each under per-tool cap can still collectively blow the
context window.
"""
from __future__ import annotations

from app.agent.tool_dispatch import ToolCallResult, enforce_turn_aggregate_cap


def _make(result: str) -> ToolCallResult:
    return ToolCallResult(result=result, result_for_llm=result)


class TestEnforceTurnAggregateCap:
    def test_disabled_cap_never_trims(self):
        results = [_make("x" * 100_000) for _ in range(5)]
        trimmed = enforce_turn_aggregate_cap(results, 0)
        assert trimmed == 0
        for r in results:
            assert len(r.result_for_llm) == 100_000

    def test_under_cap_passes_through(self):
        results = [_make("x" * 10_000) for _ in range(3)]
        trimmed = enforce_turn_aggregate_cap(results, 150_000)
        assert trimmed == 0
        for r in results:
            assert len(r.result_for_llm) == 10_000
            assert "Turn-aggregate cap" not in r.result_for_llm

    def test_over_cap_trims_biggest_first(self):
        # 3 results: one whale (80k), two small (10k each) — total 100k
        # Cap at 60k — whale gets hit, smalls untouched
        results = [_make("a" * 80_000), _make("b" * 10_000), _make("c" * 10_000)]
        trimmed = enforce_turn_aggregate_cap(results, 60_000)
        assert trimmed >= 40_000
        total_after = sum(len(r.result_for_llm) for r in results)
        # After trim the actual content is <= cap; the marker suffix adds a few chars
        # so the content itself is under, even if the decorated string runs slightly over.
        raw_after = sum(
            len(r.result_for_llm.split("\n\n[Turn-aggregate cap:")[0])
            for r in results
        )
        assert raw_after <= 60_000
        # Whale got the marker, smalls didn't
        assert "Turn-aggregate cap" in results[0].result_for_llm
        assert "Turn-aggregate cap" not in results[1].result_for_llm
        assert "Turn-aggregate cap" not in results[2].result_for_llm
        # Total is meaningfully smaller than the original 100k
        assert total_after < 100_000

    def test_multiple_whales_both_trim(self):
        # Two large results equal size — both should get trimmed when overage
        # exceeds what one of them can absorb at 50%.
        results = [_make("a" * 100_000), _make("b" * 100_000)]
        trimmed = enforce_turn_aggregate_cap(results, 60_000)
        # Both should have the marker since one-at-a-time 50%-shrink can't
        # cover 140k overage from the first alone.
        assert "Turn-aggregate cap" in results[0].result_for_llm
        assert "Turn-aggregate cap" in results[1].result_for_llm
        assert trimmed >= 140_000

    def test_empty_results_list(self):
        assert enforce_turn_aggregate_cap([], 1000) == 0

    def test_empty_result_strings(self):
        results = [_make(""), _make("")]
        assert enforce_turn_aggregate_cap(results, 1000) == 0
        for r in results:
            assert r.result_for_llm == ""

    def test_marker_preserves_truncated_content_prefix(self):
        # Trimmed content should be a prefix of original, not random bytes
        original = "abcdef" * 20_000  # 120k chars, deterministic pattern
        results = [_make(original)]
        enforce_turn_aggregate_cap(results, 50_000)
        trimmed_text = results[0].result_for_llm.split("\n\n[Turn-aggregate cap:")[0]
        assert original.startswith(trimmed_text)
        assert len(trimmed_text) < len(original)
