"""Shared in-process Future registry for agent rendezvous points.

Client-side tools and approval requests both use the same shape: create a
Future, hand its id to an external caller, then resolve or expire it later.
This module owns that lifecycle so cleanup and edge-case behavior stay in one
place while the older client/approval wrapper modules keep their public names.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import MutableMapping
from typing import Generic, TypeVar

T = TypeVar("T")


class PendingRegistry(Generic[T]):
    def __init__(self, *, label: str, logger: logging.Logger) -> None:
        self.label = label
        self.logger = logger
        self.pending: dict[str, asyncio.Future[T]] = {}

    def bind(self, pending: MutableMapping[str, asyncio.Future[T]]) -> None:
        """Replace the backing store.

        Compatibility wrappers use this when tests monkeypatch their historical
        ``_pending`` dict. Production code never needs to call it.
        """
        self.pending = pending  # type: ignore[assignment]

    def create(self, request_id: str) -> asyncio.Future[T]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        self.pending[request_id] = future
        self.logger.debug(
            "Created %s pending %s (%d active)",
            self.label,
            request_id,
            len(self.pending),
        )
        return future

    def resolve(self, request_id: str, result: T) -> bool:
        future = self.pending.pop(request_id, None)
        if future is None:
            self.logger.warning("No pending %s for %s", self.label, request_id)
            return False
        if future.done():
            self.logger.warning("%s %s already resolved", self.label, request_id)
            return False
        future.set_result(result)
        self.logger.debug("Resolved %s %s", self.label, request_id)
        return True

    def cancel(self, request_id: str, result: T) -> bool:
        future = self.pending.pop(request_id, None)
        if future is None:
            return False
        if future.done():
            return False
        future.set_result(result)
        self.logger.debug("Cancelled %s %s", self.label, request_id)
        return True

    def discard(self, request_id: str) -> bool:
        return self.pending.pop(request_id, None) is not None

    def count(self) -> int:
        return len(self.pending)

    def clear(self) -> None:
        self.pending.clear()
