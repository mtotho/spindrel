"""Tests for the multi-source HTML widget scanner — built-in and integration
roots plus tool-renderer exclusion.

Complements ``test_html_widget_scanner.py`` (channel-workspace scans). Uses
tmp_path + monkeypatching of the module-level ``BUILTIN_WIDGET_ROOT`` /
``INTEGRATIONS_ROOT`` constants so the tests don't depend on the real repo
layout.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


WIDGET_HTML_WITH_FRONTMATTER = (
    "<!--\n"
    "---\n"
    "name: {name}\n"
    "description: {desc}\n"
    "version: {ver}\n"
    "tags: [test]\n"
    "---\n"
    "-->\n"
    "<div id='root'></div>"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    """Scanner keeps a process-local cache keyed on ``(scope, rel_path)``. Each
    test gets a clean slate so cross-test leakage is impossible."""
    from app.services.html_widget_scanner import invalidate_cache
    invalidate_cache()
    yield
    invalidate_cache()


# ---------------------------------------------------------------------------
# scan_builtin
# ---------------------------------------------------------------------------

class TestScanBuiltin:
    def test_scan_returns_widgets_in_builtin_root(self, tmp_path, monkeypatch):
        """Every ``.html`` under the built-in root surfaces as a catalog
        entry, even when it has no ``spindrel.`` reference — the root itself
        IS the widgets dir by construction."""
        from app.services import html_widget_scanner

        monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path)
        # No `.widgets.yaml` siblings in tmp — nothing to exclude.
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path / "missing")

        _write(
            tmp_path / "notes" / "index.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(
                name="Notes", desc="A scratchpad", ver="1.0.0",
            ),
        )
        # Widget without a spindrel ref AND without a /widgets/ parent — the
        # channel scanner would reject it, but force_include lets it through.
        _write(
            tmp_path / "context_tracker" / "index.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(
                name="Context Tracker", desc="Gauge", ver="0.1.0",
            ),
        )

        entries = html_widget_scanner.scan_builtin()

        by_slug = {e["slug"]: e for e in entries}
        assert set(by_slug) == {"notes", "context_tracker"}
        for e in entries:
            assert e["source"] == "builtin"
            assert e["integration_id"] is None
            # is_bundle is true because force_include implies bundle treatment.
            assert e["is_bundle"] is True
            assert e["is_loose"] is False

    def test_scan_excludes_tool_renderer_html(self, tmp_path, monkeypatch):
        """HTML files referenced by a per-tool ``template.yaml``
        ``html_template.path`` are tool renderers, not standalone widgets.
        They must not surface in the built-in catalog."""
        from app.services import html_widget_scanner

        # New layout: widgets/<tool>/template.yaml lives alongside the html
        # file it references.
        widgets_root = tmp_path / "tools" / "local" / "widgets"
        monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", widgets_root)
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path / "missing")

        # Standalone widget — should surface.
        _write(
            widgets_root / "notes" / "index.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="Notes", desc="", ver="0.0.0"),
        )
        # Tool-renderer widget — referenced by generate_image/template.yaml,
        # must be excluded.
        _write(
            widgets_root / "generate_image" / "image.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="Image", desc="", ver="0.0.0"),
        )
        _write(
            widgets_root / "generate_image" / "template.yaml",
            "content_type: application/vnd.spindrel.html+interactive\n"
            "html_template:\n"
            "  path: image.html\n",
        )

        entries = html_widget_scanner.scan_builtin()
        slugs = {e["slug"] for e in entries}
        assert "notes" in slugs
        assert "image" not in slugs
        assert "generate_image" not in slugs

    def test_scan_empty_when_root_missing(self, tmp_path, monkeypatch):
        from app.services import html_widget_scanner
        monkeypatch.setattr(
            html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path / "does-not-exist",
        )
        monkeypatch.setattr(
            html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path / "also-missing",
        )
        assert html_widget_scanner.scan_builtin() == []


# ---------------------------------------------------------------------------
# scan_integration / scan_all_integrations
# ---------------------------------------------------------------------------

class TestScanIntegration:
    def test_scan_integration_returns_source_and_id(self, tmp_path, monkeypatch):
        from app.services import html_widget_scanner
        monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path / "missing-builtin")
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path)

        widgets_dir = tmp_path / "frigate" / "widgets"
        _write(
            widgets_dir / "custom_dashboard.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(
                name="Custom Dashboard", desc="Cameras", ver="1.0.0",
            ),
        )

        entries = html_widget_scanner.scan_integration("frigate")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["source"] == "integration"
        assert entry["integration_id"] == "frigate"
        assert entry["name"] == "Custom Dashboard"

    def test_scan_integration_excludes_tool_renderers(self, tmp_path, monkeypatch):
        """Widgets referenced by ``tool_widgets.<tool>.html_template.path`` in
        ``integration.yaml`` are tool renderers and must be excluded from the
        standalone catalog."""
        from app.services import html_widget_scanner
        monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path / "missing-builtin")
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path)

        integ_dir = tmp_path / "openweather"
        widgets_dir = integ_dir / "widgets"
        _write(
            widgets_dir / "get_weather.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="Weather tool renderer", desc="", ver="0.0.0"),
        )
        _write(
            widgets_dir / "standalone_forecast.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="Forecast", desc="", ver="1.0.0"),
        )
        _write(
            integ_dir / "integration.yaml",
            "id: openweather\n"
            "tool_widgets:\n"
            "  get_weather:\n"
            "    content_type: application/vnd.spindrel.html+interactive\n"
            "    html_template:\n"
            "      path: widgets/get_weather.html\n",
        )

        entries = html_widget_scanner.scan_integration("openweather")
        slugs = {e["slug"] for e in entries}
        assert "standalone_forecast" in slugs
        assert "get_weather" not in slugs

    def test_scan_integration_rejects_path_traversal(self, tmp_path, monkeypatch):
        """``integration_id`` containing ``..`` must not escape the integrations
        root."""
        from app.services import html_widget_scanner
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path)

        # Even if a file exists outside the root, the traversal guard returns [].
        outside = tmp_path.parent / "outside" / "widgets"
        _write(
            outside / "evil.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="evil", desc="", ver=""),
        )
        assert html_widget_scanner.scan_integration("../outside") == []

    def test_scan_all_integrations_omits_empty_dirs(self, tmp_path, monkeypatch):
        """Integrations that ship no standalone widgets are dropped from the
        grouped response so the UI renders compactly."""
        from app.services import html_widget_scanner
        monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path / "missing-builtin")
        monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", tmp_path)

        # frigate has one standalone widget.
        _write(
            tmp_path / "frigate" / "widgets" / "dash.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="Dash", desc="", ver=""),
        )
        # gmail has no widgets dir at all.
        (tmp_path / "gmail").mkdir()
        # github has widgets dir but only a tool-renderer (excluded) → empty.
        _write(
            tmp_path / "github" / "widgets" / "pr.html",
            WIDGET_HTML_WITH_FRONTMATTER.format(name="PR", desc="", ver=""),
        )
        _write(
            tmp_path / "github" / "integration.yaml",
            "tool_widgets:\n"
            "  github_get_pr:\n"
            "    html_template:\n"
            "      path: widgets/pr.html\n",
        )

        groups = html_widget_scanner.scan_all_integrations()
        ids = [iid for iid, _ in groups]
        assert ids == ["frigate"]
