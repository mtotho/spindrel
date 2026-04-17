"""Unit tests for the widget-package synthetic module loader."""
from __future__ import annotations

import sys
from uuid import uuid4

import pytest

from app.services.widget_package_loader import (
    discard_preview_module,
    invalidate,
    load_package_module,
    load_preview_module,
    module_name_for,
    resolve_transform_ref,
    rewrite_refs_for_preview,
)


class TestLoadPackageModule:
    def test_loads_and_exposes_transform(self):
        pkg_id = uuid4()
        code = "def transform(data, components):\n    return components + [{'type': 'text', 'content': 'added'}]\n"
        try:
            module = load_package_module(pkg_id, 1, code)
            assert module is not None
            result = module.transform({}, [{"type": "heading", "text": "x"}])
            assert result[-1] == {"type": "text", "content": "added"}
        finally:
            invalidate(pkg_id)

    def test_returns_cached_on_same_version(self):
        pkg_id = uuid4()
        code = "def transform(d, c): return c\n"
        try:
            m1 = load_package_module(pkg_id, 1, code)
            m2 = load_package_module(pkg_id, 1, code)
            assert m1 is m2
        finally:
            invalidate(pkg_id)

    def test_reloads_on_version_bump(self):
        pkg_id = uuid4()
        try:
            m1 = load_package_module(pkg_id, 1, "V = 1\n")
            m2 = load_package_module(pkg_id, 2, "V = 2\n")
            assert m1 is not m2
            assert m2.V == 2
        finally:
            invalidate(pkg_id)

    def test_empty_code_clears_module(self):
        pkg_id = uuid4()
        load_package_module(pkg_id, 1, "X = 1\n")
        name = module_name_for(pkg_id)
        assert name in sys.modules
        out = load_package_module(pkg_id, 2, "")
        assert out is None
        assert name not in sys.modules

    def test_syntax_error_does_not_register_module(self):
        pkg_id = uuid4()
        name = module_name_for(pkg_id)
        try:
            with pytest.raises(SyntaxError):
                load_package_module(pkg_id, 1, "def broken(:")
        finally:
            invalidate(pkg_id)
        assert name not in sys.modules

    def test_exec_error_cleans_up(self):
        pkg_id = uuid4()
        name = module_name_for(pkg_id)
        try:
            with pytest.raises(RuntimeError):
                load_package_module(pkg_id, 1, "raise RuntimeError('boom')")
        finally:
            invalidate(pkg_id)
        assert name not in sys.modules

    def test_importlib_finds_synthetic_module(self):
        """Proves the integration with apply_widget_template's import path."""
        import importlib
        pkg_id = uuid4()
        code = "def transform(d, c): return c + [{'type': 'text', 'content': 'via_import'}]\n"
        try:
            load_package_module(pkg_id, 1, code)
            mod = importlib.import_module(module_name_for(pkg_id))
            assert mod.transform({}, []) == [{"type": "text", "content": "via_import"}]
        finally:
            invalidate(pkg_id)


class TestResolveTransformRef:
    def test_self_is_rewritten(self):
        pkg_id = uuid4()
        assert resolve_transform_ref("self:transform", pkg_id) == (
            f"{module_name_for(pkg_id)}:transform"
        )

    def test_module_path_passes_through(self):
        pkg_id = uuid4()
        assert resolve_transform_ref(
            "app.tools.local.task_widget_transforms:task_detail", pkg_id,
        ) == "app.tools.local.task_widget_transforms:task_detail"

    def test_none_returns_none(self):
        assert resolve_transform_ref(None, uuid4()) is None


class TestPreviewModule:
    def test_load_and_discard(self):
        module, name = load_preview_module(
            "def transform(d, c): return c + [{'type': 'text', 'content': 'p'}]\n",
        )
        assert module is not None
        assert name is not None
        assert name in sys.modules
        assert name.startswith("spindrel.widget_packages.preview_")
        discard_preview_module(name)
        assert name not in sys.modules

    def test_empty_code_returns_none_name(self):
        module, name = load_preview_module(None)
        assert module is None
        assert name is None


class TestRewriteRefsForPreview:
    def test_rewrites_self_with_preview_name(self):
        out = rewrite_refs_for_preview(
            {"transform": "self:foo", "template": {"v": 1, "components": []}},
            "preview_mod",
        )
        assert out["transform"] == "preview_mod:foo"

    def test_leaves_self_untouched_without_module(self):
        out = rewrite_refs_for_preview(
            {"transform": "self:foo", "template": {"v": 1, "components": []}},
            None,
        )
        assert out["transform"] == "self:foo"

    def test_rewrites_state_poll_transform(self):
        out = rewrite_refs_for_preview(
            {
                "template": {"v": 1, "components": []},
                "state_poll": {"transform": "self:poll_xform", "template": {"v": 1}},
            },
            "preview_mod",
        )
        assert out["state_poll"]["transform"] == "preview_mod:poll_xform"
