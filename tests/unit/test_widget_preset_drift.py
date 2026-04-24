"""Phase N.1 drift-seam sweep: widget preset binding + pin persistence.

The happy-path + validation coverage lives in ``test_widget_presets.py``. This
file pins the drift seams that a manifest reload, a partial binding failure,
or a channel deletion could silently shift:

- per-source error isolation in ``resolve_preset_binding_options``
- binding_sources contribute to the tool_family contract (distinct lane from
  ``tool_dependencies``)
- ``resolve_preset_config`` is a shallow spread — nested dicts REPLACE (not
  deep-merge), and callers must not rely on deep-merge semantics
- ``list_widget_presets`` fails loud on any invalid preset rather than
  silently skipping, so one corrupt manifest can't poison the live set
- widget_origin JSONB snapshot persists across preset removal from the
  manifest (pin survives manifest reload)
- per-pin config isolation across dashboards (patching one does not mutate
  the widget_origin or widget_config of a sibling pin)
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import WidgetDashboard, WidgetDashboardPin
from app.services.dashboard_pins import (
    apply_dashboard_pin_config_patch,
    create_pin,
    get_pin,
    serialize_pin,
)
from app.services.widget_presets import (
    WidgetPresetValidationError,
    get_widget_preset,
    list_widget_presets,
    resolve_preset_binding_options,
    resolve_preset_config,
)


# ---------------------------------------------------------------------------
# Manifest builders + transforms
# ---------------------------------------------------------------------------

def _identity_options(_raw: str, _ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Binding-source transform used by two-source test manifests."""
    return [{"value": "ok", "label": "ok"}]


