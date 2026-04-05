"""Tests for ingestion dashboard router endpoints."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import verify_auth_or_user
from integrations.ingestion.router import router
from integrations.ingestion.store import IngestionStore


async def _noop_auth():
    return "test-token"


def _make_app() -> FastAPI:
    """Create a minimal app with the ingestion router mounted and auth disabled."""
    app = FastAPI()
    app.dependency_overrides[verify_auth_or_user] = _noop_auth
    app.include_router(router, prefix="/integrations/ingestion")
    return app


@pytest.fixture
def ingestion_dir(tmp_path):
    """Create a temp ingestion dir with seeded gmail.db and rss.db stores."""
    ingestion = tmp_path / ".ingestion"
    ingestion.mkdir()

    # Seed gmail store
    gmail_store = IngestionStore(ingestion / "gmail.db")
    for i in range(10):
        gmail_store.audit("gmail", f"msg-{i}", "passed", "low")
    gmail_store.quarantine("gmail", "q-1", "bad email", "high", ["injection"], "prompt injection detected")
    gmail_store.quarantine("gmail", "q-2", "err email", "medium", [], "classifier error: timeout")
    gmail_store.quarantine("gmail", "q-3", "err email2", "medium", [], "classifier error: empty response")
    gmail_store.mark_processed("gmail", "q-1")
    gmail_store.mark_processed("gmail", "q-2")
    gmail_store.mark_processed("gmail", "q-3")
    gmail_store.set_cursor("gmail:INBOX", "uid-500")
    gmail_store.close()

    # Seed rss store
    rss_store = IngestionStore(ingestion / "rss.db")
    for i in range(3):
        rss_store.audit("rss", f"entry-{i}", "passed", "low")
    rss_store.set_cursor("rss:feed1", "entry-99")
    rss_store.close()

    return ingestion


@pytest.fixture
def mock_dir(ingestion_dir):
    """Patch the ingestion directory for router functions."""
    with patch("integrations.ingestion.router.INGESTION_DB_DIR", str(ingestion_dir)):
        yield ingestion_dir


@pytest.fixture
async def client(mock_dir):
    """Async HTTP client for testing router endpoints."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestPing:
    @pytest.mark.asyncio
    async def test_ping(self, client):
        resp = await client.get("/integrations/ingestion/ping")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "ingestion"


class TestOverview:
    @pytest.mark.asyncio
    async def test_returns_all_stores(self, client):
        resp = await client.get("/integrations/ingestion/overview")
        assert resp.status_code == 200
        data = resp.json()
        stores = data["stores"]
        assert len(stores) == 2
        names = {s["name"] for s in stores}
        assert names == {"gmail", "rss"}

    @pytest.mark.asyncio
    async def test_gmail_stats(self, client):
        resp = await client.get("/integrations/ingestion/overview")
        data = resp.json()
        gmail = next(s for s in data["stores"] if s["name"] == "gmail")
        assert gmail["stats"]["total_processed"] >= 10
        assert gmail["stats"]["total_quarantined"] == 3
        assert gmail["classifier_error_count"] == 2

    @pytest.mark.asyncio
    async def test_quarantine_preview_limited(self, client):
        resp = await client.get("/integrations/ingestion/overview")
        data = resp.json()
        gmail = next(s for s in data["stores"] if s["name"] == "gmail")
        assert len(gmail["quarantine_preview"]) <= 5

    @pytest.mark.asyncio
    async def test_rss_no_classifier_errors(self, client):
        resp = await client.get("/integrations/ingestion/overview")
        data = resp.json()
        rss = next(s for s in data["stores"] if s["name"] == "rss")
        assert rss["classifier_error_count"] == 0
        assert rss["stats"]["total_quarantined"] == 0

    @pytest.mark.asyncio
    async def test_empty_dir(self, tmp_path):
        """Overview returns empty list when no .db files exist."""
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch("integrations.ingestion.router.INGESTION_DB_DIR", str(empty)):
            app = _make_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/integrations/ingestion/overview")
                assert resp.status_code == 200
                assert resp.json()["stores"] == []


class TestQuarantine:
    @pytest.mark.asyncio
    async def test_returns_quarantine_items(self, client):
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine")
        assert resp.status_code == 200
        data = resp.json()
        assert data["store"] == "gmail"
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_source_filter(self, client):
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine?source=gmail")
        data = resp.json()
        assert all(it["source"] == "gmail" for it in data["items"])

    @pytest.mark.asyncio
    async def test_limit_param(self, client):
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine?limit=1")
        data = resp.json()
        assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_unknown_store(self, client):
        resp = await client.get("/integrations/ingestion/stores/nonexistent/quarantine")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_items_have_ids(self, client):
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine")
        data = resp.json()
        for item in data["items"]:
            assert "id" in item
            assert isinstance(item["id"], int)


