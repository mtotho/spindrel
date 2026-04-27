"""Unit tests for the five OriginResolvers in ``app/services/pin_contract/resolvers/``.

Each resolver claims a ``(definition_kind, instantiation_kind)`` pair. These
tests pin the claim selection, the materialize live-fields shape, and the
stamp behavior — including the narrow-exception branches that replaced the
silent ``except Exception: pass`` at ``widget_contracts.py:514`` and ``:618``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from app.services.pin_contract.deps import (
    ContractDeps,
    HtmlManifestLocator,
    NativeCatalog,
    PresetRegistry,
    ToolTemplateRegistry,
)
from app.services.pin_contract.exceptions import (
    NativeSpecNotFound,
    PresetNotFound,
)
from app.services.pin_contract.resolvers import LiveFields, all_resolvers
from app.services.pin_contract.resolvers.direct_tool import DirectToolCallResolver
from app.services.pin_contract.resolvers.html_library import HtmlLibraryResolver
from app.services.pin_contract.resolvers.html_runtime import HtmlRuntimeEmitResolver
from app.services.pin_contract.resolvers.native import NativeCatalogResolver
from app.services.pin_contract.resolvers.preset_tool import PresetToolWidgetResolver
from app.services.pin_contract.service import PinIdentity


# ── Fakes ───────────────────────────────────────────────────────────


class _FakePresets(PresetRegistry):
    def __init__(self, presets: dict[str, dict[str, Any]] | None = None):
        self._presets = presets or {}

    def get(self, preset_id: str):
        if preset_id not in self._presets:
            raise PresetNotFound(preset_id)
        return self._presets[preset_id]

    def tool_compatibility(self, preset_id: str) -> str | None:
        preset = self.get(preset_id)
        family = preset.get("tool_family")
        return family.strip() if isinstance(family, str) and family.strip() else None


class _FakeTemplates(ToolTemplateRegistry):
    def __init__(self, entries: dict[str, dict[str, Any]] | None = None):
        self._entries = entries or {}

    def get(self, tool_name: str):
        return self._entries.get(tool_name)


class _FakeNatives(NativeCatalog):
    def __init__(self, available: set[str] | None = None):
        self._available = available or set()

    def get(self, widget_ref: str):
        if widget_ref not in self._available:
            raise NativeSpecNotFound(widget_ref)
        # Return something truthy with the attrs stamp_for_native_widget_ref reads.
        return type(
            "Spec",
            (),
            {
                "widget_ref": widget_ref,
                "config_schema": None,
                "presentation_family": "card",
                "panel_title": None,
                "show_panel_title": None,
                "layout_hints": None,
                "supported_scopes": [],
                "context_export": None,
            },
        )()


class _FakeManifests(HtmlManifestLocator):
    def __init__(self, dir_for_envelope=None):
        self._dir = dir_for_envelope

    def resolve_bundle_dir(self, envelope, *, source_bot_id):
        return self._dir


def _deps(
    presets: PresetRegistry | None = None,
    templates: ToolTemplateRegistry | None = None,
    natives: NativeCatalog | None = None,
    html_manifests: HtmlManifestLocator | None = None,
) -> ContractDeps:
    return ContractDeps(
        presets=presets or _FakePresets(),
        templates=templates or _FakeTemplates(),
        natives=natives or _FakeNatives(),
        html_manifests=html_manifests or _FakeManifests(),
    )


def _ident(*, tool_name="t", envelope=None, source_bot_id=None) -> PinIdentity:
    return PinIdentity(
        tool_name=tool_name,
        envelope=envelope or {},
        source_bot_id=source_bot_id,
    )


# ── Registry ────────────────────────────────────────────────────────


class TestRegistryOrdering:
    def test_priority_order(self):
        names = [r.__class__.__name__ for r in all_resolvers()]
        # Native catalog claims first (content_type sniff), HTML runtime emit
        # is the catch-all last.
        assert names[0] == "NativeCatalogResolver"
        assert names[-1] == "HtmlRuntimeEmitResolver"

    def test_priority_strict_increasing(self):
        priorities = [r.priority for r in all_resolvers()]
        assert priorities == sorted(priorities)


# ── NativeCatalogResolver ───────────────────────────────────────────


class TestNativeResolver:
    def test_claims_native_envelope(self):
        ident = _ident(
            tool_name="emit_native",
            envelope={
                "content_type": "application/vnd.spindrel.native-app+json",
                "body": {"widget_ref": "core/notes_native"},
            },
        )
        origin = NativeCatalogResolver().claim(ident, _deps())
        assert origin == {
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "core/notes_native",
        }

    def test_skips_non_native(self):
        ident = _ident(envelope={"content_type": "text/plain"})
        assert NativeCatalogResolver().claim(ident, _deps()) is None

    def test_skips_native_without_widget_ref(self):
        ident = _ident(
            envelope={
                "content_type": "application/vnd.spindrel.native-app+json",
                "body": {},
            },
        )
        assert NativeCatalogResolver().claim(ident, _deps()) is None

    def test_stamp_returns_none_for_missing_spec(self):
        origin = {
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "core/never_existed",
        }
        # natives is empty fake → NativeSpecNotFound → None
        assert NativeCatalogResolver().stamp(origin, _ident(), _deps()) is None


# ── PresetToolWidgetResolver ────────────────────────────────────────


class TestPresetResolver:
    def test_claims_when_preset_id_present(self):
        ident = _ident(envelope={"source_preset_id": "ha.light"})
        deps = _deps(presets=_FakePresets({"ha.light": {"tool_family": "homeassistant"}}))
        origin = PresetToolWidgetResolver().claim(ident, deps)
        assert origin["definition_kind"] == "tool_widget"
        assert origin["instantiation_kind"] == "preset"
        assert origin["preset_id"] == "ha.light"
        assert origin["tool_family"] == "homeassistant"

    def test_skip_when_no_preset_id(self):
        ident = _ident(envelope={})
        assert PresetToolWidgetResolver().claim(ident, _deps()) is None

    def test_missing_preset_during_claim_omits_family(self):
        # Replaces silent except at widget_contracts.py:514 — narrow miss
        # logs but does not raise.
        ident = _ident(envelope={"source_preset_id": "gone.preset"})
        deps = _deps(presets=_FakePresets({}))  # empty registry
        origin = PresetToolWidgetResolver().claim(ident, deps)
        assert origin is not None
        assert origin["preset_id"] == "gone.preset"
        assert "tool_family" not in origin

    def test_missing_preset_during_materialize_falls_back(self):
        # Replaces silent except at widget_contracts.py:618 — fallback path
        # serves direct-tool defaults; outer service then folds with snapshot.
        origin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": "preset",
            "tool_name": "x",
            "preset_id": "gone.preset",
        }
        live = PresetToolWidgetResolver().materialize(
            origin, _ident(tool_name="x"), _deps(),
        )
        assert isinstance(live, LiveFields)
        # Tool template is also missing (empty FakeTemplates) → all None.
        assert live.config_schema is None
        assert live.widget_contract is None


# ── DirectToolCallResolver ──────────────────────────────────────────


class TestDirectToolResolver:
    def test_claims_when_template_exists(self):
        deps = _deps(templates=_FakeTemplates({"get_weather": {"template": {}}}))
        ident = _ident(tool_name="get_weather")
        origin = DirectToolCallResolver().claim(ident, deps)
        assert origin == {
            "definition_kind": "tool_widget",
            "instantiation_kind": "direct_tool_call",
            "tool_name": "get_weather",
        }

    def test_no_claim_when_template_missing(self):
        # Without a registered template, this resolver doesn't claim — the
        # html_runtime catch-all picks it up instead.
        ident = _ident(tool_name="not_a_template")
        assert DirectToolCallResolver().claim(ident, _deps()) is None

    def test_runtime_emit_kind_when_envelope_signals(self):
        deps = _deps(templates=_FakeTemplates({"html_widget": {"template": {}}}))
        ident = _ident(
            tool_name="html_widget",
            envelope={"source_path": "x.html"},
        )
        origin = DirectToolCallResolver().claim(ident, deps)
        # source_path triggers library_pin in the inference helper, but
        # library_pin isn't in DirectToolCallResolver's instantiation_kinds
        # so it falls through to direct_tool_call.
        assert origin["instantiation_kind"] in {"direct_tool_call", "runtime_emit"}


# ── HtmlLibraryResolver ─────────────────────────────────────────────


class TestHtmlLibraryResolver:
    def test_claims_with_library_ref(self):
        ident = _ident(
            envelope={"source_library_ref": "bot/dashboard"},
            source_bot_id="b1",
        )
        origin = HtmlLibraryResolver().claim(ident, _deps())
        assert origin == {
            "definition_kind": "html_widget",
            "instantiation_kind": "library_pin",
            "source_library_ref": "bot/dashboard",
            "source_bot_id": "b1",
        }

    def test_claims_with_source_path(self):
        ident = _ident(envelope={"source_path": "thing/index.html", "source_kind": "channel"})
        origin = HtmlLibraryResolver().claim(ident, _deps())
        assert origin["definition_kind"] == "html_widget"
        assert origin["source_path"] == "thing/index.html"
        assert origin["source_kind"] == "channel"

    def test_no_claim_without_source_signals(self):
        ident = _ident(envelope={})
        assert HtmlLibraryResolver().claim(ident, _deps()) is None


# ── HtmlRuntimeEmitResolver (catch-all) ─────────────────────────────


class TestHtmlRuntimeResolver:
    def test_claims_anything(self):
        # Designed as the last-resort fallback. Always claims.
        origin = HtmlRuntimeEmitResolver().claim(_ident(), _deps())
        assert origin is not None
        assert origin["definition_kind"] == "html_widget"

    def test_stamp_is_none(self):
        # Runtime emits have no live source — snapshot is canonical.
        origin = {"definition_kind": "html_widget", "instantiation_kind": "runtime_emit"}
        assert HtmlRuntimeEmitResolver().stamp(origin, _ident(), _deps()) is None