def _two_source_manifest() -> dict[str, Any]:
    return {
        "demo": {
            "tool_families": {
                "primary": {
                    "label": "Primary",
                    "tools": ["tool_a", "tool_b"],
                },
            },
            "widget_presets": {
                "demo-two-source": {
                    "name": "Two-Source Preset",
                    "tool_name": "tool_a",
                    "tool_family": "primary",
                    "tool_dependencies": ["tool_a", "tool_b"],
                    "binding_schema": {
                        "type": "object",
                        "properties": {"ref": {"type": "string"}},
                    },
                    "binding_sources": {
                        "source_a": {
                            "tool": "tool_a",
                            "args": {},
                            "transform": (
                                "tests.unit.test_widget_preset_drift"
                                ":_identity_options"
                            ),
                        },
                        "source_b": {
                            "tool": "tool_b",
                            "args": {},
                            "transform": (
                                "tests.unit.test_widget_preset_drift"
                                ":_identity_options"
                            ),
                        },
                    },
                    "default_config": {
                        "nested": {"k1": "default", "k2": "default"},
                        "top": "default",
                    },
                    "runtime": {"tool_args": {}},
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Per-source error isolation in resolve_preset_binding_options
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_binding_options_isolates_per_source_http_failure(
    monkeypatch,
):
    """One source's HTTPException must not corrupt the other's options.

    Drift pin: a future refactor that short-circuits on first failure would
    hide half the bindings behind the wrong source id.
    """
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests",
        lambda: _two_source_manifest(),
    )

    async def _exec(tool_name, _args, bot_id=None, channel_id=None):
        if tool_name == "tool_a":
            raise HTTPException(503, f"{tool_name} upstream unavailable")
        return ({"result": "raw_b"}, None)

    monkeypatch.setattr(
        "app.services.tool_execution.execute_tool_with_context", _exec,
    )

    preset = next(p for p in list_widget_presets() if p["id"] == "demo-two-source")
    options_by_source, errors_by_source = await resolve_preset_binding_options(
        preset, source_bot_id="bot-1", source_channel_id=None,
    )

    assert options_by_source["source_a"] == []
    assert options_by_source["source_b"] == [{"value": "ok", "label": "ok"}]
    assert "source_a" in errors_by_source
    assert "source_b" not in errors_by_source
    assert "upstream unavailable" in errors_by_source["source_a"]


@pytest.mark.asyncio
async def test_resolve_binding_options_isolates_per_source_generic_exception(
    monkeypatch,
):
    """Non-HTTPException (RuntimeError, ValueError, etc.) must also isolate."""
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests",
        lambda: _two_source_manifest(),
    )

    async def _exec(tool_name, _args, bot_id=None, channel_id=None):
        if tool_name == "tool_a":
            raise RuntimeError("transform blew up")
        return ({"result": "raw_b"}, None)

    monkeypatch.setattr(
        "app.services.tool_execution.execute_tool_with_context", _exec,
    )

    preset = next(p for p in list_widget_presets() if p["id"] == "demo-two-source")
    options_by_source, errors_by_source = await resolve_preset_binding_options(
        preset, source_bot_id=None, source_channel_id=None,
    )

    assert options_by_source["source_a"] == []
    assert options_by_source["source_b"] == [{"value": "ok", "label": "ok"}]
    assert errors_by_source["source_a"] == "transform blew up"


# ---------------------------------------------------------------------------
# tool_family contract — binding_sources lane
# ---------------------------------------------------------------------------

def test_validate_dep_contract_rejects_binding_source_tool_outside_family(
    monkeypatch,
):
    """``binding_sources.<id>.tool`` contributes to the family check.

    The existing coverage only exercises ``tool_dependencies`` + ``tool_name``.
    This pins the parallel lane — a binding source declaring a foreign tool
    must fail validation at list time.
    """
    manifest = _two_source_manifest()
    manifest["demo"]["widget_presets"]["demo-two-source"]["binding_sources"][
        "source_b"
    ]["tool"] = "tool_outsider"
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests", lambda: manifest,
    )

    with pytest.raises(
        WidgetPresetValidationError, match="outside tool_family 'primary'",
    ):
        list_widget_presets()


# ---------------------------------------------------------------------------
# resolve_preset_config shallow-merge contract
# ---------------------------------------------------------------------------

def test_resolve_preset_config_shallow_merges_user_over_default():
    """User config spreads over defaults — nested dicts are REPLACED, not merged.

    Drift pin: anyone tempted to switch to a recursive/deep merge must update
    this test, because the current behavior is documented and the call sites
    (preview + pin) depend on knowing ``preset.default_config`` is authoritative
    only for keys the user omitted entirely.
    """
    preset = {
        "default_config": {
            "nested": {"k1": "default", "k2": "default"},
            "top": "default",
            "untouched": "default_only",
        },
    }
    resolved = resolve_preset_config(
        preset, {"nested": {"k1": "user"}, "top": "user"},
    )

    assert resolved["top"] == "user"
    assert resolved["untouched"] == "default_only"
    # Nested dict is replaced wholesale; k2 does NOT inherit from default.
    assert resolved["nested"] == {"k1": "user"}
    assert "k2" not in resolved["nested"]


# ---------------------------------------------------------------------------
# Fail-loud listing invariant
# ---------------------------------------------------------------------------

def test_list_widget_presets_fails_loud_when_any_preset_invalid(monkeypatch):
    """One invalid preset aborts the whole listing; never silently skipped.

    Drift pin: if a future refactor wraps per-preset validation in a try/except
    so ``/presets`` "still works" with bad data, misconfiguration becomes
    invisible in the admin UI. Fail loud so operators notice immediately.
    """
    manifest = _two_source_manifest()
    demo = manifest["demo"]
    demo["widget_presets"]["demo-valid-sibling"] = copy.deepcopy(
        demo["widget_presets"]["demo-two-source"],
    )
    demo["widget_presets"]["demo-valid-sibling"]["id"] = "demo-valid-sibling"
    # Poison the other preset.
    demo["widget_presets"]["demo-two-source"]["binding_schema"] = {"type": "array"}
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests", lambda: manifest,
    )

    with pytest.raises(WidgetPresetValidationError, match="binding_schema"):
        list_widget_presets()


# ---------------------------------------------------------------------------
# Orphan-pointer: widget_origin JSONB snapshot survives manifest removal
# ---------------------------------------------------------------------------

def _preset_envelope(label: str = "Preset Pin") -> dict[str, Any]:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 2,
        "display_label": label,
    }


