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
    widget_scope_policy,
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


class TestWidgetScopePolicy:
    def test_workspace_is_explicit_shared_library_scope(self):
        policy = widget_scope_policy("workspace")

        assert policy.root_kind == "shared_workspace_library"
        assert policy.requires_shared_root is True
        assert policy.sharing_model == "workspace_shared_library"
        assert policy.read_only is False

    def test_core_is_read_only(self):
        assert widget_scope_policy("core").read_only is True


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


class TestSymlinkRejection:
    """A bot with shell access could ``ln -s /etc /workspace/.widget_library/foo``
    to make their own bundle dir a symlink. The realpath traversal guard
    passes in that case (both ends resolve through the link). Component-by-
    component symlink rejection closes the gap — every existing path
    segment from the library root down to the target must be a real dir.
    """

    def test_bundle_root_symlink_rejected(self, tmp_path):
        ws = tmp_path
        library = ws / WIDGET_LIBRARY_DIRNAME
        library.mkdir()
        # Attacker creates a symlink at the bundle root pointing at /etc
        bundle_link = library / "evil"
        bundle_link.symlink_to("/etc")
        with pytest.raises(ValueError, match="symlink"):
            resolve_widget_uri(
                "widget://bot/evil/passwd",
                ws_root=str(ws), shared_root=None,
            )

    def test_intermediate_symlink_to_sibling_bundle_rejected(self, tmp_path):
        """Link-laundering: point a sub-dir at another bundle so realpath stays
        inside the library. The realpath traversal guard alone wouldn't catch
        this; the symlink-component check does.
        """
        ws = tmp_path
        library = ws / WIDGET_LIBRARY_DIRNAME
        foo = library / "foo"
        bar = library / "bar"
        foo.mkdir(parents=True)
        bar.mkdir()
        (bar / "secret.txt").write_text("bar-secret")
        # foo/peek -> ../bar — realpath of foo/peek/secret.txt resolves to
        # library/bar/secret.txt, which DOES start with library/foo, so
        # realpath alone wouldn't reject... no wait, foo != bar, so
        # startswith(library/foo) is False, realpath catches it. Pick a
        # case where the link target is inside the bundle:
        target_inside = foo / "real_subdir"
        target_inside.mkdir()
        (target_inside / "real.txt").write_text("inside")
        # foo/laundered -> foo/real_subdir (a symlink pointing inside the
        # same bundle). realpath resolves to foo/real_subdir, which IS
        # under foo, so realpath alone permits it. Symlink check rejects.
        (foo / "laundered").symlink_to(target_inside)
        with pytest.raises(ValueError, match="symlink"):
            resolve_widget_uri(
                "widget://bot/foo/laundered/real.txt",
                ws_root=str(ws), shared_root=None,
            )

    def test_leaf_symlink_to_outside_rejected(self, tmp_path):
        """A symlink leaf pointing outside the bundle is rejected. The realpath
        traversal guard already catches this (different error message); we
        accept either rejection path so both layers are covered.
        """
        ws = tmp_path
        library = ws / WIDGET_LIBRARY_DIRNAME
        bundle = library / "foo"
        bundle.mkdir(parents=True)
        (bundle / "evil").symlink_to("/etc/passwd")
        with pytest.raises(ValueError, match="symlink|escapes bundle"):
            resolve_widget_uri(
                "widget://bot/foo/evil",
                ws_root=str(ws), shared_root=None,
            )

    def test_new_file_under_real_bundle_allowed(self, tmp_path):
        """Writing a new file inside a real bundle is fine — only existing
        components are checked, and a non-existent leaf doesn't trigger.
        """
        ws = tmp_path
        bundle = ws / WIDGET_LIBRARY_DIRNAME / "foo"
        bundle.mkdir(parents=True)
        # leaf doesn't exist yet — this is the "first write" case
        path, scope, name, ro = resolve_widget_uri(
            "widget://bot/foo/index.html",
            ws_root=str(ws), shared_root=None,
        )
        assert scope == "bot"
        assert name == "foo"
        assert path.endswith("foo/index.html")

    def test_workspace_symlinked_bundle_rejected(self, tmp_path):
        shared = tmp_path / "shared"
        ws = shared / "bots" / "my_bot"
        ws.mkdir(parents=True)
        library = shared / WIDGET_LIBRARY_DIRNAME
        library.mkdir()
        # Workspace-shared bundle root is a symlink pointing at /etc
        (library / "team_evil").symlink_to("/etc")
        with pytest.raises(ValueError, match="symlink"):
            resolve_widget_uri(
                "widget://workspace/team_evil/passwd",
                ws_root=str(ws), shared_root=str(shared),
            )
