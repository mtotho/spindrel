"""Tests for ContentFeed base class and CycleResult."""

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from integrations.ingestion.classifier import ClassifierResult
from integrations.ingestion.config import IngestionConfig
from integrations.ingestion.envelope import ExternalMessage, RawMessage, RiskMetadata
from integrations.ingestion.feed import ContentFeed, CycleResult, FeedItem
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> IngestionStore:
    store = IngestionStore(db_path=":memory:")
    store._conn.row_factory = sqlite3.Row
    return store


def _make_pipeline(store: IngestionStore | None = None) -> IngestionPipeline:
    config = IngestionConfig(
        agent_base_url="http://localhost:8000",
        agent_api_key="test-key",
        classifier_url="http://localhost:8000/v1/chat/completions",
    )
    return IngestionPipeline(config=config, store=store or _make_store())


class MockFeed(ContentFeed):
    """Concrete subclass for testing."""

    source = "test"

    def __init__(self, pipeline, store, items=None, fetch_error=None):
        super().__init__(pipeline, store)
        self._items = items or []
        self._fetch_error = fetch_error

    async def fetch_items(self):
        if self._fetch_error:
            raise self._fetch_error
        return self._items


class FormattingFeed(ContentFeed):
    """Feed with custom format_item."""

    source = "formatted"

    def __init__(self, pipeline, store, items=None):
        super().__init__(pipeline, store)
        self._items = items or []

    async def fetch_items(self):
        return self._items

    def format_item(self, envelope):
        return FeedItem(
            title=f"[CUSTOM] {envelope.metadata.get('subject', 'no subject')}",
            body=f"# Email\n\n{envelope.body}",
            source_id=envelope.source_id,
            metadata=envelope.metadata,
            suggested_path=f"data/test/{envelope.source_id}.md",
            risk_level=envelope.risk.risk_level,
        )


def _raw(source_id="msg-1", content="Hello world", source="test", **meta):
    return RawMessage(source=source, source_id=source_id, raw_content=content, metadata=meta)


_SAFE = ClassifierResult(safe=True, reason="benign", risk_level="low")
_UNSAFE = ClassifierResult(safe=False, reason="injection detected", risk_level="high")


# ---------------------------------------------------------------------------
# Tests: full cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_cycle_processes_items():
    """A cycle with safe items should produce FeedItems."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, items=[_raw("m1"), _raw("m2")])

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_SAFE):
        result = await feed.run_cycle()

    assert result.fetched == 2
    assert result.passed == 2
    assert result.quarantined == 0
    assert result.skipped == 0
    assert len(result.items) == 2
    assert result.items[0].source_id == "m1"
    assert result.items[1].source_id == "m2"
    assert not result.errors


@pytest.mark.asyncio
async def test_quarantined_items_counted():
    """Unsafe items should be quarantined and counted, cycle continues."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, items=[_raw("m1"), _raw("m2")])

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_UNSAFE):
        result = await feed.run_cycle()

    assert result.fetched == 2
    assert result.passed == 0
    assert result.quarantined == 2
    assert len(result.items) == 0
    assert not result.errors


@pytest.mark.asyncio
async def test_duplicate_items_skipped():
    """Already-processed items should be counted as skipped."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    store.mark_processed("test", "m1")
    feed = MockFeed(pipeline, store, items=[_raw("m1"), _raw("m2")])

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_SAFE):
        result = await feed.run_cycle()

    assert result.fetched == 2
    assert result.skipped == 1
    assert result.passed == 1
    assert len(result.items) == 1
    assert result.items[0].source_id == "m2"


@pytest.mark.asyncio
async def test_fetch_error_produces_error():
    """A fetch error should not crash; it appears in CycleResult.errors."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, fetch_error=ConnectionError("IMAP down"))

    result = await feed.run_cycle()

    assert result.fetched == 0
    assert len(result.errors) == 1
    assert "fetch error" in result.errors[0]
    assert "IMAP down" in result.errors[0]


@pytest.mark.asyncio
async def test_format_error_counted():
    """If format_item raises, the error is recorded but cycle continues."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, items=[_raw("m1"), _raw("m2")])

    # Make format_item fail on first item, succeed on second
    call_count = 0
    original_format = feed.format_item

    def bad_format(envelope):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("bad format")
        return original_format(envelope)

    feed.format_item = bad_format

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_SAFE):
        result = await feed.run_cycle()

    assert result.fetched == 2
    assert result.passed == 1  # second one passed
    assert len(result.errors) == 1
    assert "m1" in result.errors[0]


@pytest.mark.asyncio
async def test_default_format_item_passthrough():
    """Default format_item should pass through body and metadata."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    items = [_raw("m1", "Hello world", subject="Test Subject")]
    feed = MockFeed(pipeline, store, items=items)

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_SAFE):
        result = await feed.run_cycle()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.body == "Hello world"
    assert item.title == "Test Subject"
    assert item.risk_level == "low"


@pytest.mark.asyncio
async def test_custom_format_item():
    """Subclass format_item should be used when overridden."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    items = [_raw("m1", "Body text", source="formatted", subject="My Email")]
    feed = FormattingFeed(pipeline, store, items=items)

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, return_value=_SAFE):
        result = await feed.run_cycle()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "[CUSTOM] My Email"
    assert item.body.startswith("# Email")
    assert item.suggested_path == "data/test/m1.md"


@pytest.mark.asyncio
async def test_mixed_safe_and_quarantined():
    """Cycle with a mix of safe and unsafe items."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, items=[_raw("m1"), _raw("m2"), _raw("m3")])

    # First safe, second unsafe, third safe
    results_iter = iter([_SAFE, _UNSAFE, _SAFE])

    async def classify_side_effect(*args, **kwargs):
        return next(results_iter)

    with patch("integrations.ingestion.pipeline.classify", new_callable=AsyncMock, side_effect=classify_side_effect):
        result = await feed.run_cycle()

    assert result.fetched == 3
    assert result.passed == 2
    assert result.quarantined == 1
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# Tests: cursor round-trip
# ---------------------------------------------------------------------------


def test_cursor_round_trip():
    """Cursor set via feed helpers should be retrievable."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store)

    assert feed.get_cursor() is None
    feed.set_cursor("uid-500")
    assert feed.get_cursor() == "uid-500"


def test_cursor_custom_key():
    """Cursor helpers should support custom keys."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store)

    feed.set_cursor("val1", key="custom-key")
    assert feed.get_cursor(key="custom-key") == "val1"
    assert feed.get_cursor() is None  # default key not set


def test_cursor_update():
    """Setting a cursor twice should update the value."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store)

    feed.set_cursor("uid-100")
    feed.set_cursor("uid-200")
    assert feed.get_cursor() == "uid-200"


# ---------------------------------------------------------------------------
# Tests: empty cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_fetch():
    """A cycle that fetches zero items should return clean CycleResult."""
    store = _make_store()
    pipeline = _make_pipeline(store)
    feed = MockFeed(pipeline, store, items=[])

    result = await feed.run_cycle()

    assert result.fetched == 0
    assert result.passed == 0
    assert result.quarantined == 0
    assert result.skipped == 0
    assert not result.items
    assert not result.errors
