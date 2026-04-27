"""Direct tool call → ``tool_widget`` whenever a registered tool template exists.

Catches the path where a tool widget is rendered straight from a tool
result (no preset, no library bundle). Lower priority than the preset
resolver so preset-bound pins don't get downgraded.
"""
from __future__ import annotations

from typing import ClassVar

from app.services.pin_contract.resolvers import (
    LiveFields,
    WidgetOrigin,
    register_resolver,
)
from app.services.pin_contract.stamps import stamp_for_tool_template


@register_resolver
class DirectToolCallResolver:
    definition_kind: ClassVar[str] = "tool_widget"
    instantiation_kinds: ClassVar[frozenset[str]] = frozenset(
        {"direct_tool_call", "runtime_emit"}
    )
    priority: ClassVar[int] = 30

    def claim(self, ident, deps) -> WidgetOrigin | None:
        # Only claim when an actual tool template is registered for this name.
        entry = deps.templates.get(ident.tool_name)
        if entry is None:
            return None
        instantiation_kind = _infer_instantiation_kind(ident)
        if instantiation_kind not in self.instantiation_kinds:
            # An emit_html_widget call ends up here too, but its template
            # entry is None (it's not a tool widget) — guarded above.
            instantiation_kind = "direct_tool_call"
        origin: WidgetOrigin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": instantiation_kind,
            "tool_name": ident.tool_name,
        }
        template_id = ident.envelope.get("template_id")
        if isinstance(template_id, str) and template_id.strip():
            origin["template_id"] = template_id.strip()
        return origin

    def materialize(self, origin, ident, deps) -> LiveFields:
        from app.services.widget_contracts import build_public_fields_for_tool_widget

        instantiation_kind = str(
            origin.get("instantiation_kind") or "direct_tool_call"
        )
        fields = build_public_fields_for_tool_widget(
            str(origin.get("tool_name") or ident.tool_name),
            instantiation_kind=instantiation_kind,
        )
        return LiveFields(
            config_schema=fields.get("config_schema"),
            widget_presentation=fields.get("widget_presentation"),
            widget_contract=fields.get("widget_contract"),
        )

    def stamp(self, origin, ident, deps) -> str | None:
        return stamp_for_tool_template(
            str(origin.get("tool_name") or ident.tool_name)
        )


def _infer_instantiation_kind(ident) -> str:
    envelope = ident.envelope
    source_instantiation_kind = envelope.get("source_instantiation_kind")
    if isinstance(source_instantiation_kind, str) and source_instantiation_kind.strip():
        return source_instantiation_kind.strip()
    if envelope.get("source_library_ref") or envelope.get("source_path"):
        return "library_pin"
    if ident.tool_name == "html_widget":
        return "runtime_emit"
    return "direct_tool_call"
