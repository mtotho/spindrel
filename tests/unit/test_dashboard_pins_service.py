"""Unit tests for app/services/dashboard_pins.py."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import WidgetInstance
from app.domain.errors import DomainError, NotFoundError, ValidationError
from app.services.dashboard_pins import (
    apply_dashboard_pin_config_patch,
    apply_layout_bulk,
    create_pin,
    delete_pin,
    get_pin,
    list_pins,
    rename_pin,
    serialize_pin,
    update_pin_envelope,
)
from app.services.native_app_widgets import build_native_widget_preview_envelope
from tests.factories import build_channel


def _env(label: str = "Light 1") -> dict:
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


@pytest.mark.asyncio
async def test_create_assigns_sequential_positions(db_session):
    a = await create_pin(db_session, source_kind="adhoc", tool_name="a", envelope=_env("a"))
    b = await create_pin(db_session, source_kind="adhoc", tool_name="b", envelope=_env("b"))
    assert a.position == 0
    assert b.position == 1


@pytest.mark.asyncio
async def test_create_pin_accepts_non_grid_zone(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="t",
        envelope=_env("dock"),
        zone="dock",
    )
    assert pin.zone == "dock"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 1, "h": 10}


@pytest.mark.asyncio
async def test_create_pin_defaults_header_zone_to_top_rail_card(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="t",
        envelope=_env("header"),
        zone="header",
    )
    assert pin.zone == "header"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 2}


@pytest.mark.asyncio
async def test_create_pin_seeds_zone_and_size_from_native_layout_hints(db_session):
    channel = build_channel()
    db_session.add(channel)
    await db_session.commit()
    pin = await create_pin(
        db_session,
        dashboard_key=f"channel:{channel.id}",
        source_kind="channel",
        source_channel_id=channel.id,
        tool_name="core/context_tracker_native",
        envelope=build_native_widget_preview_envelope("core/context_tracker"),
    )
    assert pin.zone == "header"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 2}


@pytest.mark.asyncio
async def test_create_pin_seeds_chip_preset_into_header_chip_layout(db_session, monkeypatch):
    fake_preset = {
        "id": "homeassistant-entity-toggle-chip",
        "integration_id": "homeassistant",
        "name": "Entity Toggle Chip",
        "tool_name": "GetLiveContext",
        "layout_hints": {"preferred_zone": "chip", "max_cells": {"w": 4, "h": 1}},
        "binding_schema": {"type": "object", "properties": {}},
    }
    monkeypatch.setattr(
        "app.services.widget_presets.get_widget_preset",
        lambda pid: fake_preset,
    )
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="GetLiveContext",
        envelope=_env("Office Light"),
        widget_origin={
            "definition_kind": "tool_widget",
            "instantiation_kind": "preset",
            "tool_name": "GetLiveContext",
            "preset_id": "homeassistant-entity-toggle-chip",
        },
    )
    assert pin.zone == "header"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 4, "h": 1}


@pytest.mark.asyncio
async def test_create_pin_clamps_default_size_from_layout_hints(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/todo_native",
        envelope=build_native_widget_preview_envelope("core/todo_native"),
    )
    assert pin.zone == "grid"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 8}


@pytest.mark.asyncio
async def test_create_pin_explicit_zone_beats_layout_hint_zone(db_session):
    channel = build_channel()
    db_session.add(channel)
    await db_session.commit()
    pin = await create_pin(
        db_session,
        dashboard_key=f"channel:{channel.id}",
        source_kind="channel",
        source_channel_id=channel.id,
        tool_name="core/context_tracker_native",
        envelope=build_native_widget_preview_envelope("core/context_tracker"),
        zone="grid",
    )
    assert pin.zone == "grid"
    assert pin.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 2}


@pytest.mark.asyncio
async def test_create_pin_explicit_layout_beats_layout_hint_size(db_session):
    channel = build_channel()
    db_session.add(channel)
    await db_session.commit()
    pin = await create_pin(
        db_session,
        dashboard_key=f"channel:{channel.id}",
        source_kind="channel",
        source_channel_id=channel.id,
        tool_name="core/context_tracker_native",
        envelope=build_native_widget_preview_envelope("core/context_tracker"),
        grid_layout={"x": 2, "y": 0, "w": 9, "h": 1},
    )
    assert pin.zone == "header"
    assert pin.grid_layout == {"x": 2, "y": 0, "w": 9, "h": 1}


@pytest.mark.asyncio
async def test_list_pins_orders_by_position(db_session):
    await create_pin(db_session, source_kind="adhoc", tool_name="a", envelope=_env())
    await create_pin(db_session, source_kind="adhoc", tool_name="b", envelope=_env())
    rows = await list_pins(db_session)
    assert [p.tool_name for p in rows] == ["a", "b"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_source_kind(db_session):
    with pytest.raises(ValidationError):
        await create_pin(db_session, source_kind="garbage", tool_name="x", envelope=_env())


@pytest.mark.asyncio
async def test_create_rejects_missing_tool_name(db_session):
    with pytest.raises(ValidationError):
        await create_pin(db_session, source_kind="adhoc", tool_name="", envelope=_env())


@pytest.mark.asyncio
async def test_create_rejects_empty_envelope(db_session):
    with pytest.raises(ValidationError):
        await create_pin(db_session, source_kind="adhoc", tool_name="x", envelope={})


@pytest.mark.asyncio
async def test_create_pin_seeds_ha_entity_id_widget_config(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="ha_get_state",
        envelope=_env("light.office_desk_led_strip"),
    )
    assert pin.widget_config == {"entity_id": "light.office_desk_led_strip"}


@pytest.mark.asyncio
async def test_delete_then_get_raises_404(db_session):
    pin = await create_pin(db_session, source_kind="adhoc", tool_name="t", envelope=_env())
    await delete_pin(db_session, pin.id)
    with pytest.raises(NotFoundError):
        await get_pin(db_session, pin.id)


@pytest.mark.asyncio
async def test_delete_missing_raises_404(db_session):
    with pytest.raises(NotFoundError):
        await delete_pin(db_session, uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_pinned_files_pin_clears_widget_state(db_session):
    channel = build_channel()
    db_session.add(channel)
    await db_session.commit()
    channel_id = channel.id
    pin = await create_pin(
        db_session,
        dashboard_key=f"channel:{channel_id}",
        source_kind="channel",
        source_channel_id=channel_id,
        tool_name="core/pinned_files_native",
        envelope=build_native_widget_preview_envelope("core/pinned_files_native"),
        zone="dock",
    )
    instance = await db_session.get(WidgetInstance, pin.widget_instance_id)
    assert instance is not None
    instance.state = {
        "pinned_files": [
            {"path": "notes.md", "pinned_at": "2026-04-23T10:00:00+00:00", "pinned_by": "user"},
        ],
        "active_path": "notes.md",
        "created_at": "2026-04-23T10:00:00+00:00",
        "updated_at": "2026-04-23T10:00:00+00:00",
    }

    await delete_pin(db_session, pin.id)
    await db_session.refresh(instance)
    assert instance.state["pinned_files"] == []
    assert instance.state["active_path"] is None


@pytest.mark.asyncio
async def test_config_patch_merges(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t",
        envelope=_env(), widget_config={"a": 1, "b": 2},
    )
    result = await apply_dashboard_pin_config_patch(
        db_session, pin.id, {"b": 99, "c": 3}, merge=True,
    )
    assert result["widget_config"] == {"a": 1, "b": 99, "c": 3}


@pytest.mark.asyncio
async def test_config_patch_replaces_when_merge_false(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t",
        envelope=_env(), widget_config={"a": 1, "b": 2},
    )
    result = await apply_dashboard_pin_config_patch(
        db_session, pin.id, {"c": 3}, merge=False,
    )
    assert result["widget_config"] == {"c": 3}


@pytest.mark.asyncio
async def test_update_envelope_refreshes_display_label(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t",
        envelope=_env("Old Label"),
    )
    refreshed = await update_pin_envelope(
        db_session, pin.id, _env("New Label"),
    )
    assert refreshed.display_label == "New Label"


@pytest.mark.asyncio
async def test_serialize_pin_shape(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t",
        envelope=_env("L"), widget_config={"x": 1},
        tool_args={"id": "abc"},
    )
    data = serialize_pin(pin)
    assert set(data.keys()) >= {
        "id", "dashboard_key", "position", "source_kind", "source_channel_id",
        "source_bot_id", "tool_name", "tool_args", "widget_config", "envelope",
        "display_label", "grid_layout", "pinned_at", "updated_at",
    }
    assert data["tool_args"] == {"id": "abc"}
    assert data["widget_config"] == {"x": 1}
    assert data["widget_origin"] is not None
    assert data["provenance_confidence"] == "inferred"
    assert data["display_label"] == "L"
    assert data["grid_layout"] == {"x": 0, "y": 0, "w": 6, "h": 10}


@pytest.mark.asyncio
async def test_serialize_pin_with_explicit_origin_is_authoritative(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="html_widget",
        envelope={
            **_env("Panel"),
            "content_type": "application/vnd.spindrel.html+interactive",
            "source_library_ref": "core/generate_image",
        },
        widget_origin={
            "definition_kind": "html_widget",
            "instantiation_kind": "library_pin",
            "source_library_ref": "core/generate_image",
        },
    )
    data = serialize_pin(pin)
    assert data["widget_origin"] == {
        "definition_kind": "html_widget",
        "instantiation_kind": "library_pin",
        "source_library_ref": "core/generate_image",
    }
    assert data["provenance_confidence"] == "authoritative"
    assert data["widget_presentation"] == {
        "presentation_family": "card",
        "layout_hints": None,
    }


@pytest.mark.asyncio
async def test_serialize_pin_backfills_missing_provenance(db_session):
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="t",
        envelope=_env("L"),
    )
    pin.widget_origin = None
    pin.provenance_confidence = "inferred"
    pin.widget_contract_snapshot = None
    pin.config_schema_snapshot = None
    await db_session.commit()
    await db_session.refresh(pin)

    fetched = await get_pin(db_session, pin.id)
    assert fetched.widget_origin == {
        "definition_kind": "html_widget",
        "instantiation_kind": "direct_tool_call",
    }


@pytest.mark.asyncio
async def test_rename_pin_updates_label(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env("Before"),
    )
    out = await rename_pin(db_session, pin.id, "After")
    assert out["display_label"] == "After"


@pytest.mark.asyncio
async def test_rename_pin_trims_and_clears(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env("Before"),
    )
    out = await rename_pin(db_session, pin.id, "   ")
    assert out["display_label"] is None


@pytest.mark.asyncio
async def test_apply_layout_bulk_atomic(db_session):
    pins = [
        await create_pin(
            db_session, source_kind="adhoc", tool_name=f"t{i}", envelope=_env(f"p{i}"),
        )
        for i in range(2)
    ]
    items = [
        {"id": str(pins[0].id), "x": 0, "y": 0, "w": 4, "h": 3},
        {"id": str(uuid.uuid4()), "x": 4, "y": 0, "w": 4, "h": 3},  # unknown
    ]
    with pytest.raises(DomainError):
        await apply_layout_bulk(db_session, items)
    # The valid id's layout must not have been committed.
    rows = await list_pins(db_session)
    for row in rows:
        if row.id == pins[0].id:
            assert row.grid_layout != {"x": 0, "y": 0, "w": 4, "h": 3}


@pytest.mark.asyncio
async def test_apply_layout_bulk_persists(db_session):
    pins = [
        await create_pin(
            db_session, source_kind="adhoc", tool_name=f"t{i}", envelope=_env(f"p{i}"),
        )
        for i in range(2)
    ]
    items = [
        {"id": str(pins[0].id), "x": 0, "y": 0, "w": 4, "h": 3},
        {"id": str(pins[1].id), "x": 4, "y": 0, "w": 4, "h": 3},
    ]
    result = await apply_layout_bulk(db_session, items)
    assert result == {"ok": True, "updated": 2}
    rows = {r.id: r for r in await list_pins(db_session)}
    assert rows[pins[0].id].grid_layout == {"x": 0, "y": 0, "w": 4, "h": 3}
    assert rows[pins[1].id].grid_layout == {"x": 4, "y": 0, "w": 4, "h": 3}


@pytest.mark.asyncio
async def test_apply_layout_normalizes_header_zone(db_session):
    """Writing zone=header clamps into the 2-row top rail instead of a singleton slot."""
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
    )
    items = [{
        "id": str(pin.id), "x": 2, "y": 2, "w": 24, "h": 2, "zone": "header",
    }]
    await apply_layout_bulk(db_session, items)
    rows = {r.id: r for r in await list_pins(db_session)}
    row = rows[pin.id]
    assert row.zone == "header"
    assert row.grid_layout == {"x": 0, "y": 1, "w": 12, "h": 2}


@pytest.mark.asyncio
async def test_apply_layout_normalizes_header_x_to_fit_preset_width(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
    )
    items = [{
        "id": str(pin.id), "x": 11, "y": 0, "w": 4, "h": 1, "zone": "header",
    }]
    await apply_layout_bulk(db_session, items)
    rows = {r.id: r for r in await list_pins(db_session)}
    row = rows[pin.id]
    assert row.zone == "header"
    assert row.grid_layout == {"x": 8, "y": 0, "w": 4, "h": 1}


@pytest.mark.asyncio
async def test_apply_layout_normalizes_rail_and_dock(db_session):
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
    )
    for zone in ("rail", "dock"):
        await apply_layout_bulk(db_session, [{
            "id": str(pin.id), "x": 5, "y": 3, "w": 8, "h": 4, "zone": zone,
        }])
        rows = {r.id: r for r in await list_pins(db_session)}
        assert rows[pin.id].zone == zone
        assert rows[pin.id].grid_layout == {"x": 0, "y": 3, "w": 1, "h": 4}


@pytest.mark.asyncio
async def test_list_pins_heals_stale_header_coords(db_session):
    """`list_pins` rewrites grid_layout in place when a pin's persisted
    coords violate its zone's invariants — one-shot correction when the
    dashboard is next read, no user interaction required."""
    from sqlalchemy.orm.attributes import flag_modified

    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
    )
    pin.zone = "header"
    pin.grid_layout = {"x": 2, "y": 2, "w": 24, "h": 2}
    flag_modified(pin, "grid_layout")
    await db_session.commit()

    rows = await list_pins(db_session)
    row = next(r for r in rows if r.id == pin.id)
    assert row.grid_layout == {"x": 0, "y": 1, "w": 12, "h": 2}


@pytest.mark.asyncio
async def test_list_pins_upgrades_legacy_header_singleton_to_chip_size(db_session):
    from sqlalchemy.orm.attributes import flag_modified

    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
    )
    pin.zone = "header"
    pin.grid_layout = {"x": 0, "y": 0, "w": 1, "h": 1}
    flag_modified(pin, "grid_layout")
    await db_session.commit()

    rows = await list_pins(db_session)
    row = next(r for r in rows if r.id == pin.id)
    assert row.grid_layout == {"x": 0, "y": 0, "w": 4, "h": 1}
