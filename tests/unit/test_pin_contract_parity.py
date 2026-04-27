"""Phase 2.5 parity gate — empirical proof that the new resolver chain
produces output equivalent to legacy ``build_pin_contract_metadata``.

This is the readiness gate Phase 3 needs before flipping ``list_pins`` to
snapshot-only. Each parametrized shape constructs a realistically-shaped
``WidgetDashboardPin`` and asserts the two paths agree on
``widget_origin``, ``provenance_confidence``, and the three view fields.

Drift here = Phase 3 blocker. If any test fails, the resolver chain must
be fixed to match legacy before ``list_pins`` is allowed to serve from
the new path.

Shapes that need integration-managed registry entries (preset with
``tool_family``, direct_tool with template) are exercised as
"missing → both paths fall through to fallback" rather than requiring
fixture setup. End-to-end coverage of the populated cases will land via
the production ``--verify`` run pre-Phase-3.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.db.models import WidgetDashboardPin


def _load_backfill_module():
    spec = importlib.util.spec_from_file_location(
        "backfill_pin_source_stamps_mod_parity",
        Path(__file__).resolve().parent.parent.parent
        / "scripts" / "backfill_pin_source_stamps.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backfill_mod = _load_backfill_module()


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


# ── Parametrized parity ─────────────────────────────────────────────


# Each fixture is (id, pin_kwargs). The pin is constructed inside the
# test so each parameter case starts fresh.
PARITY_SHAPES = [
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
        id="native_authoritative_real_widget",
    ),
    pytest.param(
        {
            "tool_name": "native",
            "envelope": {
                "content_type": "application/vnd.spindrel.native-app+json",
                "body": {"widget_ref": "core/notes_native"},
            },
            # No caller_origin — exercises the inferred branch
        },
        id="native_inferred_real_widget",
    ),
    pytest.param(
        {
            "tool_name": "native",
            "envelope": {
                "content_type": "application/vnd.spindrel.native-app+json",
                "body": {"widget_ref": "core/never_existed"},
            },
        },
        id="native_unknown_widget_fallback",
    ),
    pytest.param(
        {
            "tool_name": "html_widget",
            "envelope": {
                "content_type": "application/vnd.spindrel.html+interactive",
                "body": "<html></html>",
            },
        },
        id="html_runtime_emit_catchall",
    ),
    pytest.param(
        {
            "tool_name": "html_widget",
            "envelope": {
                "source_library_ref": "bot/never-existed-library-ref",
                "source_bot_id": "fake-bot",
            },
            "source_bot_id": "fake-bot",
        },
        id="html_library_missing_bundle",
    ),
    pytest.param(
        {
            "tool_name": "html_widget",
            "envelope": {
                "source_path": "never-existed/index.html",
                "source_kind": "channel",
            },
        },
        id="html_library_missing_source_path",
    ),
    pytest.param(
        {
            "tool_name": "never_registered_tool_xyz",
            "envelope": {"x": 1},
        },
        id="direct_tool_missing_template",
    ),
    pytest.param(
        {
            "tool_name": "html_widget",
            "envelope": {
                "source_preset_id": "never.existed.preset",
            },
        },
        id="preset_missing",
    ),
    pytest.param(
        {
            "tool_name": "html_widget",
            "envelope": {},  # truly degenerate
        },
        id="degenerate_empty_envelope",
    ),
]


@pytest.mark.parametrize("pin_kwargs", PARITY_SHAPES)
def test_new_path_matches_legacy(pin_kwargs):
    """Both paths must agree on all 5 view fields for every shape we ship."""
    pin = _bare_pin(**pin_kwargs)
    drift = backfill_mod._diff_views(pin)
    assert drift == [], (
        f"Phase 3 blocker: new resolver chain disagrees with legacy "
        f"build_pin_contract_metadata on fields={drift} for pin shape "
        f"id={pin.id}, tool={pin.tool_name}, envelope_keys="
        f"{list(pin.envelope.keys())}"
    )


# ── Render-vs-legacy view-shape contract ───────────────────────────


def test_render_pin_metadata_matches_legacy_when_snapshots_current():
    """Phase 3 will replace legacy ``build_pin_contract_metadata`` calls in
    ``serialize_pin`` with ``render_pin_metadata``. The flip is only safe
    when snapshots are *current* — i.e. they already contain what legacy
    would compute live. This test pins that contract: given a pin whose
    snapshots match the live native spec, the two paths produce identical
    user-visible fields.

    For un-current snapshots, the read path falls back to
    ``reconcile_pin_metadata`` (Phase 3 design); ``render_pin_metadata`` is
    not safe to invoke.
    """
    from app.services.pin_contract import render_pin_metadata
    from app.services.widget_contracts import build_pin_contract_metadata

    # Use the legacy path itself to populate "current" snapshots — this
    # mimics what the Phase 2 backfill produces for healthy pins.
    legacy_seeded = build_pin_contract_metadata(
        tool_name="native",
        envelope={
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "core/notes_native"},
        },
        source_bot_id=None,
        widget_origin={
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "core/notes_native",
        },
        provenance_confidence="authoritative",
    )
    pin = _bare_pin(
        tool_name="native",
        envelope={
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "core/notes_native"},
        },
        widget_origin=legacy_seeded["widget_origin"],
        provenance_confidence=legacy_seeded["provenance_confidence"],
        widget_contract_snapshot=legacy_seeded["widget_contract_snapshot"],
        config_schema_snapshot=legacy_seeded["config_schema_snapshot"],
        widget_presentation_snapshot=legacy_seeded["widget_presentation_snapshot"],
    )
    new_view = render_pin_metadata(pin)
    # Re-run legacy to get the same view a Phase 2-backfilled pin would
    # serve (snapshots populated; live path returns identical result).
    legacy = build_pin_contract_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        widget_origin=pin.widget_origin,
        provenance_confidence=pin.provenance_confidence,
        widget_contract_snapshot=pin.widget_contract_snapshot,
        config_schema_snapshot=pin.config_schema_snapshot,
        widget_presentation_snapshot=pin.widget_presentation_snapshot,
    )
    assert new_view.widget_origin == legacy["widget_origin"]
    assert new_view.provenance_confidence == legacy["provenance_confidence"]
    assert new_view.widget_contract == legacy["widget_contract"]
    assert new_view.widget_presentation == legacy["widget_presentation"]
    assert new_view.config_schema == legacy["config_schema"]
