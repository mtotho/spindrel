"""Unit tests for app.services.widget_db — Phase B.1 of the Widget SDK track.

Covers:
- path resolution: built-in bundle redirect + channel bundle
- WAL mode is set on opened connections
- concurrent db_exec calls serialise (lock is held)
- migration runner: happy path, gap, downgrade, already-applied steps
- has_content: empty vs populated DB
"""
from __future__ import annotations

import asyncio
import sqlite3
import textwrap
import unittest.mock as mock
from pathlib import Path

import pytest

from app.services.widget_manifest import DbConfig, MigrationEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_config(schema_version: int, migrations: list[dict] | None = None) -> DbConfig:
    steps = []
    for m in migrations or []:
        steps.append(
            MigrationEntry(
                from_version=m["from"],
                to_version=m["to"],
                sql=m["sql"],
            )
        )
    return DbConfig(schema_version=schema_version, migrations=steps)


def _fresh_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# resolve_db_path
# ---------------------------------------------------------------------------


class TestResolveDbPath:
    def test_inline_widget_raises(self, tmp_path):
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {}  # no source_path
        pin.source_channel_id = None
        pin.source_bot_id = None

        with pytest.raises(ValueError, match="inline widgets"):
            resolve_db_path(pin)

    def test_missing_channel_id_raises(self, tmp_path):
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {"source_path": "data/widgets/notes/index.html"}
        pin.source_channel_id = None
        pin.source_bot_id = None

        with pytest.raises(ValueError, match="source_channel_id"):
            resolve_db_path(pin)

    def test_missing_bot_id_raises(self, tmp_path):
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {
            "source_path": "data/widgets/notes/index.html",
            "source_channel_id": "aaaa0000-0000-0000-0000-000000000001",
        }
        pin.source_channel_id = None
        pin.source_bot_id = None

        with pytest.raises(ValueError, match="source_bot_id"):
            resolve_db_path(pin)

    def test_unknown_bot_raises(self, tmp_path):
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin
        import uuid

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {"source_path": "data/widgets/notes/index.html"}
        pin.source_channel_id = uuid.UUID("aaaa0000-0000-0000-0000-000000000001")
        pin.source_bot_id = "no-such-bot"

        with mock.patch("app.agent.bots.get_bot", return_value=None):
            with pytest.raises(ValueError, match="bot.*not found"):
                resolve_db_path(pin)

    def test_channel_bundle_db_path(self, tmp_path):
        """DB resolves to <bundle_dir>/data.sqlite inside the channel workspace."""
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin
        from app.agent.bots import BotConfig, MemoryConfig
        import uuid

        channel_id = "aaaa0000-0000-0000-0000-000000000001"
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "notes"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("<!-- widget -->")

        bot = BotConfig(
            id="test-bot",
            name="Test",
            model="test/model",
            system_prompt="",
            memory=MemoryConfig(enabled=False),
        )

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {"source_path": "data/widgets/notes/index.html"}
        pin.source_channel_id = uuid.UUID(channel_id)
        pin.source_bot_id = "test-bot"

        with mock.patch("app.agent.bots.get_bot", return_value=bot):
            with mock.patch(
                "app.services.channel_workspace.get_channel_workspace_root",
                return_value=str(ws_root),
            ):
                result = resolve_db_path(pin)

        assert result == bundle_dir / "data.sqlite"

    def test_path_traversal_raises(self, tmp_path):
        """source_path that escapes the workspace raises ValueError."""
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin
        from app.agent.bots import BotConfig, MemoryConfig
        import uuid

        ws_root = tmp_path / "workspace"
        ws_root.mkdir()

        bot = BotConfig(
            id="test-bot",
            name="Test",
            model="test/model",
            system_prompt="",
            memory=MemoryConfig(enabled=False),
        )

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {"source_path": "../../../etc/passwd"}
        pin.source_channel_id = uuid.UUID("aaaa0000-0000-0000-0000-000000000002")
        pin.source_bot_id = "test-bot"

        with mock.patch("app.agent.bots.get_bot", return_value=bot):
            with mock.patch(
                "app.services.channel_workspace.get_channel_workspace_root",
                return_value=str(ws_root),
            ):
                with pytest.raises(ValueError, match="outside"):
                    resolve_db_path(pin)

    def test_builtin_bundle_redirects(self, tmp_path):
        """Bundles inside app/tools/local/widgets/ redirect to widget_db/builtin/."""
        from app.services import widget_db as _widget_db
        from app.services.widget_db import resolve_db_path
        from app.db.models import WidgetDashboardPin
        from app.agent.bots import BotConfig, MemoryConfig
        import uuid

        # Simulate a workspace root that IS the builtin widget dir so
        # the resolved bundle_dir falls inside _BUILTIN_WIDGET_DIR.
        builtin_dir = _widget_db._BUILTIN_WIDGET_DIR
        # Temporarily set ws_root to the parent of builtin_dir so
        # "context_tracker/index.html" resolves into the builtin tree.
        ws_root = builtin_dir.parent

        bot = BotConfig(
            id="test-bot",
            name="Test",
            model="test/model",
            system_prompt="",
            memory=MemoryConfig(enabled=False),
        )

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        # source_path must be relative to ws_root and resolve INTO _BUILTIN_WIDGET_DIR.
        # ws_root = builtin_dir.parent (= .../tools/local/), so
        # "widgets/context_tracker/index.html" resolves to
        # .../tools/local/widgets/context_tracker — inside _BUILTIN_WIDGET_DIR.
        pin.envelope = {"source_path": "widgets/context_tracker/index.html"}
        pin.source_channel_id = uuid.UUID("bbbb0000-0000-0000-0000-000000000001")
        pin.source_bot_id = "test-bot"

        with mock.patch("app.agent.bots.get_bot", return_value=bot):
            with mock.patch(
                "app.services.channel_workspace.get_channel_workspace_root",
                return_value=str(ws_root),
            ):
                with mock.patch.object(
                    _widget_db, "_builtin_db_root", return_value=tmp_path / "widget_db" / "builtin"
                ):
                    result = resolve_db_path(pin)

        assert "builtin" in result.parts
        assert result.name == "data.sqlite"
        assert result.parent.name == "context_tracker"


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


