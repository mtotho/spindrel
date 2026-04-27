"""Native catalog resolver — ``native_widget`` + ``native_catalog``."""
from __future__ import annotations

from typing import Any, ClassVar

from app.services.pin_contract.exceptions import NativeSpecNotFound
from app.services.pin_contract.resolvers import (
    LiveFields,
    WidgetOrigin,
    register_resolver,
)
from app.services.pin_contract.stamps import stamp_for_native_widget_ref


NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"


@register_resolver
class NativeCatalogResolver:
    definition_kind: ClassVar[str] = "native_widget"
    instantiation_kinds: ClassVar[frozenset[str]] = frozenset({"native_catalog"})
    priority: ClassVar[int] = 10  # check first — content_type is unambiguous

    def claim(self, ident, deps) -> WidgetOrigin | None:
        envelope = ident.envelope
        if envelope.get("content_type") != NATIVE_APP_CONTENT_TYPE:
            return None
        body = envelope.get("body")
        widget_ref = None
        if isinstance(body, dict):
            raw_ref = body.get("widget_ref")
            if isinstance(raw_ref, str) and raw_ref.strip():
                widget_ref = raw_ref.strip()
        if not widget_ref:
            return None
        return {
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": widget_ref,
        }

    def materialize(self, origin, ident, deps) -> LiveFields:
        from app.services.widget_contracts import build_public_fields_for_native_widget

        widget_ref = origin.get("widget_ref")
        if not isinstance(widget_ref, str) or not widget_ref.strip():
            return LiveFields.empty()
        try:
            # build_public_fields_for_native_widget reaches into the native
            # registry directly; if the spec is missing it returns a dict
            # of Nones, which we want — snapshot fallback kicks in.
            fields = build_public_fields_for_native_widget(
                widget_ref.strip(),
                instantiation_kind=str(origin.get("instantiation_kind") or "native_catalog"),
            )
        except NativeSpecNotFound:
            return LiveFields.empty()
        return LiveFields(
            config_schema=fields.get("config_schema"),
            widget_presentation=fields.get("widget_presentation"),
            widget_contract=fields.get("widget_contract"),
        )

    def stamp(self, origin, ident, deps) -> str | None:
        widget_ref = origin.get("widget_ref")
        if not isinstance(widget_ref, str) or not widget_ref.strip():
            return None
        return stamp_for_native_widget_ref(widget_ref.strip())
