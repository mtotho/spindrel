"""Tier 2: Workspace & memory tests — verify file ops, multi-tool, and memory persistence.

These test the workspace-files memory scheme: file create/read/edit, memory
write/recall, and cross-turn file persistence.  They require the e2e bot to
have `memory_scheme: "workspace-files"` (auto-enrolls file, search_memory,
get_memory_file tools).

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
    """Short unique token for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# Explicit instruction prefix so small models use the right tool name.
_FILE_TOOL_HINT = (
    'You have a tool called "file" that accepts an "operation" parameter '
    '(one of: read, write, append, edit, list, delete, mkdir, move, grep, glob) '
    'and a "path" parameter. '
)


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_write_and_read(client: E2EClient) -> None:
    """Bot should write a file then read it back, both via the file tool."""
    cid = client.new_client_id()
    token = _unique("filetest")
    filename = f"test-{token}.txt"

    result = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="create", path="{filename}", '
        f'content="The secret value is {token}". '
        f'Then call "file" with operation="read", path="{filename}" '
        f'and tell me what it says.',
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert_tool_called(result.tools_used, ["file"])
    assert_contains_any(result.response_text, [token])


@pytest.mark.asyncio
async def test_file_edit_operation(client: E2EClient) -> None:
    """Bot should write a file, then edit it with find/replace."""
    cid = client.new_client_id()
    token = _unique("edit")
    filename = f"test-{token}.txt"

    # Turn 1: create file
    await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="create", path="{filename}", '
        f'content="color is red". Confirm you wrote it.',
        client_id=cid,
    )

    # Turn 2: edit and read back
    result = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="edit", path="{filename}", '
        f'find="red", replace="blue". '
        f'Then call "file" with operation="read", path="{filename}" '
        f'and tell me what it says.',
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert_tool_called(result.tools_used, ["file"])
    assert_contains_any(result.response_text, ["blue"])


# ---------------------------------------------------------------------------
# Multi-tool dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_tool_file_and_time(client: E2EClient) -> None:
    """Bot should use both a time tool AND the file tool in one turn."""
    cid = client.new_client_id()
    token = _unique("multi")
    filename = f"test-{token}.txt"

    result = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Do exactly these two steps in order:\n'
        f'Step 1: Call the "get_current_time" tool to get the current UTC time.\n'
        f'Step 2: Call the "file" tool with operation="create", '
        f'path="{filename}", and the time as content.\n'
        f'You MUST call both tools. Tell me the time you wrote.',
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"

    time_tools = {"get_current_time", "get_current_local_time"}
    assert any(t in time_tools for t in result.tools_used), (
        f"Should have used a time tool but used: {result.tools_used}"
    )
    assert "file" in result.tools_used, (
        f"Should have used the file tool but used: {result.tools_used}"
    )


# ---------------------------------------------------------------------------
# File persistence across turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_persistence_across_turns(client: E2EClient) -> None:
    """A file written in turn 1 should be readable in turn 2 (same channel)."""
    cid = client.new_client_id()
    token = _unique("persist")
    filename = f"test-{token}.txt"

    # Turn 1: write file
    r1 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="create", path="{filename}", '
        f'content="persistence-check-{token}". Confirm you wrote it.',
        client_id=cid,
    )
    assert not r1.error_events, f"Turn 1 errors: {r1.error_events}"
    assert_tool_called(r1.tools_used, ["file"])

    # Turn 2: read it back (same channel, so same workspace)
    r2 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="read", path="{filename}" '
        f'and tell me exactly what the file contains.',
        client_id=cid,
    )
    assert not r2.error_events, f"Turn 2 errors: {r2.error_events}"
    assert_tool_called(r2.tools_used, ["file"])
    assert_contains_any(r2.response_text, [f"persistence-check-{token}"])


# ---------------------------------------------------------------------------
# Memory round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_write_and_recall(client: E2EClient) -> None:
    """Bot should save a fact to memory and recall it in a later turn."""
    cid = client.new_client_id()
    token = _unique("mem")
    fact = f"The launch code is {token}"

    # Turn 1: ask bot to remember
    r1 = await client.chat_stream(
        f'{_FILE_TOOL_HINT}'
        f'Call the "file" tool with operation="append", '
        f'path="memory/MEMORY.md", content="{fact}". '
        f'Confirm you saved it.',
        client_id=cid,
    )
    assert not r1.error_events, f"Turn 1 errors: {r1.error_events}"
    assert_tool_called(r1.tools_used, ["file"])

    # Turn 2: ask bot to recall — it should have it in conversation context
    # or via memory tools
    r2 = await client.chat_stream(
        "What was the launch code I asked you to remember?",
        client_id=cid,
    )
    assert not r2.error_events, f"Turn 2 errors: {r2.error_events}"
    assert_contains_any(r2.response_text, [token])


# ---------------------------------------------------------------------------
# Memory tool dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_memory_file(client: E2EClient) -> None:
    """Bot should use get_memory_file to read its MEMORY.md."""
    cid = client.new_client_id()

    result = await client.chat_stream(
        'Call the "get_memory_file" tool with name="MEMORY". '
        "Tell me what it contains.",
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert_tool_called(result.tools_used, ["get_memory_file"])
    # Bot should respond with something — even if MEMORY.md is empty/template
    assert len(result.response_text.strip()) > 0


@pytest.mark.asyncio
async def test_search_memory(client: E2EClient) -> None:
    """Bot should use search_memory and return results from the memory index."""
    cid = client.new_client_id()

    # Search for something that should exist in the memory index
    # (MEMORY.md is always present after bootstrap). We just verify the tool
    # dispatches and returns content — index freshness for newly-written
    # content is not guaranteed due to indexing cooldown.
    result = await client.chat_stream(
        'Call the "search_memory" tool with query="memory". '
        "Tell me what you found.",
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert_tool_called(result.tools_used, ["search_memory"])
    assert len(result.response_text.strip()) > 0, "Should return search results"
