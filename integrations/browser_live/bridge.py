"""In-memory bridge between tool calls and live browser extensions.

The extension holds the WebSocket open. Tools send JSON-RPC requests keyed
by ``request_id``; the bridge awaits a matching reply on a per-request
Future. Multiple extensions per user are allowed (multi-device) — the
bridge fans out to the most-recently-connected one by default; pass
``connection_id`` to target a specific one.

Deliberately not persisted. A reconnect = a new connection id; any
in-flight request whose Future is still pending gets cancelled.
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
    user_id: str
    send: Any  # async callable: (dict) -> None
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class Bridge:
    def __init__(self) -> None:
        # user_id -> list[_Connection], most-recent last
        self._conns: dict[str, list[_Connection]] = {}
        self._lock = asyncio.Lock()

    async def register(self, user_id: str, send) -> _Connection:
        conn = _Connection(
            connection_id=str(uuid.uuid4()), user_id=user_id, send=send
        )
        async with self._lock:
            self._conns.setdefault(user_id, []).append(conn)
        logger.info("browser_live: connected user=%s conn=%s", user_id, conn.connection_id)
        return conn

    async def unregister(self, conn: _Connection) -> None:
        async with self._lock:
            self._conns.get(conn.user_id, []).remove(conn) if conn in self._conns.get(
                conn.user_id, []
            ) else None
            if not self._conns.get(conn.user_id):
                self._conns.pop(conn.user_id, None)
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
        user_id: str,
        op: str,
        args: dict | None = None,
        *,
        connection_id: str | None = None,
        timeout_ms: int = 15000,
    ) -> dict:
        """Send an RPC to one of the user's connected browsers; await the reply."""
        async with self._lock:
            conns = list(self._conns.get(user_id, []))
        if not conns:
            raise RuntimeError(
                "No paired browser. Install the Spindrel Live Browser "
                "extension and paste your pairing token into its Options page."
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

    def connections_for(self, user_id: str) -> list[dict]:
        return [
            {"connection_id": c.connection_id, "pending": len(c.pending)}
            for c in self._conns.get(user_id, [])
        ]


# Singleton — tools import this.
bridge = Bridge()
