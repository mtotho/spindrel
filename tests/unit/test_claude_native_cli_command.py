import pytest

pytest.importorskip("claude_agent_sdk")

from integrations.claude_code.harness import build_native_cli_command  # noqa: E402


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
        == "claude -r sess-123 --model claude-sonnet-4-6 --effort high "
        "--permission-mode bypassPermissions --dangerously-skip-permissions"
    )
