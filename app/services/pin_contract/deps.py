"""Explicit dependency injection for the pin contract resolver chain.

The legacy ``widget_contracts.py`` reached into ``widget_presets``,
``widget_templates``, ``native_app_widgets``, and ``app.agent.bots`` via
in-function lazy imports to dodge circular imports. ``ContractDeps``
consolidates those reaches into a single dataclass wired once at app
startup, breaking the cycle by topology rather than by deferral.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.services.pin_contract.exceptions import (
    NativeSpecNotFound,
    PresetNotFound,
    TemplateNotFound,
)

logger = logging.getLogger(__name__)


# ── Registry façades ────────────────────────────────────────────────


class PresetRegistry:
    """Thin façade over ``app.services.widget_presets`` exposing the bits
    pin_contract needs and translating absent presets into ``PresetNotFound``.
    """

    def get(self, preset_id: str) -> dict[str, Any]:
        from app.services.widget_presets import (
            WidgetPresetValidationError,
            get_widget_preset,
        )

        try:
            preset = get_widget_preset(preset_id)
        except (KeyError, WidgetPresetValidationError) as exc:
            raise PresetNotFound(preset_id) from exc
        if preset is None:
            raise PresetNotFound(preset_id)
        return preset

    def tool_compatibility(self, preset_id: str) -> str | None:
        """Return the preset's declared ``tool_family`` (single-string today,
        ready to widen to a structured ToolCompatibility value later).
        Returns ``None`` when the preset doesn't declare one. Raises
        ``PresetNotFound`` only when the preset itself is missing.
        """
        preset = self.get(preset_id)
        family = preset.get("tool_family")
        if isinstance(family, str) and family.strip():
            return family.strip()
        return None


class ToolTemplateRegistry:
    """Façade over ``app.services.widget_templates``."""

    def get(self, tool_name: str) -> dict[str, Any] | None:
        from app.services.widget_templates import get_widget_template

        entry = get_widget_template(tool_name)
        if entry is None and "-" in tool_name:
            entry = get_widget_template(tool_name.split("-", 1)[1])
        return entry


class NativeCatalog:
    """Façade over ``app.services.native_app_widgets``."""

    def get(self, widget_ref: str):
        from app.services.native_app_widgets import get_native_widget_spec

        spec = get_native_widget_spec(widget_ref)
        if spec is None:
            raise NativeSpecNotFound(widget_ref)
        return spec


class HtmlManifestLocator:
    """Find an HTML widget bundle's directory + ``widget.yaml`` path on disk.

    Owns the ``app.agent.bots.get_bot`` import cycle that
    ``widget_contracts._resolve_html_widget_manifest_path`` previously
    dodged via lazy in-function imports.
    """

    def resolve_bundle_dir(
        self,
        envelope: dict[str, Any],
        *,
        source_bot_id: str | None,
    ) -> Path | None:
        # Reuse the existing resolver — it already encodes scope rules
        # (core/bot/workspace), integration paths, and channel paths. We just
        # need the *directory* not the manifest file, but the existing helper
        # returns ``widget.yaml``; flip to its parent.
        from app.services.widget_contracts import _resolve_html_widget_manifest_path

        manifest_path = _resolve_html_widget_manifest_path(
            envelope, source_bot_id=source_bot_id,
        )
        if manifest_path is None:
            return None
        return manifest_path.parent


# ── Composite ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContractDeps:
    presets: PresetRegistry
    templates: ToolTemplateRegistry
    natives: NativeCatalog
    html_manifests: HtmlManifestLocator


_DEPS: ContractDeps | None = None


def wire_pin_contract(deps: ContractDeps | None = None) -> ContractDeps:
    """Bind the module-level ``ContractDeps`` singleton.

    Called from ``app/main.py`` startup. Tests pass a fake ``deps`` to
    isolate from the real registries.
    """
    global _DEPS
    _DEPS = deps or ContractDeps(
        presets=PresetRegistry(),
        templates=ToolTemplateRegistry(),
        natives=NativeCatalog(),
        html_manifests=HtmlManifestLocator(),
    )
    return _DEPS


def get_deps() -> ContractDeps:
    """Return the wired ContractDeps. Wires defaults on first use so
    services that import pin_contract before ``app/main.py`` startup
    (e.g. unit tests bypassing the lifespan hook) still work.
    """
    if _DEPS is None:
        return wire_pin_contract()
    return _DEPS
