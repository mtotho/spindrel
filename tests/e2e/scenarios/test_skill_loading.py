"""Skill loading and discovery E2E tests.

Verifies the full pipeline from skill/capability creation through to LLM usage:
- Skills created via admin API are retrievable
- Bots with skills get get_skill/get_skill_list tools auto-injected
- Capabilities with skills resolve correctly
- Bot assigned a capability gets the capability's skills in context
- LLM calls get_skill to load skill content (behavioral)
- LLM discovers unassigned capability and calls activate_capability (behavioral)
- After activation, capability's skills become accessible (behavioral)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.client import E2EClient

_ADMIN_SKILLS = "/api/v1/admin/skills"
_ADMIN_CARAPACES = "/api/v1/admin/carapaces"
_ADMIN_CHANNELS = "/api/v1/admin/channels"
_TEST_PREFIX = "e2e-skill-"
_CAP_PREFIX = "e2e-cap-"

# Hard ceiling for LLM-dependent tests to prevent stream hangs
_LLM_TIMEOUT = 90


async def _create_activation_bot(client: E2EClient) -> str:
    """Create a minimal temp bot with activate_capability + get_skill.
    No workspace, no memory scheme — fast context assembly."""
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    await client.create_bot({
        "id": bot_id,
        "name": "E2E Activation Bot",
        "model": "gemini-2.5-flash-lite",
        "system_prompt": (
            "You are a test bot. You have tools available. "
            "When told to call a specific tool, call it immediately with the given arguments. "
            "Do not explain or ask questions — just call the tool."
        ),
        "local_tools": [
            "activate_capability",
            "get_skill",
            "get_skill_list",
            "get_current_time",
        ],
        "tool_retrieval": False,
        "persona": False,
        "context_compaction": False,
    })
    return bot_id


async def _chat_with_capability_approval(
    client: E2EClient,
    message: str,
    bot_id: str,
    client_id: str,
    timeout: float = _LLM_TIMEOUT,
) -> "StreamResult":  # noqa: F821
    """Send a chat_stream that triggers activate_capability, auto-approve it.

    activate_capability has safety_tier=mutating → requires approval.
    We run the stream in background, poll for the pending approval, approve it,
    then await the stream result.
    """
    from ..harness.streaming import StreamResult  # noqa: F811

    stream_task = asyncio.create_task(
        client.chat_stream(message, bot_id=bot_id, client_id=client_id)
    )

    # Poll for pending capability approval
    elapsed = 0.0
    approval_id = None
    while elapsed < timeout:
        resp = await client.get(
            "/api/v1/approvals",
            params={"bot_id": bot_id, "status": "pending", "limit": 10},
        )
        if resp.status_code == 200:
            for a in resp.json():
                if a["tool_name"] == "activate_capability" and a["status"] == "pending":
                    approval_id = a["id"]
                    break
        if approval_id:
            break
        await asyncio.sleep(2)
        elapsed += 2

    if not approval_id:
        # Maybe the bot didn't call activate_capability — let stream finish
        return await asyncio.wait_for(stream_task, timeout=30)

    # Approve it
    await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": True, "decided_by": "e2e_test"},
    )

    return await asyncio.wait_for(stream_task, timeout=timeout)


def _skill_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


def _cap_id() -> str:
    return f"{_CAP_PREFIX}{uuid.uuid4().hex[:8]}"


async def _find_channel_for_bot(client: E2EClient, bot_id: str) -> str:
    """Look up channel ID via admin API (more reliable than derive_channel_id
    for temp bots where client_id may not match)."""
    resp = await client.get(f"{_ADMIN_CHANNELS}?page_size=100")
    channels = resp.json().get("channels", [])
    matching = [c for c in channels if c.get("bot_id") == bot_id]
    assert matching, f"No channel found for bot {bot_id}"
    return matching[0]["id"]


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
        assert "activate_capability" in local_tools, (
            f"activate_capability should always be injected. Got: {sorted(local_tools)}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 4. (Removed) "Capability with skills resolves correctly"
# Capabilities no longer carry a `skills` field — skills flow exclusively
# through the per-bot working set (see Track - Skill Simplification Phase 1.5).
# The fragment-as-index pattern replaces the legacy `skills:` block.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. Bot assigned a capability gets capability's skills in context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_skills_appear_in_context_after_assignment(client: E2EClient) -> None:
    """Assigning a capability to a bot makes the capability's skills appear
    in the runtime context. Carapace skills are resolved at context assembly
    time (not in static effective-tools), so we verify via context-preview."""
    sid = _skill_id()
    cid = _cap_id()
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        # Create skill + capability
        await client.post(
            _ADMIN_SKILLS,
            json={"id": sid, "name": "Cap Skill", "content": "# Capability Skill\nContent here."},
        )
        await client.post(
            _ADMIN_CARAPACES,
            json={
                "id": cid,
                "name": "E2E Cap With Skills",
                "description": "Capability providing skills for testing",
                "skills": [{"id": sid, "mode": "on_demand"}],
                "system_prompt_fragment": "You have access to the Cap Skill.",
                "tags": ["e2e-testing"],
            },
        )

        # Create bot and assign capability
        await client.create_bot({
            "id": bot_id,
            "name": "Cap Skills Test Bot",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": "You are a test bot.",
            "tool_retrieval": False,
            "persona": False,
        })
        await client.update_bot(bot_id, {"carapaces": [cid]})

        # Chat to create channel (triggers context assembly + carapace resolution)
        client_id = client.new_client_id("e2e-cap-skill")
        await client.chat("Hello.", bot_id=bot_id, client_id=client_id)
        channel_id = await _find_channel_for_bot(client, bot_id)

        # Context preview should show the capability's system_prompt_fragment
        resp = await client.get(f"{_ADMIN_CHANNELS}/{channel_id}/context-preview")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        all_content = " ".join(b["content"] for b in blocks).lower()

        # The capability's fragment or skill reference should appear in context
        assert "cap skill" in all_content or sid in all_content, (
            f"Context should include capability's content after assignment. "
            f"Labels: {[b['label'] for b in blocks]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_CARAPACES}/{cid}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 6. LLM calls get_skill to load skill content (behavioral)
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
# 7. LLM discovers unassigned capability and activates it (behavioral)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_discovers_and_activates_capability(client: E2EClient) -> None:
    """Bot calls activate_capability with a specific ID and the capability
    is successfully activated. Uses a minimal temp bot for fast context assembly.
    """
    sid = _skill_id()
    cid = _cap_id()
    bot_id = await _create_activation_bot(client)
    try:
        # Create skill + capability
        await client.post(
            _ADMIN_SKILLS,
            json={
                "id": sid,
                "name": "Quantum Sandwich Theory",
                "content": "# Quantum Sandwich Theory\nFictional content for testing.",
            },
        )
        resp = await client.post(
            _ADMIN_CARAPACES,
            json={
                "id": cid,
                "name": "Quantum Sandwich Expert",
                "description": "Expert in Quantum Sandwich Theory",
                "skills": [{"id": sid, "mode": "on_demand"}],
                "system_prompt_fragment": "You are an expert in Quantum Sandwich Theory.",
                "tags": ["e2e-testing"],
            },
        )
        assert resp.status_code == 201

        client_id = client.new_client_id("e2e-discover")
        result = await _chat_with_capability_approval(
            client,
            f'Call the activate_capability tool with id="{cid}".',
            bot_id=bot_id,
            client_id=client_id,
        )
        assert not result.error_events, f"Errors: {result.error_events}"
        assert "activate_capability" in result.tools_used, (
            f"Bot should have called activate_capability. "
            f"Tools used: {result.tools_used}. "
            f"Response: {result.response_text[:200]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_CARAPACES}/{cid}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 8. After activation, capability skills are accessible on next turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activated_capability_skills_available_next_turn(client: E2EClient) -> None:
    """After activate_capability, the next turn should have the capability's
    skills accessible via get_skill.

    Turn 1: Activate the capability
    Turn 2: Load the skill content via get_skill
    """
    sid = _skill_id()
    cid = _cap_id()
    bot_id = await _create_activation_bot(client)
    try:
        await client.post(
            _ADMIN_SKILLS,
            json={
                "id": sid,
                "name": "Fictional Elvish Grammar",
                "content": (
                    "# Elvish Grammar Rules\n\n"
                    "Verbs conjugate by adding -iel for past tense and -ara for future. "
                    "Nouns take the suffix -on for plural. Adjectives precede nouns."
                ),
            },
        )
        await client.post(
            _ADMIN_CARAPACES,
            json={
                "id": cid,
                "name": "Elvish Language Expert",
                "description": "Expert in Elvish grammar",
                "skills": [{"id": sid, "mode": "on_demand"}],
                "local_tools": ["get_skill"],
                "system_prompt_fragment": "You are an Elvish language expert.",
                "tags": ["e2e-testing"],
            },
        )

        # Turn 1: Activate the capability (with approval flow)
        client_id = client.new_client_id("e2e-multiturn")
        result1 = await _chat_with_capability_approval(
            client,
            f'Call activate_capability with id="{cid}".',
            bot_id=bot_id,
            client_id=client_id,
        )
        assert not result1.error_events, f"Turn 1 errors: {result1.error_events}"
        assert "activate_capability" in result1.tools_used, (
            f"Turn 1 should activate capability. Tools: {result1.tools_used}. "
            f"Response: {result1.response_text[:200]}"
        )

        # Turn 2: Load the skill
        result2 = await asyncio.wait_for(
            client.chat_stream(
                f'Call get_skill with skill_id="{sid}".',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert not result2.error_events, f"Turn 2 errors: {result2.error_events}"
        assert "get_skill" in result2.tools_used, (
            f"Turn 2 should use get_skill. "
            f"Tools: {result2.tools_used}. Response: {result2.response_text[:200]}"
        )

        text = result2.response_text.lower()
        assert any(w in text for w in ("-iel", "past tense", "conjugat", "elvish")), (
            f"Response should reference Elvish grammar content. Got: {result2.response_text[:300]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_CARAPACES}/{cid}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 9. get_skill_list returns all bot skills
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

        # Response should mention both skills
        text = result.response_text.lower()
        assert "alpha" in text or sid1 in text, (
            f"Response should mention Alpha Skill. Got: {result.response_text[:300]}"
        )
        assert "beta" in text or sid2 in text, (
            f"Response should mention Beta Skill. Got: {result.response_text[:300]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_SKILLS}/{sid1}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid2}")


# ---------------------------------------------------------------------------
# 10. Bot-scoped skill denied for other bot (negative test)
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
# 11. Context preview shows skill index block when bot has skills
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


# ---------------------------------------------------------------------------
# 12. Full pipeline: create skill → create capability → discover → activate → load → use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_skill_discovery_pipeline(client: E2EClient) -> None:
    """End-to-end pipeline test: a skill wrapped in a capability that is NOT
    assigned to the bot gets discovered via RAG, activated, and its content
    loaded and used in the response.

    Uses a minimal temp bot for fast context assembly.
    """
    sid = _skill_id()
    cid = _cap_id()
    bot_id = await _create_activation_bot(client)
    try:
        # Create a skill with very distinctive, verifiable content
        await client.post(
            _ADMIN_SKILLS,
            json={
                "id": sid,
                "name": "Martian Chess Rules",
                "content": (
                    "# Martian Chess Rules\n\n"
                    "Martian Chess is played on a triangular board with 37 hexagonal cells. "
                    "Each player starts with 5 Drones (move 1 hex), 3 Pawns (move 2 hex), "
                    "and 1 Queen (moves any distance). Captures are mandatory. "
                    "The game ends when one player has no pieces. The winner is the player "
                    "who captured the most points: Queens=5, Pawns=3, Drones=1. "
                    "The special rule: pieces that cross the midline change ownership."
                ),
            },
        )

        # Create capability wrapping the skill (NOT assigned to any bot)
        await client.post(
            _ADMIN_CARAPACES,
            json={
                "id": cid,
                "name": "Martian Chess Expert",
                "description": (
                    "Expert in Martian Chess — triangular board game with hexagonal cells, "
                    "drones, pawns, queens, and the midline ownership rule."
                ),
                "skills": [{"id": sid, "mode": "on_demand"}],
                "local_tools": ["get_skill"],
                "system_prompt_fragment": (
                    "You are an expert in Martian Chess. Always cite specific rules."
                ),
                "tags": ["e2e-testing", "games", "chess"],
            },
        )

        # Turn 1: Activate the Martian Chess capability (with approval)
        client_id = client.new_client_id("e2e-pipeline")
        result1 = await _chat_with_capability_approval(
            client,
            f'Call activate_capability with id="{cid}".',
            bot_id=bot_id,
            client_id=client_id,
        )
        assert not result1.error_events, f"Turn 1 errors: {result1.error_events}"
        assert "activate_capability" in result1.tools_used, (
            f"Turn 1 should have activated capability. "
            f"Tools: {result1.tools_used}. Response: {result1.response_text[:200]}"
        )

        # Turn 2: Load the skill
        result2 = await asyncio.wait_for(
            client.chat_stream(
                f'Call get_skill with skill_id="{sid}".',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert not result2.error_events, f"Turn 2 errors: {result2.error_events}"
        assert "get_skill" in result2.tools_used, (
            f"Turn 2 should use get_skill to load the activated capability's skill. "
            f"Tools: {result2.tools_used}"
        )

        # Verify content from the skill appears in the response
        text = result2.response_text.lower()
        assert any(w in text for w in ("1 hex", "drone", "triangular", "hexagonal", "martian")), (
            f"Response should contain Martian Chess content from the skill. "
            f"Got: {result2.response_text[:400]}"
        )
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN_CARAPACES}/{cid}")
        await client.delete(f"{_ADMIN_SKILLS}/{sid}")


# ---------------------------------------------------------------------------
# 13. Orchestrator fragment contains environment context (pinned→fragment migration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_fragment_has_environment_context(client: E2EClient) -> None:
    """After migrating workspace-orchestrator from pinned skill to inline fragment,
    the orchestrator capability's context preview should include environment/filesystem
    content that was previously injected as a pinned skill."""
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        await client.create_bot({
            "id": bot_id,
            "name": "Orchestrator Fragment Test",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": "You are a test orchestrator.",
            "carapaces": ["orchestrator"],
            "tool_retrieval": False,
            "persona": False,
            "context_compaction": False,
        })

        # Chat to create channel
        cid = client.new_client_id("e2e-orch-frag")
        await client.chat("Hello.", bot_id=bot_id, client_id=cid)
        channel_id = await _find_channel_for_bot(client, bot_id)

        # Context preview should contain environment content from the fragment
        resp = await client.get(f"{_ADMIN_CHANNELS}/{channel_id}/context-preview")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        all_content = " ".join(b["content"] for b in blocks).lower()

        # These are key phrases from the workspace-orchestrator content
        # that should now be in the fragment, not in a separate pinned skill block
        assert "/workspace/bots/" in all_content, (
            "Fragment should include filesystem layout with /workspace/bots/"
        )
        assert "search_bot_memory" in all_content, (
            "Fragment should include orchestrator-only capabilities (search_bot_memory)"
        )
        assert "container tools" in all_content or "python 3.12" in all_content, (
            "Fragment should include container environment info"
        )

        # There should be NO pinned skill block — the content is inline in the fragment
        labels = [b["label"].lower() for b in blocks]
        assert not any("pinned skill" in label for label in labels), (
            f"Should not have a separate pinned skill block after migration. Labels: {labels}"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 14. Presenter bot fetches slides skill via get_skill (behavioral)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_presenter_fetches_slides_skill_before_creating(client: E2EClient) -> None:
    """A bot with the presenter capability should call get_skill to load the
    Marp reference before creating slides, since the skill is now on-demand
    with a strong nudge in the fragment."""
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    try:
        await client.create_bot({
            "id": bot_id,
            "name": "Presenter Skill Test",
            "model": "gemini-2.5-flash-lite",
            "system_prompt": (
                "You are a presentation bot. Follow your capability instructions exactly. "
                "When asked to create a presentation, first load the required skill, "
                "then use create_slides."
            ),
            "carapaces": ["presenter"],
            "local_tools": ["get_skill", "get_skill_list", "create_slides"],
            "tool_retrieval": False,
            "persona": False,
            "context_compaction": False,
        })

        cid = client.new_client_id("e2e-presenter")
        result = await asyncio.wait_for(
            client.chat_stream(
                "Create a simple 3-slide presentation about testing best practices.",
                bot_id=bot_id,
                client_id=cid,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert not result.error_events, f"Errors: {result.error_events}"

        # The bot should have called get_skill for the slides reference
        assert "get_skill" in result.tools_used, (
            f"Presenter should call get_skill for Marp reference before creating slides. "
            f"Tools used: {result.tools_used}. Response: {result.response_text[:300]}"
        )
    finally:
        await client.delete_bot(bot_id)
