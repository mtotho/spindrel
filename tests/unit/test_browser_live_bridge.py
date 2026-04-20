"""Tests for `integrations.browser_live.bridge` — the JSON-RPC bridge
between tool calls and a paired browser extension.

Covers:
- register / unregister roundtrip
- request → reply happy path
- request with no paired browser raises
- timeout cancels the pending future
- targeted ``connection_id`` routes to the right connection
- targeted ``connection_id`` rejects unknown ids
- extension-side error reply surfaces as RuntimeError
- unregister cancels every pending future
"""
from __future__ import annotations

import asyncio

import pytest

from integrations.browser_live.bridge import Bridge


@pytest.fixture
def bridge():
    return Bridge()


async def _noop_send(_payload):
    pass


async def _reply_after(bridge: Bridge, conn, payload: dict, *, delay_ms: int = 5):
    """Fake the extension: wait for the bridge to send, then reply."""
    # The bridge always sends to ``conn.send`` synchronously before awaiting
    # the future, so by the time we sleep the request_id is already in the
    # pending dict.
    await asyncio.sleep(delay_ms / 1000)
    rid = next(iter(conn.pending))
    bridge.handle_reply(conn, {"request_id": rid, **payload})


@pytest.mark.asyncio
async def test_register_and_list(bridge):
    sent = []

    async def send(payload):
        sent.append(payload)

    conn = await bridge.register(send, label="test-browser")
    assert conn.connection_id
    listing = bridge.list_connections()
    assert len(listing) == 1
    assert listing[0]["connection_id"] == conn.connection_id
    assert listing[0]["label"] == "test-browser"


@pytest.mark.asyncio
async def test_unregister_removes_connection(bridge):
    conn = await bridge.register(_noop_send)
    await bridge.unregister(conn)
    assert bridge.list_connections() == []


@pytest.mark.asyncio
async def test_request_reply_roundtrip(bridge):
    sent = []

    async def send(payload):
        sent.append(payload)

    conn = await bridge.register(send)
    asyncio.create_task(
        _reply_after(bridge, conn, {"result": {"ok": True, "echo": "hi"}})
    )
    result = await bridge.request("noop", {"x": 1}, timeout_ms=1000)
    assert result == {"ok": True, "echo": "hi"}
    # Wire frame the extension would have received.
    assert sent[0]["op"] == "noop"
    assert sent[0]["args"] == {"x": 1}
    assert "request_id" in sent[0]


@pytest.mark.asyncio
async def test_request_with_no_browser_raises(bridge):
    with pytest.raises(RuntimeError, match="No paired browser"):
        await bridge.request("noop", {})


@pytest.mark.asyncio
async def test_request_timeout_cancels_pending(bridge):
    conn = await bridge.register(_noop_send)
    with pytest.raises(RuntimeError, match="timed out"):
        await bridge.request("hang", {}, timeout_ms=50)
    # Pending entry must be cleared so a slow late reply doesn't leak.
    assert conn.pending == {}


@pytest.mark.asyncio
async def test_request_targeted_connection_id(bridge):
    sent_a, sent_b = [], []

    async def send_a(payload):
        sent_a.append(payload)

    async def send_b(payload):
        sent_b.append(payload)

    conn_a = await bridge.register(send_a, label="laptop")
    conn_b = await bridge.register(send_b, label="desktop")
    asyncio.create_task(
        _reply_after(bridge, conn_a, {"result": {"who": "laptop"}})
    )
    result = await bridge.request(
        "noop", {}, connection_id=conn_a.connection_id, timeout_ms=1000
    )
    assert result == {"who": "laptop"}
    # Default (no connection_id) routes to the *most-recent* — that's B.
    asyncio.create_task(
        _reply_after(bridge, conn_b, {"result": {"who": "desktop"}})
    )
    result_default = await bridge.request("noop", {}, timeout_ms=1000)
    assert result_default == {"who": "desktop"}


@pytest.mark.asyncio
async def test_request_unknown_connection_id_raises(bridge):
    await bridge.register(_noop_send)
    with pytest.raises(RuntimeError, match="not paired"):
        await bridge.request("noop", {}, connection_id="bogus-id")


@pytest.mark.asyncio
async def test_extension_error_reply_surfaces(bridge):
    conn = await bridge.register(_noop_send)
    asyncio.create_task(
        _reply_after(bridge, conn, {"error": "selector not found: #x"})
    )
    with pytest.raises(RuntimeError, match="selector not found"):
        await bridge.request("act", {"selector": "#x"}, timeout_ms=1000)


@pytest.mark.asyncio
async def test_unregister_cancels_pending_futures(bridge):
    conn = await bridge.register(_noop_send)

    async def fire():
        return await bridge.request("hang", {}, timeout_ms=5000)

    task = asyncio.create_task(fire())
    # Give the bridge a tick to enqueue the pending future.
    await asyncio.sleep(0.01)
    assert len(conn.pending) == 1
    await bridge.unregister(conn)
    # The cancelled future propagates as CancelledError out of the task.
    with pytest.raises(asyncio.CancelledError):
        await task
