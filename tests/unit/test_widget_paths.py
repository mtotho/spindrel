"""Unit tests for ``app.services.widget_paths`` — the ``widget://`` URI resolver.

Phase 1b of the Widget Library track: bots address widget bundles via a
virtual URI namespace instead of filesystem paths.  These tests lock in the
contract of ``resolve_widget_uri`` + ``scope_root`` so downstream tools can
rely on the read-only / traversal guarantees.
"""
from __future__ import annotations

import os

import pytest

from app.services.widget_paths import (
    CORE_WIDGETS_DIR,
    WIDGET_LIBRARY_DIRNAME,
    is_widget_uri,
    resolve_widget_uri,
    scope_root,
)


class TestIsWidgetUri:
    def test_recognizes_core(self):
        assert is_widget_uri("widget://core/examples/sdk-smoke/index.html")

    def test_recognizes_bot(self):
        assert is_widget_uri("widget://bot/foo")

    def test_rejects_workspace_path(self):
        assert not is_widget_uri("/workspace/foo.txt")

    def test_rejects_relative(self):
        assert not is_widget_uri("foo/bar.txt")


class TestScopeRoot:
    def test_core_always_available(self, tmp_path):
        assert scope_root("core", ws_root=None, shared_root=None) == CORE_WIDGETS_DIR

    def test_bot_uses_ws_root(self, tmp_path):
        ws = str(tmp_path)
        assert scope_root("bot", ws_root=ws, shared_root=None) == os.path.join(
            ws, WIDGET_LIBRARY_DIRNAME
        )

    def test_bot_none_without_ws_root(self):
        assert scope_root("bot", ws_root=None, shared_root=None) is None

    def test_workspace_uses_shared_root(self, tmp_path):
        shared = str(tmp_path)
        assert scope_root(
            "workspace", ws_root=None, shared_root=shared,
        ) == os.path.join(shared, WIDGET_LIBRARY_DIRNAME)

    def test_workspace_none_without_shared_root(self, tmp_path):
        assert scope_root(
            "workspace", ws_root=str(tmp_path), shared_root=None,
        ) is None


class TestResolveCore:
    def test_resolves_index_html(self):
        path, scope, name, ro = resolve_widget_uri(
            "widget://core/examples/sdk-smoke/index.html", ws_root=None, shared_root=None,
        )
        assert scope == "core"
        assert name == "examples"
        assert ro is True
        assert path.endswith("/widgets/examples/sdk-smoke/index.html")

    def test_resolves_bare_bundle_dir(self):
        path, _scope, _name, _ro = resolve_widget_uri(
            "widget://core/examples", ws_root=None, shared_root=None,
        )
        assert path.endswith("/widgets/examples")

    def test_traversal_to_sibling_bundle_blocked(self):
        with pytest.raises(ValueError, match="escapes bundle"):
            resolve_widget_uri(
                "widget://core/examples/../other", ws_root=None, shared_root=None,
            )

    def test_traversal_via_slashdot_blocked(self):
        with pytest.raises(ValueError, match="escapes bundle"):
            resolve_widget_uri(
                "widget://core/examples/../../etc/passwd",
                ws_root=None, shared_root=None,
            )


class TestResolveBot:
    def test_resolves_under_ws_widget_library(self, tmp_path):
        ws = str(tmp_path)
        path, scope, name, ro = resolve_widget_uri(
            "widget://bot/foo/index.html", ws_root=ws, shared_root=None,
        )
        assert scope == "bot"
        assert name == "foo"
        assert ro is False
        assert path == os.path.realpath(
            os.path.join(ws, WIDGET_LIBRARY_DIRNAME, "foo", "index.html")
        )

    def test_errors_without_ws_root(self):
        with pytest.raises(ValueError, match="unavailable"):
            resolve_widget_uri(
                "widget://bot/foo", ws_root=None, shared_root=None,
            )

    def test_traversal_blocked(self, tmp_path):
        ws = str(tmp_path)
        with pytest.raises(ValueError, match="escapes bundle"):
            resolve_widget_uri(
                "widget://bot/foo/../bar", ws_root=ws, shared_root=None,
            )


class TestResolveWorkspace:
    def test_resolves_under_shared_widget_library(self, tmp_path):
        shared = str(tmp_path / "shared")
        os.makedirs(shared)
        ws = str(tmp_path / "shared" / "bots" / "my_bot")
        os.makedirs(ws)
        path, scope, name, ro = resolve_widget_uri(
            "widget://workspace/team_board/widget.yaml",
            ws_root=ws, shared_root=shared,
        )
        assert scope == "workspace"
        assert ro is False
        assert path == os.path.realpath(
            os.path.join(shared, WIDGET_LIBRARY_DIRNAME, "team_board", "widget.yaml")
        )

    def test_errors_without_shared_root_mentions_bot_alternative(self, tmp_path):
        ws = str(tmp_path)
        with pytest.raises(ValueError, match="shared workspace"):
            resolve_widget_uri(
                "widget://workspace/foo",
                ws_root=ws, shared_root=None,
            )


class TestResolveMalformed:
    def test_unknown_scope_rejected(self):
        with pytest.raises(ValueError, match="Invalid widget:// URI"):
            resolve_widget_uri(
                "widget://rogue/foo", ws_root="/tmp", shared_root=None,
            )

    def test_missing_name_rejected(self):
        with pytest.raises(ValueError, match="must include a widget name"):
            resolve_widget_uri(
                "widget://bot/", ws_root="/tmp", shared_root=None,
            )

    def test_invalid_name_rejected(self):
        with pytest.raises(ValueError, match="Invalid widget name"):
            resolve_widget_uri(
                "widget://bot/has spaces/index.html",
                ws_root="/tmp", shared_root=None,
            )

    def test_not_a_widget_uri_rejected(self):
        with pytest.raises(ValueError, match="Invalid widget:// URI"):
            resolve_widget_uri(
                "workspace/foo", ws_root="/tmp", shared_root=None,
            )
