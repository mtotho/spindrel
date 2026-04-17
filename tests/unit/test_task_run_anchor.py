"""Unit tests for the task-run anchor step-summary builder.

Focus: when a step is `awaiting_user_input`, the anchor payload must carry
the step's `widget_envelope`, `response_schema`, and step `title` so the web
client can render the approval UI inline in chat without a second fetch.
"""
from types import SimpleNamespace

from app.services.task_run_anchor import _step_summary


def _make_task(steps, step_states):
    return SimpleNamespace(steps=steps, step_states=step_states)


def test_step_summary_passes_through_awaiting_user_input_payload():
    steps = [
        {"id": "review", "type": "user_prompt", "title": "Review tuning proposals"},
    ]
    envelope = {
        "template": {"kind": "approval_review", "title": "Tuning"},
        "args": {"proposals": [{"id": "p1"}, {"id": "p2"}]},
    }
    schema = {"type": "multi_item", "items": [{"id": "p1"}, {"id": "p2"}]}
    states = [
        {
            "status": "awaiting_user_input",
            "widget_envelope": envelope,
            "response_schema": schema,
        },
    ]

    out = _step_summary(_make_task(steps, states))

    assert len(out) == 1
    entry = out[0]
    assert entry["status"] == "awaiting_user_input"
    assert entry["widget_envelope"] == envelope
    assert entry["response_schema"] == schema
    assert entry["title"] == "Review tuning proposals"


def test_step_summary_omits_envelope_for_non_awaiting_steps():
    steps = [
        {"id": "fetch", "type": "tool"},
        {"id": "analyze", "type": "agent"},
    ]
    states = [
        {"status": "done", "result": "ok"},
        {"status": "running"},
    ]

    out = _step_summary(_make_task(steps, states))

    for entry in out:
        assert "widget_envelope" not in entry
        assert "response_schema" not in entry
        assert "title" not in entry


def test_step_summary_awaiting_without_envelope_degrades_gracefully():
    """If a step pauses but state somehow lacks the envelope, don't crash."""
    steps = [{"id": "review", "type": "user_prompt"}]
    states = [{"status": "awaiting_user_input"}]

    out = _step_summary(_make_task(steps, states))

    assert out[0]["status"] == "awaiting_user_input"
    # No envelope was present → not attached; no title on step def → not attached.
    assert "widget_envelope" not in out[0]
    assert "response_schema" not in out[0]
    assert "title" not in out[0]


def test_step_summary_envelope_not_leaked_when_status_is_done():
    """Old envelope lingering in state after resolve must not be forwarded."""
    steps = [{"id": "review", "type": "user_prompt"}]
    states = [
        {
            "status": "done",
            "widget_envelope": {"template": {"kind": "approval_review"}},
            "response_schema": {"type": "multi_item"},
            "result": '{"decision": "approve"}',
        },
    ]

    out = _step_summary(_make_task(steps, states))

    assert out[0]["status"] == "done"
    assert "widget_envelope" not in out[0]
    assert "response_schema" not in out[0]
