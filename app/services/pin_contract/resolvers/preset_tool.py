"""Preset-instantiated tool widget — ``tool_widget`` + ``preset``."""
from __future__ import annotations

import copy
import logging
from typing import Any, ClassVar

from app.services.pin_contract.exceptions import PresetNotFound
from app.services.pin_contract.resolvers import (
    LiveFields,
    WidgetOrigin,
    register_resolver,
)
from app.services.pin_contract.stamps import stamp_for_preset

logger = logging.getLogger(__name__)


@register_resolver
class PresetToolWidgetResolver:
    definition_kind: ClassVar[str] = "tool_widget"
    instantiation_kinds: ClassVar[frozenset[str]] = frozenset({"preset"})
    priority: ClassVar[int] = 20

    def claim(self, ident, deps) -> WidgetOrigin | None:
        envelope = ident.envelope
        source_preset_id = envelope.get("source_preset_id")
        if not isinstance(source_preset_id, str) or not source_preset_id.strip():
            return None
        preset_id = source_preset_id.strip()
        origin: WidgetOrigin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": "preset",
            "tool_name": ident.tool_name,
            "preset_id": preset_id,
        }
        template_id = envelope.get("template_id")
        if isinstance(template_id, str) and template_id.strip():
            origin["template_id"] = template_id.strip()
        # Best-effort tool_family enrichment. Replaces the silent
        # ``except Exception: pass`` at widget_contracts.py:514 — narrow to
        # PresetNotFound so real bugs (validation errors, etc.) propagate.
        try:
            family = deps.presets.tool_compatibility(preset_id)
            if family:
                origin["tool_family"] = family
        except PresetNotFound:
            logger.info(
                "preset_tool resolver: preset_id=%s not found while enriching origin",
                preset_id,
            )
        return origin

    def materialize(self, origin, ident, deps) -> LiveFields:
        from app.services.widget_contracts import (
            _merge_presentation_with_defaults,
            build_public_fields_for_tool_widget,
            build_widget_presentation,
            normalize_config_schema,
        )

        preset_id = origin.get("preset_id")
        if not isinstance(preset_id, str) or not preset_id.strip():
            return _materialize_direct(origin, ident)
        try:
            preset = deps.presets.get(preset_id.strip())
        except PresetNotFound:
            # Replaces the silent ``except Exception: pass`` at
            # widget_contracts.py:618. Log and downgrade to direct
            # tool-widget materialization — outer service flips
            # provenance_confidence to "inferred" via snapshot fallback.
            logger.warning(
                "preset_tool resolver: preset_id=%s missing during materialize; "
                "falling back to tool widget defaults",
                preset_id,
            )
            return _materialize_direct(origin, ident)

        tool_name = str(preset.get("tool_name") or origin.get("tool_name") or ident.tool_name)
        fields = build_public_fields_for_tool_widget(
            tool_name,
            instantiation_kind="preset",
        )
        config_schema = normalize_config_schema(preset.get("binding_schema"))
        preset_presentation = build_widget_presentation(
            presentation_family=preset.get("presentation_family"),
            panel_title=preset.get("panel_title"),
            show_panel_title=preset.get("show_panel_title"),
            layout_hints=preset.get("layout_hints"),
        )
        existing = fields.get("widget_presentation")
        if existing is None:
            merged_presentation = preset_presentation
        else:
            merged = copy.deepcopy(existing)
            merged.update(
                {k: v for k, v in preset_presentation.items() if v is not None}
            )
            merged_presentation = _merge_presentation_with_defaults(
                merged,
                fallback_layout_hints=preset.get("layout_hints"),
            )
        return LiveFields(
            config_schema=config_schema,
            widget_presentation=merged_presentation,
            widget_contract=fields.get("widget_contract"),
        )

    def stamp(self, origin, ident, deps) -> str | None:
        preset_id = origin.get("preset_id")
        if not isinstance(preset_id, str) or not preset_id.strip():
            return None
        return stamp_for_preset(preset_id.strip())


def _materialize_direct(origin, ident) -> LiveFields:
    from app.services.widget_contracts import build_public_fields_for_tool_widget

    fields = build_public_fields_for_tool_widget(
        str(origin.get("tool_name") or ident.tool_name),
        instantiation_kind="direct_tool_call",
    )
    return LiveFields(
        config_schema=fields.get("config_schema"),
        widget_presentation=fields.get("widget_presentation"),
        widget_contract=fields.get("widget_contract"),
    )
