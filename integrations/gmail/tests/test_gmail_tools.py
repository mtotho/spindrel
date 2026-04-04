"""Tests for Gmail bot tools — trigger_gmail_poll with delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest


@dataclass
class FakeFeedItem:
    title: str = "Test Email"
    body: str = "# Test Email\n\nBody content"
    source_id: str = "gmail:INBOX:100"
    metadata: dict = field(default_factory=dict)
    suggested_path: str = "data/gmail/2026-04-03-test-email.md"
    risk_level: str = "low"


@dataclass
class FakeCycleResult:
    fetched: int = 1
    passed: int = 1
    quarantined: int = 0
    skipped: int = 0
    items: list = field(default_factory=lambda: [FakeFeedItem()])
    errors: list = field(default_factory=list)


@dataclass
class FakeEmptyResult:
    fetched: int = 0
    passed: int = 0
    quarantined: int = 0
    skipped: int = 0
    items: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class FakeFeed:
    def __init__(self, result, raw_items=None):
        self._result = result
        self._raw_items = raw_items
        self._overrides_called_with = None

    async def run_cycle(self):
        return self._result

    async def fetch_items_with_overrides(self, **kwargs):
        self._overrides_called_with = kwargs
        return self._raw_items or []

    async def _run_pipeline(self, raw_items):
        return self._result

    def _disconnect(self):
        pass


class FakeStore:
    def close(self):
        pass


class FakeSettings:
    GMAIL_EMAIL = "test@gmail.com"
    GMAIL_APP_PASSWORD = "test-pass"
    AGENT_BASE_URL = "http://localhost:8000"
    AGENT_API_KEY = "test-key"


class FakeSettingsNoEmail:
    GMAIL_EMAIL = ""
    GMAIL_APP_PASSWORD = ""
    AGENT_BASE_URL = "http://localhost:8000"
    AGENT_API_KEY = ""


# Patches target source modules (tool uses deferred imports)
_P_SETTINGS = "integrations.gmail.config.settings"
_P_CREATE_FEED = "integrations.gmail.factory.create_feed"
_P_RESOLVE = "integrations.gmail.agent_client.resolve_channels_for_binding"
_P_WRITE = "integrations.gmail.agent_client.write_workspace_file"


@pytest.mark.asyncio
async def test_trigger_poll_delivers_to_channels():
    """trigger_gmail_poll should deliver items to bound channels by default."""
    result = FakeCycleResult()

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock, return_value=[
            {"id": "ch-1", "name": "Gmail", "client_id": "gmail:test@gmail.com"},
        ]) as mock_resolve,
        patch(_P_WRITE, new_callable=AsyncMock, return_value=True) as mock_write,
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    assert "1 passed" in output
    assert "Delivered 1 file(s)" in output
    mock_resolve.assert_called_once_with("gmail:test@gmail.com")
    mock_write.assert_called_once_with(
        "ch-1", "data/gmail/2026-04-03-test-email.md", "# Test Email\n\nBody content"
    )


@pytest.mark.asyncio
async def test_trigger_poll_no_delivery_when_disabled():
    """trigger_gmail_poll(deliver=False) should skip delivery."""
    result = FakeCycleResult()

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock) as mock_resolve,
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll(deliver=False)

    assert "1 passed" in output
    assert "Delivered" not in output
    mock_resolve.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_poll_warns_no_channels():
    """trigger_gmail_poll warns when no channels are bound."""
    result = FakeCycleResult()

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock, return_value=[]),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    assert "No channels bound" in output
    assert "not delivered" in output


@pytest.mark.asyncio
async def test_trigger_poll_empty():
    """trigger_gmail_poll with no new emails."""
    result = FakeEmptyResult()

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    assert "0 passed" in output
    assert "No new emails" in output


@pytest.mark.asyncio
async def test_trigger_poll_not_configured():
    """trigger_gmail_poll returns error when Gmail is not configured."""
    with patch(_P_SETTINGS, FakeSettingsNoEmail()):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    assert "not configured" in output


@pytest.mark.asyncio
async def test_trigger_poll_multiple_channels():
    """trigger_gmail_poll delivers to all bound channels."""
    items = [
        FakeFeedItem(title="Email 1", suggested_path="data/gmail/email-1.md"),
        FakeFeedItem(title="Email 2", suggested_path="data/gmail/email-2.md"),
    ]
    result = FakeCycleResult(fetched=2, passed=2, items=items)

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock, return_value=[
            {"id": "ch-1", "client_id": "gmail:test@gmail.com"},
            {"id": "ch-2", "client_id": "gmail:test@gmail.com"},
        ]),
        patch(_P_WRITE, new_callable=AsyncMock, return_value=True) as mock_write,
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    # 2 items × 2 channels = 4 deliveries
    assert mock_write.call_count == 4
    assert "Delivered 4 file(s)" in output


@pytest.mark.asyncio
async def test_trigger_poll_partial_delivery_failure():
    """Some deliveries fail — only count successful ones."""
    result = FakeCycleResult()

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(FakeFeed(result), FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock, return_value=[
            {"id": "ch-1", "client_id": "gmail:test@gmail.com"},
        ]),
        patch(_P_WRITE, new_callable=AsyncMock, return_value=False) as mock_write,
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    mock_write.assert_called_once()
    # Delivery failed, so no "Delivered" line
    assert "Delivered" not in output


# ---------------------------------------------------------------------------
# Override parameter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_poll_with_since_days():
    """since_days param should use fetch_items_with_overrides path."""
    result = FakeCycleResult()
    feed = FakeFeed(result, raw_items=[])

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(feed, FakeStore())),
        patch(_P_RESOLVE, new_callable=AsyncMock, return_value=[
            {"id": "ch-1", "client_id": "gmail:test@gmail.com"},
        ]),
        patch(_P_WRITE, new_callable=AsyncMock, return_value=True),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll(since_days=3)

    assert feed._overrides_called_with is not None
    assert feed._overrides_called_with["since_days"] == 3
    assert "1 passed" in output


@pytest.mark.asyncio
async def test_trigger_poll_with_max_items():
    """max_items param should use override path with correct max."""
    result = FakeEmptyResult()
    feed = FakeFeed(result, raw_items=[])

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(feed, FakeStore())),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll(max_items=10)

    assert feed._overrides_called_with["max_items"] == 10


@pytest.mark.asyncio
async def test_trigger_poll_with_folders():
    """folders param should be parsed into a list and passed to overrides."""
    result = FakeEmptyResult()
    feed = FakeFeed(result, raw_items=[])

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(feed, FakeStore())),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll(folders="INBOX, [Gmail]/Sent Mail")

    assert feed._overrides_called_with["folders"] == ["INBOX", "[Gmail]/Sent Mail"]


@pytest.mark.asyncio
async def test_trigger_poll_no_overrides_uses_run_cycle():
    """Without override params, should use normal run_cycle path."""
    result = FakeEmptyResult()
    feed = FakeFeed(result)

    with (
        patch(_P_SETTINGS, FakeSettings()),
        patch(_P_CREATE_FEED, return_value=(feed, FakeStore())),
    ):
        from integrations.gmail.tools.gmail import trigger_gmail_poll
        output = await trigger_gmail_poll()

    # Should NOT have called overrides path
    assert feed._overrides_called_with is None
    assert "No new emails" in output
