from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.services.native_app_widgets import (
    dispatch_native_widget_action,
    get_or_create_native_widget_instance,
    list_native_widget_catalog_entries,
)


@pytest.mark.asyncio
async def test_todo_native_actions_round_trip(db_session):
    instance = await get_or_create_native_widget_instance(
        db_session,
        widget_ref="core/todo_native",
        dashboard_key=f"channel:{uuid.uuid4()}",
        source_channel_id=uuid.uuid4(),
    )

    added = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="add_item",
        args={"title": "Buy milk"},
    )
    item_id = added["item"]["id"]
    assert added["item"]["title"] == "Buy milk"
    assert added["counts"] == {"total": 1, "open": 1, "completed": 0}

    renamed = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="rename_item",
        args={"id": item_id, "title": "Buy oat milk"},
    )
    assert renamed["item"]["title"] == "Buy oat milk"

    toggled_done = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="toggle_item",
        args={"id": item_id},
    )
    assert toggled_done["item"]["done"] is True
    assert toggled_done["counts"] == {"total": 1, "open": 0, "completed": 1}

    toggled_open = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="toggle_item",
        args={"id": item_id, "done": False},
    )
    assert toggled_open["item"]["done"] is False
    assert toggled_open["counts"] == {"total": 1, "open": 1, "completed": 0}

    deleted = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="delete_item",
        args={"id": item_id},
    )
    assert deleted == {
        "deleted": True,
        "id": item_id,
        "counts": {"total": 0, "open": 0, "completed": 0},
    }
    assert (instance.state or {}).get("items") == []


@pytest.mark.asyncio
async def test_todo_native_reorders_open_items_and_clears_completed(db_session):
    channel_id = uuid.uuid4()
    instance = await get_or_create_native_widget_instance(
        db_session,
        widget_ref="core/todo_native",
        dashboard_key=f"channel:{channel_id}",
        source_channel_id=channel_id,
    )

    first = await dispatch_native_widget_action(
        db_session, instance=instance, action="add_item", args={"title": "First"}
    )
    second = await dispatch_native_widget_action(
        db_session, instance=instance, action="add_item", args={"title": "Second"}
    )
    third = await dispatch_native_widget_action(
        db_session, instance=instance, action="add_item", args={"title": "Third"}
    )
    await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="toggle_item",
        args={"id": second["item"]["id"], "done": True},
    )

    reordered = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="reorder_items",
        args={"ordered_ids": [third["item"]["id"], first["item"]["id"]]},
    )
    assert [item["title"] for item in reordered["items"]] == ["Third", "First", "Second"]
    assert reordered["counts"] == {"total": 3, "open": 2, "completed": 1}

    cleared = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="clear_completed",
        args={},
    )
    assert cleared["cleared"] == 1
    assert [item["title"] for item in cleared["items"]] == ["Third", "First"]
    assert cleared["counts"] == {"total": 2, "open": 2, "completed": 0}


@pytest.mark.asyncio
async def test_todo_native_rejects_bad_payloads(db_session):
    instance = await get_or_create_native_widget_instance(
        db_session,
        widget_ref="core/todo_native",
        dashboard_key=f"channel:{uuid.uuid4()}",
        source_channel_id=uuid.uuid4(),
    )

    with pytest.raises(HTTPException, match="Missing required action arg: title"):
        await dispatch_native_widget_action(
            db_session,
            instance=instance,
            action="add_item",
            args={},
        )

    await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="add_item",
        args={"title": "Only"},
    )

    with pytest.raises(HTTPException, match="unknown todo item id"):
        await dispatch_native_widget_action(
            db_session,
            instance=instance,
            action="rename_item",
            args={"id": "missing", "title": "Nope"},
        )

    with pytest.raises(HTTPException, match="ordered_ids must list each open item exactly once"):
        await dispatch_native_widget_action(
            db_session,
            instance=instance,
            action="reorder_items",
            args={"ordered_ids": []},
        )


def test_native_catalog_entries_expose_contract():
    entries = list_native_widget_catalog_entries()
    todo = next(entry for entry in entries if entry["name"] == "todo_native")
    assert todo["widget_contract"]["definition_kind"] == "native_widget"
    assert todo["widget_contract"]["auth_model"] == "host_native"
    assert todo["config_schema"]["type"] == "object"
