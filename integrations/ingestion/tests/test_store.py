"""Tests for SQLite ingestion store using in-memory DB."""

import json

from integrations.ingestion.store import IngestionStore


def make_store() -> IngestionStore:
    """Create an in-memory store for testing."""
    return IngestionStore(db_path=":memory:")


class TestSchema:
    def test_tables_created(self):
        store = make_store()
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cur.fetchall()]
        assert "processed_ids" in tables
        assert "quarantine" in tables
        assert "audit_log" in tables
        assert "cursors" in tables
        store.close()


class TestIdempotency:
    def test_not_processed_initially(self):
        store = make_store()
        assert not store.already_processed("gmail", "msg-1")
        store.close()

    def test_mark_processed(self):
        store = make_store()
        store.mark_processed("gmail", "msg-1")
        assert store.already_processed("gmail", "msg-1")
        store.close()

    def test_different_source_ids_independent(self):
        store = make_store()
        store.mark_processed("gmail", "msg-1")
        assert not store.already_processed("gmail", "msg-2")
        assert not store.already_processed("webhook", "msg-1")
        store.close()

    def test_mark_processed_idempotent(self):
        store = make_store()
        store.mark_processed("gmail", "msg-1")
        store.mark_processed("gmail", "msg-1")  # should not raise
        assert store.already_processed("gmail", "msg-1")
        store.close()


class TestQuarantine:
    def test_quarantine_inserts_row(self):
        store = make_store()
        store.quarantine(
            source="gmail",
            source_id="msg-bad",
            raw_content="<script>alert('xss')</script>",
            risk_level="high",
            flags=["injection_attempt"],
            reason="dangerous content",
        )
        cur = store._conn.execute("SELECT * FROM quarantine WHERE source_id = ?", ("msg-bad",))
        row = cur.fetchone()
        assert row is not None
        assert row["source"] == "gmail"
        assert row["risk_level"] == "high"
        assert row["reason"] == "dangerous content"
        assert json.loads(row["flags"]) == ["injection_attempt"]
        assert row["quarantined_at"] is not None
        store.close()

    def test_quarantine_multiple_entries(self):
        store = make_store()
        for i in range(3):
            store.quarantine(
                source="webhook",
                source_id=f"msg-{i}",
                raw_content=f"bad content {i}",
                risk_level="medium",
                flags=[],
                reason="test",
            )
        cur = store._conn.execute("SELECT COUNT(*) as cnt FROM quarantine")
        assert cur.fetchone()["cnt"] == 3
        store.close()


class TestAudit:
    def test_audit_log_entry(self):
        store = make_store()
        store.audit("gmail", "msg-1", "passed", "low")
        cur = store._conn.execute("SELECT * FROM audit_log WHERE source_id = ?", ("msg-1",))
        row = cur.fetchone()
        assert row is not None
        assert row["action"] == "passed"
        assert row["risk_level"] == "low"
        assert row["ts"] is not None
        store.close()

    def test_audit_without_risk_level(self):
        store = make_store()
        store.audit("gmail", "msg-1", "discarded")
        cur = store._conn.execute("SELECT * FROM audit_log WHERE source_id = ?", ("msg-1",))
        row = cur.fetchone()
        assert row["risk_level"] is None
        store.close()

    def test_multiple_audit_entries_same_message(self):
        store = make_store()
        store.audit("gmail", "msg-1", "quarantined", "high")
        store.audit("gmail", "msg-1", "released", "high")
        cur = store._conn.execute("SELECT COUNT(*) as cnt FROM audit_log WHERE source_id = ?", ("msg-1",))
        assert cur.fetchone()["cnt"] == 2
        store.close()


class TestCursors:
    def test_get_cursor_returns_none_initially(self):
        store = make_store()
        assert store.get_cursor("gmail") is None
        store.close()

    def test_set_and_get_cursor(self):
        store = make_store()
        store.set_cursor("gmail", "uid-500")
        assert store.get_cursor("gmail") == "uid-500"
        store.close()

    def test_set_cursor_upsert(self):
        store = make_store()
        store.set_cursor("gmail", "uid-100")
        store.set_cursor("gmail", "uid-200")
        assert store.get_cursor("gmail") == "uid-200"
        store.close()

    def test_independent_cursor_keys(self):
        store = make_store()
        store.set_cursor("gmail", "uid-100")
        store.set_cursor("rss", "entry-50")
        assert store.get_cursor("gmail") == "uid-100"
        assert store.get_cursor("rss") == "entry-50"
        store.close()

    def test_cursor_updated_at_tracked(self):
        store = make_store()
        store.set_cursor("gmail", "uid-1")
        cur = store._conn.execute("SELECT updated_at FROM cursors WHERE key = ?", ("gmail",))
        row = cur.fetchone()
        assert row is not None
        assert row["updated_at"] is not None
        store.close()


