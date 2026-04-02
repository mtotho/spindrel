"""Tests for query_feed_store tool."""

import json
from unittest.mock import patch

import pytest

from integrations.ingestion.store import IngestionStore
from integrations.ingestion.tools.feed_store import (
    _discover_stores,
    _open_readonly,
    query_feed_store,
)


@pytest.fixture
def ingestion_dir(tmp_path):
    """Create a temp ingestion dir with a seeded gmail.db store."""
    ingestion = tmp_path / ".ingestion"
    ingestion.mkdir()

    db_path = ingestion / "gmail.db"
    store = IngestionStore(db_path)
    # Seed data
    for i in range(5):
        store.audit("gmail", f"msg-{i}", "passed", "low")
    store.audit("gmail", "q-1", "quarantined", "high")
    store.quarantine("gmail", "q-1", "bad email", "high", ["injection"], "prompt injection detected")
    store.quarantine("gmail", "q-2", "suspicious", "medium", [], "suspicious links")
    store.set_cursor("gmail", "uid-500")
    store.close()

    # Also create an empty rss.db
    rss_path = ingestion / "rss.db"
    rss_store = IngestionStore(rss_path)
    rss_store.audit("rss", "entry-1", "passed", "low")
    rss_store.close()

    return ingestion


@pytest.fixture
def mock_ingestion_dir(ingestion_dir):
    """Patch the ingestion directory for tool functions."""
    with patch("integrations.ingestion.tools.feed_store.INGESTION_DB_DIR", str(ingestion_dir)):
        yield ingestion_dir


class TestDiscoverStores:
    def test_discovers_db_files(self, mock_ingestion_dir):
        stores = _discover_stores()
        assert "gmail" in stores
        assert "rss" in stores
        assert stores["gmail"].suffix == ".db"

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch("integrations.ingestion.tools.feed_store.INGESTION_DB_DIR", str(empty)):
            stores = _discover_stores()
        assert stores == {}

    def test_missing_dir(self, tmp_path):
        with patch("integrations.ingestion.tools.feed_store.INGESTION_DB_DIR", str(tmp_path / "nonexistent")):
            stores = _discover_stores()
        assert stores == {}


class TestOpenReadonly:
    def test_opens_store_readonly(self, mock_ingestion_dir):
        stores = _discover_stores()
        db = _open_readonly(stores["gmail"])
        # Can read
        sources = db.list_sources()
        assert "gmail" in sources
        db.close()


class TestQueryFeedStoreActions:
    @pytest.mark.asyncio
    async def test_sources_action(self, mock_ingestion_dir):
        result = await query_feed_store(action="sources")
        data = json.loads(result)
        names = [s["store"] for s in data]
        assert "gmail" in names
        assert "rss" in names

    @pytest.mark.asyncio
    async def test_sources_no_stores(self, tmp_path):
        with patch("integrations.ingestion.tools.feed_store.INGESTION_DB_DIR", str(tmp_path / "nope")):
            result = await query_feed_store(action="sources")
        assert "No feed stores found" in result

    @pytest.mark.asyncio
    async def test_stats_action(self, mock_ingestion_dir):
        result = await query_feed_store(action="stats", store="gmail")
        data = json.loads(result)
        assert data["total_processed"] == 6  # 5 passed + 1 quarantined audit
        assert data["total_quarantined"] == 2
        # No source filter → no cursor returned
        assert data["last_cursor"] is None

    @pytest.mark.asyncio
    async def test_stats_with_source_filter(self, mock_ingestion_dir):
        result = await query_feed_store(action="stats", store="gmail", source="gmail")
        data = json.loads(result)
        assert data["total_processed"] == 6

    @pytest.mark.asyncio
    async def test_recent_action(self, mock_ingestion_dir):
        result = await query_feed_store(action="recent", store="gmail")
        data = json.loads(result)
        assert len(data) == 5
        assert all(item["action"] == "passed" for item in data)

    @pytest.mark.asyncio
    async def test_recent_with_limit(self, mock_ingestion_dir):
        result = await query_feed_store(action="recent", store="gmail", limit=2)
        data = json.loads(result)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_quarantine_action(self, mock_ingestion_dir):
        result = await query_feed_store(action="quarantine", store="gmail")
        data = json.loads(result)
        assert len(data) == 2
        flagged = [d for d in data if d["flags"]]
        assert len(flagged) == 1
        assert "injection" in flagged[0]["flags"]

    @pytest.mark.asyncio
    async def test_missing_store_param(self, mock_ingestion_dir):
        result = await query_feed_store(action="stats")
        assert "Missing required 'store' parameter" in result
        assert "gmail" in result

    @pytest.mark.asyncio
    async def test_unknown_store(self, mock_ingestion_dir):
        result = await query_feed_store(action="stats", store="nonexistent")
        assert "not found" in result
        assert "gmail" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_ingestion_dir):
        result = await query_feed_store(action="bogus", store="gmail")
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_empty_recent(self, mock_ingestion_dir):
        result = await query_feed_store(action="recent", store="gmail", source="nonexistent")
        assert "No recent passed items" in result

    @pytest.mark.asyncio
    async def test_empty_quarantine(self, mock_ingestion_dir):
        result = await query_feed_store(action="quarantine", store="rss")
        assert "No quarantined items" in result
