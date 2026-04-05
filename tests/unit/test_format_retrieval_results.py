"""Tests for _format_retrieval_results — ensure top_k coercion handles string values."""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from app.agent.fs_indexer import _format_retrieval_results


def _make_row(distance: float, content: str = "chunk", file_path: str = "/a.py",
              symbol: str | None = None, start_line: int | None = None, end_line: int | None = None):
    return SimpleNamespace(
        distance=distance, content=content, file_path=file_path,
        symbol=symbol, start_line=start_line, end_line=end_line,
    )


def _mock_settings(top_k=5):
    s = MagicMock()
    s.FS_INDEX_TOP_K = top_k
    return s


class TestFormatRetrievalResults:
    def test_string_top_k_does_not_crash(self):
        """Regression: top_k passed as string from JSONB should not cause TypeError."""
        rows = [_make_row(0.2)]  # similarity = 0.8
        with patch("app.agent.fs_indexer.settings", _mock_settings()):
            results, best_sim = _format_retrieval_results(rows, 0.3, "test query", top_k="5")
        assert len(results) == 1
        assert best_sim == pytest.approx(0.8)

    def test_int_top_k_works(self):
        rows = [_make_row(0.1), _make_row(0.2), _make_row(0.3)]
        with patch("app.agent.fs_indexer.settings", _mock_settings()):
            results, _ = _format_retrieval_results(rows, 0.3, "q", top_k=2)
        assert len(results) == 2

    def test_none_top_k_falls_back_to_settings(self):
        rows = [_make_row(0.1)] * 10
        with patch("app.agent.fs_indexer.settings", _mock_settings(top_k=3)):
            results, _ = _format_retrieval_results(rows, 0.0, "q", top_k=None)
        assert len(results) == 3

    def test_empty_rows(self):
        results, best_sim = _format_retrieval_results([], 0.3, "q")
        assert results == []
        assert best_sim == 0.0

    def test_threshold_filters(self):
        rows = [_make_row(0.1), _make_row(0.8)]  # sims: 0.9, 0.2
        with patch("app.agent.fs_indexer.settings", _mock_settings()):
            results, _ = _format_retrieval_results(rows, 0.5, "q")
        assert len(results) == 1
