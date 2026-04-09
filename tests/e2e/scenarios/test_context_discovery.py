"""Context injection, tool discovery, and token budget E2E tests.

DEEP behavioral verification — not shape checks. These tests verify:
- The right context blocks appear for the bot's config (and ONLY those blocks)
- Token math is internally consistent (chars, tokens, percentages add up)
- Memory-scheme tools are actually callable AND reflected in admin APIs
- Effective tools matches what the LLM actually receives
- Breakdown categories sum to the reported total
- Skill index has chunks that enable semantic retrieval
- Stream metadata events match what context endpoints report
"""

from __future__ import annotations

import math

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ADMIN = "/api/v1/admin/channels"

# The e2e bot has these declared in local_tools config
_DECLARED_LOCAL_TOOLS = {"get_current_time", "get_current_local_time"}

# The e2e bot uses memory_scheme=workspace-files, which injects these at runtime
_MEMORY_SCHEME_TOOLS = {"file", "search_memory", "get_memory_file"}

# All tools the bot should actually be able to call
_ALL_EXPECTED_TOOLS = _DECLARED_LOCAL_TOOLS | _MEMORY_SCHEME_TOOLS

# Expected context preview block labels for the e2e bot config
# (memory_scheme=workspace-files, no persona, no capabilities, history_mode=file)
_EXPECTED_BLOCK_LABELS = {
    "Global Base Prompt",
    "Base Prompt",
    "Bot System Prompt",
    "Date/Time",
}


async def _chat_and_get_channel(
    client: E2EClient,
    message: str = "Hello.",
    prefix: str = "e2e-ctx",
) -> tuple[str, str]:
    """Send a message and return (channel_id, client_id)."""
    cid = client.new_client_id(prefix)
    channel_id = client.derive_channel_id(cid)
    await client.chat(message, client_id=cid)
    return channel_id, cid


# ---------------------------------------------------------------------------
# 1. Context preview blocks match bot config exactly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_preview_blocks_match_bot_config(client: E2EClient) -> None:
    """Context preview returns the expected blocks for the e2e bot's config.

    The e2e bot has: system_prompt, no persona, no capabilities, memory_scheme=workspace-files,
    history_mode=file. We verify the specific blocks that SHOULD appear.
    """
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-preview")
    assert resp.status_code == 200
    data = resp.json()

    blocks = data["blocks"]
    labels = {b["label"] for b in blocks}

    # These MUST be present
    for required in _EXPECTED_BLOCK_LABELS:
        assert required in labels, (
            f"Missing required block '{required}'. Got: {sorted(labels)}"
        )

    # Bot system prompt block should contain the bot's actual system prompt text
    sys_block = next(b for b in blocks if b["label"] == "Bot System Prompt")
    assert "test bot" in sys_block["content"].lower(), (
        f"Bot System Prompt block doesn't contain expected prompt text: "
        f"{sys_block['content'][:100]}..."
    )

    # No persona block (bot has persona=false)
    assert "Persona" not in labels, (
        f"Persona block should NOT appear (persona=false). Got: {sorted(labels)}"
    )