class TestRunMigrations:
    def test_no_migrations_noop(self, tmp_path):
        from app.services.widget_db import run_migrations

        db_path = tmp_path / "test.sqlite"
        conn = _fresh_conn(db_path)
        try:
            db_config = _make_db_config(1)
            # schema_version=1, no migration steps: user_version starts at 0.
            # With no steps, current=0 != target=1, so it raises.
            # But if current==target (both 1), it's a noop.
            conn.execute("PRAGMA user_version = 1")
            run_migrations(conn, db_config)  # should be a no-op
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        finally:
            conn.close()

    def test_applies_single_migration(self, tmp_path):
        from app.services.widget_db import run_migrations

        db_path = tmp_path / "test.sqlite"
        conn = _fresh_conn(db_path)
        try:
            db_config = _make_db_config(
                1,
                [{"from": 0, "to": 1, "sql": "CREATE TABLE items (id INTEGER PRIMARY KEY, text TEXT)"}],
            )
            run_migrations(conn, db_config)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
            # Table should exist.
            conn.execute("INSERT INTO items(text) VALUES ('hello')")
            assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        finally:
            conn.close()

    def test_skips_already_applied(self, tmp_path):
        from app.services.widget_db import run_migrations

        db_path = tmp_path / "test.sqlite"
        conn = _fresh_conn(db_path)
        try:
            # Pre-apply migration 1 manually.
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
            conn.execute("PRAGMA user_version = 1")

            db_config = _make_db_config(
                2,
                [
                    {"from": 0, "to": 1, "sql": "CREATE TABLE items (id INTEGER PRIMARY KEY)"},
                    {"from": 1, "to": 2, "sql": "ALTER TABLE items ADD COLUMN text TEXT"},
                ],
            )
            run_migrations(conn, db_config)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
            # items table should have the new column.
            conn.execute("INSERT INTO items(id, text) VALUES (1, 'hi')")
        finally:
            conn.close()

    def test_downgrade_refused(self, tmp_path):
        from app.services.widget_db import run_migrations

        db_path = tmp_path / "test.sqlite"
        conn = _fresh_conn(db_path)
        try:
            conn.execute("PRAGMA user_version = 3")
            db_config = _make_db_config(2)  # manifest declares version 2
            with pytest.raises(ValueError, match="downgrade"):
                run_migrations(conn, db_config)
        finally:
            conn.close()

    def test_migration_gap_raises(self, tmp_path):
        from app.services.widget_db import run_migrations

        db_path = tmp_path / "test.sqlite"
        conn = _fresh_conn(db_path)
        try:
            # current version = 0, but only migration 2→3 is present.
            db_config = _make_db_config(
                3,
                [{"from": 2, "to": 3, "sql": "SELECT 1"}],
            )
            with pytest.raises(ValueError, match="gap"):
                run_migrations(conn, db_config)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# has_content
