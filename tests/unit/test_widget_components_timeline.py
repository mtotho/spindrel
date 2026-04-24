"""Schema tests for the `timeline` primitive.

Phase 3 of the Widget Primitives track introduces a lane-based event
renderer. These tests pin the contract:

  - events require stable ``id`` (selection state depends on it)
  - ``lane_id`` required when lanes present, absent when not — loud failure
  - ``lane_id`` must match a declared lane when lanes are present
  - explicit ``range: {start, end}`` is accepted; omitted = auto-fit
  - ``on_event_click`` reuses the existing ``WidgetAction`` shape
  - extra/typo'd fields are rejected at registration
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.widget_components import (
    SEMANTIC_COLORS,
    ComponentBody,
    TimelineNode,
)


# ── Minimal / flat ──


def test_timeline_accepts_flat_shape():
    """No lanes + events with just id+start is the minimum legal shape."""
    node = TimelineNode(
        type="timeline",
        events=[
            {"id": "ev-1", "start": "2026-04-23T14:00:00Z"},
            {"id": "ev-2", "start": "2026-04-23T14:05:00Z"},
        ],
    )
    assert len(node.events) == 2
    assert node.range is None
    assert node.lanes is None
    assert node.on_event_click is None


def test_timeline_rejects_event_without_id():
    with pytest.raises(ValidationError) as exc:
        TimelineNode(
            type="timeline",
            events=[{"start": "2026-04-23T14:00:00Z"}],
        )
    assert "id" in str(exc.value).lower()


def test_timeline_rejects_event_without_start():
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            events=[{"id": "ev-1"}],
        )


# ── Explicit range ──


def test_timeline_accepts_explicit_range():
    node = TimelineNode(
        type="timeline",
        range={"start": "2026-04-23T12:00:00Z", "end": "2026-04-23T18:00:00Z"},
        events=[{"id": "ev-1", "start": "2026-04-23T14:00:00Z"}],
    )
    assert node.range is not None
    assert node.range.start == "2026-04-23T12:00:00Z"
    assert node.range.end == "2026-04-23T18:00:00Z"


def test_timeline_range_rejects_partial():
    """Range is all-or-nothing — partial (just start, just end) fails fast."""
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            range={"start": "2026-04-23T12:00:00Z"},
            events=[{"id": "ev-1", "start": "2026-04-23T14:00:00Z"}],
        )


# ── Lanes + lane_id invariants ──


def test_timeline_accepts_lanes_with_matching_lane_ids():
    node = TimelineNode(
        type="timeline",
        lanes=[{"id": "driveway", "label": "Driveway"}, {"id": "backyard"}],
        events=[
            {"id": "ev-1", "start": "2026-04-23T14:00:00Z", "lane_id": "driveway"},
            {"id": "ev-2", "start": "2026-04-23T14:05:00Z", "lane_id": "backyard"},
        ],
    )
    assert len(node.lanes) == 2
    assert node.events[0].lane_id == "driveway"


def test_timeline_rejects_event_missing_lane_id_when_lanes_present():
    with pytest.raises(ValidationError) as exc:
        TimelineNode(
            type="timeline",
            lanes=[{"id": "driveway"}],
            events=[{"id": "ev-1", "start": "2026-04-23T14:00:00Z"}],
        )
    assert "lane_id is required" in str(exc.value)


def test_timeline_rejects_event_with_lane_id_when_no_lanes():
    """Flat timeline invariant — lane_id must be absent when no lanes declared."""
    with pytest.raises(ValidationError) as exc:
        TimelineNode(
            type="timeline",
            events=[{"id": "ev-1", "start": "2026-04-23T14:00:00Z", "lane_id": "somewhere"}],
        )
    assert "lane_id must be absent" in str(exc.value)


def test_timeline_rejects_event_with_unknown_lane_id():
    with pytest.raises(ValidationError) as exc:
        TimelineNode(
            type="timeline",
            lanes=[{"id": "driveway"}],
            events=[{"id": "ev-1", "start": "x", "lane_id": "garage"}],
        )
    assert "does not match any declared lane" in str(exc.value)


# ── color + subtitle ──


@pytest.mark.parametrize("slot", SEMANTIC_COLORS)
def test_timeline_event_color_accepts_each_semantic_slot(slot):
    node = TimelineNode(
        type="timeline",
        events=[{"id": "ev-1", "start": "x", "color": slot}],
    )
    assert node.events[0].color == slot


def test_timeline_event_color_rejects_unknown_slot():
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            events=[{"id": "ev-1", "start": "x", "color": "fuschia"}],
        )


# ── on_event_click + selected_event_id ──


def test_timeline_accepts_on_event_click():
    node = TimelineNode(
        type="timeline",
        events=[{"id": "ev-1", "start": "x"}],
        on_event_click={
            "dispatch": "widget_config",
            "config": {"selected_event": "{{event.id}}"},
        },
    )
    assert node.on_event_click is not None
    assert node.on_event_click.dispatch == "widget_config"


def test_timeline_accepts_selected_event_id_binding():
    """Templated selected_event_id — binds widget_config round-trip."""
    node = TimelineNode(
        type="timeline",
        events=[{"id": "ev-1", "start": "x"}],
        selected_event_id="{{widget_config.selected_event}}",
    )
    assert node.selected_event_id == "{{widget_config.selected_event}}"


# ── Shape policing ──


def test_timeline_rejects_extra_event_field():
    """``extra='forbid'`` — typo'd fields on events should fail loudly."""
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            events=[{"id": "ev-1", "start": "x", "stat_time": "bad"}],  # typo'd start_time
        )


