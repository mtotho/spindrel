from app.services.workspace_map_state import _derive_cue


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
