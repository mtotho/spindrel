"""Minimal server-side Slack web-API helper for tools.

The renderer owns its own rate-limited call path (``_call_slack``) because
it carries DeliveryReceipt semantics. Tools don't need receipts — they
need a plain request/response. This helper shares the renderer's
``slack_rate_limiter`` so per-method bucket limits stay global (a tool
that pins 10 messages is competing with the renderer's ``chat.postMessage``
stream for the same 1-req/sec slot).

Tool authors call ``slack_call("pins.add", body={"channel": "...", "timestamp": "..."})``
and get back the parsed JSON dict. Errors raise ``SlackApiError`` with
``message`` + ``status_code`` + ``data``.

Channel resolution — use ``resolve_slack_channel_id(channel_id)`` to turn
the server-side channel UUID (from ``current_channel_id``) into a Slack
``C...`` id. Raises ``SlackApiError`` for non-Slack channels so the
calling tool returns a clean error to the agent.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from integrations.slack.config import settings
from integrations.slack.rate_limit import slack_rate_limiter

logger = logging.getLogger(__name__)


class SlackApiError(Exception):
    """Raised when a Slack web-API call fails or the channel can't be resolved."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        data: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.data = data or {}


_SLACK_API_ROOT = "https://slack.com/api"


async def slack_call(
    method: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict:
    """Call a Slack web-API method, rate-limited + error-normalized.

    ``body`` is sent as JSON; Slack accepts JSON for the methods used by
    our tools (pins.add, bookmarks.add, chat.scheduleMessage, …). Methods
    that require form encoding (views.open with trigger_id on older
    Bolt flows) are not in the tool surface.

    Raises ``SlackApiError`` on non-200 HTTP, 429, or ``ok=false``. The
    agent-facing tool catches and returns a JSON error string.
    """
    bot_token = token or settings.SLACK_BOT_TOKEN
    if not bot_token:
        raise SlackApiError("slack bot token is not configured")

    await slack_rate_limiter.acquire(method)
    url = f"{_SLACK_API_ROOT}/{method}"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body or {}, headers=headers)
    except httpx.RequestError as exc:
        raise SlackApiError(f"connection error: {exc}") from exc

    if response.status_code == 429:
        retry_after = float(response.headers.get("Retry-After", "1"))
        slack_rate_limiter.record_429(method, retry_after)
        raise SlackApiError(
            f"slack {method} 429 (retry after {retry_after:.1f}s)",
            status_code=429,
        )

    try:
        data = response.json()
    except ValueError:
        raise SlackApiError(
            f"slack {method} returned non-JSON (HTTP {response.status_code})",
            status_code=response.status_code,
        )

    if not response.is_success:
        raise SlackApiError(
            f"slack {method} HTTP {response.status_code}: {data.get('error', 'unknown')}",
            status_code=response.status_code,
            data=data,
        )
    if not data.get("ok"):
        raise SlackApiError(
            f"slack {method}: {data.get('error', 'unknown error')}",
            status_code=response.status_code,
            data=data,
        )
    return data


async def resolve_slack_channel_id(channel_id: uuid.UUID) -> str:
    """Return the ``C...`` Slack channel id for a server-side channel UUID.

    Reads the ``Channel.client_id``. Non-Slack channels raise
    ``SlackApiError`` — the tool is being called from a channel that
    doesn't map to a Slack conversation, so there's nothing sensible to
    do.
    """
    from integrations.sdk import Channel, async_session

    async with async_session() as db:
        row = (
            await db.execute(select(Channel).where(Channel.id == channel_id))
        ).scalar_one_or_none()
    if row is None:
        raise SlackApiError(f"channel {channel_id} not found")
    client_id = row.client_id or ""
    if not client_id.startswith("slack:"):
        raise SlackApiError(
            f"channel {channel_id} is not a Slack channel (client_id={client_id!r})"
        )
    return client_id.split(":", 1)[1]
