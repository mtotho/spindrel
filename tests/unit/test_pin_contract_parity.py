"""Final pin-contract shape tests.

Phase 4 deleted the legacy widget_contracts parity oracle. These tests pin the
public fields produced directly by ``app.services.pin_contract`` for the
representative origin shapes that previously depended on oracle comparison.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db.models import WidgetDashboardPin
from app.services.pin_contract import (
    ContractSnapshot,
    compute_pin_metadata,
    render_pin_metadata,
)


def _bare_pin(**overrides: Any) -> WidgetDashboardPin:
    base = {
        "id": uuid.uuid4(),
        "dashboard_key": "default",
        "position": 0,
        "source_kind": "channel",
        "source_channel_id": None,
        "source_bot_id": None,
        "tool_name": "html_widget",
        "tool_args": {},
        "widget_config": {},
        "envelope": {},
        "grid_layout": {},
        "widget_origin": None,
        "provenance_confidence": "inferred",
        "widget_contract_snapshot": None,
        "config_schema_snapshot": None,
        "widget_presentation_snapshot": None,
        "source_stamp": None,
    }
    base.update(overrides)
    return WidgetDashboardPin(**base)


def _compute_for_pin(pin: WidgetDashboardPin):
    return compute_pin_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        caller_origin=pin.widget_origin if pin.widget_origin else None,
        snapshot=ContractSnapshot(
            widget_contract=pin.widget_contract_snapshot,
            config_schema=pin.config_schema_snapshot,
            widget_presentation=pin.widget_presentation_snapshot,
        ),
    )


@pytest.mark.parametrize(
    ("pin_kwargs", "expected_origin", "expected_confidence", "expected_contract_kind"),
    [
        pytest.param(
            {
                "tool_name": "native",
                "envelope": {
                    "content_type": "application/vnd.spindrel.native-app+json",
                    "body": {"widget_ref": "core/notes_native"},
                },
            },
            {
                "definition_kind": "native_widget",
                "instantiation_kind": "native_catalog",
                "widget_ref": "core/notes_native",
            },
            "inferred",
            "native_widget",
            id="native_inferred_real_widget",
        ),
        pytest.param(
            {
                "tool_name": "native",
                "envelope": {
                    "content_type": "application/vnd.spindrel.native-app+json",
                    "body": {"widget_ref": "core/notes_native"},
                },
                "widget_origin": {
                    "definition_kind": "native_widget",
                    "instantiation_kind": "native_catalog",
                    "widget_ref": "core/notes_native",
                },
                "provenance_confidence": "authoritative",
            },
            {
                "definition_kind": "native_widget",
                "instantiation_kind": "native_catalog",
                "widget_ref": "core/notes_native",
            },
            "authoritative",
            "native_widget",
            id="native_authoritative_real_widget",
        ),
        pytest.param(
            {
                "tool_name": "html_widget",
                "envelope": {
                    "content_type": "application/vnd.spindrel.html+interactive",
                    "body": "<html></html>",
                },
            },
            {
                "definition_kind": "html_widget",
                "instantiation_kind": "runtime_emit",
            },
            "inferred",
            "html_widget",
            id="html_runtime_emit",
        ),
        pytest.param(
            {
                "tool_name": "never_registered_tool_xyz",
                "envelope": {"x": 1},
            },
            {
                "definition_kind": "html_widget",
                "instantiation_kind": "direct_tool_call",
            },
            "inferred",
            "html_widget",
            id="unknown_tool_html_fallback",
        ),
        pytest.param(
            {
                "tool_name": "html_widget",
                "envelope": {"source_preset_id": "never.existed.preset"},
            },
            {
                "definition_kind": "tool_widget",
                "instantiation_kind": "preset",
                "tool_name": "html_widget",
                "preset_id": "never.existed.preset",
            },
            "inferred",
            None,
            id="preset_missing_downgrades_to_snapshot_fallback",
        ),
    ],
)
def test_compute_pin_metadata_final_contract_shapes(
    pin_kwargs,
    expected_origin,
    expected_confidence,
    expected_contract_kind,
):
    pin = _bare_pin(**pin_kwargs)

    view, _stamp = _compute_for_pin(pin)

    assert view.widget_origin == expected_origin
    assert view.provenance_confidence == expected_confidence
    if expected_contract_kind is None:
        assert view.widget_contract is None
    else:
        assert view.widget_contract["definition_kind"] == expected_contract_kind
    assert view.widget_presentation["presentation_family"] == "card"


def test_render_pin_metadata_serves_current_snapshots_without_live_compute():
    seeded, stamp = compute_pin_metadata(
        tool_name="native",
        envelope={
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "core/notes_native"},
        },
        source_bot_id=None,
        caller_origin={
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "core/notes_native",
        },
    )
    pin = _bare_pin(
        tool_name="native",
        envelope={
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "core/notes_native"},
        },
        widget_origin=seeded.widget_origin,
        provenance_confidence=seeded.provenance_confidence,
        widget_contract_snapshot=seeded.widget_contract,
        config_schema_snapshot=seeded.config_schema,
        widget_presentation_snapshot=seeded.widget_presentation,
        source_stamp=stamp,
    )

    rendered = render_pin_metadata(pin)

    assert rendered == seeded


def test_widget_contracts_no_longer_exposes_pin_oracle():
    from app.services import widget_contracts

    assert not hasattr(widget_contracts, "build_pin_contract_metadata")
    assert not hasattr(widget_contracts, "build_public_fields_for_pin")
    assert not hasattr(widget_contracts, "build_public_fields_from_origin")
