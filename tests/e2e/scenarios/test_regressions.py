"""Regression tests for specific bugs — API-only, no LLM dependency.

Each test documents the bug it catches and the fix that resolved it.
LLM-dependent regression tests live in test_server_behavior.py.
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.client import E2EClient

_TEST_PREFIX = "e2e-regr-"


def _test_bot_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Bug: Bot creation defaults (convention enforcement)
# memory_scheme should default to "workspace-files", not null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_default_memory_scheme(client: E2EClient) -> None:
    """New bots must default to memory_scheme='workspace-files'."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {"id": bot_id, "name": "Defaults", "model": "gemini-2.5-flash-lite"}
        )
        assert created.get("memory_scheme") == "workspace-files", (
            "memory_scheme must default to 'workspace-files'"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Tool persistence: bot tools survive PATCH updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_tools_persist_after_update(client: E2EClient) -> None:
    """Updating a bot field must not wipe its local_tools list."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {
                "id": bot_id,
                "name": "Tools persist",
                "model": "gemini-2.5-flash-lite",
                "local_tools": ["get_current_time"],
            }
        )

        # Update an unrelated field
        result = await client.update_bot(bot_id, {"name": "Tools persist v2"})
        assert "get_current_time" in result.get("local_tools", []), (
            "local_tools must survive unrelated PATCH"
        )
    finally:
        await client.delete_bot(bot_id)
