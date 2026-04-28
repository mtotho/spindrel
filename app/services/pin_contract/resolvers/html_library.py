"""HTML widget bundle — library_pin instantiation across all scopes."""
from __future__ import annotations

from typing import Any, ClassVar

from app.services.pin_contract.resolvers import (
    LiveFields,
    WidgetOrigin,
    register_resolver,
)
from app.services.pin_contract.stamps import stamp_for_html_bundle


@register_resolver
class HtmlLibraryResolver:
    definition_kind: ClassVar[str] = "html_widget"
    instantiation_kinds: ClassVar[frozenset[str]] = frozenset({"library_pin"})
    priority: ClassVar[int] = 40

    def claim(self, ident, deps) -> WidgetOrigin | None:
        envelope = ident.envelope
        source_library_ref = envelope.get("source_library_ref")
        source_path = envelope.get("source_path")
        if not (
            (isinstance(source_library_ref, str) and source_library_ref.strip())
            or (isinstance(source_path, str) and source_path.strip())
        ):
            return None
        instantiation_kind = (
            envelope.get("source_instantiation_kind")
            if isinstance(envelope.get("source_instantiation_kind"), str)
            and envelope.get("source_instantiation_kind").strip()
            else "library_pin"
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
        return stamp_for_html_bundle(
            _origin_envelope(ident.envelope, origin),
            source_bot_id=ident.source_bot_id,
            deps=deps,
        )


def _materialize_html(origin, ident, deps) -> LiveFields:
    from app.services.widget_contracts import (
        _merge_presentation_with_defaults,
        build_html_widget_contract,
        resolve_html_widget_manifest_for_pin,
    )

    html_source_bot_id = origin.get("source_bot_id")
    merged_source_bot_id = (
        html_source_bot_id.strip()
        if isinstance(html_source_bot_id, str) and html_source_bot_id.strip()
        else ident.source_bot_id
    )
    instantiation_kind = str(origin.get("instantiation_kind") or "library_pin")
    html_meta = (
        resolve_html_widget_manifest_for_pin(
            _origin_envelope(ident.envelope, origin),
            source_bot_id=merged_source_bot_id,
        )
        or {}
    )
    return LiveFields(
        config_schema=html_meta.get("config_schema"),
        widget_presentation=_merge_presentation_with_defaults(
            html_meta.get("widget_presentation"),
        ),
        widget_contract=build_html_widget_contract(
            auth_model="source_bot" if merged_source_bot_id else "viewer",
            actions=html_meta.get("actions"),
            supported_scopes=html_meta.get("supported_scopes"),
            theme_support=html_meta.get("theme_support") or "html",
            context_export=html_meta.get("context_export"),
            instantiation_kind=instantiation_kind,
        ),
    )


def _origin_envelope(envelope: dict[str, Any], origin: WidgetOrigin) -> dict[str, Any]:
    """Project origin scope hints back onto the envelope for manifest lookup
    so manifest resolution does not depend on caller-specific envelope shape.
    """
    import copy

    merged = copy.deepcopy(envelope)
    for key in (
        "source_library_ref",
        "source_path",
        "source_kind",
        "source_channel_id",
        "source_integration_id",
        "source_bot_id",
    ):
        value = origin.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged
