"""Tests for the in-memory pinned-path reverse index."""
import uuid
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pinned_panels import (
    _pinned_paths,
    is_path_pinned,
    _mimetype_for_path,
)


class TestMimetypeForPath:
    def test_markdown(self):
        assert _mimetype_for_path("report.md") == "text/markdown"
        assert _mimetype_for_path("notes.mdx") == "text/markdown"

    def test_json(self):
        assert _mimetype_for_path("data.json") == "application/json"

    def test_html(self):
        assert _mimetype_for_path("page.html") == "text/html"

    def test_plain(self):
        assert _mimetype_for_path("script.py") == "text/x-python"

    def test_unknown_extension(self):
        assert _mimetype_for_path("file.xyz123") == "text/plain"

    def test_no_extension(self):
        assert _mimetype_for_path("Makefile") == "text/plain"


class TestIsPinned:
    def setup_method(self):
        _pinned_paths.clear()

    def teardown_method(self):
        _pinned_paths.clear()

    def test_empty_cache_returns_empty_set(self):
        assert is_path_pinned("anything.md") == set()

    def test_returns_matching_channel_ids(self):
        cid1 = uuid.uuid4()
        cid2 = uuid.uuid4()
        _pinned_paths["report.md"].add(cid1)
        _pinned_paths["report.md"].add(cid2)
        result = is_path_pinned("report.md")
        assert result == {cid1, cid2}

    def test_non_pinned_path_returns_empty(self):
        _pinned_paths["other.md"].add(uuid.uuid4())
        assert is_path_pinned("report.md") == set()


class TestNotifyPinnedFileChanged:
    def setup_method(self):
        _pinned_paths.clear()

    def teardown_method(self):
        _pinned_paths.clear()

    @pytest.mark.asyncio
    async def test_no_publish_when_path_not_pinned(self):
        with patch("app.services.channel_events.publish_typed") as mock_pub:
            from app.services.pinned_panels import notify_pinned_file_changed
            await notify_pinned_file_changed("not-pinned.md")
            mock_pub.assert_not_called()

    @pytest.mark.asyncio
    async def test_publishes_to_each_pinned_channel(self):
        cid1 = uuid.uuid4()
        cid2 = uuid.uuid4()
        _pinned_paths["report.md"].add(cid1)
        _pinned_paths["report.md"].add(cid2)

        with patch("app.services.channel_events.publish_typed") as mock_pub:
            from app.services.pinned_panels import notify_pinned_file_changed
            await notify_pinned_file_changed("report.md")
            assert mock_pub.call_count == 2
            channel_ids = {call.args[0] for call in mock_pub.call_args_list}
            assert channel_ids == {cid1, cid2}
