"""Multi-bot channel tests — bot member CRUD and multi-bot routing.

Tier 1 tests (API contract): no LLM, verify bot member CRUD operations,
channel creation with member_bot_ids, validation errors, config persistence.

Tier 2 tests (server behavior): use LLM (via E2E_DEFAULT_MODEL, preferably
ollama) to verify @-mention routing, identity isolation, and context sharing
in multi-bot channels.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.client import E2EClient


_TEST_PREFIX = "e2e-multibot-"


def _test_bot_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


# ===========================================================================
# Tier 1: API contract — no LLM
# ===========================================================================


@pytest.mark.asyncio
async def test_create_channel_with_member_bots(client: E2EClient) -> None:
    """POST /api/v1/channels with member_bot_ids populates member_bots."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Member Bot",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        ch = await client.create_channel({
            "bot_id": client.default_bot_id,
            "member_bot_ids": [member_id],
        })
        channel_id = ch["id"]

        assert "member_bots" in ch, "ChannelOut must include member_bots"
        member_ids = [m["bot_id"] for m in ch["member_bots"]]
        assert member_id in member_ids, f"Member {member_id} not in {member_ids}"

        # Cleanup channel
        await client.delete_channel(channel_id)
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_add_and_list_bot_members(client: E2EClient) -> None:
    """Add a bot member, list members, verify it appears."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "List Test Member",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        # Create channel via chat to get a channel_id
        cid = client.new_client_id()
        await client.chat("Init channel for member test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        # Add member
        added = await client.add_bot_member(channel_id, member_id)
        assert added["bot_id"] == member_id
        assert added["bot_name"] == "List Test Member"
        assert "id" in added
        assert "config" in added

        # List members
        members = await client.list_bot_members(channel_id)
        assert len(members) >= 1
        assert any(m["bot_id"] == member_id for m in members)
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_remove_bot_member(client: E2EClient) -> None:
    """Add then remove a bot member, verify it's gone."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Remove Test Member",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for remove test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)
        await client.remove_bot_member(channel_id, member_id)

        members = await client.list_bot_members(channel_id)
        assert not any(m["bot_id"] == member_id for m in members)
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_add_duplicate_member_returns_409(client: E2EClient) -> None:
    """Adding the same bot member twice returns 409 Conflict."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Dup Test",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for dup test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # Second add should fail
        resp = await client.post(
            f"/api/v1/channels/{channel_id}/bot-members",
            json={"bot_id": member_id},
        )
        assert resp.status_code == 409
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_add_primary_bot_as_member_returns_400(client: E2EClient) -> None:
    """Adding the channel's primary bot as a member returns 400."""
    cid = client.new_client_id()
    await client.chat("Init channel for primary test.", client_id=cid)
    channel_id = client.derive_channel_id(cid)

    resp = await client.post(
        f"/api/v1/channels/{channel_id}/bot-members",
        json={"bot_id": client.default_bot_id},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_unknown_bot_returns_400(client: E2EClient) -> None:
    """Adding a non-existent bot as member returns 400."""
    cid = client.new_client_id()
    await client.chat("Init channel for unknown bot test.", client_id=cid)
    channel_id = client.derive_channel_id(cid)

    resp = await client.post(
        f"/api/v1/channels/{channel_id}/bot-members",
        json={"bot_id": "totally-fake-bot-does-not-exist"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_remove_nonexistent_member_returns_404(client: E2EClient) -> None:
    """Removing a bot that isn't a member returns 404."""
    cid = client.new_client_id()
    await client.chat("Init channel for 404 test.", client_id=cid)
    channel_id = client.derive_channel_id(cid)

    resp = await client.delete(
        f"/api/v1/channels/{channel_id}/bot-members/nonexistent-bot"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_member_config(client: E2EClient) -> None:
    """Update per-member config and verify persistence."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Config Test Member",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for config test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # Update config
        updated = await client.update_bot_member_config(
            channel_id, member_id,
            {"response_style": "brief", "max_rounds": 3, "priority": 1},
        )
        assert updated["config"]["response_style"] == "brief"
        assert updated["config"]["max_rounds"] == 3
        assert updated["config"]["priority"] == 1

        # Verify persistence via list
        members = await client.list_bot_members(channel_id)
        member = next(m for m in members if m["bot_id"] == member_id)
        assert member["config"]["response_style"] == "brief"
        assert member["config"]["max_rounds"] == 3
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_update_member_config_null_removes_key(client: E2EClient) -> None:
    """Setting a config field to null removes it."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Null Config Test",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for null config test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # Set a value
        await client.update_bot_member_config(
            channel_id, member_id, {"response_style": "detailed"},
        )

        # Remove it with null
        updated = await client.update_bot_member_config(
            channel_id, member_id, {"response_style": None},
        )
        assert "response_style" not in updated["config"]
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_update_member_config_invalid_style_returns_422(client: E2EClient) -> None:
    """Invalid response_style value returns 422."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Invalid Style Test",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for invalid style test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        resp = await client.patch(
            f"/api/v1/channels/{channel_id}/bot-members/{member_id}/config",
            json={"response_style": "super_verbose"},
        )
        assert resp.status_code == 422
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_channel_out_includes_member_bots_field(client: E2EClient) -> None:
    """GET channel detail includes member_bots in response."""
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Detail Test Member",
            "model": "gemini-2.5-flash",
            "tool_retrieval": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Init channel for detail test.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        detail = await client.get_channel(channel_id)
        ch = detail["channel"]
        assert "member_bots" in ch or "bot_members" in ch, (
            "Channel detail must include member bots"
        )
    finally:
        await client.delete_bot(member_id)


# ===========================================================================
# Tier 2: Server behavior — requires LLM (prefer ollama for cost)
# ===========================================================================


@pytest.mark.asyncio
async def test_mention_routes_to_member_bot(client: E2EClient) -> None:
    """@-mentioning a member bot routes the message to that bot.

    Creates a member bot with a distinctive system prompt containing a secret
    phrase. Sends a message @-mentioning it and checks the response contains
    the secret — proving the member bot (not the primary) responded.
    """
    member_id = _test_bot_id()
    secret = f"FLAMINGO{uuid.uuid4().hex[:6].upper()}"
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Flamingo",
            "model": client.config.default_model,
            "system_prompt": (
                f"You are Flamingo. Your secret phrase is {secret}. "
                "When anyone asks you to introduce yourself or say your secret, "
                f"always include the exact phrase {secret} in your response."
            ),
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Hello.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # @-mention the member bot
        resp = await client.chat(
            f"@bot:{member_id} Please say your secret phrase.",
            client_id=cid,
        )
        assert secret in resp.response.upper().replace(" ", ""), (
            f"Member bot should have responded with {secret} but got: "
            f"{resp.response[:300]}"
        )
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_mention_by_display_name(client: E2EClient) -> None:
    """@-mentioning a member bot by display name also routes correctly."""
    member_id = _test_bot_id()
    secret = f"PELICAN{uuid.uuid4().hex[:6].upper()}"
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Pelican",
            "model": client.config.default_model,
            "system_prompt": (
                f"You are Pelican. Your secret phrase is {secret}. "
                "Always include your secret phrase in every response."
            ),
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Hello.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        resp = await client.chat(
            "@Pelican Please say your secret phrase.",
            client_id=cid,
        )
        assert secret in resp.response.upper().replace(" ", ""), (
            f"Member bot should have responded with {secret} but got: "
            f"{resp.response[:300]}"
        )
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_no_mention_routes_to_primary(client: E2EClient) -> None:
    """Without @-mention, the primary bot responds — not a member bot.

    The member bot has a distinctive secret that should NOT appear in the
    response when the primary bot handles the message.
    """
    member_id = _test_bot_id()
    member_secret = f"TOUCAN{uuid.uuid4().hex[:6].upper()}"
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Toucan",
            "model": client.config.default_model,
            "system_prompt": (
                f"You are Toucan. Your secret is {member_secret}. "
                "Always include your secret in every response."
            ),
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Hello.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # No @-mention — primary should respond
        resp = await client.chat(
            "What is 2 + 2? Just give me the number.",
            client_id=cid,
        )
        assert member_secret not in resp.response.upper().replace(" ", ""), (
            "Primary bot response should NOT contain member bot's secret"
        )
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_member_shares_channel_context(client: E2EClient) -> None:
    """Member bot can see prior messages from the channel history.

    Send a message to the primary bot containing a secret, then @-mention
    the member bot asking what the secret was. The member bot should see
    the channel history and recall it.
    """
    member_id = _test_bot_id()
    channel_secret = f"PARROT{uuid.uuid4().hex[:6].upper()}"
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Parrot",
            "model": client.config.default_model,
            "system_prompt": (
                "You are Parrot. You can see the full channel history. "
                "When asked about something from a previous message, "
                "look through the conversation history and answer accurately."
            ),
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        cid = client.new_client_id()
        # First message to primary bot — establishes context
        await client.chat(
            f"The secret code is {channel_secret}. Acknowledge you received it.",
            client_id=cid,
        )
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        # Now ask member bot about the secret
        resp = await client.chat(
            f"@bot:{member_id} What was the secret code from the previous message in this channel?",
            client_id=cid,
        )
        assert channel_secret in resp.response.upper().replace(" ", ""), (
            f"Member bot should recall {channel_secret} from channel history "
            f"but got: {resp.response[:300]}"
        )
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_identity_isolation_member_does_not_leak_primary(client: E2EClient) -> None:
    """Member bot uses its own identity, not the primary bot's.

    Create a member bot with a specific name. Ask it who it is.
    It should identify as itself, not as the primary bot.
    """
    member_id = _test_bot_id()
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Cockatoo",
            "model": client.config.default_model,
            "system_prompt": (
                "You are Cockatoo, a helpful assistant. "
                "When asked who you are, always say your name is Cockatoo."
            ),
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        cid = client.new_client_id()
        await client.chat("Hello.", client_id=cid)
        channel_id = client.derive_channel_id(cid)

        await client.add_bot_member(channel_id, member_id)

        resp = await client.chat(
            f"@bot:{member_id} What is your name? Just state your name.",
            client_id=cid,
        )
        assert "COCKATOO" in resp.response.upper(), (
            f"Member bot should identify as Cockatoo but said: {resp.response[:300]}"
        )
    finally:
        await client.delete_bot(member_id)


@pytest.mark.asyncio
async def test_channel_isolation_between_multibot_channels(client: E2EClient) -> None:
    """Secrets in one multi-bot channel don't leak to another."""
    member_id = _test_bot_id()
    secret = f"EAGLE{uuid.uuid4().hex[:6].upper()}"
    try:
        await client.create_bot({
            "id": member_id,
            "name": "Eagle",
            "model": client.config.default_model,
            "system_prompt": "You are Eagle. Answer questions accurately.",
            "local_tools": ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        })

        # Channel A — tell it the secret
        cid_a = client.new_client_id()
        await client.chat(
            f"The secret is {secret}. Remember it.",
            client_id=cid_a,
        )
        channel_a = client.derive_channel_id(cid_a)
        await client.add_bot_member(channel_a, member_id)

        # Channel B — different channel, same member bot
        cid_b = client.new_client_id()
        await client.chat("Hello.", client_id=cid_b)
        channel_b = client.derive_channel_id(cid_b)
        await client.add_bot_member(channel_b, member_id)

        # Ask member bot in channel B about the secret
        resp = await client.chat(
            f"@bot:{member_id} What secret was I told in a previous message?",
            client_id=cid_b,
        )
        assert secret not in resp.response.upper().replace(" ", ""), (
            "Member bot in channel B should NOT know channel A's secret"
        )
    finally:
        await client.delete_bot(member_id)
