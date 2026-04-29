"""Unit tests for the integration SDK slash-command host client."""
from __future__ import annotations

import pytest

from integrations.slash_command_client import (
    SlashCommandClient,
    SlashCommandClientError,
)


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _HTTP:
    def __init__(self, responses: list[_Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url, *, json, headers, timeout):
        self.calls.append({
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        })
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_execute_for_client_channel_resolves_channel_then_executes_command():
    http = _HTTP([
        _Response(200, {"id": "channel-1"}),
        _Response(200, {
            "command_id": "compact",
            "result_type": "harness_native_compaction",
            "payload": {"status": "completed"},
            "fallback_text": "Native compaction completed",
        }),
    ])
    client = SlashCommandClient("http://agent.test/", "secret", http=http)

    result = await client.execute_for_client_channel(
        client_id="slack:C123",
        bot_id="harness-bot",
        command_id="compact",
    )

    assert result.command_id == "compact"
    assert result.result_type == "harness_native_compaction"
    assert result.fallback_text == "Native compaction completed"
    assert http.calls[0]["url"] == "http://agent.test/api/v1/channels"
    assert http.calls[0]["json"] == {"client_id": "slack:C123", "bot_id": "harness-bot"}
    assert http.calls[1]["url"] == "http://agent.test/api/v1/slash-commands/execute"
    assert http.calls[1]["json"] == {
        "command_id": "compact",
        "args": [],
        "channel_id": "channel-1",
    }
    assert http.calls[1]["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_execute_includes_args_and_current_session():
    http = _HTTP([
        _Response(200, {
            "command_id": "model",
            "result_type": "side_effect",
            "payload": {"effect": "model"},
            "fallback_text": "Model set",
        }),
    ])
    client = SlashCommandClient("http://agent.test", None, http=http)

    await client.execute(
        command_id="model",
        channel_id="channel-1",
        current_session_id="scratch-1",
        args=["gpt-4o"],
    )

    assert http.calls[0]["headers"] == {}
    assert http.calls[0]["json"] == {
        "command_id": "model",
        "args": ["gpt-4o"],
        "channel_id": "channel-1",
        "current_session_id": "scratch-1",
    }


@pytest.mark.asyncio
async def test_error_uses_detail_from_backend():
    http = _HTTP([
        _Response(400, {"detail": "/model requires a channel context"}),
    ])
    client = SlashCommandClient("http://agent.test", "secret", http=http)

    with pytest.raises(SlashCommandClientError, match="channel context"):
        await client.execute(command_id="model", session_id="session-1")


@pytest.mark.asyncio
async def test_missing_channel_id_is_an_error():
    http = _HTTP([_Response(200, {})])
    client = SlashCommandClient("http://agent.test", "secret", http=http)

    with pytest.raises(SlashCommandClientError, match="channel id"):
        await client.execute_for_client_channel(
            client_id="discord:123",
            bot_id="bot",
            command_id="context",
        )
