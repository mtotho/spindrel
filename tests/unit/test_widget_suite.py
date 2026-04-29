"""Unit tests for app.services.widget_suite — Phase B.6 of the Widget SDK."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services.widget_suite import (
    SuiteError,
    clear_suite_cache,
    load_suite,
    parse_suite_manifest,
    scan_suites,
)


def _write(dir_: Path, name: str, body: str) -> Path:
    p = dir_ / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_suite_cache()
    yield
    clear_suite_cache()


class TestParseSuiteManifest:
    def test_minimal_valid(self, tmp_path):
        suite_dir = tmp_path / "mission-control"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: Mission Control
            description: Task management
            members: [mc_timeline, mc_kanban]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql: "create table items (id integer primary key);"
            """,
        )
        m = parse_suite_manifest(p)
        assert m.suite_id == "mission-control"
        assert m.name == "Mission Control"
        assert m.description == "Task management"
        assert m.members == ["mc_timeline", "mc_kanban"]
        assert m.schema_version == 1
        assert len(m.migrations) == 1
        assert m.migrations[0].from_version == 0
        assert m.migrations[0].to_version == 1
        assert "create table items" in m.migrations[0].sql

    def test_sql_file_resolution(self, tmp_path):
        suite_dir = tmp_path / "mc"
        _write(
            suite_dir,
            "migrations/001_items.sql",
            "create table items (id integer primary key);",
        )
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql_file: migrations/001_items.sql
            """,
        )
        m = parse_suite_manifest(p)
        assert "create table items" in m.migrations[0].sql

    def test_rejects_sql_file_path_traversal(self, tmp_path):
        suite_dir = tmp_path / "mc"
        _write(tmp_path, "evil.sql", "drop table users;")
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql_file: ../evil.sql
            """,
        )
        with pytest.raises(SuiteError, match="outside the suite directory"):
            parse_suite_manifest(p)

    def test_rejects_invalid_slug(self, tmp_path):
        suite_dir = tmp_path / "BAD SLUG"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: X
            members: [a]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
            """,
        )
        with pytest.raises(SuiteError, match="valid slug"):
            parse_suite_manifest(p)

    def test_rejects_missing_members(self, tmp_path):
        suite_dir = tmp_path / "mc"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: []
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
            """,
        )
        with pytest.raises(SuiteError, match="non-empty list"):
            parse_suite_manifest(p)

    def test_rejects_duplicate_members(self, tmp_path):
        suite_dir = tmp_path / "mc"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a, a]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
            """,
        )
        with pytest.raises(SuiteError, match="duplicate member"):
            parse_suite_manifest(p)

    def test_rejects_migration_gap(self, tmp_path):
        suite_dir = tmp_path / "mc"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a]
            db:
              schema_version: 3
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
                - from: 2
                  to: 3
                  sql: "select 2;"
            """,
        )
        with pytest.raises(SuiteError, match="contiguous"):
            parse_suite_manifest(p)

    def test_rejects_final_mismatch(self, tmp_path):
        suite_dir = tmp_path / "mc"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a]
            db:
              schema_version: 3
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
            """,
        )
        with pytest.raises(SuiteError, match="last step ends"):
            parse_suite_manifest(p)

    def test_rejects_no_db_block(self, tmp_path):
        suite_dir = tmp_path / "mc"
        p = _write(
            suite_dir,
            "suite.yaml",
            """
            name: MC
            members: [a]
            """,
        )
        with pytest.raises(SuiteError, match="'db' is required"):
            parse_suite_manifest(p)


class TestSuiteDiscovery:
    def test_load_suite_discovers_external_integration_widget_suites(self, tmp_path, monkeypatch):
        from app.services import widget_suite
        from integrations.discovery import IntegrationSource

        integration_root = tmp_path / "spindrel-home" / "bennieloggins"
        _write(
            integration_root / "widgets" / "ops",
            "suite.yaml",
            """
            name: Ops
            members: [status]
            db:
              schema_version: 1
              migrations:
                - from: 0
                  to: 1
                  sql: "create table status (id integer primary key);"
            """,
        )
        monkeypatch.setattr(widget_suite, "_BUILTIN_WIDGETS_DIR", tmp_path / "missing")
        monkeypatch.setattr(
            "integrations.discovery.iter_integration_sources",
            lambda: [
                IntegrationSource(
                    integration_id="bennieloggins",
                    path=integration_root.resolve(),
                    source="external",
                    is_external=True,
                )
            ],
        )

        suite = load_suite("ops")
        suites = scan_suites()

        assert suite is not None
        assert suite.name == "Ops"
        assert [item.suite_id for item in suites] == ["ops"]
