"""Tests for app.agent.vector_ops — halfvec cosine distance utility."""
from unittest.mock import MagicMock, patch

import pytest

from app.agent import vector_ops


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level cache between tests."""
    vector_ops._halfvec_available = None
    yield
    vector_ops._halfvec_available = None


class TestCheckHalfvec:
    def test_available_when_import_succeeds(self):
        """HALFVEC importable + PostgreSQL → returns True."""
        with patch.object(vector_ops.settings, "DATABASE_URL", "postgresql://localhost/test"):
            assert vector_ops._check_halfvec() is True

    def test_unavailable_on_sqlite(self):
        """HALFVEC importable but SQLite → returns False."""
        with patch.object(vector_ops.settings, "DATABASE_URL", "sqlite:///test.db"):
            assert vector_ops._check_halfvec() is False

    def test_caches_result(self):
        """Second call uses cached value without re-importing."""
        vector_ops._check_halfvec()
        vector_ops._halfvec_available = False  # override cache
        assert vector_ops._check_halfvec() is False  # uses cached

    def test_unavailable_when_import_fails(self):
        """HALFVEC not importable → returns False."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pgvector.sqlalchemy":
                raise ImportError("no pgvector")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            vector_ops._halfvec_available = None
            assert vector_ops._check_halfvec() is False


class TestHalfvecCosineDistance:
    def test_fallback_when_unavailable(self):
        """When HALFVEC is unavailable, falls back to column.cosine_distance()."""
        vector_ops._halfvec_available = False
        col = MagicMock()
        query = [0.1, 0.2, 0.3]
        result = vector_ops.halfvec_cosine_distance(col, query, dims=3)
        col.cosine_distance.assert_called_once_with(query)
        assert result == col.cosine_distance.return_value

    def test_halfvec_cast_when_available(self):
        """When HALFVEC is available, uses cast + type_coerce."""
        vector_ops._halfvec_available = True
        col = MagicMock()
        query = [0.1] * 1536
        result = vector_ops.halfvec_cosine_distance(col, query)
        # Should call col.cast(...).cosine_distance(...)
        col.cast.assert_called_once()
        cast_arg = col.cast.call_args[0][0]
        from pgvector.sqlalchemy import HALFVEC
        assert isinstance(cast_arg, HALFVEC)
        col.cast.return_value.cosine_distance.assert_called_once()

    def test_custom_dims(self):
        """Custom dims parameter is respected."""
        vector_ops._halfvec_available = True
        col = MagicMock()
        query = [0.1] * 768
        vector_ops.halfvec_cosine_distance(col, query, dims=768)
        from pgvector.sqlalchemy import HALFVEC
        cast_arg = col.cast.call_args[0][0]
        assert isinstance(cast_arg, HALFVEC)
        assert cast_arg.dim == 768

    def test_default_dims_from_settings(self):
        """Defaults to settings.EMBEDDING_DIMENSIONS when dims not specified."""
        vector_ops._halfvec_available = True
        col = MagicMock()
        query = [0.1] * 10
        with patch.object(vector_ops.settings, "EMBEDDING_DIMENSIONS", 256):
            vector_ops.halfvec_cosine_distance(col, query)
        from pgvector.sqlalchemy import HALFVEC
        cast_arg = col.cast.call_args[0][0]
        assert cast_arg.dim == 256
