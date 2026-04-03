"""Tests for app.services.cross_encoder."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services.cross_encoder import rerank_sync, rerank_async, _loaded_models


class TestRerankSync:
    def setup_method(self):
        _loaded_models.clear()

    def test_empty_documents(self):
        scores = rerank_sync("query", [], model_name="test-model")
        assert scores == []

    @patch("app.services.cross_encoder._get_or_load_model")
    def test_scores_in_original_order(self, mock_load):
        mock_encoder = MagicMock()
        # fastembed TextCrossEncoder.rerank returns Iterable[float] in document order
        mock_encoder.rerank.return_value = [0.5, 0.9, 0.1]
        mock_load.return_value = mock_encoder

        scores = rerank_sync("query", ["doc0", "doc1", "doc2"], model_name="test-model")
        assert len(scores) == 3
        assert scores[0] == 0.5  # doc0
        assert scores[1] == 0.9  # doc1
        assert scores[2] == 0.1  # doc2

    @patch("app.services.cross_encoder._get_or_load_model")
    def test_single_document(self, mock_load):
        mock_encoder = MagicMock()
        mock_encoder.rerank.return_value = [0.8]
        mock_load.return_value = mock_encoder

        scores = rerank_sync("query", ["only doc"], model_name="test-model")
        assert scores == [0.8]

    @patch("app.services.cross_encoder._get_or_load_model")
    def test_passes_query_and_docs_to_encoder(self, mock_load):
        mock_encoder = MagicMock()
        mock_encoder.rerank.return_value = [0.5, 0.3]
        mock_load.return_value = mock_encoder

        rerank_sync("my query", ["doc A", "doc B"], model_name="test-model")
        mock_encoder.rerank.assert_called_once_with("my query", ["doc A", "doc B"])

    @patch("app.services.cross_encoder._get_or_load_model")
    def test_handles_generator_return(self, mock_load):
        """fastembed may return a generator; rerank_sync should consume it."""
        mock_encoder = MagicMock()
        mock_encoder.rerank.return_value = iter([0.9, 0.1])
        mock_load.return_value = mock_encoder

        scores = rerank_sync("query", ["doc0", "doc1"], model_name="test-model")
        assert scores == [0.9, 0.1]


class TestRerankAsync:
    def setup_method(self):
        _loaded_models.clear()

    @pytest.mark.asyncio
    @patch("app.services.cross_encoder._get_or_load_model")
    async def test_async_wrapper(self, mock_load):
        mock_encoder = MagicMock()
        # fastembed returns Iterable[float] in document order
        mock_encoder.rerank.return_value = [0.7, 0.3]
        mock_load.return_value = mock_encoder

        scores = await rerank_async("query", ["doc0", "doc1"], model_name="test-model")
        assert scores == [0.7, 0.3]

    @pytest.mark.asyncio
    async def test_import_error_raises(self):
        with patch("app.services.cross_encoder._get_or_load_model", side_effect=RuntimeError("fastembed not installed")):
            with pytest.raises(RuntimeError, match="fastembed"):
                await rerank_async("query", ["doc"], model_name="test-model")


class TestModelLoading:
    def setup_method(self):
        _loaded_models.clear()

    def test_cached_model_reused(self):
        sentinel = MagicMock()
        _loaded_models["cached-model"] = sentinel
        from app.services.cross_encoder import _get_or_load_model
        result = _get_or_load_model("cached-model")
        assert result is sentinel

    def test_fastembed_unavailable_raises(self):
        """When fastembed.rerank.cross_encoder can't be imported, RuntimeError is raised."""
        import sys
        from app.services.cross_encoder import _get_or_load_model
        _loaded_models.clear()
        # Temporarily remove fastembed from sys.modules to force re-import
        saved = {}
        keys_to_remove = [k for k in sys.modules if k.startswith("fastembed")]
        for k in keys_to_remove:
            saved[k] = sys.modules.pop(k)
        # Block the import
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if "fastembed" in name:
                raise ImportError("no fastembed")
            return real_import(name, *args, **kwargs)
        try:
            builtins.__import__ = fake_import
            with pytest.raises(RuntimeError, match="fastembed"):
                _get_or_load_model("nonexistent-model")
        finally:
            builtins.__import__ = real_import
            sys.modules.update(saved)

    @patch("app.services.cross_encoder._fastembed_rerank_available", return_value=False)
    def test_availability_check(self, mock_avail):
        from app.services.cross_encoder import _fastembed_rerank_available
        assert not _fastembed_rerank_available()
