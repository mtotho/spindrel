import pytest

pytest.importorskip("claude_agent_sdk")

from integrations.sdk import HarnessContextHint, TurnContext  # noqa: E402
from integrations.claude_code.harness import (  # noqa: E402
    _prompt_with_context_hints,
    _set_context_hint_system_prompt_kwarg,
    build_native_cli_command,
)

import uuid


def _hint() -> HarnessContextHint:
    return HarnessContextHint(
        kind="channel_prompt",
        text="Read AGENTS.md first.",
        source="project",
        priority="instruction",
        created_at="2026-05-02T00:00:00Z",
    )


def _ctx(*, context_hints=()) -> TurnContext:
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="bot",
        turn_id=uuid.uuid4(),
        workdir="/workspace",
        harness_session_id="claude-session",
        permission_mode="bypassPermissions",
        db_session_factory=lambda: None,
        context_hints=tuple(context_hints),
    )


def test_claude_native_cli_command_resumes_session_with_settings():
    command = build_native_cli_command(
        native_session_id="sess-123",
        cwd="/workspace/project",
        model="claude-sonnet-4-6",
        effort="high",
        title="Harness parity",
        permission_mode="bypassPermissions",
    )

    assert (
        command
        == "claude --add-dir /workspace/project -r sess-123 --name 'Harness parity' --model claude-sonnet-4-6 --effort high "
        "--permission-mode bypassPermissions --dangerously-skip-permissions"
    )


def test_claude_prompt_keeps_user_request_before_host_hints():
    hint = _hint()

    text = _prompt_with_context_hints("Fix the upload bug.", _ctx(context_hints=(hint,)))

    assert text.startswith("Fix the upload bug.")
    assert text.index("Fix the upload bug.") < text.index("<spindrel_host_instructions>")


def test_claude_system_prompt_append_carries_instruction_hints_when_supported():
    class Options:
        def __init__(self, *, system_prompt=None):
            self.system_prompt = system_prompt

    hint = _hint()
    options_kwargs = {}

    assert _set_context_hint_system_prompt_kwarg(Options, options_kwargs, _ctx(context_hints=(hint,)))
    assert options_kwargs["system_prompt"]["preset"] == "claude_code"
    assert "Read AGENTS.md first." in options_kwargs["system_prompt"]["append"]
