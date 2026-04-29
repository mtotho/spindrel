import ast
import inspect
import textwrap
import uuid
from types import SimpleNamespace

import app.services.workspace_map_state as workspace_map_state
from app.services.workspace_map_state import (
    MapStateSeed,
    _derive_cue,
    _nodes_for_attention_item,
    _nodes_for_trace_signal,
)


def _obj(**overrides):
    base = {
        "kind": "channel",
        "target_id": "channel-1",
        "label": "Quality",
        "status": "idle",
        "severity": None,
        "primary_signal": None,
        "counts": {
            "upcoming": 0,
            "recent": 0,
            "warnings": 0,
            "widgets": 0,
            "integrations": 0,
            "bots": 1,
        },
        "next": None,
        "recent": [],
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_cue_investigates_warnings_first():
    cue = _derive_cue(_obj(
        status="error",
        severity="critical",
        counts={"upcoming": 1, "recent": 1, "warnings": 1, "widgets": 0, "integrations": 0, "bots": 1},
        next={"kind": "heartbeat", "title": "Heartbeat"},
        warnings=[{"kind": "attention", "title": "Deploy failed", "message": "Probe failed"}],
    ))

    assert cue["intent"] == "investigate"
    assert cue["label"] == "Investigate"
    assert cue["reason"] == "Probe failed"
    assert cue["target_surface"] == "attention"


def test_cue_surfaces_next_recent_and_quiet_states():
    assert _derive_cue(_obj(next={"kind": "heartbeat", "title": "Heartbeat"}))["intent"] == "next"
    assert _derive_cue(_obj(recent=[{"kind": "task", "title": "Notes summary"}]))["intent"] == "recent"

    quiet = _derive_cue(_obj())
    assert quiet["intent"] == "quiet"
    assert quiet["label"] == "Quiet"


def _seed(**overrides):
    base = {
        "channels": [],
        "channel_by_id": {},
        "visible_channel_ids": set(),
        "node_pairs": [],
        "node_by_channel": {},
        "node_by_bot": {},
        "node_by_pin": {},
        "pin_by_id": {},
        "objects": {},
        "daily_health": None,
        "memory_observatory": None,
    }
    base.update(overrides)
    return MapStateSeed(**base)


def test_attention_target_resolution_prefers_explicit_target_then_channel_fallback():
    channel_id = uuid.uuid4()
    fallback_channel_id = uuid.uuid4()
    channel_node = SimpleNamespace(id=uuid.uuid4())
    fallback_node = SimpleNamespace(id=uuid.uuid4())
    seed = _seed(
        node_by_channel={
            channel_id: channel_node,
            fallback_channel_id: fallback_node,
        },
    )

    explicit = SimpleNamespace(
        target_kind="channel",
        target_id=str(channel_id),
        channel_id=fallback_channel_id,
    )
    fallback = SimpleNamespace(
        target_kind="unknown",
        target_id="ignored",
        channel_id=fallback_channel_id,
    )

    assert _nodes_for_attention_item(seed, explicit) == [channel_node]
    assert _nodes_for_attention_item(seed, fallback) == [fallback_node]


def test_trace_signal_target_resolution_dedupes_channel_and_bot_hits():
    channel_id = uuid.uuid4()
    shared_node = SimpleNamespace(id=uuid.uuid4())
    seed = _seed(
        node_by_channel={channel_id: shared_node},
        node_by_bot={"ops-bot": shared_node},
    )

    nodes = _nodes_for_trace_signal(
        seed,
        {"channel_id": str(channel_id), "bot_id": "ops-bot"},
    )

    assert nodes == [shared_node]


def test_workspace_map_state_coordinator_stays_stage_only():
    source = textwrap.dedent(inspect.getsource(workspace_map_state.build_workspace_map_state))
    tree = ast.parse(source)
    fn = tree.body[0]

    assert isinstance(fn, ast.AsyncFunctionDef)
    assert fn.end_lineno - fn.lineno + 1 <= 40
    assert "select(" not in source
    assert "list_upcoming_activity" not in source
    for helper_name in (
        "_load_map_state_seed",
        "_attach_channel_rooms",
        "_attach_widgets",
        "_attach_heartbeats",
        "_attach_activity",
        "_attach_attention",
        "_attach_trace_errors",
        "_attach_bot_summaries",
        "_attach_landmarks",
        "_finalize_map_state_response",
    ):
        assert helper_name in source
