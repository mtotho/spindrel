"""Tests for the codex app-server stdio JSON-RPC client.

Drives ``CodexAppServer`` against an in-memory fake stdin/stdout pair so we
exercise:

* request / response correlation by id
* server-pushed notifications surface on ``notifications()``
* server-pushed requests surface on ``server_requests()`` and can be
  responded to via ``respond`` / ``respond_error``
* ``CodexAppServerError`` is raised when the server returns ``error``
* ``CodexBinaryNotFound`` is raised when the binary is missing
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from integrations.codex.app_server import (
    CodexAppServer,
    CodexAppServerError,
    CodexBinaryNotFound,
    Notification,
    ServerRequest,
)

pytestmark = pytest.mark.asyncio


class _FakeStream:
    """Minimal asyncio StreamReader/StreamWriter stand-in for one direction."""

    def __init__(self) -> None:
        self.outbox: list[bytes] = []
        self._inbox: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    # writer side
    def write(self, data: bytes) -> None:
        self.outbox.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True

    # reader side
    async def readline(self) -> bytes:
        if self._closed:
            return b""
        return await self._inbox.get()

    def push(self, payload: dict) -> None:
        self._inbox.put_nowait((json.dumps(payload) + "\n").encode("utf-8"))

    def push_eof(self) -> None:
        self._closed = True
        self._inbox.put_nowait(b"")


class _FakeProc:
    def __init__(self) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self.returncode = 0
        self._wait_event = asyncio.Event()

    async def wait(self) -> int:
        await self._wait_event.wait()
        return self.returncode

    def kill(self) -> None:
        self._wait_event.set()


def _last_outbox(stream: _FakeStream) -> dict:
    assert stream.outbox, "no outbound messages"
    return json.loads(stream.outbox[-1].decode("utf-8").strip())


async def _make_client(monkeypatch) -> tuple[CodexAppServer, _FakeProc]:
    fake = _FakeProc()

    async def _fake_create(*args, **kwargs):
        return fake

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setenv("CODEX_BIN", "/bin/true")
    client = CodexAppServer()
    await client._open()
    return client, fake


async def test_request_response_correlation(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        async def _push_response_after_request() -> dict:
            request_task = asyncio.create_task(client.request("ping", {"x": 1}, timeout=5))
            await asyncio.sleep(0.01)
            sent = _last_outbox(fake.stdin)
            fake.stdout.push({"jsonrpc": "2.0", "id": sent["id"], "result": {"ok": True, "echo": sent["params"]}})
            return await request_task

        result = await _push_response_after_request()
        assert result == {"ok": True, "echo": {"x": 1}}
    finally:
        await client.close()


async def test_request_error_raises_codex_error(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        request_task = asyncio.create_task(client.request("boom", {}, timeout=5))
        await asyncio.sleep(0.01)
        sent = _last_outbox(fake.stdin)
        fake.stdout.push(
            {
                "jsonrpc": "2.0",
                "id": sent["id"],
                "error": {"code": "not_authenticated", "message": "login first"},
            }
        )
        with pytest.raises(CodexAppServerError) as exc_info:
            await request_task
        assert exc_info.value.code == "not_authenticated"
        assert "login first" in str(exc_info.value)
    finally:
        await client.close()


async def test_notifications_stream(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        fake.stdout.push({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": "hi"}})

        async def _first() -> Notification:
            async for note in client.notifications():
                return note
            raise AssertionError("no notification")

        note = await asyncio.wait_for(_first(), timeout=2)
        assert note.method == "item/agentMessage/delta"
        assert note.params == {"delta": "hi"}
    finally:
        await client.close()


async def test_server_requests_can_respond(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        fake.stdout.push(
            {"jsonrpc": "2.0", "id": 999, "method": "approval/request", "params": {"toolName": "Bash"}}
        )

        async def _first() -> ServerRequest:
            async for req in client.server_requests():
                return req
            raise AssertionError("no server request")

        req = await asyncio.wait_for(_first(), timeout=2)
        assert req.method == "approval/request"
        await req.respond({"decision": "approved"})
        sent = _last_outbox(fake.stdin)
        assert sent == {"jsonrpc": "2.0", "id": 999, "result": {"decision": "approved"}}
    finally:
        await client.close()


async def test_server_request_respond_error(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        fake.stdout.push(
            {"jsonrpc": "2.0", "id": 12, "method": "approval/request", "params": {}}
        )

        async def _first() -> ServerRequest:
            async for req in client.server_requests():
                return req
            raise AssertionError("no server request")

        req = await asyncio.wait_for(_first(), timeout=2)
        await req.respond_error("denied", "no thanks", data={"why": "policy"})
        sent = _last_outbox(fake.stdin)
        assert sent["error"]["code"] == "denied"
        assert sent["error"]["data"] == {"why": "policy"}
    finally:
        await client.close()


async def test_request_timeout(monkeypatch) -> None:
    client, _fake = await _make_client(monkeypatch)
    try:
        with pytest.raises(asyncio.TimeoutError):
            await client.request("never-responds", {}, timeout=0.05)
    finally:
        await client.close()


async def test_request_fails_when_stream_closes(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        request_task = asyncio.create_task(client.request("never", {}, timeout=5))
        await asyncio.sleep(0.01)
        fake.stdout.push_eof()
        with pytest.raises(RuntimeError, match="stream closed"):
            await request_task
    finally:
        fake._wait_event.set()
        await client.close()


async def test_notification_iterator_exits_on_stream_close(monkeypatch) -> None:
    client, fake = await _make_client(monkeypatch)
    try:
        fake.stdout.push_eof()

        async def _drain() -> list[Notification]:
            return [note async for note in client.notifications()]

        assert await asyncio.wait_for(_drain(), timeout=2) == []
    finally:
        fake._wait_event.set()
        await client.close()


async def test_binary_not_found(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    from integrations.codex.app_server import _resolve_binary

    with pytest.raises(CodexBinaryNotFound):
        _resolve_binary()


async def test_binary_explicit_missing(monkeypatch, tmp_path) -> None:
    bogus = tmp_path / "no-such-binary"
    monkeypatch.setenv("CODEX_BIN", str(bogus))
    from integrations.codex.app_server import _resolve_binary

    with pytest.raises(CodexBinaryNotFound):
        _resolve_binary()
