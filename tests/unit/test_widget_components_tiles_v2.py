"""Schema tests for the `tiles` v2 primitive fields.

Phase 2 of the Widget Primitives track extends `_TileItem` with image-first
mode (`image_url`, `image_aspect_ratio`, `image_auth`), an optional
`status` corner chip, and an optional per-item `action` dispatch.

One primitive, two layouts — presence of `image_url` flips the tile's
render mode. These tests pin that contract: text-only tiles stay valid,
image-first tiles accept the full vocabulary, and typos / unknown enums
fail loudly at registration time.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.widget_components import (
    AUTH_MODES,
    SEMANTIC_COLORS,
    ComponentBody,
    TilesNode,
)


# ── Text-only (pre-v2) tiles keep working ──


def test_tiles_accepts_text_only_items():
    node = TilesNode(
        type="tiles",
        items=[
            {"label": "CPU", "value": "42%", "caption": "1m avg"},
            {"label": "Mem", "value": "3.1 GB"},
        ],
    )
    assert len(node.items) == 2
    assert node.items[0].image_url is None
    assert node.items[0].status is None
    assert node.items[0].action is None


def test_tiles_accepts_empty_item_shape():
    """No fields required — template engine may emit blank placeholders."""
    node = TilesNode(type="tiles", items=[{}])
    assert node.items[0].label is None


# ── Image-first mode ──


def test_tiles_accepts_image_first_item():
    node = TilesNode(
        type="tiles",
        min_width=220,
        items=[
            {
                "label": "Driveway",
                "caption": "1920×1080 · 5fps",
                "image_url": "/api/v1/attachments/abc/file",
                "image_aspect_ratio": "16 / 9",
                "image_auth": "bearer",
            }
        ],
    )
    item = node.items[0]
    assert item.image_url == "/api/v1/attachments/abc/file"
    assert item.image_aspect_ratio == "16 / 9"
    assert item.image_auth == "bearer"


@pytest.mark.parametrize("mode", AUTH_MODES)
def test_tiles_image_auth_accepts_each_known_mode(mode):
    node = TilesNode(
        type="tiles",
        items=[{"image_url": "/x", "image_auth": mode}],
    )
    assert node.items[0].image_auth == mode


def test_tiles_image_auth_rejects_unknown_value():
    with pytest.raises(ValidationError) as exc:
        TilesNode(type="tiles", items=[{"image_url": "/x", "image_auth": "oauth"}])
    assert "must be one of" in str(exc.value)


def test_tiles_image_auth_accepts_templated_string():
    """Templated values must pass through — the engine substitutes at render time."""
    node = TilesNode(
        type="tiles",
        items=[{"image_url": "/x", "image_auth": "{{config.auth_mode}}"}],
    )
    assert node.items[0].image_auth == "{{config.auth_mode}}"


# ── status chip ──


@pytest.mark.parametrize("slot", SEMANTIC_COLORS)
def test_tiles_status_accepts_each_semantic_slot(slot):
    node = TilesNode(type="tiles", items=[{"label": "x", "status": slot}])
    assert node.items[0].status == slot


def test_tiles_status_rejects_unknown_slot():
    with pytest.raises(ValidationError):
        TilesNode(type="tiles", items=[{"label": "x", "status": "fuschia"}])


# ── per-item action ──


def test_tiles_action_accepts_tool_dispatch():
    node = TilesNode(
        type="tiles",
        items=[
            {
                "label": "Driveway",
                "image_url": "/x",
                "action": {
                    "dispatch": "tool",
                    "tool": "frigate_snapshot",
                    "args": {"camera": "driveway"},
                },
            }
        ],
    )
    assert node.items[0].action is not None
    assert node.items[0].action.dispatch == "tool"
    assert node.items[0].action.tool == "frigate_snapshot"


def test_tiles_action_accepts_widget_config_dispatch():
    node = TilesNode(
        type="tiles",
        items=[
            {
                "label": "Toggle",
                "action": {
                    "dispatch": "widget_config",
                    "config": {"selected_camera": "driveway"},
                },
            }
        ],
    )
    assert node.items[0].action.dispatch == "widget_config"


def test_tiles_action_rejects_unknown_dispatch():
    with pytest.raises(ValidationError):
        TilesNode(
            type="tiles",
            items=[{"label": "x", "action": {"dispatch": "oauth"}}],
        )


# ── Shape policing ──


def test_tiles_item_rejects_extra_keys():
    """``extra='forbid'`` — typo'd field names should fail loudly."""
    with pytest.raises(ValidationError):
        TilesNode(type="tiles", items=[{"label": "x", "imageUrl": "/x"}])  # camelCase typo


def test_tiles_mixed_text_and_image_items_in_one_list():
    """Mixed modes are the whole point — same primitive, per-item switch."""
    node = TilesNode(
        type="tiles",
        items=[
            {"label": "CPU", "value": "42%"},
            {"label": "Driveway", "image_url": "/x", "image_aspect_ratio": "16 / 9"},
        ],
    )
    assert node.items[0].image_url is None
    assert node.items[1].image_url == "/x"


# ── round-trip through ComponentBody ──


def test_component_body_accepts_tiles_v2_under_root():
    body = ComponentBody(
        v=1,
        components=[
            {
                "type": "tiles",
                "min_width": 220,
                "items": [
                    {
                        "label": "Driveway",
                        "caption": "live",
                        "image_url": "/api/v1/attachments/abc/file",
                        "image_aspect_ratio": "16 / 9",
                        "image_auth": "bearer",
                        "status": "success",
                        "action": {
                            "dispatch": "tool",
                            "tool": "frigate_snapshot",
                            "args": {"camera": "driveway"},
                        },
                    }
                ],
            }
        ],
    )
    (tiles,) = body.components
    assert isinstance(tiles, TilesNode)
    item = tiles.items[0]
    assert item.status == "success"
    assert item.image_url == "/api/v1/attachments/abc/file"
    assert item.action.tool == "frigate_snapshot"
