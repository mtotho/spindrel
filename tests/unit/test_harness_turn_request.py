"""Pin the harness-turn-request envelope contract.

These tests exercise the typed envelope in isolation. The seam-shape guard
(no callsite uses kwargs splat to call ``_run_harness_turn``) lives in
``test_harness_turn_host_architecture.py``.
"""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import pytest

from app.services.agent_harnesses.turn_request import HarnessTurnRequest


def _base_request(**overrides) -> HarnessTurnRequest:
    defaults = dict(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        bot=SimpleNamespace(id="bot-1", harness_runtime="claude_code"),
        user_message="hi",
        correlation_id=uuid.uuid4(),
        msg_metadata=None,
        pre_user_msg_id=None,
        suppress_outbox=False,
    )
    defaults.update(overrides)
    return HarnessTurnRequest(**defaults)


def test_request_is_frozen():
    req = _base_request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.user_message = "changed"  # type: ignore[misc]


def test_field_set_is_pinned():
    fields = {f.name for f in dataclasses.fields(HarnessTurnRequest)}
    assert fields == {
        "channel_id",
        "bus_key",
        "session_id",
        "turn_id",
        "bot",
        "user_message",
        "correlation_id",
        "msg_metadata",
        "pre_user_msg_id",
        "suppress_outbox",
        "is_heartbeat",
        "harness_model_override",
        "harness_effort_override",
        "harness_permission_mode_override",
        "harness_tool_names",
        "harness_skill_ids",
        "harness_attachments",
    }


def test_post_init_coerces_lists_to_tuples():
    req = _base_request(
        harness_tool_names=["a", "b"],
        harness_skill_ids=["x"],
        harness_attachments=[{"id": "att-1"}],
    )
    assert isinstance(req.harness_tool_names, tuple)
    assert req.harness_tool_names == ("a", "b")
    assert isinstance(req.harness_skill_ids, tuple)
    assert isinstance(req.harness_attachments, tuple)


def test_with_task_execution_config_dedupes_and_drops_blanks():
    req = _base_request().with_task_execution_config({
        "tools": ["list_channels", "file", "list_channels", "", "  "],
        "skills": ["triage", "code-review", "triage"],
        "skip_tool_approval": True,
    })
    assert req.harness_tool_names == ("list_channels", "file")
    assert req.harness_skill_ids == ("triage", "code-review")
    assert req.harness_permission_mode_override == "bypassPermissions"


def test_with_task_execution_config_keeps_default_permission_mode_without_skip():
    req = _base_request().with_task_execution_config({"tools": ["list_channels"]})
    assert req.harness_tool_names == ("list_channels",)
    assert req.harness_skill_ids == ()
    assert req.harness_permission_mode_override is None


def test_with_task_execution_config_injects_report_issue_when_allowed():
    req = _base_request().with_task_execution_config({
        "tools": ["list_channels"],
        "allow_issue_reporting": True,
    })
    assert req.harness_tool_names == ("list_channels", "report_issue")


def test_with_task_execution_config_does_not_double_inject_report_issue():
    req = _base_request().with_task_execution_config({
        "tools": ["report_issue", "list_channels"],
        "allow_issue_reporting": True,
    })
    assert req.harness_tool_names == ("report_issue", "list_channels")


def test_with_task_execution_config_preserves_unrelated_fields():
    base = _base_request(
        user_message="prompt",
        is_heartbeat=True,
        harness_model_override="claude-sonnet-4-6",
        harness_effort_override="high",
        harness_attachments=({"id": "att-1"},),
    )
    derived = base.with_task_execution_config({"tools": ["t"]})
    assert derived.user_message == "prompt"
    assert derived.is_heartbeat is True
    assert derived.harness_model_override == "claude-sonnet-4-6"
    assert derived.harness_effort_override == "high"
    assert derived.harness_attachments == ({"id": "att-1"},)
    assert derived.session_id == base.session_id