class TestQuarantineDetail:
    @pytest.mark.asyncio
    async def test_returns_full_item(self, client):
        # Get an item ID first
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine")
        items = resp.json()["items"]
        item_id = items[0]["id"]

        resp = await client.get(f"/integrations/ingestion/stores/gmail/quarantine/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["store"] == "gmail"
        item = data["item"]
        assert item is not None
        assert "raw_content" in item
        assert item["raw_content"] is not None
        assert len(item["raw_content"]) > 0
        assert "id" in item
        assert "reason" in item

    @pytest.mark.asyncio
    async def test_nonexistent_item(self, client):
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine/99999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"] is None
        assert "error" in data

    @pytest.mark.asyncio
    async def test_unknown_store(self, client):
        resp = await client.get("/integrations/ingestion/stores/nonexistent/quarantine/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"] is None
        assert "error" in data

    @pytest.mark.asyncio
    async def test_includes_metadata(self, mock_dir):
        """Item with metadata should return it in detail view."""
        # Seed a quarantine item with metadata
        store = IngestionStore(mock_dir / "gmail.db")
        store.quarantine(
            "gmail", "meta-test", "body with metadata", "high",
            flags=["test_flag"], reason="test reason",
            metadata={"from": "sender@example.com", "subject": "Test Subject"},
        )
        store.close()

        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Get the ID of the item we just added
            resp = await c.get("/integrations/ingestion/stores/gmail/quarantine?limit=100")
            items = resp.json()["items"]
            meta_item = next(it for it in items if it["source_id"] == "meta-test")

            resp = await c.get(f"/integrations/ingestion/stores/gmail/quarantine/{meta_item['id']}")
            data = resp.json()
            item = data["item"]
            assert item["metadata"] is not None
            assert item["metadata"]["from"] == "sender@example.com"
            assert item["metadata"]["subject"] == "Test Subject"
            assert item["raw_content"] == "body with metadata"


class TestReprocess:
    @pytest.mark.asyncio
    async def test_release_by_ids(self, client):
        # First get quarantine IDs
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine")
        items = resp.json()["items"]
        ids = [it["id"] for it in items if "classifier error" in (it.get("reason") or "")]
        assert len(ids) == 2

        resp = await client.post(
            "/integrations/ingestion/stores/gmail/reprocess",
            json={"quarantine_ids": ids},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["released"] == 2

        # Verify only 1 item left (the prompt injection one)
        resp = await client.get("/integrations/ingestion/stores/gmail/quarantine")
        assert len(resp.json()["items"]) == 1

    @pytest.mark.asyncio
    async def test_release_by_reason_pattern(self, client):
        resp = await client.post(
            "/integrations/ingestion/stores/gmail/reprocess",
            json={"reason_pattern": "classifier error:%"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["released"] == 2

    @pytest.mark.asyncio
    async def test_missing_params(self, client):
        resp = await client.post(
            "/integrations/ingestion/stores/gmail/reprocess",
            json={},
        )
        data = resp.json()
        assert data["released"] == 0
        assert "error" in data

    @pytest.mark.asyncio
    async def test_unknown_store(self, client):
        resp = await client.post(
            "/integrations/ingestion/stores/nonexistent/reprocess",
            json={"reason_pattern": "classifier error:%"},
        )
        data = resp.json()
        assert data["released"] == 0
        assert "error" in data


class TestHudStatus:
    @pytest.mark.asyncio
    async def test_returns_badges(self, client):
        resp = await client.get("/integrations/ingestion/hud/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["visible"] is True

        # Should have at least Processed badge
        badge_items = [i for i in data["items"] if i["type"] == "badge"]
        assert len(badge_items) >= 1
        processed = next(i for i in badge_items if i["label"] == "Processed")
        assert int(processed["value"]) >= 10  # gmail has 10+ processed
        assert processed["on_click"]["type"] == "link"

    @pytest.mark.asyncio
    async def test_quarantine_badge_present(self, client):
        resp = await client.get("/integrations/ingestion/hud/status")
        data = resp.json()
        badge_items = [i for i in data["items"] if i["type"] == "badge"]
        quarantined = next((i for i in badge_items if i["label"] == "Quarantined"), None)
        assert quarantined is not None
        assert int(quarantined["value"]) == 3
        assert quarantined["variant"] in ("warning", "danger")

    @pytest.mark.asyncio
    async def test_classifier_error_action(self, client):
        resp = await client.get("/integrations/ingestion/hud/status")
        data = resp.json()
        actions = [i for i in data["items"] if i["type"] == "action"]
        assert len(actions) == 1
        action = actions[0]
        assert action["label"] == "Release Errors"
        assert action["variant"] == "warning"
        assert action["on_click"]["type"] == "action"
        assert action["on_click"]["method"] == "POST"
        assert "confirm" in action["on_click"]

    @pytest.mark.asyncio
    async def test_empty_stores_invisible(self, tmp_path):
        """HUD returns visible=false when no stores exist."""
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch("integrations.ingestion.router.INGESTION_DB_DIR", str(empty)):
            app = _make_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/integrations/ingestion/hud/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["visible"] is False
                assert data["items"] == []

    @pytest.mark.asyncio
    async def test_no_classifier_errors_no_action(self, tmp_path):
        """When no classifier errors, the Release Errors action should not appear."""
        ingestion = tmp_path / ".ingestion"
        ingestion.mkdir()
        store = IngestionStore(ingestion / "clean.db")
        for i in range(5):
            store.audit("rss", f"entry-{i}", "passed", "low")
        store.close()
        with patch("integrations.ingestion.router.INGESTION_DB_DIR", str(ingestion)):
            app = _make_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/integrations/ingestion/hud/status")
                data = resp.json()
                assert data["visible"] is True
                actions = [i for i in data["items"] if i["type"] == "action"]
                assert len(actions) == 0
                dividers = [i for i in data["items"] if i["type"] == "divider"]
                assert len(dividers) == 0

    @pytest.mark.asyncio
    async def test_has_divider_before_action(self, client):
        """A divider should appear between badges and the action."""
        resp = await client.get("/integrations/ingestion/hud/status")
        data = resp.json()
        dividers = [i for i in data["items"] if i["type"] == "divider"]
        assert len(dividers) >= 1


class TestReprocessAllStores:
    @pytest.mark.asyncio
    async def test_release_across_stores(self, client):
        resp = await client.post(
            "/integrations/ingestion/stores/all/reprocess",
            json={"reason_pattern": "classifier error:%"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["released"] == 2  # 2 classifier errors in gmail

    @pytest.mark.asyncio
    async def test_missing_pattern(self, client):
        resp = await client.post(
            "/integrations/ingestion/stores/all/reprocess",
            json={},
        )
        data = resp.json()
        assert data["released"] == 0
        assert "error" in data


class TestCountByReasonPrefix:
    """Test the new store method used by the overview endpoint."""

    def test_counts_matching(self):
        store = IngestionStore(":memory:")
        store.quarantine("gmail", "e1", "c1", "high", [], "classifier error: timeout")
        store.quarantine("gmail", "e2", "c2", "high", [], "classifier error: empty")
        store.quarantine("gmail", "e3", "c3", "high", [], "prompt injection")
        assert store.count_by_reason_prefix(None, "classifier error:") == 2
        assert store.count_by_reason_prefix("gmail", "classifier error:") == 2
        store.close()

    def test_no_matches(self):
        store = IngestionStore(":memory:")
        store.quarantine("gmail", "e1", "c1", "high", [], "prompt injection")
        assert store.count_by_reason_prefix(None, "classifier error:") == 0
        store.close()

    def test_source_filter(self):
        store = IngestionStore(":memory:")
        store.quarantine("gmail", "e1", "c1", "high", [], "classifier error: timeout")
        store.quarantine("rss", "e2", "c2", "high", [], "classifier error: timeout")
        assert store.count_by_reason_prefix("gmail", "classifier error:") == 1
        assert store.count_by_reason_prefix("rss", "classifier error:") == 1
        assert store.count_by_reason_prefix(None, "classifier error:") == 2
        store.close()

    def test_empty_store(self):
        store = IngestionStore(":memory:")
        assert store.count_by_reason_prefix(None, "classifier error:") == 0
        store.close()


class TestPreMigrationDB:
    """Verify that DBs created before the metadata column still work via router."""

    @pytest.mark.asyncio
    async def test_list_and_detail_on_old_schema_db(self, tmp_path):
        """A DB without the metadata column should be auto-migrated on read."""
        import sqlite3 as _sqlite3

        ingestion = tmp_path / ".ingestion"
        ingestion.mkdir()
        db_path = ingestion / "legacy.db"

        # Create a DB with the OLD schema (no metadata column)
        conn = _sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE processed_ids (
                source TEXT NOT NULL, source_id TEXT NOT NULL, processed_at TEXT NOT NULL,
                PRIMARY KEY (source, source_id)
            );
            CREATE TABLE quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, source_id TEXT NOT NULL,
                raw_content TEXT NOT NULL, risk_level TEXT NOT NULL,
                flags TEXT, reason TEXT, quarantined_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, source_id TEXT NOT NULL,
                action TEXT NOT NULL, risk_level TEXT, ts TEXT NOT NULL
            );
            CREATE TABLE cursors (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        # Insert a quarantine row WITHOUT metadata
        conn.execute(
            "INSERT INTO quarantine (source, source_id, raw_content, risk_level, flags, reason, quarantined_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("gmail", "old-msg", "old content", "high", '["test"]', "old reason", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO audit_log (source, source_id, action, risk_level, ts) VALUES (?, ?, ?, ?, ?)",
            ("gmail", "old-msg", "quarantined", "high", "2026-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        with patch("integrations.ingestion.router.INGESTION_DB_DIR", str(ingestion)):
            app = _make_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                # List endpoint should work and return items with metadata=None
                resp = await c.get("/integrations/ingestion/stores/legacy/quarantine")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["items"]) == 1
                assert data["items"][0]["source_id"] == "old-msg"
                assert data["items"][0]["metadata"] is None

                # Detail endpoint should also work
                item_id = data["items"][0]["id"]
                resp = await c.get(f"/integrations/ingestion/stores/legacy/quarantine/{item_id}")
                assert resp.status_code == 200
                detail = resp.json()["item"]
                assert detail is not None
                assert detail["raw_content"] == "old content"
                assert detail["metadata"] is None
