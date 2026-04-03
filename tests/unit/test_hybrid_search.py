"""Tests for app.agent.hybrid_search — Reciprocal Rank Fusion."""
from __future__ import annotations

import pytest

from app.agent.hybrid_search import reciprocal_rank_fusion


class TestReciprocalRankFusion:
    def test_basic_fusion(self):
        """Two lists with overlapping items get higher RRF scores."""
        list_a = [("doc1",), ("doc2",), ("doc3",)]
        list_b = [("doc2",), ("doc1",), ("doc4",)]

        fused = reciprocal_rank_fusion(list_a, list_b, k=60)

        # doc1 and doc2 appear in both lists -> higher scores
        items = [item for item, score in fused]
        # doc1: rank 0 in A (1/61) + rank 1 in B (1/62) = 0.01639 + 0.01613 = 0.03252
        # doc2: rank 1 in A (1/62) + rank 0 in B (1/61) = 0.01613 + 0.01639 = 0.03252
        # doc3: rank 2 in A (1/63) = 0.01587
        # doc4: rank 2 in B (1/63) = 0.01587
        assert len(fused) == 4

        # doc1 and doc2 should be at top (tied scores, both in both lists)
        top_two = {items[0][0], items[1][0]}
        assert top_two == {"doc1", "doc2"}

    def test_single_list(self):
        """Single list preserves original order."""
        single = [("a",), ("b",), ("c",)]
        fused = reciprocal_rank_fusion(single, k=60)

        items = [item[0] for item, score in fused]
        assert items == ["a", "b", "c"]

    def test_empty_lists(self):
        """Empty lists return empty result."""
        fused = reciprocal_rank_fusion([], [], k=60)
        assert fused == []

    def test_no_overlap(self):
        """Disjoint lists: all items present, ordered by rank."""
        list_a = [("x",), ("y",)]
        list_b = [("a",), ("b",)]

        fused = reciprocal_rank_fusion(list_a, list_b, k=60)
        assert len(fused) == 4

        # All items from rank 0 should tie (1/61 each)
        items = [item[0] for item, _ in fused]
        assert set(items) == {"x", "y", "a", "b"}

    def test_disjoint_sets(self):
        """Completely disjoint: each appears once with score 1/(k+rank+1)."""
        list_a = [("only_a",)]
        list_b = [("only_b",)]

        fused = reciprocal_rank_fusion(list_a, list_b, k=60)
        assert len(fused) == 2

        # Both have same rank (0) -> same score
        scores = [score for _, score in fused]
        assert abs(scores[0] - scores[1]) < 1e-10

    def test_k_parameter_effect(self):
        """Lower k gives more weight to top-ranked items."""
        list_a = [("top",), ("bottom",)]
        list_b = [("bottom",), ("top",)]

        # With k=1: top gets 1/2 + 1/3 = 0.833, bottom gets 1/3 + 1/2 = 0.833 (tied)
        fused_low_k = reciprocal_rank_fusion(list_a, list_b, k=1)
        # Both should have equal scores
        scores = {item[0]: score for item, score in fused_low_k}
        assert abs(scores["top"] - scores["bottom"]) < 1e-10

    def test_three_lists(self):
        """Fusion works with three ranked lists."""
        list_a = [("d1",), ("d2",)]
        list_b = [("d2",), ("d3",)]
        list_c = [("d1",), ("d3",)]

        fused = reciprocal_rank_fusion(list_a, list_b, list_c, k=60)
        assert len(fused) == 3

        # d1 appears in A(0) + C(0) = 2 * 1/61 = 0.03279
        # d2 appears in A(1) + B(0) = 1/62 + 1/61 = 0.03252
        # d3 appears in B(1) + C(1) = 2 * 1/62 = 0.03226
        items = [item[0] for item, _ in fused]
        assert items[0] == "d1"  # highest score

    def test_duplicate_within_list(self):
        """Duplicates within a single list are handled (last occurrence wins)."""
        # This is an edge case — normally lists shouldn't have dupes
        list_a = [("a",), ("b",), ("a",)]  # 'a' appears twice

        fused = reciprocal_rank_fusion(list_a, k=60)
        # 'a' gets score from rank 0 and rank 2 (both added)
        assert len(fused) == 2  # only 2 unique items

    def test_negative_k_raises(self):
        with pytest.raises(ValueError, match="positive"):
            reciprocal_rank_fusion([("a",)], k=-1)

    def test_zero_k_raises(self):
        with pytest.raises(ValueError, match="positive"):
            reciprocal_rank_fusion([("a",)], k=0)
