"""Schema tests for the `image` v2 primitive fields.

Phase 1 of the Widget Primitives track adds `aspect_ratio`, `auth`,
`lightbox`, and `overlays` to `ImageNode`. Tests here pin the contract so
unknown `auth` values and shape drift fail loudly at registration time.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.widget_components import (
    AUTH_MODES,
    ComponentBody,
    ImageNode,
)


# ── Field presence ──


def test_image_accepts_minimal_shape():
    """Pre-v2 callers keep working — just `type` + `url` is still valid."""
    node = ImageNode(type="image", url="/api/v1/attachments/abc/file")
    assert node.url == "/api/v1/attachments/abc/file"
    assert node.aspect_ratio is None
    assert node.auth is None
    assert node.lightbox is None
    assert node.overlays is None


def test_image_accepts_full_v2_shape():
    node = ImageNode(
        type="image",
        url="/api/v1/attachments/abc/file",
        alt="Driveway camera",
        aspect_ratio="16 / 9",
        auth="bearer",
        lightbox=True,
        overlays=[
            {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "person", "color": "accent"},
        ],
    )
    assert node.auth == "bearer"
    assert node.aspect_ratio == "16 / 9"
    assert node.lightbox is True
    assert isinstance(node.overlays, list) and len(node.overlays) == 1
    assert node.overlays[0].label == "person"


# ── auth enum ──


def test_image_auth_rejects_unknown_value():
    with pytest.raises(ValidationError) as exc:
        ImageNode(type="image", url="/x", auth="oauth")
    assert "must be one of" in str(exc.value)


@pytest.mark.parametrize("mode", AUTH_MODES)
def test_image_auth_accepts_each_known_mode(mode):
    node = ImageNode(type="image", url="/x", auth=mode)
    assert node.auth == mode


def test_image_auth_accepts_templated_string():
    """Templated expressions resolve at runtime — schema must pass them through."""
    node = ImageNode(type="image", url="/x", auth="{{widget_config.auth_mode}}")
    assert node.auth == "{{widget_config.auth_mode}}"


# ── overlay shape ──


def test_image_overlay_accepts_string_coords_for_templating():
    """Templated coord strings (``"{{box.x}}"``) are valid — the engine
    substitutes at render time; the schema layer only shapes the input."""
    node = ImageNode(
        type="image",
        url="/x",
        overlays=[{"x": "{{d.x}}", "y": "{{d.y}}", "w": "{{d.w}}", "h": "{{d.h}}"}],
    )
    assert node.overlays[0].x == "{{d.x}}"


def test_image_overlay_rejects_missing_coord_fields():
    with pytest.raises(ValidationError):
        ImageNode(type="image", url="/x", overlays=[{"x": 0.1, "y": 0.2, "w": 0.3}])


def test_image_overlay_rejects_unknown_color():
    with pytest.raises(ValidationError):
        ImageNode(
            type="image",
            url="/x",
            overlays=[{"x": 0, "y": 0, "w": 0.1, "h": 0.1, "color": "fuschia"}],
        )


def test_image_overlay_rejects_extra_keys():
    """`extra="forbid"` — typo'd field names should fail loudly, not silently drop."""
    with pytest.raises(ValidationError):
        ImageNode(
            type="image",
            url="/x",
            overlays=[{"x": 0, "y": 0, "w": 0.1, "h": 0.1, "labell": "typo"}],
        )


# ── round-trip through ComponentBody ──


def test_component_body_accepts_image_v2_under_root():
    body = ComponentBody(
        v=1,
        components=[
            {
                "type": "image",
                "url": "/api/v1/attachments/abc/file",
                "aspect_ratio": "4 / 3",
                "auth": "bearer",
                "lightbox": True,
                "overlays": [
                    {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "label": "full frame"},
                ],
            }
        ],
    )
    (img,) = body.components
    assert isinstance(img, ImageNode)
    assert img.aspect_ratio == "4 / 3"