def _populate_store(store: IngestionStore) -> None:
    """Seed a store with audit + quarantine data for query tests."""
    for i in range(5):
        store.audit("gmail", f"passed-{i}", "passed", "low")
    for i in range(3):
        store.audit("rss", f"rss-{i}", "passed", "low")
    store.audit("gmail", "q-1", "quarantined", "high")
    store.quarantine("gmail", "q-1", "bad stuff", "high", ["injection"], "prompt injection")
    store.quarantine("gmail", "q-2", "more bad", "medium", [], "suspicious links")
    store.quarantine("rss", "q-rss", "rss bad", "high", ["hidden_chars"], "zero-width")
    store.set_cursor("gmail:INBOX", "uid-500")
    store.set_cursor("rss:feed1", "entry-99")


class TestFeedStats:
    def test_stats_all_sources(self):
        store = make_store()
        _populate_store(store)
        stats = store.get_feed_stats()
        assert stats["total_processed"] == 9  # 5 gmail + 3 rss + 1 quarantine audit
        assert stats["total_quarantined"] == 3
        # No source filter → returns ALL cursors
        assert len(stats["last_cursor"]) == 2
        keys = {c["key"] for c in stats["last_cursor"]}
        assert keys == {"gmail:INBOX", "rss:feed1"}
        store.close()

    def test_stats_filtered_by_source(self):
        store = make_store()
        _populate_store(store)
        stats = store.get_feed_stats("gmail")
        assert stats["total_processed"] == 6  # 5 passed + 1 quarantined
        assert stats["total_quarantined"] == 2
        assert len(stats["last_cursor"]) == 1
        assert stats["last_cursor"][0]["key"] == "gmail:INBOX"
        assert stats["last_cursor"][0]["value"] == "uid-500"
        store.close()

    def test_stats_composite_key_match(self):
        """Source filter matches both exact and composite cursor keys."""
        store = make_store()
        store.set_cursor("gmail", "uid-100")  # exact match
        store.set_cursor("gmail:INBOX", "uid-200")  # composite match
        store.set_cursor("rss:feed1", "entry-1")  # should not match
        store.audit("gmail", "msg-1", "passed", "low")
        stats = store.get_feed_stats("gmail")
        assert len(stats["last_cursor"]) == 2
        keys = {c["key"] for c in stats["last_cursor"]}
        assert keys == {"gmail", "gmail:INBOX"}
        store.close()

    def test_stats_24h_counts(self):
        store = make_store()
        _populate_store(store)
        # All items were just inserted, so 24h counts should match totals
        stats = store.get_feed_stats()
        assert stats["processed_24h"] == 9
        assert stats["quarantined_24h"] == 3
        store.close()

    def test_stats_empty_store(self):
        store = make_store()
        stats = store.get_feed_stats()
        assert stats["total_processed"] == 0
        assert stats["total_quarantined"] == 0
        assert stats["processed_24h"] == 0
        assert stats["quarantined_24h"] == 0
        store.close()


class TestRecentItems:
    def test_returns_passed_items(self):
        store = make_store()
        _populate_store(store)
        items = store.get_recent_items()
        assert len(items) == 8  # 5 gmail + 3 rss passed
        assert all(it["action"] == "passed" for it in items)
        store.close()

    def test_filtered_by_source(self):
        store = make_store()
        _populate_store(store)
        items = store.get_recent_items("rss")
        assert len(items) == 3
        assert all(it["source"] == "rss" for it in items)
        store.close()

    def test_limit(self):
        store = make_store()
        _populate_store(store)
        items = store.get_recent_items(limit=2)
        assert len(items) == 2
        store.close()

    def test_empty_store(self):
        store = make_store()
        items = store.get_recent_items()
        assert items == []
        store.close()


