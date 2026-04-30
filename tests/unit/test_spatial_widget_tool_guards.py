import uuid

from app.agent.context import current_spatial_widget_scene_seen
from app.tools.local.workspace_spatial import _recent_widget_scene_required


def test_spatial_widget_mutations_require_matching_preview_after_inspection():
    bot_id = "garden-bot"
    channel_id = uuid.uuid4()
    target_node_id = str(uuid.uuid4())

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "score": {"widget_count": 2},
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="move",
        target_node_id=target_node_id,
    ) == "Preview spatial widget changes first with preview_spatial_widget_changes."

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{"action": "move", "target_node_id": str(uuid.uuid4())}],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="move",
        target_node_id=target_node_id,
    ) == "Preview this exact spatial widget move before applying it."

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{
            "action": "move",
            "target_node_id": target_node_id,
            "dx_steps": 1,
            "dy_steps": 0,
        }],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="move",
        target_node_id=target_node_id,
        expected={"dx_steps": 2, "dy_steps": 0},
    ) == "Preview this exact spatial widget move before applying it."

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{
            "action": "move",
            "target_node_id": target_node_id,
            "dx_steps": 1,
            "dy_steps": 0,
        }],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="move",
        target_node_id=target_node_id,
        expected={"dx_steps": 1, "dy_steps": 0},
    ) is None


def test_spatial_widget_pin_requires_matching_pin_preview():
    bot_id = "garden-bot"
    channel_id = uuid.uuid4()

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{"action": "resize", "target_node_id": str(uuid.uuid4())}],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="pin",
        widget="core/todo_native",
    ) == "Preview this exact spatial widget pin before applying it."

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{
            "action": "pin",
            "widget": "core/todo_native",
            "world_x": 600,
            "world_y": 120,
            "world_w": 360,
            "world_h": 240,
            "display_label": "Garden todo",
        }],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="pin",
        widget="core/todo_native",
        expected={
            "world_x": 620,
            "world_y": 120,
            "world_w": 360,
            "world_h": 240,
            "display_label": "Garden todo",
        },
    ) == "Preview this exact spatial widget pin before applying it."

    current_spatial_widget_scene_seen.set({
        "bot_id": bot_id,
        "channel_id": str(channel_id),
        "previewed": True,
        "operations": [{
            "action": "pin",
            "widget": "core/todo_native",
            "world_x": 600,
            "world_y": 120,
            "world_w": 360,
            "world_h": 240,
            "display_label": "Garden todo",
        }],
    })

    assert _recent_widget_scene_required(
        bot_id,
        channel_id,
        action="pin",
        widget="core/todo_native",
        expected={
            "world_x": 600,
            "world_y": 120,
            "world_w": 360,
            "world_h": 240,
            "display_label": "Garden todo",
        },
    ) is None