# ---------------------------------------------------------------------------


class TestHasContent:
    def test_missing_file_returns_false(self, tmp_path):
        from app.services.widget_db import has_content

        assert has_content(tmp_path / "nonexistent.sqlite") is False

    def test_empty_db_returns_false(self, tmp_path):
        from app.services.widget_db import has_content

        db_path = tmp_path / "empty.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        conn.close()

        assert has_content(db_path) is False

    def test_populated_db_returns_true(self, tmp_path):
        from app.services.widget_db import has_content

        db_path = tmp_path / "populated.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        assert has_content(db_path) is True

    def test_multiple_tables_one_populated(self, tmp_path):
        from app.services.widget_db import has_content

        db_path = tmp_path / "mixed.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        assert has_content(db_path) is True


# ---------------------------------------------------------------------------
# acquire_db (WAL mode + migration integration)
# ---------------------------------------------------------------------------


class TestAcquireDb:
    @pytest.mark.asyncio
    async def test_wal_mode_set(self, tmp_path):
        from app.services.widget_db import acquire_db

        db_path = tmp_path / "wal_test.sqlite"
        async with acquire_db(db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    @pytest.mark.asyncio
    async def test_runs_migrations_on_open(self, tmp_path):
        from app.services.widget_db import acquire_db

        db_path = tmp_path / "migrations_test.sqlite"
        db_config = _make_db_config(
            1,
            [{"from": 0, "to": 1, "sql": "CREATE TABLE items (id INTEGER PRIMARY KEY, text TEXT)"}],
        )
        async with acquire_db(db_path, db_config) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
            conn.execute("INSERT INTO items(text) VALUES ('row1')")

    @pytest.mark.asyncio
    async def test_concurrent_exec_serialises(self, tmp_path):
        """Two coroutines writing to the same DB must not interleave."""
        from app.services.widget_db import acquire_db

        db_path = tmp_path / "concurrent_test.sqlite"
        # Create the table first.
        async with acquire_db(db_path) as conn:
            conn.execute("CREATE TABLE log (n INTEGER)")
            conn.commit()

        order: list[int] = []

        async def writer(n: int) -> None:
            async with acquire_db(db_path) as conn:
                order.append(n)
                await asyncio.sleep(0)  # yield
                conn.execute("INSERT INTO log(n) VALUES (?)", (n,))
                conn.commit()

        await asyncio.gather(writer(1), writer(2), writer(3))
        # All three writes should complete (no collision).
        async with acquire_db(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM log").fetchone()[0]
        assert count == 3


# ---------------------------------------------------------------------------
# resolve_suite_db_path (Phase B.6 — dashboard-scoped shared DB)
# ---------------------------------------------------------------------------


class TestResolveSuiteDbPath:
    def _pin(self, dashboard_key: str):
        from app.db.models import WidgetDashboardPin
        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.dashboard_key = dashboard_key
        return pin

    def test_channel_dashboard_slug(self, tmp_path):
        from app.services.widget_db import resolve_suite_db_path
        from app.services import paths as paths_mod

        with mock.patch.object(
            paths_mod, "local_workspace_base", return_value=str(tmp_path)
        ):
            p = resolve_suite_db_path(
                self._pin("channel:abc-123"), "mission-control",
            )
        expected = tmp_path / "widget_db" / "suites" / "channel_abc-123" / "mission-control" / "data.sqlite"
        assert p == expected.resolve()

    def test_global_dashboard_slug(self, tmp_path):
        from app.services.widget_db import resolve_suite_db_path
        from app.services import paths as paths_mod

        with mock.patch.object(
            paths_mod, "local_workspace_base", return_value=str(tmp_path)
        ):
            p = resolve_suite_db_path(self._pin("default"), "mission-control")
        expected = tmp_path / "widget_db" / "suites" / "default" / "mission-control" / "data.sqlite"
        assert p == expected.resolve()

    def test_same_dashboard_same_db(self, tmp_path):
        """Two different bundles on the same dashboard must resolve to the
        same DB when both declare the same suite slug."""
        from app.services.widget_db import resolve_suite_db_path
        from app.services import paths as paths_mod

        with mock.patch.object(
            paths_mod, "local_workspace_base", return_value=str(tmp_path)
        ):
            a = resolve_suite_db_path(self._pin("work-board"), "mission-control")
            b = resolve_suite_db_path(self._pin("work-board"), "mission-control")
        assert a == b

    def test_different_dashboards_different_db(self, tmp_path):
        from app.services.widget_db import resolve_suite_db_path
        from app.services import paths as paths_mod

        with mock.patch.object(
            paths_mod, "local_workspace_base", return_value=str(tmp_path)
        ):
            a = resolve_suite_db_path(self._pin("channel:aaaa"), "mission-control")
            b = resolve_suite_db_path(self._pin("channel:bbbb"), "mission-control")
        assert a != b

    def test_rejects_dashboard_traversal(self, tmp_path):
        from app.services.widget_db import resolve_suite_db_path

        with pytest.raises(ValueError, match="path-traversal"):
            resolve_suite_db_path(self._pin("../etc"), "mission-control")

    def test_rejects_suite_id_traversal(self, tmp_path):
        from app.services.widget_db import resolve_suite_db_path

        with pytest.raises(ValueError, match="path-traversal"):
            resolve_suite_db_path(self._pin("default"), "../etc")

    def test_resolve_db_path_delegates_when_shared(self, tmp_path):
        """resolve_db_path must route suite-manifest pins to the shared path."""
        from app.services.widget_db import resolve_db_path
        from app.services.widget_manifest import DbConfig, WidgetManifest, Permissions
        from app.services import paths as paths_mod
        from app.db.models import WidgetDashboardPin

        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.dashboard_key = "default"
        # Envelope / bot / channel should be irrelevant for suite paths.
        pin.envelope = {}
        pin.source_channel_id = None
        pin.source_bot_id = None

        manifest = WidgetManifest(
            name="X",
            version="1.0.0",
            description="",
            permissions=Permissions(),
            cron=[],
            events=[],
            db=DbConfig(schema_version=0, migrations=[], shared="mission-control"),
            source_path=None,
        )

        with mock.patch.object(
            paths_mod, "local_workspace_base", return_value=str(tmp_path)
        ):
            p = resolve_db_path(pin, manifest)

        assert "suites" in p.parts
        assert "mission-control" in p.parts
        assert p.name == "data.sqlite"
