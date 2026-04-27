"""HTML widget runtime emit — the catch-all for ``emit_html_widget`` outputs.

Lowest priority (last claim). Fires when no other resolver claimed the pin
and the tool name doesn't resolve to a tool template. The body is whatever
the bot emitted; there's no live source to invalidate against, so the
stamp is permanently ``None`` — the snapshot is the canonical view.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.services.pin_contract.resolvers import (
    LiveFields,
    WidgetOrigin,
    register_resolver,
)
from app.services.pin_contract.resolvers.html_library import _materialize_html


@register_resolver
class HtmlRuntimeEmitResolver:
    definition_kind: ClassVar[str] = "html_widget"
    instantiation_kinds: ClassVar[frozenset[str]] = frozenset({"runtime_emit"})
    priority: ClassVar[int] = 100  # last-resort fallback

    def claim(self, ident, deps) -> WidgetOrigin | None:
        envelope = ident.envelope
        instantiation_kind = (
            envelope.get("source_instantiation_kind")
            if isinstance(envelope.get("source_instantiation_kind"), str)
            and envelope.get("source_instantiation_kind").strip()
            else None
        )
        if instantiation_kind is None:
            instantiation_kind = (
                "runtime_emit" if ident.tool_name == "html_widget" else "runtime_emit"
            )
        origin: WidgetOrigin = {
            "definition_kind": "html_widget",
            "instantiation_kind": instantiation_kind,
        }
        for key in (
            "source_library_ref",
            "source_path",
            "source_kind",
            "source_channel_id",
            "source_integration_id",
        ):
            value = envelope.get(key)
            if isinstance(value, str) and value.strip():
                origin[key] = value.strip()
        bot_id = ident.source_bot_id
        if isinstance(bot_id, str) and bot_id.strip():
            origin["source_bot_id"] = bot_id.strip()
        return origin

    def materialize(self, origin, ident, deps) -> LiveFields:
        return _materialize_html(origin, ident, deps)

    def stamp(self, origin, ident, deps) -> str | None:
        # Runtime emits live entirely on the pin row — the snapshot IS the
        # canonical state. Returning None signals "no live source" and the
        # background reconciler skips this pin.
        return None