def test_timeline_rejects_extra_lane_field():
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            lanes=[{"id": "driveway", "color": "accent"}],  # color is not a lane field
            events=[{"id": "ev-1", "start": "x", "lane_id": "driveway"}],
        )


def test_timeline_rejects_extra_range_field():
    with pytest.raises(ValidationError):
        TimelineNode(
            type="timeline",
            range={"start": "a", "end": "b", "step": "1h"},
            events=[{"id": "ev-1", "start": "a"}],
        )


# ── round-trip through ComponentBody ──


def test_component_body_accepts_full_timeline():
    body = ComponentBody(
        v=1,
        components=[
            {
                "type": "timeline",
                "range": {
                    "start": "2026-04-23T12:00:00Z",
                    "end": "2026-04-23T18:00:00Z",
                },
                "lanes": [
                    {"id": "driveway", "label": "Driveway"},
                    {"id": "backyard", "label": "Backyard"},
                ],
                "events": [
                    {
                        "id": "ev-1",
                        "start": "2026-04-23T14:00:12Z",
                        "end": "2026-04-23T14:00:28Z",
                        "lane_id": "driveway",
                        "label": "person",
                        "color": "accent",
                        "subtitle": "score 0.91",
                    },
                ],
                "on_event_click": {
                    "dispatch": "widget_config",
                    "config": {"selected_event": "{{event.id}}"},
                },
                "selected_event_id": "{{widget_config.selected_event}}",
            }
        ],
    )
    (tl,) = body.components
    assert isinstance(tl, TimelineNode)
    assert tl.events[0].color == "accent"
    assert tl.lanes[0].label == "Driveway"
    assert tl.on_event_click.dispatch == "widget_config"


# ── Templated lists / each-blocks bypass lane invariant (enforced at render) ──


def test_timeline_templated_events_bypasses_lane_invariant():
    """When events is a templated string, the engine materializes at render
    time — schema can't enforce the lane_id invariant against an unknown list,
    so it lets the template through. (Runtime is responsible from there.)"""
    node = TimelineNode(
        type="timeline",
        lanes=[{"id": "l1"}],
        events="{{d.events}}",  # templated string
    )
    assert isinstance(node.events, str)
