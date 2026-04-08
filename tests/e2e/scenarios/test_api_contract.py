"""API contract tests — deterministic, no LLM dependency.

These verify that admin endpoints return correct shapes, persist fields,
and handle CRUD operations. They catch bugs like the carapaces field
missing from BotUpdateIn/BotOut.
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.client import E2EClient

# Unique suffix to avoid collisions with real bots
_TEST_PREFIX = "e2e-contract-"


def _test_bot_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint(client: E2EClient) -> None:
    """Health endpoint returns expected structure."""
    data = await client.health()
    assert "healthy" in data or "status" in data
    # Admin health has richer fields
    if "healthy" in data:
        assert isinstance(data["healthy"], bool)
        assert "database" in data
        assert "uptime_seconds" in data


# ---------------------------------------------------------------------------
# Bot CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_create_and_get(client: E2EClient) -> None:
    """Create a bot, GET it back, verify fields round-trip."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {
                "id": bot_id,
                "name": "Contract Test Bot",
                "model": "gemini/gemini-2.5-flash",
                "system_prompt": "You are a test bot.",
                "local_tools": ["get_current_time"],
                "tool_retrieval": False,
                "persona": False,
            }
        )
        assert created["id"] == bot_id
        assert created["name"] == "Contract Test Bot"
        assert created["model"] == "gemini/gemini-2.5-flash"
        assert "get_current_time" in created["local_tools"]

        # GET should match
        fetched = await client.get_bot(bot_id)
        assert fetched["id"] == bot_id
        assert fetched["name"] == "Contract Test Bot"
        assert fetched["model"] == "gemini/gemini-2.5-flash"
        assert fetched["tool_retrieval"] is False
    finally:
        await client.delete_bot(bot_id)


@pytest.mark.asyncio
async def test_bot_update_fields(client: E2EClient) -> None:
    """Update bot fields and verify they persist."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {
                "id": bot_id,
                "name": "Update Test",
                "model": "gemini/gemini-2.5-flash",
            }
        )

        updated = await client.update_bot(
            bot_id,
            {
                "name": "Updated Name",
                "system_prompt": "Updated prompt.",
                "local_tools": ["get_current_time", "get_current_local_time"],
                "tool_retrieval": True,
            },
        )
        assert updated["name"] == "Updated Name"
        assert updated["system_prompt"] == "Updated prompt."
        assert set(updated["local_tools"]) >= {
            "get_current_time",
            "get_current_local_time",
        }

        # Verify persistence via GET
        fetched = await client.get_bot(bot_id)
        assert fetched["name"] == "Updated Name"
        assert fetched["system_prompt"] == "Updated prompt."
    finally:
        await client.delete_bot(bot_id)


@pytest.mark.asyncio
async def test_bot_delete(client: E2EClient) -> None:
    """Delete a bot, verify it's gone."""
    bot_id = _test_bot_id()
    await client.create_bot(
        {
            "id": bot_id,
            "name": "Delete Test",
            "model": "gemini/gemini-2.5-flash",
        }
    )
    await client.delete_bot(bot_id)

    # GET should 404
    resp = await client.get(f"/api/v1/admin/bots/{bot_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_bots_shape(client: E2EClient) -> None:
    """List bots returns expected wrapper structure."""
    bots = await client.list_bots()
    assert isinstance(bots, list)
    if bots:
        bot = bots[0]
        assert "id" in bot
        assert "name" in bot
        assert "model" in bot


# ---------------------------------------------------------------------------
# Bot field persistence — regression targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carapaces_persist_through_update(client: E2EClient) -> None:
    """Regression: carapaces field must survive create → update → get cycle.

    Bug: BotUpdateIn was missing carapaces field, so UI saves silently dropped it.
    Bug: BotOut was missing carapaces field, so API responses never returned it.
    """
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {
                "id": bot_id,
                "name": "Carapaces Test",
                "model": "gemini/gemini-2.5-flash",
            }
        )

        # Update with carapaces
        updated = await client.update_bot(
            bot_id, {"carapaces": ["e2e-testing", "orchestrator"]}
        )
        assert "carapaces" in updated, "BotOut must include carapaces field"
        assert set(updated["carapaces"]) == {"e2e-testing", "orchestrator"}

        # Verify persistence
        fetched = await client.get_bot(bot_id)
        assert set(fetched["carapaces"]) == {"e2e-testing", "orchestrator"}

        # Update other fields — carapaces should NOT be wiped
        updated2 = await client.update_bot(bot_id, {"name": "Carapaces Test v2"})
        assert set(updated2["carapaces"]) == {"e2e-testing", "orchestrator"}
    finally:
        await client.delete_bot(bot_id)


