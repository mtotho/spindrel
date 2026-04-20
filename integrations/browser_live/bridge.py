"""In-memory bridge between tool calls and live browser extensions.

The extension holds the WebSocket open. Tools send JSON-RPC requests keyed
by ``request_id``; the bridge awaits a matching reply on a per-request
Future. Multiple paired browsers (e.g. desktop + laptop) are supported —
the bridge fans out to the most-recently-connected one by default; pass
``connection_id`` to target a specific one.

Bridge state is process-local. Multi-worker deployments need an external
broker (Redis pub/sub keyed by connection_id) to route replies back to
the right worker — out of scope for this sketch; single-worker uvicorn
is fine.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _Connection:
    connection_id: str
    label: str
    send: Any  # async callable: (dict) -> None
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class Bridge:
    def __init__(self) -> None:
        self._conns: list[_Connection] = []  # most-recent last
        self._lock = asyncio.Lock()

    async def register(self, send, *, label: str = "browser") -> _Connection:
        conn = _Connection(connection_id=str(uuid.uuid4()), label=label, send=send)
        async with self._lock:
            self._conns.append(conn)
        logger.info("browser_live: connected conn=%s label=%s", conn.connection_id, label)
        return conn

    async def unregister(self, conn: _Connection) -> None:
        async with self._lock:
            if conn in self._conns:
                self._conns.remove(conn)
        for fut in list(conn.pending.values()):
            if not fut.done():
                fut.cancel()
        conn.pending.clear()
        logger.info("browser_live: disconnected conn=%s", conn.connection_id)

    def handle_reply(self, conn: _Connection, payload: dict) -> None:
        rid = payload.get("request_id")
        fut = conn.pending.pop(rid, None) if rid else None
        if fut and not fut.done():
            fut.set_result(payload)

    async def request(
        self,
        op: str,
        args: dict | None = None,
        *,
        connection_id: str | None = None,
        timeout_ms: int = 15000,
    ) -> dict:
        """Send an RPC to a paired browser; await the reply.

        With no ``connection_id`` the most-recently-connected browser
        services the call. Raises if no browser is paired or if the
        request times out.
        """
        async with self._lock:
            conns = list(self._conns)
        if not conns:
            raise RuntimeError(
                "No paired browser. Install the Spindrel Live Browser "
                "extension and paste the pairing token from the admin UI."
            )
        conn = (
            next((c for c in conns if c.connection_id == connection_id), None)
            if connection_id
            else conns[-1]
        )
        if conn is None:
            raise RuntimeError(f"connection_id {connection_id!r} not paired")

        rid = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        conn.pending[rid] = fut
        await conn.send({"request_id": rid, "op": op, "args": args or {}})
        try:
            reply = await asyncio.wait_for(fut, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            conn.pending.pop(rid, None)
            raise RuntimeError(f"browser_live: {op} timed out after {timeout_ms}ms")
        if reply.get("error"):
            raise RuntimeError(f"browser_live: {reply['error']}")
        return reply.get("result") or {}

    def list_connections(self) -> list[dict]:
        return [
            {
                "connection_id": c.connection_id,
                "label": c.label,
                "pending": len(c.pending),
            }
            for c in self._conns
        ]


# Singleton — tools and the router import this.
bridge = Bridge()
