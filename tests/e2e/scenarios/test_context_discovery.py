"""Context injection, tool discovery, and token budget E2E tests.

Tests that the right things get injected at the right time:
- Context preview has plausible token counts that grow with conversation
- Effective tools reflect bot config and capability activation
- Context breakdown categories are populated after chat
- Skill/tool retrieval surfaces relevant results
- Config overhead is non-zero for a configured bot
"""

from __future__ import annotations

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ADMIN = "/api/v1/admin/channels"


async def _chat_and_get_channel(client: E2EClient, message: str = "Hello.") -> str:
    """Send a message and return the channel ID."""
    cid = client.new_client_id("e2e-ctx")
    channel_id = client.derive_channel_id(cid)
    await client.chat(message, client_id=cid)
    return channel_id


# ---------------------------------------------------------------------------
# 1. Context preview returns real blocks with plausible token counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_preview_has_blocks_and_tokens(client: E2EClient) -> None:
    """Context preview after chat returns labeled blocks with non-zero token estimates."""
    channel_id = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-preview")
    assert resp.status_code == 200
    data = resp.json()

    assert "blocks" in data
    blocks = data["blocks"]
    assert len(blocks) >= 1, "Expected at least one context block (system prompt)"

    # At minimum, system prompt block should exist
    labels = [b["label"] for b in blocks]
    assert any("prompt" in label.lower() or "system" in label.lower() for label in labels), (
        f"Expected a system/prompt block in labels: {labels}"
    )

    # Token estimate should be plausible (> 0)
    assert data.get("total_chars", 0) > 0, "Expected non-zero total_chars"
    assert data.get("total_tokens_approx", 0) > 0, "Expected non-zero token estimate"

    # Each block should have content
    for block in blocks:
        assert "label" in block
        assert "content" in block
        assert isinstance(block["content"], str)


# ---------------------------------------------------------------------------
# 2. Context preview token count grows with conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_grows_with_conversation(client: E2EClient) -> None:
    """Token count in context preview should increase after additional messages."""
    cid = client.new_client_id("e2e-ctx-grow")
    channel_id = client.derive_channel_id(cid)

    # First message
    await client.chat("Hello, this is a test.", client_id=cid)
    resp1 = await client.get(
        f"{_ADMIN}/{channel_id}/context-preview",
        params={"include_history": "true"},
    )
    assert resp1.status_code == 200
    tokens_1 = resp1.json().get("total_tokens_approx", 0)
    assert tokens_1 > 0

    # Second message adds more context
    await client.chat(
        "Tell me a short fact about the Roman Empire.",
        client_id=cid,
    )
    resp2 = await client.get(
        f"{_ADMIN}/{channel_id}/context-preview",
        params={"include_history": "true"},
    )
    assert resp2.status_code == 200
    tokens_2 = resp2.json().get("total_tokens_approx", 0)

    assert tokens_2 > tokens_1, (
        f"Expected token count to grow: {tokens_1} → {tokens_2}"
    )


# ---------------------------------------------------------------------------
# 3. Effective tools includes expected core tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_tools_include_core(client: E2EClient) -> None:
    """Effective tools for the e2e bot should include its configured tools."""
    channel_id = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/effective-tools")
    assert resp.status_code == 200
    data = resp.json()

    # Should have at least local_tools populated
    local_tools = data.get("local_tools") or data.get("local") or []
    # Flatten if it's a list of dicts
    tool_names = []
    for t in local_tools:
        if isinstance(t, str):
            tool_names.append(t)
        elif isinstance(t, dict):
            tool_names.append(t.get("name", t.get("tool_name", "")))

    assert "get_current_time" in tool_names, (
        f"Expected get_current_time in effective tools but got: {tool_names}"
    )


# ---------------------------------------------------------------------------
# 4. Context breakdown has populated categories after chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_breakdown_populated(client: E2EClient) -> None:
    """Context breakdown after chat has at least one category with tokens > 0."""
    channel_id = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-breakdown")
    if resp.status_code == 404:
        pytest.skip("context-breakdown not available for this channel")

    assert resp.status_code == 200
    data = resp.json()

    # Should have categories
    categories = data.get("categories", [])
    assert len(categories) > 0, "Expected at least one context category"

    # At least one category should have non-zero chars
    total_chars = sum(c.get("chars", 0) for c in categories)
    assert total_chars > 0, (
        f"Expected non-zero total chars across categories, got: {categories}"
    )

    # Token estimation fields
    if "total_tokens_approx" in data:
        assert data["total_tokens_approx"] > 0

    # Model context window should be present
    if "model_context_window" in data:
        assert data["model_context_window"] > 0