@pytest.mark.asyncio
async def test_bot_out_includes_all_expected_fields(client: E2EClient) -> None:
    """BotOut schema must include critical fields that have been missed before."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {
                "id": bot_id,
                "name": "Schema Test",
                "model": "gemini/gemini-2.5-flash",
            }
        )
        # Fields that have been missing from BotOut at various points
        required_fields = [
            "id",
            "name",
            "model",
            "system_prompt",
            "local_tools",
            "tool_retrieval",
            "carapaces",
            "history_mode",
            "memory_scheme",
            "workspace",
        ]
        for field in required_fields:
            assert field in created, f"BotOut missing field: {field}"
    finally:
        await client.delete_bot(bot_id)


@pytest.mark.asyncio
async def test_bot_default_values(client: E2EClient) -> None:
    """Newly created bots get expected defaults."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {
                "id": bot_id,
                "name": "Defaults Test",
                "model": "gemini/gemini-2.5-flash",
            }
        )
        assert created["tool_retrieval"] is True  # default on
        assert created["tool_discovery"] is True  # default on
        assert created["persona"] is False  # default off
        assert created["carapaces"] == []  # default empty
        assert created["local_tools"] == [] or isinstance(
            created["local_tools"], list
        )
        assert created["memory_scheme"] == "workspace-files"  # convention default
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Channel operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels_shape(client: E2EClient) -> None:
    """List channels returns expected wrapper structure."""
    channels = await client.list_channels()
    assert isinstance(channels, list)
    if channels:
        ch = channels[0]
        assert "id" in ch
        assert "bot_id" in ch
        assert "name" in ch


@pytest.mark.asyncio
async def test_channel_created_via_chat(client: E2EClient) -> None:
    """Sending a chat message with a client_id creates a channel.

    Channels don't have a dedicated POST endpoint — they're created
    implicitly through client_id routing. The channel UUID is derived
    from the client_id deterministically.
    """
    cid = client.new_client_id()
    channel_id = client.derive_channel_id(cid)

    resp = await client.chat(
        "Hello, this is a channel creation test.",
        client_id=cid,
    )
    assert resp.session_id  # got a valid session back

    # Channel should now exist in admin API at the derived UUID
    detail = await client.get_channel(channel_id)
    assert detail["channel"]["bot_id"] == client.default_bot_id


@pytest.mark.asyncio
async def test_channel_settings_update(client: E2EClient) -> None:
    """Update channel settings and verify persistence."""
    cid = client.new_client_id()
    channel_id = client.derive_channel_id(cid)
    await client.chat("Settings test init.", client_id=cid)

    # Update settings
    updated = await client.update_channel_settings(
        channel_id,
        {
            "name": "E2E Settings Test",
            "history_mode": "file",
            "max_iterations": 5,
        },
    )
    assert updated["name"] == "E2E Settings Test"
    assert updated["history_mode"] == "file"
    assert updated["max_iterations"] == 5

    # Verify persistence
    settings = await client.get_channel_settings(channel_id)
    assert settings["name"] == "E2E Settings Test"
    assert settings["history_mode"] == "file"


@pytest.mark.asyncio
async def test_channel_carapaces_extra(client: E2EClient) -> None:
    """Channel-level carapaces_extra can be set and retrieved."""
    cid = client.new_client_id()
    channel_id = client.derive_channel_id(cid)
    await client.chat("Carapaces extra test.", client_id=cid)

    updated = await client.update_channel_settings(
        channel_id,
        {"carapaces_extra": ["e2e-testing"]},
    )
    assert "e2e-testing" in updated.get("carapaces_extra", [])

    settings = await client.get_channel_settings(channel_id)
    assert "e2e-testing" in settings.get("carapaces_extra", [])
