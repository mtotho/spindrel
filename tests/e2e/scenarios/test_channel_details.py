"""Channel detail endpoint tests — deterministic, no LLM dependency.

Creates a single channel via chat (with the e2e bot) then exercises
all GET sub-endpoints on that channel. No existing channels are touched.
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Shared channel — created once, reused across all tests
# ---------------------------------------------------------------------------

_ADMIN = "/api/v1/admin/channels"
_shared_channel_id: str | None = None


async def _get_channel(client: E2EClient) -> str:
    """Return the shared test channel, creating it on first call."""
    global _shared_channel_id
    if _shared_channel_id is None:
        cid = client.new_client_id("e2e-chandetail")
        _shared_channel_id = client.derive_channel_id(cid)
        await client.chat("Channel detail test setup.", client_id=cid)
    return _shared_channel_id


# ---------------------------------------------------------------------------
# Channel sub-endpoint GETs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_effective_tools(client: E2EClient) -> None:
    """GET .../effective-tools returns resolved tool lists."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/effective-tools")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_channel_sections(client: E2EClient) -> None:
    """GET .../sections returns list of conversation sections."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/sections")
    assert resp.status_code == 200
    data = resp.json()
    assert "sections" in data
    assert isinstance(data["sections"], list)


@pytest.mark.asyncio
async def test_channel_compaction_logs(client: E2EClient) -> None:
    """GET .../compaction-logs returns log entries."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/compaction-logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)


@pytest.mark.asyncio
async def test_channel_context_breakdown(client: E2EClient) -> None:
    """GET .../context-breakdown returns context analysis."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/context-breakdown")
    # May return 404 if no active session yet — accept both
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_channel_context_budget(client: E2EClient) -> None:
    """GET .../context-budget returns budget utilization."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/context-budget")
    # May return 404 if no trace events yet
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_channel_context_preview(client: E2EClient) -> None:
    """GET .../context-preview returns system message preview."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/context-preview")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_channel_sessions(client: E2EClient) -> None:
    """GET .../sessions returns session list."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)
    assert len(data["sessions"]) >= 1  # We just created one via chat


@pytest.mark.asyncio
async def test_channel_tasks(client: E2EClient) -> None:
    """GET .../tasks returns task list."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


@pytest.mark.asyncio
async def test_channel_plans(client: E2EClient) -> None:
    """GET .../plans returns plans list."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert "plans" in data
    assert isinstance(data["plans"], list)


@pytest.mark.asyncio
async def test_channel_heartbeat(client: E2EClient) -> None:
    """GET .../heartbeat returns heartbeat config."""
    channel_id = await _get_channel(client)
    resp = await client.get(f"{_ADMIN}/{channel_id}/heartbeat")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_channel_detail_404(client: E2EClient) -> None:
    """GET endpoints with nonexistent channel ID return 404."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"{_ADMIN}/{fake_id}/effective-tools")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_channels_enriched_list(client: E2EClient) -> None:
    """GET /channels-enriched returns paginated enriched list."""
    resp = await client.get(f"{_ADMIN}/channels-enriched")
    # May return 422 if workspace scoping is enforced — accept both
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert "channels" in data
        assert isinstance(data["channels"], list)
