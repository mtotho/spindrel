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
# Bug: BotUpdateIn missing carapaces field (April 8, 2026)
# Fix: Added carapaces: Optional[list[str]] to BotUpdateIn
# File: app/routers/api_v1_admin/_schemas.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_carapaces_update_not_dropped(client: E2EClient) -> None:
    """PATCH bot with carapaces must persist the value, not silently drop it."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Regr carapaces", "model": "gemini-2.5-flash-lite"}
        )

        # This was the exact operation that failed — UI sends carapaces via PATCH
        result = await client.update_bot(bot_id, {"carapaces": ["orchestrator"]})
        assert result["carapaces"] == ["orchestrator"], (
            "PATCH must accept and return carapaces"
        )

        # And it must persist, not just echo back
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == ["orchestrator"], (
            "Carapaces must persist after PATCH"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Bug: BotOut missing carapaces field (April 8, 2026)
# Fix: Added carapaces: list[str] = [] to BotOut
# File: app/routers/api_v1_admin/_schemas.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_out_has_carapaces(client: E2EClient) -> None:
    """GET /bots/{id} must include carapaces in the response body."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {"id": bot_id, "name": "Regr BotOut", "model": "gemini-2.5-flash-lite"}
        )
        assert "carapaces" in created, "BotOut must include carapaces field"
        assert isinstance(created["carapaces"], list)
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Bug: Updating unrelated fields wipes carapaces (potential regression)
# This tests that PATCH with partial fields doesn't null out other fields.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_partial_update_preserves_carapaces(
    client: E2EClient,
) -> None:
    """Updating bot name must not clear carapaces."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Partial", "model": "gemini-2.5-flash-lite"}
        )
        await client.update_bot(bot_id, {"carapaces": ["e2e-testing"]})

        # Update an unrelated field
        result = await client.update_bot(bot_id, {"name": "Partial Updated"})
        assert result["carapaces"] == ["e2e-testing"], (
            "Unrelated PATCH must not wipe carapaces"
        )
    finally:
        await client.delete_bot(bot_id)


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


# ---------------------------------------------------------------------------
# Capability activation: carapaces can be assigned and removed via API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_capability_activation_roundtrip(
    client: E2EClient,
) -> None:
    """Activating and deactivating a carapace must reflect in bot config."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Cap test", "model": "gemini-2.5-flash-lite"}
        )

        # Activate
        result = await client.update_bot(bot_id, {"carapaces": ["e2e-testing"]})
        assert result["carapaces"] == ["e2e-testing"], "Carapace must activate"

        # Verify persistence
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == ["e2e-testing"], "Activation must persist"

        # Deactivate
        result = await client.update_bot(bot_id, {"carapaces": []})
        assert result["carapaces"] == [], "Carapace must deactivate"

        # Verify deactivation persists
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == [], "Deactivation must persist"
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Multiple capabilities: bot can have several carapaces at once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_multiple_capabilities(client: E2EClient) -> None:
    """Bot should support multiple carapaces simultaneously."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Multi cap", "model": "gemini-2.5-flash-lite"}
        )

        caps = ["e2e-testing", "researcher"]
        result = await client.update_bot(bot_id, {"carapaces": caps})
        assert sorted(result["carapaces"]) == sorted(caps), (
            "Must support multiple carapaces"
        )
    finally:
        await client.delete_bot(bot_id)
