"""Tests for channel_id filtering on IndexSegment / retrieval."""
import pytest

from app.agent.bots import IndexSegment
from app.agent.fs_indexer import _excluded_prefixes
from app.services.workspace_indexing import _resolve_segments


# ---------------------------------------------------------------------------
# _excluded_prefixes
# ---------------------------------------------------------------------------

class TestExcludedPrefixes:
    """Test that _excluded_prefixes correctly identifies segments to skip."""

    def _seg(self, prefix: str, channel_id: str | None = None) -> dict:
        return {"path_prefix": prefix, "channel_id": channel_id, "embedding_model": "m"}

    def test_no_segments_returns_empty(self):
        assert _excluded_prefixes(None, "ch-1") == []
        assert _excluded_prefixes([], "ch-1") == []

    def test_no_channel_id_on_segment_always_included(self):
        """Segments without channel_id are never excluded."""
        segs = [self._seg("michael/"), self._seg("docs/")]
        assert _excluded_prefixes(segs, "ch-1") == []
        assert _excluded_prefixes(segs, None) == []

    def test_matching_channel_not_excluded(self):
        """Segment with matching channel_id is not excluded."""
        segs = [self._seg("C0AMSUWBHPU/", channel_id="ch-1")]
        assert _excluded_prefixes(segs, "ch-1") == []

    def test_non_matching_channel_excluded(self):
        """Segment with non-matching channel_id is excluded."""
        segs = [self._seg("C0AMSUWBHPU/", channel_id="ch-1")]
        assert _excluded_prefixes(segs, "ch-2") == ["C0AMSUWBHPU/"]

    def test_no_active_channel_excludes_all_gated(self):
        """When no active channel, all channel-gated segments are excluded."""
        segs = [
            self._seg("michael/"),
            self._seg("C0AMSUWBHPU/", channel_id="ch-1"),
            self._seg("private/", channel_id="ch-2"),
        ]
        result = _excluded_prefixes(segs, None)
        assert "C0AMSUWBHPU/" in result
        assert "private/" in result
        assert "michael/" not in result

    def test_mixed_segments(self):
        """Mix of global, matching, and non-matching segments."""
        segs = [
            self._seg("shared/"),                              # global → never excluded
            self._seg("channel-a/", channel_id="ch-a"),        # matches → not excluded
            self._seg("channel-b/", channel_id="ch-b"),        # doesn't match → excluded
        ]
        result = _excluded_prefixes(segs, "ch-a")
        assert result == ["channel-b/"]

    def test_channel_id_compared_as_string(self):
        """UUID channel_id is stringified for comparison."""
        import uuid
        uid = uuid.uuid4()
        segs = [self._seg("data/", channel_id=str(uid))]
        # Pass UUID object — should be stringified
        assert _excluded_prefixes(segs, uid) == []
        assert _excluded_prefixes(segs, uuid.uuid4()) == ["data/"]


# ---------------------------------------------------------------------------
# _resolve_segments preserves channel_id
# ---------------------------------------------------------------------------

class TestResolveSegmentsChannelId:
    """Test that _resolve_segments passes channel_id through."""

    def test_channel_id_preserved(self):
        base = {
            "embedding_model": "m1",
            "patterns": ["**/*.py"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
        }
        segs = [
            IndexSegment(path_prefix="shared/"),
            IndexSegment(path_prefix="private/", channel_id="ch-123"),
        ]
        result = _resolve_segments(segs, base)
        assert result[0]["channel_id"] is None
        assert result[1]["channel_id"] == "ch-123"

    def test_channel_id_none_by_default(self):
        base = {
            "embedding_model": "m1",
            "patterns": ["**/*.py"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
        }
        segs = [IndexSegment(path_prefix="lib/")]
        result = _resolve_segments(segs, base)
        assert result[0]["channel_id"] is None


# ---------------------------------------------------------------------------
# IndexSegment dataclass
# ---------------------------------------------------------------------------

class TestIndexSegmentDataclass:
    """Test that IndexSegment accepts and stores channel_id."""

    def test_default_none(self):
        seg = IndexSegment(path_prefix="src/")
        assert seg.channel_id is None

    def test_explicit_channel_id(self):
        seg = IndexSegment(path_prefix="data/", channel_id="abc-123")
        assert seg.channel_id == "abc-123"
