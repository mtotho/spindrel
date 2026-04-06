"""Dispatcher protocol and registry for task result delivery.

Core dispatchers (none, webhook, internal) are registered here.
Integration-specific dispatchers register themselves by importing this module
and calling register() — e.g. integrations/slack/dispatcher.py.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


@runtime_checkable
class Dispatcher(Protocol):
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None: ...
    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool: ...


_registry: dict[str, Dispatcher] = {}


def register(dispatch_type: str, dispatcher: Dispatcher) -> None:
    _registry[dispatch_type] = dispatcher


def get(dispatch_type: str | None) -> Dispatcher:
    return _registry.get(dispatch_type or "none", _registry.get("none", _NoneDispatcher()))


# ---------------------------------------------------------------------------
# Core dispatchers (always available, no external service required)
# ---------------------------------------------------------------------------

class _NoneDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None:
        pass  # result stored in DB only; caller polls get_task

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool:
        return False


class _WebhookDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None:
        cfg = task.dispatch_config or {}
        url = cfg.get("url")
        if not url:
            logger.warning("WebhookDispatcher: missing url for task %s", task.id)
            return
        # SSRF protection with DNS pinning: resolve once, connect to pinned IP
        try:
            from app.utils.url_validation import resolve_and_pin, pin_url
            _orig, pinned_ip = resolve_and_pin(url)
        except ValueError as exc:
            logger.warning("WebhookDispatcher: SSRF blocked for task %s: %s", task.id, exc)
            return
        from app.security.audit import log_outbound_request
        log_outbound_request(url=url, method="POST", tool_name="webhook_dispatch",
                             bot_id=task.bot_id)
        try:
            pinned, extra_headers = pin_url(url, pinned_ip)
            r = await _http.post(
                pinned, json={"task_id": str(task.id), "result": result},
                headers=extra_headers,
            )
            r.raise_for_status()
        except Exception:
            logger.exception("WebhookDispatcher.deliver failed for task %s", task.id)

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool:
        return False


class _InternalDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None:
        """Persist result as a user message in a parent session so the parent bot can process it."""
        cfg = task.dispatch_config or {}
        session_id_str = cfg.get("session_id")
        if not session_id_str:
            logger.warning("InternalDispatcher: missing session_id for task %s", task.id)
            return
        try:
            from app.db.engine import async_session
            from app.db.models import Message, Session
            session_id = uuid.UUID(session_id_str)
            async with async_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    logger.error(
                        "InternalDispatcher: session %s not found for task %s", session_id, task.id
                    )
                    return
                db.add(Message(
                    session_id=session_id,
                    role="user",
                    content=f"[Task {task.id} completed]\n\n{result}",
                    created_at=datetime.now(timezone.utc),
                ))
                await db.commit()
                # Notify channel event subscribers
                if session.channel_id:
                    from app.services.channel_events import publish as _publish_event
                    _publish_event(session.channel_id, "new_message")
        except Exception:
            logger.exception("InternalDispatcher.deliver failed for task %s", task.id)

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool:
        return False


# Register core dispatchers at module import time
register("none", _NoneDispatcher())
register("webhook", _WebhookDispatcher())
register("internal", _InternalDispatcher())
