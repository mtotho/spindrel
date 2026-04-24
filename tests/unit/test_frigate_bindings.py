"""Tests for integrations/frigate/bindings.py — preset picker transforms."""
from __future__ import annotations

import json

from integrations.frigate.bindings import camera_options, label_options


_SAMPLE = json.dumps({
    "cameras": [
        {"name": "driveway", "enabled": True, "width": 1920, "height": 1080, "fps": 5},
        {"name": "garage", "enabled": False, "width": 1920, "height": 1080, "fps": 5},
        {"name": "backyard", "enabled": True, "width": 2560, "height": 1440, "fps": 5},
    ],
})


def test_camera_options_includes_enabled_and_disabled_by_default():
    opts = camera_options(_SAMPLE, {})
    by_value = {o["value"]: o for o in opts}
    assert set(by_value) == {"driveway", "garage", "backyard"}
    assert by_value["driveway"]["group"] == "Cameras"
    assert by_value["garage"]["group"] == "Disabled"
    # Alphabetical within group; disabled group sorts before 'cameras' group
    # by its lowercased label, so we check per-group ordering instead.
    by_group: dict[str, list[str]] = {}
    for o in opts:
        by_group.setdefault(o["group"], []).append(o["label"])
    assert by_group["Cameras"] == ["backyard", "driveway"]


def test_camera_options_enabled_only_filters_disabled():
    opts = camera_options(_SAMPLE, {"params": {"enabled_only": True}})
    assert {o["value"] for o in opts} == {"driveway", "backyard"}


def test_camera_options_description_has_resolution_and_fps():
    opts = camera_options(_SAMPLE, {})
    driveway = next(o for o in opts if o["value"] == "driveway")
    assert driveway["description"] == "1920×1080 · 5fps"


def test_camera_options_disabled_description_includes_flag():
    opts = camera_options(_SAMPLE, {})
    garage = next(o for o in opts if o["value"] == "garage")
    assert "disabled" in garage["description"]


def test_camera_options_handles_non_json():
    assert camera_options("not json", {}) == []
    assert camera_options(json.dumps({"cameras": "oops"}), {}) == []


def test_camera_options_skips_entries_without_name():
    raw = json.dumps({"cameras": [{"enabled": True}, {"name": "keep", "enabled": True}]})
    opts = camera_options(raw, {})
    assert [o["value"] for o in opts] == ["keep"]


def test_label_options_returns_curated_set():
    opts = label_options("", {})
    values = [o["value"] for o in opts]
    assert set(values) >= {"person", "car", "dog"}
    assert all(o["group"] == "Objects" for o in opts)
