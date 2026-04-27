"""Async JSON-RPC client over stdio for ``codex app-server``.

Spawns the user-installed ``codex`` binary as ``codex app-server`` (path
overridable via the ``CODEX_BIN`` env var). Speaks line-delimited JSON-RPC
2.0 on the binary's stdin/stdout. Stderr is logged.

Three concurrent streams come back from the server:

* responses — correlated to outgoing requests by ``id``
* notifications — server-pushed events with ``method`` but no ``id``
* server-initiated requests — server-pushed messages with both ``method``
  and ``id``; clients must respond

Each is exposed as its own iterator/Future so the harness can fan out to
the appropriate translator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class CodexAppServerError(RuntimeError):
    """JSON-RPC error response from the codex app-server."""

    def __init__(self, code: int | str, message: str, data: Any = None) -> None:
        super().__init__(f"codex app-server error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class CodexBinaryNotFound(FileNotFoundError):
    """Raised when the codex binary is not on PATH and ``CODEX_BIN`` is unset."""


def _resolve_binary() -> str:
    explicit = os.environ.get("CODEX_BIN")
    if explicit:
        if not os.path.isfile(explicit):
            raise CodexBinaryNotFound(f"CODEX_BIN={explicit!r} does not exist")
        return explicit
    found = shutil.which("codex")
    if not found:
        raise CodexBinaryNotFound(
            "codex binary not found on PATH. Install it or set CODEX_BIN."
        )
    return found


@dataclass
class Notification:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ServerRequest:
    """A server-initiated JSON-RPC request awaiting a client response."""

    method: str
    params: dict[str, Any]
    id: Any
    _client: "CodexAppServer"
    _responded: bool = False

    async def respond(self, result: Any) -> None:
        if self._responded:
            return
        self._responded = True
        await self._client._send({"jsonrpc": "2.0", "id": self.id, "result": result})

    async def respond_error(
        self, code: int | str, message: str, data: Any = None
    ) -> None:
        if self._responded:
            return
        self._responded = True
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        await self._client._send({"jsonrpc": "2.0", "id": self.id, "error": err})


class CodexAppServer:
    """Async context manager wrapping a spawned ``codex app-server`` process."""

    def __init__(self, *, binary: str | None = None) -> None:
        self._binary = binary
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[Notification] = asyncio.Queue()
        self._server_requests: asyncio.Queue[ServerRequest] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._closed = False
        self.server_capabilities: dict[str, Any] = {}
        self.server_version: str | None = None

    @classmethod
    @asynccontextmanager
    async def spawn(cls) -> "AsyncIterator[CodexAppServer]":
        client = cls()
        await client._open()
        try:
            yield client
        finally:
            await client.close()

    async def _open(self) -> None:
        binary = self._binary or _resolve_binary()
        self._proc = await asyncio.create_subprocess_exec(
            binary,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name="codex-app-server-reader")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name="codex-app-server-stderr")

    async def initialize(
        self,
        *,
        client_info: dict[str, Any] | None = None,
        experimental_api: bool = True,
    ) -> dict[str, Any]:
        from integrations.codex.schema import METHOD_INITIALIZE, NOTIFICATION_INITIALIZED

        capabilities: dict[str, Any] = {}
        if experimental_api:
            capabilities["experimentalApi"] = True
        params = {
            "clientInfo": client_info or {"name": "spindrel", "title": "Spindrel", "version": "1.0"},
            "capabilities": capabilities,
        }
        result = await self.request(METHOD_INITIALIZE, params)
        self.server_capabilities = dict(result.get("capabilities") or {})
        self.server_version = (
            result.get("userAgent")
            or result.get("serverInfo", {}).get("version")
        )
        # Per the app-server protocol the client must acknowledge with an
        # ``initialized`` notification before issuing further requests.
        await self.notify(NOTIFICATION_INITIALIZED, {})
        return result

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if self._proc is None or self._closed:
            raise RuntimeError("codex app-server client is closed")
        message_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[message_id] = future
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "method": method,
                "params": params or {},
            }
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(message_id, None)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def notifications(self) -> AsyncIterator[Notification]:
        while not self._closed:
            try:
                note = await self._notifications.get()
            except asyncio.CancelledError:
                raise
            yield note

    async def server_requests(self) -> AsyncIterator[ServerRequest]:
        while not self._closed:
            try:
                req = await self._server_requests.get()
            except asyncio.CancelledError:
                raise
            yield req

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("codex app-server stdin is unavailable")
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._send_lock:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        reader = self._proc.stdout
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.warning("codex app-server: discarding non-JSON line: %r", line[:200])
                    continue
                self._dispatch(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("codex app-server reader crashed")
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("codex app-server stream closed"))
            self._pending.clear()

    def _dispatch(self, payload: dict[str, Any]) -> None:
        if "id" in payload and ("result" in payload or "error" in payload):
            try:
                message_id = int(payload["id"])
            except (TypeError, ValueError):
                logger.warning("codex app-server: response with non-int id %r", payload.get("id"))
                return
            future = self._pending.get(message_id)
            if future is None or future.done():
                return
            if "error" in payload:
                err = payload["error"] or {}
                future.set_exception(
                    CodexAppServerError(
                        code=err.get("code", "unknown"),
                        message=err.get("message", "error"),
                        data=err.get("data"),
                    )
                )
            else:
                future.set_result(payload.get("result") or {})
            return
        method = payload.get("method")
        if not isinstance(method, str):
            return
        params = payload.get("params") or {}
        if "id" in payload:
            self._server_requests.put_nowait(
                ServerRequest(
                    method=method,
                    params=params if isinstance(params, dict) else {},
                    id=payload["id"],
                    _client=self,
                )
            )
            return
        self._notifications.put_nowait(
            Notification(
                method=method,
                params=params if isinstance(params, dict) else {},
                raw=payload,
            )
        )

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        reader = self._proc.stderr
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                logger.info("codex app-server stderr: %s", line.decode("utf-8", errors="replace").rstrip())
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is None:
                continue
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
