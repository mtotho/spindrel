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
    assert todo["widget_presentation"] == {
        "presentation_family": "card",
        "layout_hints": {
            "preferred_zone": "grid",
            "min_cells": {"w": 4, "h": 3},
            "max_cells": {"w": 12, "h": 8},
        },
    }
    assert todo["config_schema"]["type"] == "object"
    assert todo["layout_hints"] == {
        "preferred_zone": "grid",
        "min_cells": {"w": 4, "h": 3},
        "max_cells": {"w": 12, "h": 8},
    }
    assert todo["widget_contract"]["layout_hints"] == todo["layout_hints"]
    context = next(entry for entry in entries if entry["name"] == "context_tracker")
    assert context["format"] == "native_app"
    assert context["widget_ref"] == "core/context_tracker"
    assert context["supported_scopes"] == ["channel"]
    assert context["actions"] == []
    assert context["widget_contract"]["definition_kind"] == "native_widget"
    assert context["widget_contract"]["supported_scopes"] == ["channel"]
    assert context["widget_presentation"] == {
        "presentation_family": "card",
        "layout_hints": {
            "preferred_zone": "header",
            "min_cells": {"w": 6, "h": 2},
            "max_cells": {"w": 12, "h": 2},
        },
    }
    assert context["layout_hints"] == {
        "preferred_zone": "header",
        "min_cells": {"w": 6, "h": 2},
        "max_cells": {"w": 12, "h": 2},
    }
    usage = next(entry for entry in entries if entry["name"] == "usage_forecast_native")
    assert usage["supported_scopes"] == ["channel", "dashboard"]
    assert usage["widget_contract"]["layout_hints"] == usage["layout_hints"]
    upcoming = next(entry for entry in entries if entry["name"] == "upcoming_activity_native")
    assert upcoming["supported_scopes"] == ["channel", "dashboard"]
    names = {entry["name"] for entry in entries}
    assert "pinned_files_native" not in names


@pytest.mark.asyncio
async def test_pinned_files_native_actions_round_trip(db_session):
    channel_id = uuid.uuid4()
    instance = await get_or_create_native_widget_instance(
        db_session,
        widget_ref="core/pinned_files_native",
        dashboard_key=f"channel:{channel_id}",
        source_channel_id=channel_id,
        state={
            "pinned_files": [
                {"path": "notes.md", "pinned_at": "2026-04-23T10:00:00+00:00", "pinned_by": "user"},
                {"path": "report.md", "pinned_at": "2026-04-23T09:00:00+00:00", "pinned_by": "user"},
            ],
            "active_path": "notes.md",
        },
    )

    switched = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="set_active_path",
        args={"path": "report.md"},
    )
    assert switched == {"active_path": "report.md"}
    assert (instance.state or {})["active_path"] == "report.md"

    removed = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="unpin_path",
        args={"path": "report.md"},
    )
    assert removed["removed"] is True
    assert removed["active_path"] == "notes.md"
    assert removed["pinned_files"] == [
        {"path": "notes.md", "pinned_at": "2026-04-23T10:00:00+00:00", "pinned_by": "user"},
    ]


@pytest.mark.asyncio
async def test_pinned_files_native_rejects_unknown_path(db_session):
    channel_id = uuid.uuid4()
    instance = await get_or_create_native_widget_instance(
        db_session,
        widget_ref="core/pinned_files_native",
        dashboard_key=f"channel:{channel_id}",
        source_channel_id=channel_id,
        state={
            "pinned_files": [
                {"path": "notes.md", "pinned_at": "2026-04-23T10:00:00+00:00", "pinned_by": "user"},
            ],
            "active_path": "notes.md",
        },
    )

    with pytest.raises(HTTPException, match="unknown pinned file path"):
        await dispatch_native_widget_action(
            db_session,
            instance=instance,
            action="set_active_path",
            args={"path": "missing.md"},
        )


@pytest.mark.asyncio
async def test_context_tracker_rejects_user_dashboard_scope(db_session):
    with pytest.raises(HTTPException, match="does not support scope 'dashboard'"):
        await get_or_create_native_widget_instance(
            db_session,
            widget_ref="core/context_tracker",
            dashboard_key="default",
            source_channel_id=None,
        )


@pytest.mark.asyncio
async def test_usage_and_upcoming_native_widgets_allow_channel_and_dashboard_scopes(db_session):
    channel_id = uuid.uuid4()
    for widget_ref in ("core/usage_forecast_native", "core/upcoming_activity_native"):
        channel_instance = await get_or_create_native_widget_instance(
            db_session,
            widget_ref=widget_ref,
            dashboard_key=f"channel:{channel_id}",
            source_channel_id=channel_id,
        )
        assert channel_instance.scope_kind == "channel"
        assert channel_instance.scope_ref == str(channel_id)

        dashboard_instance = await get_or_create_native_widget_instance(
            db_session,
            widget_ref=widget_ref,
            dashboard_key="default",
            source_channel_id=None,
        )
        assert dashboard_instance.scope_kind == "dashboard"
        assert dashboard_instance.scope_ref == "default"
