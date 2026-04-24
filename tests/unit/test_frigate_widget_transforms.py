"""Tests for integrations/frigate/widget_transforms.py.

Two pipelines (initial render + state_poll) share one reshape core; these
tests exercise the edges that matter:

  - epoch-float timestamps coerce to ISO 8601 Z
  - missing ``id`` or unparseable ``start_time`` drops the row (loud-silence
    at the transform, not at the primitive — so the whole widget survives
    one bad event)
  - labels map to SemanticSlot colors; unknown labels fall to ``muted``
  - lanes derive from distinct cameras, alphabetized
  - error payloads produce a single status-color-danger component
  - empty payloads produce a single muted "no events" text component
  - widget_config.selected_event rides through to ``selected_event_id``
"""
from __future__ import annotations

import json

from integrations.frigate.widget_transforms import (
    cameras_view,
    events_view,
    render_cameras_widget,
    render_events_widget,
)


_SAMPLE = {
    "events": [
        {
            "id": "abc",
            "camera": "driveway",
            "label": "person",
            "score": 0.91,
            "start_time": 1713607200.5,
            "end_time": 1713607212.3,
        },
        {
            "id": "def",
            "camera": "backyard",
            "label": "dog",
            "score": 0.82,
            "start_time": 1713607260.0,
            "end_time": 1713607268.0,
        },
        {
            "id": "ghi",
            "camera": "driveway",
            "label": "car",
            "score": 0.97,
            "start_time": 1713607300.0,
            "end_time": 1713607340.0,
        },
    ],
    "count": 3,
}


# ── events_view (state_poll) ──


def test_events_view_reshapes_valid_events():
    res = events_view(json.dumps(_SAMPLE), {})
    assert res["has_events"] is True
    assert res["count"] == 3
    assert {e["id"] for e in res["events"]} == {"abc", "def", "ghi"}


def test_events_view_coerces_epoch_to_iso_z():
    res = events_view(json.dumps(_SAMPLE), {})
    for ev in res["events"]:
        assert ev["start"].endswith("Z")
        assert "T" in ev["start"]
        assert ev["end"].endswith("Z")


def test_events_view_maps_labels_to_semantic_slots():
    res = events_view(json.dumps(_SAMPLE), {})
    by_id = {e["id"]: e for e in res["events"]}
    assert by_id["abc"]["color"] == "accent"   # person
    assert by_id["def"]["color"] == "warning"  # dog
    assert by_id["ghi"]["color"] == "success"  # car


def test_events_view_unknown_label_falls_to_muted():
    res = events_view(
        json.dumps({"events": [{"id": "x", "label": "dragon", "start_time": 1_713_607_200.0}]}),
        {},
    )
    assert res["events"][0]["color"] == "muted"


def test_events_view_derives_lanes_from_cameras():
    res = events_view(json.dumps(_SAMPLE), {})
    lane_ids = [lane["id"] for lane in res["lanes"]]
    assert lane_ids == ["backyard", "driveway"]  # alphabetized
    assert all(lane["label"] == lane["id"] for lane in res["lanes"])


def test_events_view_drops_events_missing_id():
    res = events_view(
        json.dumps({"events": [{"start_time": 1_713_607_200.0}, {"id": "keep", "start_time": 1_713_607_200.0}]}),
        {},
    )
    assert [e["id"] for e in res["events"]] == ["keep"]


def test_events_view_drops_events_with_bad_start_time():
    res = events_view(
        json.dumps({"events": [{"id": "bad", "start_time": "garbage"}, {"id": "keep", "start_time": 1_713_607_200.0}]}),
        {},
    )
    assert [e["id"] for e in res["events"]] == ["keep"]


def test_events_view_passes_error_through():
    res = events_view(json.dumps({"error": "FRIGATE_URL not set"}), {})
    assert res["error"] == "FRIGATE_URL not set"
    assert res["has_events"] is False


def test_events_view_handles_empty_payload():
    res = events_view(json.dumps({}), {})
    assert res == {
        "events": [],
        "lanes": [],
        "count": 0,
        "has_events": False,
        "error": None,
    }


def test_events_view_handles_non_json_input():
    """Malformed input doesn't crash — returns the empty shape."""
    res = events_view("not json", {})
    assert res["events"] == []
    assert res["has_events"] is False