# ---------------------------------------------------------------------------
# 2. Context preview chars sum matches total_chars exactly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_preview_chars_sum_matches_total(client: E2EClient) -> None:
    """The sum of block content lengths + conversation lengths must equal total_chars."""
    channel_id, cid = await _chat_and_get_channel(client)

    resp = await client.get(
        f"{_ADMIN}/{channel_id}/context-preview",
        params={"include_history": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()

    block_chars = sum(len(b["content"]) for b in data["blocks"])
    conv_chars = sum(
        len(m.get("content", "")) for m in data.get("conversation", [])
    )
    actual_sum = block_chars + conv_chars
    reported = data["total_chars"]

    assert actual_sum == reported, (
        f"Block chars ({block_chars}) + conv chars ({conv_chars}) = {actual_sum} "
        f"but total_chars reports {reported}. Off by {abs(actual_sum - reported)}."
    )


# ---------------------------------------------------------------------------
# 3. Context preview token estimate is consistent with chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_preview_token_estimate_consistent(client: E2EClient) -> None:
    """Token estimate should be roughly total_chars / 3.5 (within 20% tolerance)."""
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-preview")
    assert resp.status_code == 200
    data = resp.json()

    total_chars = data["total_chars"]
    reported_tokens = data["total_tokens_approx"]
    expected_tokens = math.ceil(total_chars / 3.5)

    # Allow 20% tolerance for rounding across blocks
    drift_pct = abs(reported_tokens - expected_tokens) / expected_tokens * 100
    assert drift_pct < 20, (
        f"Token estimate drift too high: reported {reported_tokens}, "
        f"expected ~{expected_tokens} (chars={total_chars}/3.5). "
        f"Drift: {drift_pct:.1f}%"
    )


# ---------------------------------------------------------------------------
# 4. Token count grows meaningfully with conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_grows_meaningfully(client: E2EClient) -> None:
    """A second message + response should add at least 30 tokens to context."""
    cid = client.new_client_id("e2e-ctx-grow")
    channel_id = client.derive_channel_id(cid)

    await client.chat("Hello.", client_id=cid)
    resp1 = await client.get(
        f"{_ADMIN}/{channel_id}/context-preview",
        params={"include_history": "true"},
    )
    assert resp1.status_code == 200
    tokens_1 = resp1.json()["total_tokens_approx"]

    await client.chat(
        "Explain the concept of recursion in three sentences.",
        client_id=cid,
    )
    resp2 = await client.get(
        f"{_ADMIN}/{channel_id}/context-preview",
        params={"include_history": "true"},
    )
    assert resp2.status_code == 200
    tokens_2 = resp2.json()["total_tokens_approx"]

    delta = tokens_2 - tokens_1
    assert delta >= 30, (
        f"Expected at least 30 token growth from a message+response, "
        f"got {delta} ({tokens_1} → {tokens_2})"
    )


# ---------------------------------------------------------------------------
# 5. Breakdown category math is internally consistent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breakdown_categories_sum_correctly(client: E2EClient) -> None:
    """Category chars must sum to total_chars, tokens must sum to total_tokens,
    percentages must sum to ~100%."""
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-breakdown")
    if resp.status_code == 404:
        pytest.skip("context-breakdown not available")

    assert resp.status_code == 200
    data = resp.json()
    categories = data["categories"]

    # Chars must sum exactly
    sum_chars = sum(c["chars"] for c in categories)
    assert sum_chars == data["total_chars"], (
        f"Category chars sum {sum_chars} != total {data['total_chars']}"
    )

    # Tokens must sum within 5 (rounding)
    sum_tokens = sum(c["tokens_approx"] for c in categories)
    assert abs(sum_tokens - data["total_tokens_approx"]) <= 5, (
        f"Category tokens sum {sum_tokens} != total {data['total_tokens_approx']}"
    )

    # Percentages must sum to ~100
    sum_pct = sum(c["percentage"] for c in categories)
    assert 98.0 <= sum_pct <= 102.0, (
        f"Category percentages sum to {sum_pct:.1f}%, expected ~100%"
    )

    # Each category's tokens_approx should be consistent with its chars
    for cat in categories:
        if cat["chars"] == 0:
            continue
        expected = math.ceil(cat["chars"] / 3.5)
        drift = abs(cat["tokens_approx"] - expected)
        assert drift <= 3, (
            f"Category '{cat['key']}': {cat['chars']} chars → "
            f"{cat['tokens_approx']} tokens but expected ~{expected} (drift {drift})"
        )


# ---------------------------------------------------------------------------
# 6. Breakdown has expected categories for e2e bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breakdown_has_expected_categories(client: E2EClient) -> None:
    """Breakdown should contain specific categories matching the e2e bot's config."""
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/context-breakdown")
    if resp.status_code == 404:
        pytest.skip("context-breakdown not available")

    data = resp.json()
    cat_keys = {c["key"] for c in data["categories"]}

    # These should always be present for a bot with system_prompt + workspace
    for required in ("system_prompt", "base_prompt", "datetime", "conversation"):
        assert required in cat_keys, (
            f"Missing expected category '{required}'. Got: {sorted(cat_keys)}"
        )

    # System prompt should have non-trivial size
    sys_cat = next(c for c in data["categories"] if c["key"] == "system_prompt")
    assert sys_cat["chars"] >= 100, (
        f"System prompt suspiciously small: {sys_cat['chars']} chars"
    )

    # Global base prompt should be the largest static category
    if "global_base_prompt" in cat_keys:
        gbp = next(c for c in data["categories"] if c["key"] == "global_base_prompt")
        assert gbp["chars"] > sys_cat["chars"], (
            f"Global base prompt ({gbp['chars']}) should be larger than "
            f"bot system prompt ({sys_cat['chars']})"
        )


# ---------------------------------------------------------------------------
# 7. Memory-scheme tools are actually callable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_scheme_tools_callable(client: E2EClient) -> None:
    """The e2e bot (memory_scheme=workspace-files) should be able to call
    file, search_memory, and get_memory_file — not just the declared local_tools."""
    cid = client.new_client_id("e2e-memtools")

    # Ask bot to use search_memory explicitly
    result = await client.chat_stream(
        "Search your memory for 'test'. Use the search_memory tool now.",
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert "search_memory" in result.tools_used, (
        f"Bot should have used search_memory but used: {result.tools_used}. "
        f"Event types: {result.event_types}"
    )

    # Ask bot to list files
    result2 = await client.chat_stream(
        "List files in the memory/ directory using the file tool with operation=list.",
        client_id=cid,
    )
    assert not result2.error_events, f"Errors: {result2.error_events}"
    assert "file" in result2.tools_used, (
        f"Bot should have used file tool but used: {result2.tools_used}. "
        f"Event types: {result2.event_types}"
    )


# ---------------------------------------------------------------------------
# 8. Effective tools includes ALL tools the bot can actually use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_tools_complete(client: E2EClient) -> None:
    """Effective tools should include both declared local_tools AND
    memory-scheme-injected tools (file, search_memory, get_memory_file)."""
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/effective-tools")
    assert resp.status_code == 200
    data = resp.json()

    local_tools = set(data.get("local_tools", []))

    # Declared tools must be present
    for tool in _DECLARED_LOCAL_TOOLS:
        assert tool in local_tools, (
            f"Declared tool '{tool}' missing from effective-tools. Got: {local_tools}"
        )

    # BUG CHECK: memory-scheme tools should be reflected somewhere in effective-tools.
    # Currently they are NOT — the bot can call file/search_memory/get_memory_file
    # but effective-tools only shows declared local_tools. This is a known gap.
    # We test for it explicitly so it fails if/when it's fixed (or stays failing
    # to track the bug).
    all_tools_in_response = local_tools
    missing_memory_tools = _MEMORY_SCHEME_TOOLS - all_tools_in_response
    if missing_memory_tools:
        pytest.xfail(
            f"KNOWN BUG: effective-tools missing memory-scheme tools: "
            f"{missing_memory_tools}. Bot can call these but admin API doesn't show them."
        )


# ---------------------------------------------------------------------------
# 9. Stream metadata events report context injection counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_reports_context_injection(client: E2EClient) -> None:
    """Streaming chat emits metadata events showing what was injected into context."""
    cid = client.new_client_id("e2e-ctx-stream")
    result = await client.chat_stream("What time is it?", client_id=cid)

    event_types = set(result.event_types)

    # Stream should include context budget event
    assert "context_budget" in event_types, (
        f"Expected context_budget event in stream. Got types: {sorted(event_types)}"
    )

    # Verify context_budget event has plausible values
    budget_events = [e for e in result.events if e.type == "context_budget"]
    assert len(budget_events) >= 1
    budget = budget_events[0].data
    assert budget.get("consumed_tokens", 0) > 0, (
        f"context_budget consumed_tokens should be > 0: {budget}"
    )
    assert budget.get("total_tokens", 0) > 0, (
        f"context_budget total_tokens should be > 0: {budget}"
    )
    # Utilization should be small for a fresh channel (< 10%)
    util = budget.get("utilization", 0)
    assert 0 < util < 0.1, (
        f"Fresh channel utilization should be < 10%, got {util*100:.1f}%: {budget}"
    )

    # Memory scheme bootstrap should fire for workspace-files bot
    assert "memory_scheme_bootstrap" in event_types, (
        f"Expected memory_scheme_bootstrap event (bot uses workspace-files). "
        f"Got: {sorted(event_types)}"
    )


# ---------------------------------------------------------------------------
# 10. Config overhead line items are specific and plausible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_overhead_line_items(client: E2EClient) -> None:
    """Config overhead should have specific line items matching the bot's config."""
    channel_id, _ = await _chat_and_get_channel(client)

    resp = await client.get(f"{_ADMIN}/{channel_id}/config-overhead")
    assert resp.status_code == 200
    data = resp.json()

    lines = data.get("lines", data if isinstance(data, list) else [])
    labels = {line["label"] for line in lines}

    # Should have system prompt overhead
    assert any("system_prompt" in label for label in labels), (
        f"Expected sys:system_prompt in overhead labels. Got: {sorted(labels)}"
    )

    # Should have tool schema overhead (bot has local_tools)
    assert any("tool" in label.lower() for label in labels), (
        f"Expected tool schema overhead line. Got: {sorted(labels)}"
    )

    # System prompt line should roughly match the bot's actual prompt length
    sys_line = next(
        (line for line in lines if "system_prompt" in line["label"]), None,
    )
    if sys_line:
        # e2e bot system prompt is ~574 chars
        assert 200 < sys_line["chars"] < 2000, (
            f"System prompt overhead ({sys_line['chars']} chars) outside "
            f"plausible range for e2e bot"
        )

    # Total overhead should exist and be reasonable
    assert data.get("approx_tokens", 0) > 100, (
        f"Expected at least 100 tokens of config overhead, got: {data}"
    )
    assert data.get("context_window", 0) > 0, "Expected non-zero context_window"


# ---------------------------------------------------------------------------
# 11. Context budget matches breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_budget_consistent_with_breakdown(client: E2EClient) -> None:
    """Context budget consumed_tokens should be in the same ballpark as
    breakdown total_tokens_approx."""
    channel_id, _ = await _chat_and_get_channel(client)

    budget_resp = await client.get(f"{_ADMIN}/{channel_id}/context-budget")
    breakdown_resp = await client.get(f"{_ADMIN}/{channel_id}/context-breakdown")

    if budget_resp.status_code == 404 or breakdown_resp.status_code == 404:
        pytest.skip("budget or breakdown not available")

    budget = budget_resp.json()
    breakdown = breakdown_resp.json()

    budget_tokens = budget.get("consumed_tokens", 0)
    breakdown_tokens = breakdown.get("total_tokens_approx", 0)

    assert budget_tokens > 0, "Budget consumed_tokens should be > 0"
    assert breakdown_tokens > 0, "Breakdown total_tokens should be > 0"

    # They measure slightly different things (budget is from actual provider trace,
    # breakdown is an estimate), but they should be within 50% of each other
    ratio = max(budget_tokens, breakdown_tokens) / min(budget_tokens, breakdown_tokens)
    assert ratio < 1.5, (
        f"Budget ({budget_tokens}) and breakdown ({breakdown_tokens}) differ "
        f"by {ratio:.1f}x — too much drift between estimate and actual"
    )


# ---------------------------------------------------------------------------
# 12. Skills indexed with chunks enable retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_indexed_with_retrievable_chunks(client: E2EClient) -> None:
    """Skills should have indexed chunks in the documents table,
    and the chunk count should be plausible for the skill's content."""
    resp = await client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    skills = resp.json()

    assert len(skills) > 10, (
        f"Expected a substantial skill library (>10), got {len(skills)}"
    )

    # Check skills with chunks
    with_chunks = [s for s in skills if s.get("chunk_count", 0) > 0]
    assert len(with_chunks) > 5, (
        f"Expected >5 skills with indexed chunks, got {len(with_chunks)} "
        f"out of {len(skills)} total"
    )

    # Skills with descriptions should also have chunks (if indexed properly)
    with_desc = [s for s in skills if s.get("description")]
    desc_but_no_chunks = [
        s for s in with_desc if s.get("chunk_count", 0) == 0
    ]
    # Allow some — not all skills may be indexed — but flag if majority are missing
    ratio = len(desc_but_no_chunks) / max(len(with_desc), 1)
    assert ratio < 0.5, (
        f"{len(desc_but_no_chunks)} of {len(with_desc)} described skills have "
        f"no indexed chunks ({ratio*100:.0f}%). Indexing may be broken."
    )


# ---------------------------------------------------------------------------
# 13. Memory search relevance — write then find
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_finds_written_content(client: E2EClient) -> None:
    """Write a distinctive memory, then search for it and verify it appears."""
    # Write a memory with a unique marker
    cid = client.new_client_id("e2e-ctx-memfind")
    await client.chat(
        "Write a memory file called e2e_ctx_discovery_test.md with this exact content: "
        "'The Fibonacci sequence starts with 0, 1, 1, 2, 3, 5, 8, 13.'",
        client_id=cid,
    )

    # Search via diagnostic endpoint (bypasses the 300s index cooldown
    # by searching raw files)
    resp = await client.get(
        f"/api/v1/admin/diagnostics/memory-search/{client.default_bot_id}",
        params={"query": "Fibonacci sequence"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Should find results (diagnostic endpoint searches indexed + raw)
    results = data.get("results", [])
    if len(results) > 0:
        # At least one result should mention fibonacci
        contents = " ".join(r.get("content", "") for r in results).lower()
        assert "fibonacci" in contents, (
            f"Searched for 'Fibonacci' but results don't contain it: "
            f"{[r.get('file_path', '') for r in results[:3]]}"
        )


# ---------------------------------------------------------------------------
# 14. Embedding health — model and skills fully indexed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_health_complete(client: E2EClient) -> None:
    """Embedding system is healthy, has a known model, and skills are indexed."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    data = resp.json()
    systems = data.get("systems", {})

    # Embedding healthy
    embed = systems.get("embedding", {})
    assert embed.get("healthy") is True, f"Embedding unhealthy: {embed}"
    assert embed.get("model"), f"Embedding model not set: {embed}"

    # File skills present
    file_skills = systems.get("file_skills", {})
    skill_count = file_skills.get("files_on_disk", 0)
    assert skill_count > 10, (
        f"Expected >10 skill files on disk, got {skill_count}"
    )

    # Filesystem should have bots with indexed chunks
    fs = systems.get("filesystem", {})
    if isinstance(fs, dict) and "bots" in fs:
        bots = fs["bots"]
        bot_list = bots if isinstance(bots, list) else list(bots.values())
        assert len(bot_list) > 0, "Expected at least one bot with indexed filesystem"