class TestQuarantineItems:
    def test_returns_quarantined(self):
        store = make_store()
        _populate_store(store)
        items = store.get_quarantine_items()
        assert len(items) == 3
        # Every item must include its row id for reprocessing
        assert all("id" in it for it in items)
        assert all(isinstance(it["id"], int) for it in items)
        store.close()

    def test_filtered_by_source(self):
        store = make_store()
        _populate_store(store)
        items = store.get_quarantine_items("gmail")
        assert len(items) == 2
        assert all(it["source"] == "gmail" for it in items)
        store.close()

    def test_flags_deserialized(self):
        store = make_store()
        _populate_store(store)
        items = store.get_quarantine_items("gmail")
        flagged = [it for it in items if it["flags"]]
        assert len(flagged) >= 1
        assert isinstance(flagged[0]["flags"], list)
        store.close()

    def test_limit(self):
        store = make_store()
        _populate_store(store)
        items = store.get_quarantine_items(limit=1)
        assert len(items) == 1
        store.close()


class TestUnquarantine:
    def test_unquarantine_by_ids(self):
        store = make_store()
        _populate_store(store)
        # Get quarantine IDs for gmail
        items = store.get_quarantine_items("gmail")
        ids = [store._conn.execute(
            "SELECT id FROM quarantine WHERE source_id = ?", (it["source_id"],)
        ).fetchone()["id"] for it in items]
        count = store.unquarantine(ids)
        assert count == 2
        # Quarantine should be empty for gmail now
        assert store.get_quarantine_items("gmail") == []
        # processed_ids should be cleared so messages can be re-ingested
        assert not store.already_processed("gmail", "q-1")
        assert not store.already_processed("gmail", "q-2")
        # Audit log should have unquarantined entries
        cur = store._conn.execute(
            "SELECT COUNT(*) as cnt FROM audit_log WHERE action = 'unquarantined'"
        )
        assert cur.fetchone()["cnt"] == 2
        store.close()

    def test_unquarantine_empty_list(self):
        store = make_store()
        assert store.unquarantine([]) == 0
        store.close()

    def test_unquarantine_nonexistent_ids(self):
        store = make_store()
        assert store.unquarantine([999, 1000]) == 0
        store.close()

    def test_unquarantine_by_reason_pattern(self):
        store = make_store()
        store.quarantine("gmail", "err-1", "content1", "high", [], "classifier error: timeout")
        store.quarantine("gmail", "err-2", "content2", "high", [], "classifier error: empty")
        store.quarantine("gmail", "legit-bad", "content3", "high", [], "prompt injection")
        store.mark_processed("gmail", "err-1")
        store.mark_processed("gmail", "err-2")
        store.mark_processed("gmail", "legit-bad")
        count = store.unquarantine_by_reason("classifier error:%")
        assert count == 2
        # legit-bad should still be quarantined
        items = store.get_quarantine_items("gmail")
        assert len(items) == 1
        assert items[0]["source_id"] == "legit-bad"
        # err-1/err-2 should be clearable for re-ingestion
        assert not store.already_processed("gmail", "err-1")
        assert not store.already_processed("gmail", "err-2")
        assert store.already_processed("gmail", "legit-bad")
        store.close()

    def test_unquarantine_by_reason_with_source_filter(self):
        store = make_store()
        store.quarantine("gmail", "g-err", "c1", "high", [], "classifier error: timeout")
        store.quarantine("rss", "r-err", "c2", "high", [], "classifier error: timeout")
        count = store.unquarantine_by_reason("classifier error:%", source="gmail")
        assert count == 1
        # rss quarantine should be untouched
        assert len(store.get_quarantine_items("rss")) == 1
        store.close()

    def test_unquarantine_by_reason_no_match(self):
        store = make_store()
        _populate_store(store)
        count = store.unquarantine_by_reason("nonexistent pattern%")
        assert count == 0
        store.close()


class TestListSources:
    def test_lists_distinct_sources(self):
        store = make_store()
        _populate_store(store)
        sources = store.list_sources()
        assert sources == ["gmail", "rss"]
        store.close()

    def test_empty_store(self):
        store = make_store()
        sources = store.list_sources()
        assert sources == []
        store.close()
