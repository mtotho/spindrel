import pytest

pytest.importorskip("claude_agent_sdk")

from integrations.claude_code.harness import build_native_cli_command  # noqa: E402


def test_claude_native_cli_command_resumes_session_with_title_and_settings():
    command = build_native_cli_command(
        native_session_id="sess-123",
        cwd="/workspace/project",
        model="claude-sonnet-4-6",
        effort="high",
        title="Harness parity",
    )

    assert command == "claude --resume sess-123 --name 'Harness parity' --model claude-sonnet-4-6 --effort high"
