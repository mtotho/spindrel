"""Unit tests for _match_segment helper in fs_indexer."""
import pytest

from app.agent.fs_indexer import _match_segment


class TestMatchSegment:
    """Test segment matching by path prefix (longest prefix wins)."""

    def _seg(self, prefix: str, model: str = "default") -> dict:
        return {"path_prefix": prefix, "embedding_model": model}

    def test_no_segments_returns_none(self):
        assert _match_segment("src/main.py", None) is None
        assert _match_segment("src/main.py", []) is None

    def test_exact_prefix_match(self):
        segments = [self._seg("src/")]
        result = _match_segment("src/main.py", segments)
        assert result is not None
        assert result["path_prefix"] == "src/"

    def test_no_match_returns_none(self):
        segments = [self._seg("src/")]
        assert _match_segment("docs/readme.md", segments) is None

    def test_longest_prefix_wins(self):
        segments = [
            self._seg("src/", "model-a"),
            self._seg("src/core/", "model-b"),
            self._seg("src/core/utils/", "model-c"),
        ]
        # Most specific match
        result = _match_segment("src/core/utils/helpers.py", segments)
        assert result["path_prefix"] == "src/core/utils/"
        assert result["embedding_model"] == "model-c"

        # Mid-level match
        result = _match_segment("src/core/engine.py", segments)
        assert result["path_prefix"] == "src/core/"
        assert result["embedding_model"] == "model-b"

        # Top-level match
        result = _match_segment("src/app.py", segments)
        assert result["path_prefix"] == "src/"
        assert result["embedding_model"] == "model-a"

    def test_prefix_without_trailing_slash(self):
        """Prefix without trailing slash should still match as directory prefix."""
        segments = [self._seg("src")]
        result = _match_segment("src/main.py", segments)
        assert result is not None
        assert result["path_prefix"] == "src"

    def test_prefix_does_not_partial_match_dirname(self):
        """'src' should not match 'srclib/foo.py'."""
        segments = [self._seg("src")]
        assert _match_segment("srclib/foo.py", segments) is None

    def test_exact_file_match(self):
        """Exact path match (path_prefix == file path)."""
        segments = [self._seg("config.yaml")]
        result = _match_segment("config.yaml", segments)
        assert result is not None

    def test_multiple_segments_order_independent(self):
        """Longest prefix wins regardless of list order."""
        segments = [
            self._seg("a/b/c/", "deep"),
            self._seg("a/", "shallow"),
            self._seg("a/b/", "mid"),
        ]
        result = _match_segment("a/b/c/d.py", segments)
        assert result["embedding_model"] == "deep"
