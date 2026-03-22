"""Tests for SQLite ingestion store using in-memory DB."""

import json
import sqlite3

from integrations.ingestion.store import IngestionStore


def make_store() -> IngestionStore:
    """Create an in-memory store for testing."""
    store = IngestionStore(db_path=":memory:")
    store._conn.row_factory = sqlite3.Row
    return store


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
