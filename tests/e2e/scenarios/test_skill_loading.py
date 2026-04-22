"""Skill loading and discovery E2E tests.

Verifies the skill-only pipeline from admin skill creation through runtime usage:
- Skills created via admin API are retrievable
- Bots with skills get get_skill/get_skill_list tools auto-injected
- LLM calls get_skill to load skill content
- get_skill_list and context preview reflect the enrolled skill surface
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.client import E2EClient

_ADMIN_SKILLS = "/api/v1/admin/skills"
_ADMIN_CHANNELS = "/api/v1/admin/channels"
_TEST_PREFIX = "e2e-skill-"


def _skill_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


async def _find_channel_for_bot(client: E2EClient, bot_id: str) -> str:
    """Look up channel ID via admin API (more reliable than derive_channel_id
    for temp bots where client_id may not match)."""
    resp = await client.get(f"{_ADMIN_CHANNELS}?page_size=100")
    channels = resp.json().get("channels", [])
    matching = [c for c in channels if c.get("bot_id") == bot_id]
    assert matching, f"No channel found for bot {bot_id}"
    return matching[0]["id"]


# Hard ceiling for LLM-dependent tests to prevent stream hangs
_LLM_TIMEOUT = 90


# ---------------------------------------------------------------------------
# 1. Skill CRUD via admin API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_create_and_retrieve(client: E2EClient) -> None:
    """POST creates a skill, GET returns it with matching fields."""
    sid = _skill_id()
    try:
        resp = await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "E2E Skill Test", "content": "# Test\n\nThis is test content."},
        )
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()
        assert created["id"] == sid
        assert created["name"] == "E2E Skill Test"

        # GET should match
        resp = await client.get(f"{_ADMIN_SKILLS}/{sid}")
        assert resp.status_code == 200
        fetched = resp.json()
        assert fetched["id"] == sid
        assert "test content" in fetched["content"].lower()
    finally:
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 2. Skill with content gets embedded (chunk_count > 0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_embedding_on_create(client: E2EClient) -> None:
    """Creating a skill with content triggers embedding — chunk_count > 0."""
    sid = _skill_id()
    content = (
        "# Underwater Basket Weaving\n\n"
        "## Materials\nYou need reeds, a basin of water, and patience.\n\n"
        "## Technique\nSubmerge the reeds for 30 minutes. Then weave using "
        "an over-under pattern while keeping the basket submerged.\n\n"
        "## Tips\n- Keep water at room temperature\n- Use fresh reeds\n"
        "- Practice the basic weave before attempting complex patterns"
    )
    try:
        resp = await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "Underwater Basket Weaving", "content": content},
        )
        assert resp.status_code == 201

        # Re-fetch — chunk_count should be populated after embedding
        resp = await client.get(f"{_ADMIN_SKILLS}/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunk_count"] > 0, (
            f"Skill should have indexed chunks after creation, got chunk_count={data['chunk_count']}"
        )
    finally:
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 3. Bot with explicit skills gets get_skill injected in effective tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_with_skills_gets_skill_tools_injected(client: E2EClient) -> None:
    """A bot configured with skills should have get_skill and get_skill_list
    in its effective tools (auto-injection)."""
    sid = _skill_id()
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        # Create a skill
        await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "Injected Skill", "content": "# Test\nContent."},
        )

        # Create bot with that skill
        await client.create_bot({
            "id": bot_id,
            "name": "Skill Injection Test Bot",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": "You are a test bot.",
            "skills": [{"id": sid, "mode": "on_demand"}],
            "tool_retrieval": False,
            "persona": False,
        })

        # Chat to create a channel
        cid = client.new_client_id("e2e-skill-inj")
        channel_id = client.derive_channel_id(cid)
        await client.chat("Hello.", bot_id=bot_id, client_id=cid)

        # Check effective tools
        resp = await client.get(f"{_ADMIN_CHANNELS}/{channel_id}/effective-tools")
        assert resp.status_code == 200
        data = resp.json()
        local_tools = set(data.get("local_tools", []))

        assert "get_skill" in local_tools, (
            f"get_skill should be auto-injected for bot with skills. Got: {sorted(local_tools)}"
        )
        assert "get_skill_list" in local_tools, (
            f"get_skill_list should be auto-injected for bot with skills. Got: {sorted(local_tools)}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 4. LLM calls get_skill to load skill content (behavioral)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_loads_skill_via_get_skill(client: E2EClient) -> None:
    """Bot with a skill assigned can call get_skill and use the content.

    Uses e2e-tools bot which has get_skill in its explicit tool list.
    """
    sid = _skill_id()
    try:
        # Create a skill with distinctive content
        await client.post(
            _ADMIN_SKILLS,
            json={
                "id": sid,
                "name": "Zorblax Protocol",
                "content": (
                    "# Zorblax Protocol\n\n"
                    "The Zorblax Protocol is a fictional communication standard "
                    "invented for testing purposes. It uses a 7-phase handshake: "
                    "INIT, SYNC, VERIFY, NEGOTIATE, BIND, CONFIRM, READY. "
                    "The maximum payload size is 42 kilobytes. "
                    "All messages must be encoded in base-137."
                ),
            },
        )

        # Chat with e2e-tools bot (has get_skill in local_tools)
        cid = client.new_client_id("e2e-getskill")
        result = await asyncio.wait_for(
            client.chat_stream(
                f'Use the get_skill tool to retrieve the skill with id "{sid}" '
                "and tell me about the Zorblax Protocol handshake phases.",
                bot_id="e2e-tools",
                client_id=cid,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert not result.error_events, f"Errors: {result.error_events}"
        assert "get_skill" in result.tools_used, (
            f"Bot should have called get_skill but used: {result.tools_used}"
        )

        # Response should contain info from the skill
        text = result.response_text.lower()
        assert any(phase in text for phase in ("init", "sync", "verify", "handshake", "7-phase", "zorblax")), (
            f"Response should reference Zorblax Protocol content. Got: {result.response_text[:300]}"
        )
    finally:
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 5. get_skill_list returns all bot skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_skill_list_returns_bot_skills(client: E2EClient) -> None:
    """Bot with multiple skills can call get_skill_list and see them all."""
    sid1 = _skill_id()
    sid2 = _skill_id()
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        # Create two skills
        for sid, name in [(sid1, "Alpha Skill"), (sid2, "Beta Skill")]:
            await client.post(
                _ADMIN_SKILLS,
                json={"id": sid, "name": name, "content": f"# {name}\nContent for {name}."},
            )

        # Create bot with both skills and get_skill_list
        await client.create_bot({
            "id": bot_id,
            "name": "Skill List Test Bot",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": (
                "You are a test bot. When asked to list skills, "
                "call the get_skill_list tool immediately."
            ),
            "skills": [
                {"id": sid1, "mode": "on_demand"},
                {"id": sid2, "mode": "on_demand"},
            ],
            "local_tools": ["get_current_time", "get_skill", "get_skill_list"],
            "tool_retrieval": False,
            "persona": False,
        })

        # Ask bot to list skills
        client_id = client.new_client_id("e2e-skilllist")
        result = await asyncio.wait_for(
            client.chat_stream(
                "Use the get_skill_list tool to show me all your available skills.",
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert not result.error_events, f"Errors: {result.error_events}"
        assert "get_skill_list" in result.tools_used, (
            f"Bot should have called get_skill_list. Tools: {result.tools_used}"
        )

        # Inspect the actual tool result rather than the LLM's prose. With 38+
        # skills system-wide, the LLM frequently summarizes and omits the
        # test-created skills from the response text — see Loose Ends "Skill
        # loading drift" entry. The bus payload's `result_summary` is also
        # truncated to 500 chars (`turn_event_emit.py:141`), so we go straight
        # to the messages table where the full tool output is persisted.
        msgs_resp = await client.get(f"/api/v1/sessions/{result.session_id}/messages")
        assert msgs_resp.status_code == 200, (
            f"Failed to fetch session messages: {msgs_resp.status_code} {msgs_resp.text[:200]}"
        )
        tool_contents = "\n".join(
            (m.get("content") or "")
            for m in msgs_resp.json()
            if m.get("role") == "tool"
        )
        assert sid1 in tool_contents, (
            f"Tool result should contain sid1={sid1}. "
            f"Tool contents (first 500): {tool_contents[:500]}"
        )
        assert sid2 in tool_contents, (
            f"Tool result should contain sid2={sid2}. "
            f"Tool contents (first 500): {tool_contents[:500]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_SKILLS}/{sid1}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid2}")


# ---------------------------------------------------------------------------
# 6. Bot-scoped skill denied for other bot (negative test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_scoped_skill_denied_for_other_bot(client: E2EClient) -> None:
    """A skill scoped to a specific bot (bots/<bot_id>/...) is NOT accessible
    to other bots. Only the owning bot can load bot-authored skills.

    Uses a skill ID prefixed with bots/some-other-bot/ to ensure scoping.
    """
    # Bot-scoped skill IDs use the pattern bots/<bot_id>/<name>
    sid = f"bots/nonexistent-bot/{_skill_id()}"
    try:
        await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "Scoped Skill", "content": "# Scoped\nThis belongs to another bot."},
        )

        # e2e-tools bot should NOT have access to another bot's skill
        client_id = client.new_client_id("e2e-denied")
        result = await asyncio.wait_for(
            client.chat_stream(
                f'Use the get_skill tool to retrieve skill "{sid}" right now.',
                bot_id="e2e-tools",
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert "get_skill" in result.tools_used, (
            f"Bot should have attempted get_skill. Tools: {result.tools_used}"
        )

        # The response should indicate the skill isn't fully accessible —
        # either an explicit denial or the bot noting it belongs to another bot
        text = result.response_text.lower()
        assert any(w in text for w in (
            "not configured", "not found", "not available", "denied", "access",
            "cannot", "another bot", "belong", "unable", "error", "no access",
        )), (
            f"Expected access denial for bot-scoped skill. Got: {result.response_text[:300]}"
        )
    finally:
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 7. Context preview shows skill index block when bot has skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_preview_includes_skill_index(client: E2EClient) -> None:
    """A bot with on-demand skills should have a skill index block in context preview."""
    sid = _skill_id()
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        # Create skill
        await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "Preview Test Skill", "content": "# Test\nContent."},
        )

        # Create bot with that skill
        await client.create_bot({
            "id": bot_id,
            "name": "Context Preview Test Bot",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": "Test bot with skills.",
            "skills": [{"id": sid, "mode": "on_demand"}],
            "tool_retrieval": False,
            "persona": False,
        })

        # Chat to create channel
        client_id = client.new_client_id("e2e-preview")
        await client.chat("Hello.", bot_id=bot_id, client_id=client_id)
        channel_id = await _find_channel_for_bot(client, bot_id)

        # Context preview should show skill-related block
        resp = await client.get(f"{_ADMIN_CHANNELS}/{channel_id}/context-preview")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        labels = {b["label"] for b in blocks}

        # Look for skill index block (may be labeled "Skill Index" or "Available Skills")
        has_skill_block = any(
            "skill" in label.lower() for label in labels
        )
        assert has_skill_block, (
            f"Context should include a skill-related block for a bot with skills. "
            f"Labels: {sorted(labels)}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")
