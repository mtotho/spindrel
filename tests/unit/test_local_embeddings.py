"""Tests for app.agent.local_embeddings — prefix helpers + model listing + cache detection."""
from unittest.mock import MagicMock, patch

from app.agent.local_embeddings import (
    LOCAL_PREFIX,
    KNOWN_MODELS,
    download_model_sync,
    get_model_size_mb,
    is_local_model,
    is_model_cached,
    list_local_models,
    strip_prefix,
)


class TestIsLocalModel:
    def test_local_prefix(self):
        assert is_local_model("local/BAAI/bge-small-en-v1.5") is True

    def test_non_local(self):
        assert is_local_model("text-embedding-3-small") is False

    def test_empty(self):
        assert is_local_model("") is False

    def test_partial_prefix(self):
        assert is_local_model("loca/something") is False


class TestStripPrefix:
    def test_strips(self):
        assert strip_prefix("local/BAAI/bge-small-en-v1.5") == "BAAI/bge-small-en-v1.5"

    def test_no_prefix(self):
        assert strip_prefix("text-embedding-3-small") == "text-embedding-3-small"


class TestGetModelSizeMb:
    def test_known_model(self):
        size = get_model_size_mb("BAAI/bge-small-en-v1.5")
        assert size is not None
        assert size > 0

    def test_unknown_model(self):
        assert get_model_size_mb("unknown/model") is None


class TestIsModelCached:
    def test_returns_false_when_fastembed_unavailable(self):
        with patch("app.agent.local_embeddings._fastembed_available", return_value=False):
            assert is_model_cached("BAAI/bge-small-en-v1.5") is False

    def test_returns_false_when_cache_dir_missing(self):
        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings._get_cache_dir", return_value="/nonexistent/path"),
            patch("app.agent.local_embeddings.Path") as mock_path,
        ):
            mock_path.return_value.exists.return_value = False
            assert is_model_cached("BAAI/bge-small-en-v1.5") is False

    def test_returns_true_when_model_in_cache(self):
        mock_rev = MagicMock()
        mock_rev.nb_files = 5
        mock_repo = MagicMock()
        mock_repo.repo_id = "BAAI/bge-small-en-v1.5"
        mock_repo.revisions = [mock_rev]
        mock_cache_info = MagicMock()
        mock_cache_info.repos = [mock_repo]

        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings._get_cache_dir", return_value="/some/cache"),
            patch("app.agent.local_embeddings.Path") as mock_path,
            patch("huggingface_hub.scan_cache_dir", return_value=mock_cache_info),
        ):
            mock_path.return_value.exists.return_value = True
            assert is_model_cached("BAAI/bge-small-en-v1.5") is True

    def test_returns_false_when_model_not_in_cache(self):
        mock_repo = MagicMock()
        mock_repo.repo_id = "other/model"
        mock_repo.revisions = []
        mock_cache_info = MagicMock()
        mock_cache_info.repos = [mock_repo]

        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings._get_cache_dir", return_value="/some/cache"),
            patch("app.agent.local_embeddings.Path") as mock_path,
            patch("huggingface_hub.scan_cache_dir", return_value=mock_cache_info),
        ):
            mock_path.return_value.exists.return_value = True
            assert is_model_cached("BAAI/bge-small-en-v1.5") is False

    def test_returns_false_on_exception(self):
        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings._get_cache_dir", side_effect=Exception("boom")),
        ):
            assert is_model_cached("BAAI/bge-small-en-v1.5") is False


class TestListLocalModels:
    def test_returns_models_when_fastembed_available(self):
        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings.is_model_cached", return_value=False),
        ):
            models = list_local_models()
        assert len(models) == len(KNOWN_MODELS)
        for m in models:
            assert m["id"].startswith(LOCAL_PREFIX)
            assert "dimensions" in m
            assert "download_status" in m
            assert "size_mb" in m
            assert m["download_status"] == "not_downloaded"

    def test_returns_cached_status(self):
        with (
            patch("app.agent.local_embeddings._fastembed_available", return_value=True),
            patch("app.agent.local_embeddings.is_model_cached", return_value=True),
        ):
            models = list_local_models()
        assert all(m["download_status"] == "cached" for m in models)

    def test_returns_empty_when_fastembed_unavailable(self):
        with patch("app.agent.local_embeddings._fastembed_available", return_value=False):
            models = list_local_models()
        assert models == []


class TestDownloadModelSync:
    def test_raises_when_fastembed_unavailable(self):
        with patch.dict("sys.modules", {"fastembed": None}):
            try:
                download_model_sync("BAAI/bge-small-en-v1.5")
                assert False, "Should have raised"
            except (RuntimeError, ImportError):
                pass

    def test_calls_text_embedding(self):
        mock_te_class = MagicMock()
        mock_te_instance = MagicMock()
        mock_te_class.return_value = mock_te_instance

        mock_fastembed = MagicMock()
        mock_fastembed.TextEmbedding = mock_te_class

        with (
            patch.dict("sys.modules", {"fastembed": mock_fastembed}),
            patch("app.agent.local_embeddings._get_cache_dir", return_value=None),
        ):
            download_model_sync("BAAI/bge-small-en-v1.5")
            mock_te_class.assert_called_once_with(
                model_name="BAAI/bge-small-en-v1.5", cache_dir=None
            )
