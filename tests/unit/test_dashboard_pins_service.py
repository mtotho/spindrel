"""Unit tests for app/services/dashboard_pins.py."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

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
async def test_list_pins_orders_by_position(db_session):
    await create_pin(db_session, source_kind="adhoc", tool_name="a", envelope=_env())
    await create_pin(db_session, source_kind="adhoc", tool_name="b", envelope=_env())
    rows = await list_pins(db_session)
    assert [p.tool_name for p in rows] == ["a", "b"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_source_kind(db_session):
    with pytest.raises(HTTPException) as exc:
        await create_pin(db_session, source_kind="garbage", tool_name="x", envelope=_env())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_missing_tool_name(db_session):
    with pytest.raises(HTTPException):
        await create_pin(db_session, source_kind="adhoc", tool_name="", envelope=_env())


@pytest.mark.asyncio
async def test_create_rejects_empty_envelope(db_session):
    with pytest.raises(HTTPException):
        await create_pin(db_session, source_kind="adhoc", tool_name="x", envelope={})


@pytest.mark.asyncio
async def test_delete_then_get_raises_404(db_session):
    pin = await create_pin(db_session, source_kind="adhoc", tool_name="t", envelope=_env())
    await delete_pin(db_session, pin.id)
    with pytest.raises(HTTPException) as exc:
        await get_pin(db_session, pin.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_raises_404(db_session):
    with pytest.raises(HTTPException) as exc:
        await delete_pin(db_session, uuid.uuid4())
    assert exc.value.status_code == 404


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
    assert data["display_label"] == "L"
    assert data["grid_layout"] == {"x": 0, "y": 0, "w": 6, "h": 6}


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
    with pytest.raises(HTTPException):
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