def _preset_widget_origin(preset_id: str = "demo-two-source") -> dict[str, Any]:
    return {
        "definition_kind": "tool_widget",
        "instantiation_kind": "preset",
        "tool_name": "tool_a",
        "preset_id": preset_id,
        "tool_family": "primary",
    }


@pytest.mark.asyncio
async def test_pin_widget_origin_survives_preset_removal_from_manifest(
    db_session, monkeypatch,
):
    """widget_origin is a JSONB snapshot, independent of the live manifest.

    Create a pin referencing a preset, then drop the preset from the manifest
    (simulating a reload that removes or renames it). The pin must still be
    readable and its widget_origin.preset_id snapshot intact.

    Drift pin: if someone later decides to hard-validate ``widget_origin.preset_id``
    against ``get_widget_preset`` on serialize, every pre-existing pin breaks
    after any integration ships/removes a preset. The snapshot must remain the
    source of truth for already-pinned widgets.
    """
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests",
        lambda: _two_source_manifest(),
    )

    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="tool_a",
        envelope=_preset_envelope(),
        widget_config={"ref": "xyz"},
        widget_origin=_preset_widget_origin(),
    )
    pin_id = pin.id

    # Reload: preset is gone from manifest entirely.
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests", lambda: {},
    )

    # Lookup against the live manifest now 404s — the preset is truly gone.
    with pytest.raises(HTTPException) as exc:
        get_widget_preset("demo-two-source")
    assert exc.value.status_code == 404

    # But the pin's snapshot is durable.
    refetched = await get_pin(db_session, pin_id)
    assert refetched.widget_origin["preset_id"] == "demo-two-source"
    assert refetched.widget_origin["instantiation_kind"] == "preset"
    assert refetched.widget_config == {"ref": "xyz"}

    # Serialize must not raise when the upstream preset is missing.
    data = serialize_pin(refetched)
    assert data["widget_origin"]["preset_id"] == "demo-two-source"
    assert data["provenance_confidence"] == "authoritative"


# ---------------------------------------------------------------------------
# Cross-dashboard pin isolation (multi-row sync invariant)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_pins_from_same_preset_on_different_dashboards_isolated(
    db_session, monkeypatch,
):
    """Two pins sourced from the same preset, on distinct dashboards, must
    not share widget_config. Patching one is a no-op on the other.

    Drift pin: if a refactor ever normalizes preset widget_config into a
    shared ``widget_instances`` row keyed by ``widget_origin.preset_id``
    (rather than per-pin JSONB), this test catches the leak.
    """
    monkeypatch.setattr(
        "app.services.widget_presets.get_all_manifests",
        lambda: _two_source_manifest(),
    )

    # Seed a second dashboard so the two pins live on distinct surfaces.
    db_session.add(WidgetDashboard(
        slug="secondary", name="Secondary", icon="LayoutDashboard",
    ))
    await db_session.commit()

    origin = _preset_widget_origin()
    pin_a = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="tool_a",
        envelope=_preset_envelope("Pin A"),
        widget_config={"ref": "shared_default"},
        widget_origin=copy.deepcopy(origin),
        dashboard_key="default",
    )
    pin_b = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="tool_a",
        envelope=_preset_envelope("Pin B"),
        widget_config={"ref": "shared_default"},
        widget_origin=copy.deepcopy(origin),
        dashboard_key="secondary",
    )
    pin_b_id = pin_b.id

    await apply_dashboard_pin_config_patch(
        db_session, pin_a.id, {"ref": "A_override"}, merge=True,
    )

    # Force a fresh read to defeat identity-map caching.
    refreshed_b = (await db_session.execute(
        select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_b_id)
    )).scalar_one()
    await db_session.refresh(refreshed_b)

    assert refreshed_b.widget_config == {"ref": "shared_default"}
    assert refreshed_b.dashboard_key == "secondary"
    assert refreshed_b.widget_origin["preset_id"] == "demo-two-source"

    # Sanity: pin A actually moved.
    refreshed_a = await get_pin(db_session, pin_a.id)
    assert refreshed_a.widget_config == {"ref": "A_override"}
    assert refreshed_a.dashboard_key == "default"
