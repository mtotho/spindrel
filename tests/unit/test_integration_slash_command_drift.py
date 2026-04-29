"""Static drift gates for integration slash-command ownership."""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SLACK_SLASH = REPO_ROOT / "integrations" / "slack" / "slash_commands.py"
DISCORD_SLASH = REPO_ROOT / "integrations" / "discord" / "slash_commands.py"


def _read(path: Path) -> str:
    return path.read_text()


def test_slack_and_discord_use_shared_slash_command_client_for_server_owned_commands():
    for path in (SLACK_SLASH, DISCORD_SLASH):
        source = _read(path)
        assert "SlashCommandClient" in source
        assert "execute_for_client_channel" in source
        assert 'command_id="context"' in source
        assert 'command_id="compact"' in source
        assert 'command_id="model"' in source


def test_server_owned_platform_commands_do_not_call_legacy_endpoints_directly():
    forbidden = (
        "compact_session",
        "fetch_session_context(",
        "fetch_session_context_compressed",
        "fetch_session_context_diagnostics",
        "get_channel_settings",
        "update_channel_settings",
    )
    for path in (SLACK_SLASH, DISCORD_SLASH):
        source = _read(path)
        for needle in forbidden:
            assert needle not in source, f"{path}: {needle} should go through slash host"


def test_platform_ask_is_channel_participant_scoped_and_todos_is_retired():
    for path in (SLACK_SLASH, DISCORD_SLASH):
        source = _read(path)
        assert "list_channel_ask_targets" in source
        assert "resolve_ask_target" in source
        assert "fetch_todos" not in source
        assert "/api/v1/todos" not in source
        assert "`/todos` is retired" in source


def test_discord_slash_ask_uses_enqueue_boundary_not_legacy_streaming():
    source = _read(DISCORD_SLASH)
    assert "submit_chat" in source
    assert "stream_chat" not in source