# ---------------------------------------------------------------------------
# 5. Config overhead is non-zero
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_overhead_nonzero(client: E2EClient) -> None:
    """Config overhead endpoint returns non-zero estimate for a configured bot."""
    channel_id = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/config-overhead")
    assert resp.status_code == 200
    data = resp.json()

    # Should be a list of overhead line items or a dict with lines
    lines = data if isinstance(data, list) else data.get("lines", [])
    assert len(lines) > 0, "Expected at least one config overhead line item"

    # Total chars should be positive
    total_chars = sum(line.get("chars", 0) for line in lines)
    assert total_chars > 0, f"Expected non-zero config overhead chars, got {total_chars}"


# ---------------------------------------------------------------------------
# 6. Skills list has indexed content with descriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_have_descriptions_and_chunks(client: E2EClient) -> None:
    """Skills list returns entries with descriptions and non-zero chunk counts."""
    resp = await client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    skills = resp.json()

    assert len(skills) > 0, "Expected at least one skill indexed on the server"

    # Skills should have key fields for discovery
    first = skills[0]
    for key in ("id", "name"):
        assert key in first, f"Missing skill key: {key}"

    # At least some skills should have descriptions (populated by auto-discovery)
    with_desc = [s for s in skills if s.get("description")]
    assert len(with_desc) > 0, (
        f"Expected some skills with descriptions, got keys: {list(skills[0].keys())}"
    )

    # At least some should have chunk counts (meaning they're indexed for RAG)
    with_chunks = [s for s in skills if s.get("chunk_count", 0) > 0]
    assert len(with_chunks) > 0, "Expected some skills with indexed chunks"


# ---------------------------------------------------------------------------
# 7. Memory search returns results with relevance scores
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_returns_scored_results(client: E2EClient) -> None:
    """Memory search returns results with relevance scores."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={
            "query": "file operations",
            "bot_ids": [client.default_bot_id],
            "top_k": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    results = data.get("results", [])

    # Memory search should return a list (may be empty if no memories yet)
    assert isinstance(results, list)

    if len(results) > 0:
        first = results[0]
        # Should have score and content
        assert "score" in first, f"Expected score field, got keys: {list(first.keys())}"
        assert "content" in first
        assert "file_path" in first
        assert first["score"] > 0, "Expected positive relevance score"

        # Results should be ordered by score descending
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "Results should be ranked by score"


# ---------------------------------------------------------------------------
# 8. Tool list includes tool descriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_list_has_descriptions(client: E2EClient) -> None:
    """Admin tools list returns tools with descriptions (not just names)."""
    resp = await client.get("/api/v1/admin/tools")
    assert resp.status_code == 200
    data = resp.json()
    tools = data if isinstance(data, list) else data.get("tools", [])

    assert len(tools) > 0, "Expected at least one tool for the e2e bot"

    # At least some tools should have descriptions
    with_desc = [t for t in tools if t.get("description")]
    assert len(with_desc) > 0, (
        f"Expected tools with descriptions but got keys: {[list(t.keys()) for t in tools[:3]]}"
    )


# ---------------------------------------------------------------------------
# 9. Context budget returns utilization after chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_budget_utilization(client: E2EClient) -> None:
    """Context budget should show non-zero utilization after a chat exchange."""
    channel_id = await _chat_and_get_channel(
        client, "Explain the concept of recursion in programming."
    )

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-budget")
    if resp.status_code == 404:
        pytest.skip("context-budget not available (no trace events)")

    assert resp.status_code == 200
    data = resp.json()

    # Should have utilization fields
    if "consumed_tokens" in data:
        assert data["consumed_tokens"] > 0, "Expected non-zero consumed tokens"
    if "total_tokens" in data:
        assert data["total_tokens"] > 0, "Expected non-zero total token window"
    if "utilization" in data:
        assert 0 < data["utilization"] < 1.0, (
            f"Expected utilization between 0-1, got: {data['utilization']}"
        )


# ---------------------------------------------------------------------------
# 10. Diagnostic embedding health confirms indexing is active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_health_active(client: E2EClient) -> None:
    """Diagnostics confirm embedding indexes are healthy and have content."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    data = resp.json()

    # Embedding should be healthy
    embed = data.get("embedding") or data.get("embeddings") or {}
    if isinstance(embed, dict):
        healthy = embed.get("healthy", embed.get("status") == "healthy")
        assert healthy, f"Expected embedding to be healthy: {embed}"

    # Should have indexed content
    fs = data.get("filesystem") or {}
    if isinstance(fs, dict) and "bots" in fs:
        bots = fs["bots"]
        if isinstance(bots, list):
            assert len(bots) > 0, "Expected at least one bot with indexed content"
        elif isinstance(bots, dict):
            assert len(bots) > 0, "Expected at least one bot with indexed content"