def test_events_view_score_formatting_skipped_when_missing():
    res = events_view(
        json.dumps({"events": [{"id": "x", "start_time": 1_713_607_200.0, "label": "person"}]}),
        {},
    )
    assert res["events"][0]["subtitle"] is None


def test_events_view_end_defaults_to_start_when_unparseable():
    res = events_view(
        json.dumps({"events": [{"id": "x", "start_time": 1_713_607_200.0, "end_time": "bad"}]}),
        {},
    )
    assert res["events"][0]["start"] == res["events"][0]["end"]


# ── render_events_widget (initial) ──


def test_render_events_widget_builds_status_and_timeline():
    comps = render_events_widget(_SAMPLE, [])
    assert len(comps) == 2
    assert comps[0]["type"] == "status"
    assert comps[0]["text"] == "3 events"
    assert comps[1]["type"] == "timeline"
    assert len(comps[1]["events"]) == 3
    assert len(comps[1]["lanes"]) == 2


def test_render_events_widget_empty_case_is_single_muted_text():
    comps = render_events_widget({"events": [], "count": 0}, [])
    assert comps == [
        {"type": "text", "content": "No events in this window.", "style": "muted"}
    ]


def test_render_events_widget_error_case_is_single_status_danger():
    comps = render_events_widget({"error": "FRIGATE_URL not set"}, [])
    assert len(comps) == 1
    assert comps[0]["type"] == "status"
    assert comps[0]["color"] == "danger"


def test_render_events_widget_carries_selected_event_from_widget_config():
    data = {**_SAMPLE, "widget_config": {"selected_event": "abc"}}
    comps = render_events_widget(data, [])
    timeline = next(c for c in comps if c["type"] == "timeline")
    assert timeline["selected_event_id"] == "abc"


def test_render_events_widget_on_event_click_uses_value_key():
    comps = render_events_widget(_SAMPLE, [])
    timeline = next(c for c in comps if c["type"] == "timeline")
    action = timeline["on_event_click"]
    assert action["dispatch"] == "widget_config"
    assert action["value_key"] == "selected_event"


def test_render_events_widget_null_selected_event_when_unset():
    comps = render_events_widget(_SAMPLE, [])
    timeline = next(c for c in comps if c["type"] == "timeline")
    assert timeline["selected_event_id"] is None


# ── cameras_view / render_cameras_widget ──


_CAMERAS_SAMPLE = {
    "cameras": [
        {
            "name": "driveway",
            "enabled": True,
            "width": 1920,
            "height": 1080,
            "fps": 5,
            "snapshot_url": "http://frigate:5000/api/driveway/latest.jpg",
        },
        {
            "name": "backyard",
            "enabled": True,
            "width": 2560,
            "height": 1440,
            "fps": 5,
            "snapshot_url": "http://frigate:5000/api/backyard/latest.jpg",
        },
        {
            "name": "garage",
            "enabled": False,
            "width": 1920,
            "height": 1080,
            "fps": 5,
            "snapshot_url": "http://frigate:5000/api/garage/latest.jpg",
        },
    ],
}


def test_cameras_view_builds_one_tile_per_camera():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    assert res["count"] == 3
    assert [t["label"] for t in res["tiles"]] == ["driveway", "backyard", "garage"]


def test_cameras_view_status_slot_reflects_enabled():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    by_label = {t["label"]: t for t in res["tiles"]}
    assert by_label["driveway"]["status"] == "success"
    assert by_label["garage"]["status"] == "muted"


def test_cameras_view_caption_has_resolution_and_fps():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    assert res["tiles"][0]["caption"] == "1920×1080 · 5fps"


def test_cameras_view_caption_omits_missing_fields():
    res = cameras_view(
        json.dumps({"cameras": [{"name": "x", "enabled": True}]}), {}
    )
    assert res["tiles"][0]["caption"] is None


def test_cameras_view_tile_action_dispatches_snapshot_with_camera_name():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    action = res["tiles"][0]["action"]
    assert action["dispatch"] == "tool"
    assert action["tool"] == "frigate_snapshot"
    assert action["args"]["camera"] == "driveway"


