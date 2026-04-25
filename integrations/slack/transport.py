"""Slack Web API transport for renderer delivery.

The renderer and streaming layer need receipt-shaped Slack calls: callers
must know whether a failure is retryable and, on success, read Slack's raw
response data for message timestamps.
"""
from __future__ import annotations

import logging

import httpx

from integrations.sdk import DeliveryReceipt
from integrations.slack.rate_limit import slack_rate_limiter

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


class SlackCallResult:
    """Success/failure carrier for renderer Slack Web API calls."""

    __slots__ = ("success", "data", "error", "retryable")

    def __init__(
        self,
        success: bool,
        *,
        data: dict | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.success = success
        self.data = data
        self.error = error
        self.retryable = retryable

    @classmethod
    def ok(cls, data: dict) -> "SlackCallResult":
        return cls(True, data=data)

    @classmethod
    def failed(cls, error: str, *, retryable: bool) -> "SlackCallResult":
        return cls(False, error=error, retryable=retryable)

    def to_receipt(self) -> DeliveryReceipt:
        if self.success:
            return DeliveryReceipt.ok(
                external_id=(self.data or {}).get("ts") if self.data else None,
            )
        return DeliveryReceipt.failed(self.error or "unknown", retryable=self.retryable)


async def call_slack(method: str, token: str, body: dict) -> SlackCallResult:
    """Make a single rate-limited Slack Web API call."""
    await slack_rate_limiter.acquire(method)
    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = await _http.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("Slack transport: %s connection error: %s", method, exc)
        return SlackCallResult.failed(f"connection error: {exc}", retryable=True)

    if response.status_code == 429:
        retry_after = float(response.headers.get("Retry-After", "1"))
        slack_rate_limiter.record_429(method, retry_after)
        return SlackCallResult.failed(
            f"slack 429 (Retry-After={retry_after}s)", retryable=True,
        )

    try:
        data = response.json()
    except ValueError:
        return SlackCallResult.failed(
            f"slack {method} returned non-JSON status={response.status_code}",
            retryable=response.status_code >= 500,
        )

    if not response.is_success:
        return SlackCallResult.failed(
            f"slack {method} HTTP {response.status_code}",
            retryable=response.status_code >= 500,
        )

    if not data.get("ok"):
        error = data.get("error", "unknown")
        non_retryable = {
            "invalid_auth", "not_authed", "channel_not_found",
            "is_archived", "msg_too_long", "no_text",
        }
        retryable = error not in non_retryable
        return SlackCallResult.failed(
            f"slack {method} error: {error}", retryable=retryable,
        )

    return SlackCallResult.ok(data)
