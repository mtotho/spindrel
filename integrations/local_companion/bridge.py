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
    target_id: str
    label: str
    hostname: str
    platform: str
    capabilities: list[str]
    send: Any
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class Bridge:
    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        send,
        *,
        target_id: str,
        label: str,
        hostname: str,
        platform: str,
        capabilities: list[str],
    ) -> _Connection:
        conn = _Connection(
            connection_id=str(uuid.uuid4()),
            target_id=target_id,
            label=label,
            hostname=hostname,
            platform=platform,
            capabilities=list(capabilities),
            send=send,
        )
        async with self._lock:
            old = self._conns.get(target_id)
            self._conns[target_id] = conn
        if old is not None:
            await self.unregister(old)
        logger.info("local_companion: connected target=%s label=%s", target_id, label)
        return conn

    async def unregister(self, conn: _Connection) -> None:
        async with self._lock:
            current = self._conns.get(conn.target_id)
            if current is conn:
                self._conns.pop(conn.target_id, None)
        for fut in list(conn.pending.values()):
            if not fut.done():
                fut.cancel()
        conn.pending.clear()
        logger.info("local_companion: disconnected target=%s", conn.target_id)

    async def unregister_target(self, target_id: str) -> None:
        conn = self.get_target_connection(target_id)
        if conn is not None:
            await self.unregister(conn)

    def get_target_connection(self, target_id: str) -> _Connection | None:
        return self._conns.get(target_id)

    def handle_reply(self, conn: _Connection, payload: dict[str, Any]) -> None:
        rid = payload.get("request_id")
        fut = conn.pending.pop(rid, None) if rid else None
        if fut is not None and not fut.done():
            fut.set_result(payload)

    async def request(
        self,
        target_id: str,
        op: str,
        args: dict | None = None,
        *,
        timeout_ms: int = 30000,
    ) -> dict[str, Any]:
        conn = self.get_target_connection(target_id)
        if conn is None:
            raise RuntimeError(f"Machine target {target_id!r} is not connected.")

        rid = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        conn.pending[rid] = fut
        await conn.send({"request_id": rid, "op": op, "args": args or {}})
        try:
            reply = await asyncio.wait_for(fut, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            conn.pending.pop(rid, None)
            raise RuntimeError(f"local_companion: {op} timed out after {timeout_ms}ms")
        if reply.get("error"):
            raise RuntimeError(str(reply["error"]))
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def list_targets(self) -> list[dict[str, Any]]:
        return [
            {
                "target_id": conn.target_id,
                "connection_id": conn.connection_id,
                "label": conn.label,
                "hostname": conn.hostname,
                "platform": conn.platform,
                "capabilities": list(conn.capabilities),
                "pending": len(conn.pending),
            }
            for conn in self._conns.values()
        ]


bridge = Bridge()
