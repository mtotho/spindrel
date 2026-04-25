"""Tests for Slack renderer transport receipt semantics."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from integrations.slack import transport as slack_transport
from integrations.slack.rate_limit import slack_rate_limiter

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    slack_rate_limiter.reset()
    yield
    slack_rate_limiter.reset()


@pytest.fixture
def fake_http():
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self.data: dict | None = {"ok": True, "ts": "1700000000.1"}
            self.status_code = 200
            self.headers: dict[str, str] = {}
            self.raise_exc: Exception | None = None
            self.json_exc: Exception | None = None

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json, "headers": headers})
            if self.raise_exc is not None:
                raise self.raise_exc
            response = MagicMock()
            response.status_code = self.status_code
            response.headers = self.headers
            response.is_success = 200 <= self.status_code < 300
            if self.json_exc is not None:
                response.json = MagicMock(side_effect=self.json_exc)
            else:
                response.json = MagicMock(return_value=self.data or {})
            return response

    fake = FakeHTTP()
    with patch.object(slack_transport, "_http", fake):
        yield fake


async def test_success_returns_data_and_receipt(fake_http):
    result = await slack_transport.call_slack(
        "chat.postMessage", "xoxb-token", {"channel": "C1", "text": "hi"}
    )

    assert result.success is True
    assert result.data["ts"] == "1700000000.1"
    assert result.to_receipt().success is True
    assert result.to_receipt().external_id == "1700000000.1"
    assert fake_http.calls[0]["url"] == "https://slack.com/api/chat.postMessage"
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer xoxb-token"


async def test_429_is_retryable_and_records_retry_after(fake_http):
    fake_http.status_code = 429
    fake_http.headers = {"Retry-After": "2"}

    result = await slack_transport.call_slack("chat.update", "token", {})

    assert result.success is False
    assert result.retryable is True
    assert "Retry-After=2.0s" in result.error


async def test_invalid_auth_is_non_retryable(fake_http):
    fake_http.data = {"ok": False, "error": "invalid_auth"}

    result = await slack_transport.call_slack("chat.postMessage", "token", {})

    assert result.success is False
    assert result.retryable is False
    assert "invalid_auth" in result.error


async def test_5xx_is_retryable(fake_http):
    fake_http.status_code = 500
    fake_http.data = {}

    result = await slack_transport.call_slack("chat.postMessage", "token", {})

    assert result.success is False
    assert result.retryable is True
    assert "HTTP 500" in result.error


async def test_non_json_response_uses_http_status_retryability(fake_http):
    fake_http.status_code = 502
    fake_http.json_exc = ValueError("not json")

    result = await slack_transport.call_slack("chat.postMessage", "token", {})

    assert result.success is False
    assert result.retryable is True
    assert "non-JSON" in result.error


async def test_request_error_is_retryable(fake_http):
    fake_http.raise_exc = httpx.ConnectError("boom")

    result = await slack_transport.call_slack("chat.postMessage", "token", {})

    assert result.success is False
    assert result.retryable is True
    assert "connection error" in result.error
