"""Codex turn/thread parameter construction.

These tests pin the Spindrel -> Codex mode bridge. Spindrel plan mode is a
session contract, while Codex plan mode is a per-turn collaboration mode; the
runtime must translate between them on every turn, including resumed threads.
"""

from __future__ import annotations

import uuid

from integrations.codex import schema
from integrations.codex.harness import (
    _build_thread_start_params,
    _build_turn_start_params,
    _parse_model_options,
)
from integrations.sdk import HarnessModelOption, TurnContext


def _ctx(
    *,
    permission_mode: str = "bypassPermissions",
    session_plan_mode: str = "chat",
    model: str | None = "gpt-5.5",
    effort: str | None = "high",
) -> TurnContext:
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="bot",
        turn_id=uuid.uuid4(),
        workdir="/workspace",
        harness_session_id="thread-old",
        permission_mode=permission_mode,
        db_session_factory=lambda: None,  # not used by these pure helpers
        model=model,
        effort=effort,
        session_plan_mode=session_plan_mode,
    )


def test_spindrel_planning_turn_sets_codex_collaboration_mode_and_readonly_policy():
    params = _build_turn_start_params(
        thread_id="thread-1",
        prompt="please plan this",
        ctx=_ctx(session_plan_mode="planning", permission_mode="bypassPermissions"),
    )

    assert params["threadId"] == "thread-1"
    assert params["collaborationMode"] == {
        "mode": schema.COLLABORATION_MODE_PLAN,
        "settings": {
            "model": "gpt-5.5",
            "reasoning_effort": "high",
            "developer_instructions": None,
        },
    }
    assert params["approvalPolicy"] == schema.APPROVAL_POLICY_NEVER
    assert params["sandboxPolicy"] == {"type": schema.SANDBOX_POLICY_READ_ONLY}


def test_default_turn_omits_collaboration_mode_and_uses_workspace_write_policy():
    params = _build_turn_start_params(
        thread_id="thread-1",
        prompt="implement this",
        ctx=_ctx(session_plan_mode="chat", permission_mode="default"),
    )

    assert "collaborationMode" not in params
    assert params["approvalPolicy"] == schema.APPROVAL_POLICY_UNLESS_TRUSTED
    assert params["sandboxPolicy"] == {"type": schema.SANDBOX_POLICY_WORKSPACE_WRITE}


def test_thread_start_keeps_legacy_sandbox_and_dynamic_tools_slot_separate():
    params = _build_thread_start_params(_ctx(permission_mode="acceptEdits"))

    assert params["cwd"] == "/workspace"
    assert params["model"] == "gpt-5.5"
    assert params["approvalPolicy"] == schema.APPROVAL_POLICY_UNLESS_TRUSTED
    assert params["sandbox"] == schema.SANDBOX_WORKSPACE_WRITE
    assert "sandboxPolicy" not in params


def test_parse_model_options_preserves_per_model_efforts_and_defaults():
    options = _parse_model_options(
        {
            "data": [
                {
                    "id": "gpt-5.5",
                    "displayName": "GPT-5.5",
                    "hidden": False,
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "low"},
                        {"reasoningEffort": "medium"},
                    ],
                    "defaultReasoningEffort": "medium",
                },
                {"id": "hidden-model", "hidden": True},
            ]
        }
    )

    assert options == (
        HarnessModelOption(
            id="gpt-5.5",
            label="GPT-5.5",
            effort_values=("low", "medium"),
            default_effort="medium",
        ),
    )
