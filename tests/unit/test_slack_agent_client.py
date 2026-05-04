"""Slack agent HTTP client regressions."""
from __future__ import annotations

import importlib
import sys

import pytest


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"ok": True}


class _Http:
    def __init__(self) -> None:
        self.post_kwargs: dict | None = None

    async def post(self, *args, **kwargs):
        self.post_kwargs = kwargs
        return _Response()


@pytest.mark.asyncio
async def test_submit_chat_uses_long_chat_timeout(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("API_KEY", "dev")
    monkeypatch.syspath_prepend("integrations/slack")
    sys.modules.pop("agent_client", None)
    sys.modules.pop("slack_settings", None)
    sys.modules.pop("session_helpers", None)

    agent_client = importlib.import_module("agent_client")
    fake_http = _Http()
    monkeypatch.setattr(agent_client, "http", fake_http)

    await agent_client.submit_chat(
        message="hello",
        bot_id="dev_bot",
        client_id="slack:C123",
    )

    assert fake_http.post_kwargs is not None
    assert fake_http.post_kwargs["timeout"] == 120
