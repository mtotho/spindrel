"""Codex turn/thread parameter construction.

These tests pin the Spindrel -> Codex mode bridge. Spindrel plan mode is a
session contract, while Codex plan mode is a per-turn collaboration mode; the
runtime must translate between them on every turn, including resumed threads.
"""

from __future__ import annotations

import uuid

from integrations.codex import schema
from integrations.codex.harness import (
    build_native_cli_command,
    _codex_thread_name_from_prompt,
    _build_turn_input,
    _build_thread_start_params,
    _build_turn_start_params,
    _parse_model_options,
)
from integrations.sdk import HarnessContextHint, HarnessModelOption, TurnContext


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


def test_turn_input_keeps_user_request_first_and_hints_afterward():
    ctx = _ctx()
    ctx = TurnContext(
        **{
            **ctx.__dict__,
            "context_hints": (
                HarnessContextHint(
                    kind="compact_summary",
                    text="remember the prior deploy",
                    created_at="2026-04-28T00:00:00+00:00",
                    source="compact",
                ),
                HarnessContextHint(
                    kind="channel_prompt",
                    text="always mention channel prompt marker",
                    created_at="2026-04-28T00:00:01+00:00",
                    source="channel",
                    priority="instruction",
                    consume_after_next_turn=False,
                ),
            ),
        }
    )

    items = _build_turn_input("current user request", ctx)
    assert items[0] == {"type": "text", "text": "current user request"}
    text = items[1]["text"]

    assert text.index("<spindrel_host_instructions>") < text.index("<spindrel_context_hints>")
    assert text.index("always mention channel prompt marker") < text.index("remember the prior deploy")


def test_turn_input_keeps_native_request_ahead_of_spindrel_bridge_guidance():
    ctx = _ctx()

    [item] = _build_turn_input(
        "Fix the repo bug.\n\n<spindrel_tool_guidance>\nbridge note\n</spindrel_tool_guidance>",
        ctx,
    )
    text = item["text"]

    assert text.startswith("Fix the repo bug.")
    assert text.index("Fix the repo bug.") < text.index("<spindrel_tool_guidance>")


def test_codex_native_cli_command_resumes_thread_in_cwd():
    command = build_native_cli_command(
        native_session_id="thread-123",
        cwd="/workspace/my repo",
        model="gpt-5.5",
        effort="high",
    )

    assert command == "codex resume thread-123 --model gpt-5.5 -c 'model_reasoning_effort=\"high\"' --cd '/workspace/my repo'"


def test_codex_thread_name_from_prompt_ignores_spindrel_wrappers():
    assert _codex_thread_name_from_prompt(
        "<spindrel_context_hints>ignore</spindrel_context_hints>\n\nFix the upload bug and update tests."
    ) == "Fix the upload bug and update tests."


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
