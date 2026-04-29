"""Unit tests for the provider-health aggregator helper.

Tests the `_percentile` math directly — the endpoint itself needs a FastAPI
TestClient which is a heavier pattern; the core aggregation logic is what
matters for correctness and can be pinned via the helper.
"""
from __future__ import annotations


class TestPercentile:
    def test_empty_list_returns_none(self):
        from app.services.usage_reports import _percentile
        assert _percentile([], 0.5) is None

    def test_single_element_returns_that_element(self):
        from app.services.usage_reports import _percentile
        assert _percentile([42.0], 0.5) == 42.0
        assert _percentile([42.0], 0.95) == 42.0

    def test_p50_of_sorted_list(self):
        from app.services.usage_reports import _percentile
        assert _percentile([1.0, 2.0, 3.0], 0.5) == 2.0

    def test_p95_interpolates_between_highest_two(self):
        from app.services.usage_reports import _percentile
        # 100 values [1..100]. p95 should be ~95-96 with linear interp.
        vals = [float(i) for i in range(1, 101)]
        p95 = _percentile(vals, 0.95)
        assert p95 is not None
        # linear interp at index 94.05 → 95.05
        assert 95.0 <= p95 <= 96.5

    def test_unsorted_input_is_sorted(self):
        from app.services.usage_reports import _percentile
        # Shuffled version of [1..5] — p50 should still be 3.0
        assert _percentile([5.0, 1.0, 3.0, 4.0, 2.0], 0.5) == 3.0
