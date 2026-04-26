from __future__ import annotations

import re
import uuid
from unittest.mock import patch

from app.services import secret_registry
from app.services.agent_harnesses.base import ChannelEventEmitter


def _enable_secret(value: str) -> None:
    secret_registry._known_secrets = {value}
    secret_registry._pattern = re.compile(re.escape(value))


def test_harness_emitter_redacts_streamed_text_and_tool_result():
    _enable_secret("ghp_secret_token_123")
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.token("token is ghp_secret_token_123")
        emitter.tool_result(
            tool_name="Bash",
            tool_call_id="tu_1",
            result_summary="GITHUB_TOKEN=ghp_secret_token_123",
        )

    assert events[0].payload.delta == "token is [REDACTED]"
    assert events[1].payload.result_summary == "GITHUB_TOKEN=[REDACTED]"


def test_harness_emitter_redacts_nested_tool_arguments():
    _enable_secret("ghp_secret_token_456")
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_start(
            tool_name="Bash",
            tool_call_id="tu_2",
            arguments={
                "command": "echo ghp_secret_token_456",
                "env": {"GITHUB_TOKEN": "ghp_secret_token_456"},
            },
        )

    assert events[0].payload.arguments == {
        "command": "echo [REDACTED]",
        "env": {"GITHUB_TOKEN": "[REDACTED]"},
    }
