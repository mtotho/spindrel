from __future__ import annotations

import pytest

import json
from typing import Any

import websockets

from integrations.truenas.client import (
    TrueNASClient,
    TrueNASClientConfig,
    TrueNASConfigurationError,
    normalize_truenas_ws_url,
    truenas_ws_url_candidates,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("truenas.local", "wss://truenas.local/api/current"),
        ("https://truenas.local", "wss://truenas.local/api/current"),
        ("http://truenas.local", "ws://truenas.local/api/current"),
        ("wss://nas.example/api/current", "wss://nas.example/api/current"),
        ("https://nas.example/api", "wss://nas.example/api/current"),
        ("https://nas.example/ui", "wss://nas.example/ui/api/current"),
        ("https://nas.example/api/v25.04", "wss://nas.example/api/v25.04"),
    ],
)
def test_normalize_truenas_ws_url(raw: str, expected: str) -> None:
    assert normalize_truenas_ws_url(raw) == expected


def test_truenas_ws_url_candidates_include_legacy_for_base_urls() -> None:
    assert truenas_ws_url_candidates("http://truenas.local") == [
        "ws://truenas.local/api/current",
        "ws://truenas.local/websocket",
    ]


def test_truenas_ws_url_candidates_honor_explicit_legacy_path() -> None:
    assert truenas_ws_url_candidates("http://truenas.local/websocket") == [
        "ws://truenas.local/websocket",
    ]


def test_normalize_truenas_ws_url_rejects_missing_url() -> None:
    with pytest.raises(TrueNASConfigurationError):
        normalize_truenas_ws_url("")


class FakeWebSocket:
    def __init__(self, replies: list[dict[str, Any]]):
        self.replies = [json.dumps(item) for item in replies]
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        return self.replies.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_client_falls_back_to_legacy_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_ws = FakeWebSocket([
        {"msg": "connected"},
        {"msg": "result", "id": "1", "result": True},
        {"msg": "result", "id": "2", "result": {"hostname": "nas"}},
    ])
    attempts: list[str] = []

    async def fake_connect(url: str, **_kwargs: Any) -> FakeWebSocket:
        attempts.append(url)
        if url.endswith("/api/current"):
            raise websockets.InvalidURI("http://truenas.local/ui/", "redirected")
        return legacy_ws

    monkeypatch.setattr("integrations.truenas.client.websockets.connect", fake_connect)

    async with TrueNASClient(TrueNASClientConfig(
        base_url="http://truenas.local",
        api_key="secret",
    )) as client:
        result = await client.call("system.info")

    assert attempts == [
        "ws://truenas.local/api/current",
        "ws://truenas.local/websocket",
    ]
    assert result == {"hostname": "nas"}
    assert legacy_ws.sent == [
        {"msg": "connect", "version": "1", "support": ["1"]},
        {"msg": "method", "method": "auth.login_with_api_key", "params": ["secret"], "id": "1"},
        {"msg": "method", "method": "system.info", "params": [], "id": "2"},
    ]
    assert legacy_ws.closed is True
