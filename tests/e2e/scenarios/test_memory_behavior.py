"""Tier 2: Memory system behavior — cross-channel recall, session persistence, API search.

Tests the memory system end-to-end: LLM writes to memory, then we verify
recall works across channels (memory is per-bot, not per-channel), across
sessions, and via the REST search API.

Tier 2 — server behavior (model via E2E_DEFAULT_MODEL).
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.assertions import (
    assert_contains_any,
    assert_tool_called,
)
from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


_FILE_TOOL_HINT = (
    'You have a tool called "file" that accepts an "operation" parameter '
    '(one of: read, write, append, edit, list, delete, mkdir, move) '
    'and a "path" parameter. '
)


# ---------------------------------------------------------------------------
# Cross-channel memory recall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_recall_cross_channel(client: E2EClient) -> None:
    """Memory written in channel A should be readable in channel B (same bot).

    Workspace memory is per-bot, not per-channel — so a fact stored in one
    conversation should be accessible from another.
    """
    token = _unique("xchan")
    cid_a = client.new_client_id()
    cid_b = client.new_client_id()

    # Channel A: write a fact to memory
    r1 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="write", '
        f'path="memory/e2e-cross-channel-{token}.md", '
        f'content="Cross-channel secret: {token}". '
        f'Confirm you wrote it.',
        client_id=cid_a,
    )
    assert not r1.error_events, f"Write errors: {r1.error_events}"
    assert_tool_called(r1.tools_used, ["file"])

    # Channel B: read the same file back
    r2 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="read", '
        f'path="memory/e2e-cross-channel-{token}.md" '
        f'and tell me what it contains.',
        client_id=cid_b,
    )
    assert not r2.error_events, f"Read errors: {r2.error_events}"
    assert_tool_called(r2.tools_used, ["file"])
    assert_contains_any(r2.response_text, [token])


# ---------------------------------------------------------------------------
# Memory persistence across sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(client: E2EClient) -> None:
    """Memory file written in one session persists when accessed from a new session.

    Each client_id creates a fresh channel (new session), but the bot's
    workspace memory directory persists across sessions.
    """
    token = _unique("persist")
    filename = f"memory/e2e-persist-{token}.md"
    cid1 = client.new_client_id()

    # Session 1: write memory file
    r1 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="write", '
        f'path="{filename}", '
        f'content="Session persistence value: {token}". '
        f'Confirm you wrote it.',
        client_id=cid1,
    )
    assert not r1.error_events
    assert_tool_called(r1.tools_used, ["file"])

    # Session 2: fresh channel, read the same file
    cid2 = client.new_client_id()
    r2 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="read", '
        f'path="{filename}" '
        f'and tell me what the file contains.',
        client_id=cid2,
    )
    assert not r2.error_events
    assert_tool_called(r2.tools_used, ["file"])
    assert_contains_any(r2.response_text, [token])


# ---------------------------------------------------------------------------
# Memory search via REST API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_api_finds_bot_content(client: E2EClient) -> None:
    """REST search/memory API returns real results for the e2e bot.

    The e2e bot has workspace-files memory scheme with at least MEMORY.md
    bootstrapped. Searching for "memory" should return indexed content.
    """
    resp = await client.post(
        "/api/v1/search/memory",
        json={
            "query": "memory",
            "bot_ids": [client.default_bot_id],
            "top_k": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    # All results should be from the e2e bot
    for item in data["results"]:
        assert item["bot_id"] == client.default_bot_id
        assert len(item["content"]) > 0, "Search result content should be non-empty"
        assert item["score"] > 0, "Search result score should be positive"


@pytest.mark.asyncio
async def test_memory_search_diagnostic_has_indexed_chunks(client: E2EClient) -> None:
    """Memory search diagnostic for e2e bot shows indexed chunks exist."""
    resp = await client.get(
        f"/api/v1/admin/diagnostics/memory-search/{client.default_bot_id}",
        params={"query": "memory"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_id"] == client.default_bot_id
    assert isinstance(data["result_count"], int)
    diag = data["diagnostics"]
    assert diag["total_chunks_in_table"] > 0, "No chunks in filesystem_chunks table"
    assert diag["matching_bot_id"] > 0, (
        f"No chunks matching bot_id={client.default_bot_id}"
    )


@pytest.mark.asyncio
async def test_memory_write_then_read_via_admin_api(client: E2EClient) -> None:
    """Write a memory file via LLM, then verify it exists via workspace admin API.

    This is a round-trip: LLM tool writes a file, then we directly call the
    workspace file API to confirm the file actually landed on disk.
    """
    token = _unique("apicheck")
    filename = f"e2e-api-verify-{token}.md"
    cid = client.new_client_id()

    # LLM writes the file
    r1 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="write", '
        f'path="memory/{filename}", '
        f'content="API verification token: {token}". '
        f'Confirm you wrote it.',
        client_id=cid,
    )
    assert not r1.error_events
    assert_tool_called(r1.tools_used, ["file"])

    # Now read via admin workspace API — get the bot's shared workspace ID
    bot = await client.get_bot(client.default_bot_id)
    workspace_id = bot.get("shared_workspace_id")
    if not workspace_id:
        pytest.skip("Bot has no shared_workspace_id — can't verify via API")

    # In a shared workspace, the bot's files live under bots/{bot_id}/
    ws_path = f"bots/{client.default_bot_id}/memory/{filename}"
    resp = await client.get(
        f"/api/v1/workspaces/{workspace_id}/files/content",
        params={"path": ws_path},
    )
    assert resp.status_code == 200, (
        f"File not found via API at {ws_path}: {resp.status_code} {resp.text[:200]}"
    )
    content = resp.text
    assert token in content, (
        f"Expected token {token} in file content but got: {content[:200]}"
    )


# ---------------------------------------------------------------------------
# Memory hygiene endpoints (admin API — no LLM, just API contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_hygiene_status_shape(client: E2EClient) -> None:
    """GET /bots/{bot_id}/memory-hygiene returns config + run times."""
    resp = await client.get(
        f"/api/v1/admin/bots/{client.default_bot_id}/memory-hygiene"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)


@pytest.mark.asyncio
async def test_memory_hygiene_runs_shape(client: E2EClient) -> None:
    """GET /bots/{bot_id}/memory-hygiene/runs returns run history."""
    resp = await client.get(
        f"/api/v1/admin/bots/{client.default_bot_id}/memory-hygiene/runs"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)
    assert "total" in data
    assert isinstance(data["total"], int)


# ---------------------------------------------------------------------------
# Memory file listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_file_listing_includes_memory_md(client: E2EClient) -> None:
    """Bot can list memory directory and it includes MEMORY.md."""
    cid = client.new_client_id()

    result = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="list", path="memory/". '
        f'Tell me what files are in the memory directory.',
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert_tool_called(result.tools_used, ["file"])
    # Must mention MEMORY.md specifically (bootstrapped for workspace-files bots)
    assert_contains_any(result.response_text, ["MEMORY.md"])
