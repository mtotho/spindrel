"""Tests for app.services.html_widget_scanner.

Covers:
  * Frontmatter parsing (happy path, absent, malformed, non-dict)
  * Workspace scan: bundle discovery, loose-file detection via spindrel ref,
    ordering, de-dup of dual-match entries
  * mtime cache: hit, miss-on-mtime-change, negative-result caching
  * Path-traversal / symlink escape protection
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _make_bot():
    return SimpleNamespace(
        id="bot-test",
        shared_workspace_id="ws-1",
        shared_workspace_role="worker",
    )


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_valid_frontmatter_is_extracted(self):
        from app.services.html_widget_scanner import parse_frontmatter
        html = (
            "<!--\n"
            "---\n"
            "name: Project status\n"
            "version: 1.2.0\n"
            "tags: [dashboard, project]\n"
            "---\n"
            "-->\n"
            "<div>body</div>"
        )
        meta = parse_frontmatter(html)
        assert meta["name"] == "Project status"
        assert meta["version"] == "1.2.0"
        assert meta["tags"] == ["dashboard", "project"]

    def test_missing_frontmatter_returns_empty(self):
        from app.services.html_widget_scanner import parse_frontmatter
        assert parse_frontmatter("<div>hi</div>") == {}

    def test_empty_input_returns_empty(self):
        from app.services.html_widget_scanner import parse_frontmatter
        assert parse_frontmatter("") == {}

    def test_malformed_yaml_returns_empty_not_raise(self):
        from app.services.html_widget_scanner import parse_frontmatter
        html = "<!--\n---\nname: [unterminated\n---\n-->\n<div/>"
        # Must not raise — a bad block should never crash a scan.
        assert parse_frontmatter(html) == {}

    def test_non_dict_yaml_returns_empty(self):
        """A frontmatter block that parses to a list or scalar must be
        discarded — callers expect a dict."""
        from app.services.html_widget_scanner import parse_frontmatter
        html = "<!--\n---\n- just\n- a list\n---\n-->\n<div/>"
        assert parse_frontmatter(html) == {}

    def test_frontmatter_must_be_leading(self):
        """A frontmatter block appearing mid-document should not match."""
        from app.services.html_widget_scanner import parse_frontmatter
        html = "<div>prefix</div>\n<!--\n---\nname: nope\n---\n-->"
        assert parse_frontmatter(html) == {}


# ---------------------------------------------------------------------------
# has_spindrel_reference
# ---------------------------------------------------------------------------

class TestHasSpindrelReference:
    def test_detects_window_spindrel(self):
        from app.services.html_widget_scanner import has_spindrel_reference
        assert has_spindrel_reference("<script>window.spindrel.api('/x')</script>")

    def test_detects_bare_spindrel_token(self):
        from app.services.html_widget_scanner import has_spindrel_reference
        assert has_spindrel_reference("const s = spindrel.callTool('x')")

    def test_absent_returns_false(self):
        from app.services.html_widget_scanner import has_spindrel_reference
        assert not has_spindrel_reference("<div>no js here</div>")

    def test_empty_returns_false(self):
        from app.services.html_widget_scanner import has_spindrel_reference
        assert not has_spindrel_reference("")


# ---------------------------------------------------------------------------
# scan_channel — bundle discovery
# ---------------------------------------------------------------------------

_BUNDLE_HTML = """<!--
---
name: Project status
description: Live phase tracker
version: 1.2.0
tags: [dashboard, project]
---
-->
<div class="sd-card">hello</div>
"""

_LOOSE_HTML = """<!-- no frontmatter -->
<script>window.spindrel.api('/x')</script>
<div>loose widget</div>
"""

_NOT_A_WIDGET = "<html><body>Just a markdown export</body></html>"


@pytest.fixture
def tmp_workspace():
    """Yields (channel_id, bot, ws_path) with scanner cache cleared + mocked root."""
    from app.services import html_widget_scanner
    html_widget_scanner.invalidate_cache()
    with tempfile.TemporaryDirectory() as tmp:
        bot = _make_bot()
        with patch(
            "app.services.html_widget_scanner.get_channel_workspace_root",
            return_value=tmp,
        ):
            yield ("ch-1", bot, tmp)
    html_widget_scanner.invalidate_cache()


class TestScanChannel:
    def test_empty_workspace_returns_empty(self, tmp_workspace):
        from app.services.html_widget_scanner import scan_channel
        ch, bot, _ws = tmp_workspace
        assert scan_channel(ch, bot) == []

    def test_discovers_bundle_widget(self, tmp_workspace):
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(os.path.join(ws, "data/widgets/project-status/index.html"), _BUNDLE_HTML)
        entries = scan_channel(ch, bot)
        assert len(entries) == 1
        e = entries[0]
        assert e["path"] == "data/widgets/project-status/index.html"
        assert e["slug"] == "project-status"
        assert e["name"] == "Project status"
        assert e["version"] == "1.2.0"
        assert e["tags"] == ["dashboard", "project"]
        assert e["is_bundle"] is True
        assert e["is_loose"] is False

    def test_discovers_loose_file_with_spindrel_ref(self, tmp_workspace):
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(os.path.join(ws, "notes/scratch.html"), _LOOSE_HTML)
        entries = scan_channel(ch, bot)
        assert len(entries) == 1
        assert entries[0]["is_bundle"] is False
        assert entries[0]["is_loose"] is True
        # Frontmatter absent -> slug fallback
        assert entries[0]["name"] == "scratch"

    def test_skips_html_without_spindrel_outside_widgets_dir(self, tmp_workspace):
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(os.path.join(ws, "reports/summary.html"), _NOT_A_WIDGET)
        assert scan_channel(ch, bot) == []

    def test_bundle_match_wins_over_loose_when_both_rules_apply(self, tmp_workspace):
        """A file inside widgets/ that also has a spindrel ref should be
        listed once, as a bundle (is_loose=False)."""
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(
            os.path.join(ws, "data/widgets/combo/index.html"),
            _BUNDLE_HTML + "\n<script>window.spindrel.api('/x')</script>",
        )
        entries = scan_channel(ch, bot)
        assert len(entries) == 1
        assert entries[0]["is_bundle"] is True
        assert entries[0]["is_loose"] is False

    def test_bundles_sorted_before_loose_files(self, tmp_workspace):
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(os.path.join(ws, "notes/scratch.html"), _LOOSE_HTML)
        _write(os.path.join(ws, "data/widgets/zebra/index.html"), _BUNDLE_HTML.replace("Project status", "Zebra"))
        _write(os.path.join(ws, "data/widgets/apple/index.html"), _BUNDLE_HTML.replace("Project status", "Apple"))
        entries = scan_channel(ch, bot)
        assert [e["name"] for e in entries] == ["Apple", "Zebra", "scratch"]

    def test_frontmatter_fallbacks_use_path_slug(self, tmp_workspace):
        """Empty frontmatter -> slug from the containing directory."""
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(
            os.path.join(ws, "data/widgets/home-control/index.html"),
            "<div>no frontmatter, no spindrel</div>",
        )
        entries = scan_channel(ch, bot)
        assert len(entries) == 1
        assert entries[0]["name"] == "home-control"
        assert entries[0]["display_label"] == "home-control"
        assert entries[0]["version"] == "0.0.0"

    def test_hidden_dirs_are_skipped(self, tmp_workspace):
        """``.versions``/``.git`` etc. must not be walked."""
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        _write(os.path.join(ws, ".versions/data/widgets/x/index.html"), _BUNDLE_HTML)
        assert scan_channel(ch, bot) == []


# ---------------------------------------------------------------------------
# mtime cache behavior
# ---------------------------------------------------------------------------

class TestMtimeCache:
    def test_cache_reuses_parsed_metadata_when_mtime_unchanged(self, tmp_workspace, monkeypatch):
        from app.services import html_widget_scanner
        ch, bot, ws = tmp_workspace
        path = os.path.join(ws, "data/widgets/p/index.html")
        _write(path, _BUNDLE_HTML)

        # Prime the cache with one scan.
        html_widget_scanner.scan_channel(ch, bot)

        # Second scan — intercept open() to confirm it's NOT called.
        real_open = open
        opens: list[str] = []

        def _tracking_open(p, *a, **kw):
            opens.append(str(p))
            return real_open(p, *a, **kw)

        monkeypatch.setattr("builtins.open", _tracking_open)
        html_widget_scanner.scan_channel(ch, bot)
        # The scanner should not have re-read the widget file (mtime unchanged).
        assert not any(str(path) in o for o in opens)

    def test_cache_busts_on_mtime_change(self, tmp_workspace):
        from app.services import html_widget_scanner
        ch, bot, ws = tmp_workspace
        path = os.path.join(ws, "data/widgets/p/index.html")
        _write(path, _BUNDLE_HTML)
        first = html_widget_scanner.scan_channel(ch, bot)
        assert first[0]["version"] == "1.2.0"

        # Edit the file AND bump mtime explicitly (tempdir mtimes can repeat).
        _write(path, _BUNDLE_HTML.replace("1.2.0", "2.0.0"))
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))

        second = html_widget_scanner.scan_channel(ch, bot)
        assert second[0]["version"] == "2.0.0"

    def test_non_widget_files_are_cached_negative(self, tmp_workspace, monkeypatch):
        """An HTML file that's neither a bundle nor spindrel-referencing
        should be cached so subsequent scans don't re-read it."""
        from app.services import html_widget_scanner
        ch, bot, ws = tmp_workspace
        path = os.path.join(ws, "reports/summary.html")
        _write(path, _NOT_A_WIDGET)

        html_widget_scanner.scan_channel(ch, bot)

        real_open = open
        opens: list[str] = []

        def _tracking_open(p, *a, **kw):
            opens.append(str(p))
            return real_open(p, *a, **kw)

        monkeypatch.setattr("builtins.open", _tracking_open)
        html_widget_scanner.scan_channel(ch, bot)
        assert not any(str(path) in o for o in opens)


# ---------------------------------------------------------------------------
# Security: symlink / traversal protection
# ---------------------------------------------------------------------------

class TestSecurityGuards:
    def test_symlinks_are_skipped(self, tmp_workspace):
        """A symlink inside the workspace pointing at a file with widget
        content must not be included — the scanner walks with
        ``followlinks=False`` AND rejects symlinked files explicitly."""
        from app.services.html_widget_scanner import scan_channel
        ch, bot, ws = tmp_workspace
        real_target = os.path.join(ws, "..", "external-widget.html")
        _write(os.path.realpath(real_target), _BUNDLE_HTML)
        try:
            link_path = os.path.join(ws, "data/widgets/link/index.html")
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            os.symlink(os.path.realpath(real_target), link_path)
        except OSError:
            pytest.skip("symlink not supported on this filesystem")
        entries = scan_channel(ch, bot)
        assert entries == []
