"""Phase 3 hot-path regression — ``serialize_pin`` on a fully-stamped pin
must NOT touch the preset registry, the tool-template registry, the
native catalog, or the HTML manifest filesystem. The whole point of the
deepening is that stamped + populated rows serve from columns alone.

If a future refactor reintroduces a registry call on the read path, one
of the sentinels below will raise and this test will surface it.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from app.db.models import WidgetDashboardPin
from app.services.dashboard_pins import serialize_pin
from app.services.pin_contract.deps import (
    ContractDeps,
    HtmlManifestLocator,
    NativeCatalog,
    PresetRegistry,
    ToolTemplateRegistry,
)


def _stamped_native_pin(**overrides: Any) -> WidgetDashboardPin:
    """A native pin with every snapshot column populated and a stamp set.

    Mirrors what Phase 2 backfill produces for ``native_widget`` /
    ``native_catalog`` rows: widget_origin authoritative, contract +
    presentation snapshots cached, source_stamp present.
    """
    base = {
        "id": uuid.uuid4(),
        "dashboard_key": "default",
        "position": 0,
        "source_kind": "channel",
        "source_channel_id": None,
        "widget_instance_id": None,
        "source_bot_id": None,
        "tool_name": "native_app_widget",
        "tool_args": {},
        "widget_config": {},
        "envelope": {
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "test_native"},
            "display_label": "Test Native",
        },
        "display_label": "Test Native",
        "grid_layout": {"x": 0, "y": 0, "w": 6, "h": 10},
        "is_main_panel": False,
        "zone": "grid",
        "widget_origin": {
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "test_native",
        },
        "provenance_confidence": "authoritative",
        "widget_contract_snapshot": {
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "auth_model": "viewer",
            "actions": [],
            "supported_scopes": [],
            "theme_support": "native",
            "context_export": None,
            "layout_hints": None,
        },
        "config_schema_snapshot": None,
        "widget_presentation_snapshot": {
            "presentation_family": "card",
            "panel_title": "Test Native",
            "show_panel_title": True,
            "layout_hints": None,
        },
        "source_stamp": "abc123stamp",
    }
    base.update(overrides)
    return WidgetDashboardPin(**base)


class _RaisingPresets(PresetRegistry):
    def get(self, preset_id: str) -> dict[str, Any]:  # pragma: no cover - sentinel
        raise AssertionError(
            f"Hot path invoked PresetRegistry.get({preset_id!r}); "
            "render_pin_metadata must be column-only"
        )

    def tool_compatibility(self, preset_id: str) -> str | None:  # pragma: no cover
        raise AssertionError(
            f"Hot path invoked PresetRegistry.tool_compatibility({preset_id!r})"
        )


class _RaisingTemplates(ToolTemplateRegistry):
    def get(self, tool_name: str):  # pragma: no cover
        raise AssertionError(
            f"Hot path invoked ToolTemplateRegistry.get({tool_name!r})"
        )


class _RaisingNatives(NativeCatalog):
    def get(self, widget_ref: str):  # pragma: no cover
        raise AssertionError(
            f"Hot path invoked NativeCatalog.get({widget_ref!r})"
        )


class _RaisingManifests(HtmlManifestLocator):
    def resolve_bundle_dir(self, envelope, *, source_bot_id):  # pragma: no cover
        raise AssertionError(
            "Hot path invoked HtmlManifestLocator.resolve_bundle_dir"
        )


def _raising_deps() -> ContractDeps:
    return ContractDeps(
        presets=_RaisingPresets(),
        templates=_RaisingTemplates(),
        natives=_RaisingNatives(),
        html_manifests=_RaisingManifests(),
    )


class TestSerializePinHotPath:
    def test_stamped_pin_serializes_without_registry_calls(self) -> None:
        pin = _stamped_native_pin()
        with patch(
            "app.services.pin_contract.deps.get_deps",
            return_value=_raising_deps(),
        ), patch(
            "app.services.pin_contract.service.get_deps",
            return_value=_raising_deps(),
        ):
            data = serialize_pin(pin)
        assert data["widget_origin"] == pin.widget_origin
        assert data["provenance_confidence"] == "authoritative"
        assert data["widget_contract"] == pin.widget_contract_snapshot
        assert data["widget_presentation"] == pin.widget_presentation_snapshot
        assert data["panel_title"] == "Test Native"
        assert data["show_panel_title"] is True

    def test_legacy_pin_metadata_helpers_are_removed(self) -> None:
        """Phase 4 removes the legacy parity oracle from widget_contracts."""
        from app.services import widget_contracts

        assert not hasattr(widget_contracts, "build_public_fields_for_pin")
        assert not hasattr(widget_contracts, "build_pin_contract_metadata")
        assert not hasattr(widget_contracts, "infer_pin_origin")
        assert not hasattr(widget_contracts, "build_public_fields_from_origin")

    def test_unstamped_pin_falls_back_to_compute(self) -> None:
        """Un-stamped rows (legacy / hand-edited / restored from backup)
        must still serialize correctly via the compute fallback path. The
        regression is: pin not stamped => render path crashes or returns
        empty contract.
        """
        pin = _stamped_native_pin(source_stamp=None)
        # No raising deps — compute path is allowed to invoke registries.
        data = serialize_pin(pin)
        assert data["widget_origin"] == pin.widget_origin
        # widget_contract should still be populated (from snapshot fallback
        # inside compute_pin_metadata).
        assert data["widget_contract"] is not None


@pytest.mark.parametrize(
    "missing_field",
    [
        "widget_origin",
        "provenance_confidence",
        "widget_contract_snapshot",
        "widget_presentation_snapshot",
    ],
)
def test_partial_population_falls_back_to_compute(missing_field: str) -> None:
    """Each required gate field, when None, must trip the fallback. The
    Phase 3 plan deliberately excludes ``config_schema_snapshot`` from the
    gate (legitimately NULL for many widgets), so don't add it here.
    """
    pin = _stamped_native_pin(**{missing_field: None})
    # Compute path is allowed to invoke registries; assert no crash + view
    # is still produced.
    data = serialize_pin(pin)
    assert data["id"] == str(pin.id)