def test_cameras_view_action_bbox_reflects_widget_config():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {"widget_config": {"show_bbox": False}})
    assert all(t["action"]["args"]["bounding_box"] is False for t in res["tiles"])


def test_cameras_view_action_bbox_defaults_true_when_unset():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    assert all(t["action"]["args"]["bounding_box"] is True for t in res["tiles"])


def test_cameras_view_summary_counts_live_vs_disabled():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    assert res["enabled_count"] == 2
    assert res["disabled_count"] == 1
    assert res["summary"] == "2 live · 1 disabled"


def test_cameras_view_summary_all_live():
    res = cameras_view(
        json.dumps({"cameras": [{"name": "a", "enabled": True}, {"name": "b", "enabled": True}]}),
        {},
    )
    assert res["summary"] == "2 live"


def test_cameras_view_drops_cameras_without_name():
    res = cameras_view(
        json.dumps({"cameras": [{"enabled": True}, {"name": "keep", "enabled": True}]}), {}
    )
    assert [t["label"] for t in res["tiles"]] == ["keep"]


def test_cameras_view_passes_error_through():
    res = cameras_view(json.dumps({"error": "FRIGATE_URL is not configured"}), {})
    assert res["error"] == "FRIGATE_URL is not configured"
    assert res["has_cameras"] is False


def test_cameras_view_empty_payload():
    res = cameras_view(json.dumps({}), {})
    assert res["tiles"] == []
    assert res["has_cameras"] is False
    assert res["summary"] == "No cameras"


def test_cameras_view_handles_non_json_input():
    res = cameras_view("not json", {})
    assert res["tiles"] == []
    assert res["has_cameras"] is False


def test_render_cameras_widget_builds_status_and_tiles():
    comps = render_cameras_widget(_CAMERAS_SAMPLE, [])
    assert len(comps) == 2
    assert comps[0]["type"] == "status"
    assert comps[0]["text"] == "2 live · 1 disabled"
    assert comps[1]["type"] == "tiles"
    assert len(comps[1]["items"]) == 3
    assert comps[1]["min_width"] == 280


def test_cameras_view_enabled_tiles_have_image_url():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    by_label = {t["label"]: t for t in res["tiles"]}
    driveway = by_label["driveway"]
    assert driveway["image_url"].startswith("http://frigate:5000/api/driveway/latest.jpg?")
    assert "bbox=1" in driveway["image_url"]
    assert "t=" in driveway["image_url"]
    assert driveway["image_aspect_ratio"] == "16 / 9"
    assert driveway["image_auth"] == "none"


def test_cameras_view_disabled_tile_has_no_image():
    res = cameras_view(json.dumps(_CAMERAS_SAMPLE), {})
    by_label = {t["label"]: t for t in res["tiles"]}
    garage = by_label["garage"]
    assert "image_url" not in garage
    assert garage["status"] == "muted"


def test_cameras_view_image_url_drops_bbox_when_show_bbox_false():
    res = cameras_view(
        json.dumps(_CAMERAS_SAMPLE), {"widget_config": {"show_bbox": False}}
    )
    by_label = {t["label"]: t for t in res["tiles"]}
    assert "bbox=1" not in by_label["driveway"]["image_url"]


def test_cameras_view_tile_without_snapshot_url_stays_text_mode():
    res = cameras_view(
        json.dumps({"cameras": [{"name": "x", "enabled": True}]}), {}
    )
    assert "image_url" not in res["tiles"][0]


def test_render_cameras_widget_empty_case_is_muted_text():
    comps = render_cameras_widget({"cameras": []}, [])
    assert comps == [
        {"type": "text", "content": "No cameras configured.", "style": "muted"}
    ]


def test_render_cameras_widget_error_case_is_status_danger():
    comps = render_cameras_widget({"error": "FRIGATE_URL is not configured"}, [])
    assert len(comps) == 1
    assert comps[0]["type"] == "status"
    assert comps[0]["color"] == "danger"


def test_render_cameras_widget_threads_widget_config_show_bbox():
    data = {**_CAMERAS_SAMPLE, "widget_config": {"show_bbox": False}}
    comps = render_cameras_widget(data, [])
    tiles = next(c for c in comps if c["type"] == "tiles")
    assert all(t["action"]["args"]["bounding_box"] is False for t in tiles["items"])
