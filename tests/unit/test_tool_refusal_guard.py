"""Tests for tool_refusal_guard — detecting stale refusals and building
corrective system messages."""

from app.services.tool_refusal_guard import (
    build_tool_authority_block,
    scan_assistant_refusals,
)


# ---------------------------------------------------------------------------
# scan_assistant_refusals
# ---------------------------------------------------------------------------


def test_no_refusals_returns_clean_result():
    result = scan_assistant_refusals(
        ["Sure, here's the answer.", "Let me help with that."],
        {"web_search"},
    )
    assert result.any_refusal is False
    assert result.stale_refused == []


def test_detects_generic_refusal_without_tool_name():
    result = scan_assistant_refusals(
        ["I am unable to perform that task."],
        {"web_search"},
    )
    assert result.any_refusal is True
    assert result.stale_refused == []


def test_names_stale_refused_tool():
    """Refusal that references a currently-authorized tool is flagged as stale."""
    result = scan_assistant_refusals(
        ["I cannot execute the `web_search` tool. It is not available to me."],
        {"web_search", "search_memory"},
    )
    assert result.any_refusal is True
    assert result.stale_refused == ["web_search"]


def test_unlisted_tool_mentions_not_flagged():
    """A refusal mentioning a tool that is NOT authorized shouldn't show up."""
    result = scan_assistant_refusals(
        ["I cannot use the generate_video tool — it's not available."],
        {"web_search"},
    )
    # refusal detected but no stale tools because generate_video isn't authorized
    assert result.any_refusal is True
    assert result.stale_refused == []


def test_multiple_turns_dedupe_tool_names():
    """Same tool refused in multiple turns only listed once."""
    result = scan_assistant_refusals(
        [
            "I don't have access to web_search.",
            "I still cannot perform web_search right now.",
            "The web_search tool is not currently available.",
        ],
        {"web_search"},
    )
    assert result.stale_refused == ["web_search"]


def test_order_of_appearance_preserved():
    result = scan_assistant_refusals(
        [
            "I cannot call web_search right now.",
            "I am also unable to access search_memory.",
        ],
        {"web_search", "search_memory", "file"},
    )
    assert result.stale_refused == ["web_search", "search_memory"]


def test_scan_window_caps_at_five_turns():
    """Only the first 5 assistant turns are scanned."""
    turns = (
        ["fine response"] * 6  # first 5 are clean
        + ["I cannot perform web_search; not available."]  # 6th has refusal — should be ignored
    )
    result = scan_assistant_refusals(turns, {"web_search"})
    assert result.any_refusal is False
    assert result.stale_refused == []


def test_empty_inputs_safe():
    assert scan_assistant_refusals([], set()).any_refusal is False
    assert scan_assistant_refusals([""], {"web_search"}).any_refusal is False
    assert scan_assistant_refusals(["hi"], set()).stale_refused == []


def test_non_string_entries_skipped():
    result = scan_assistant_refusals(
        [None, 123, "I cannot execute web_search."],  # type: ignore[list-item]
        {"web_search"},
    )
    assert result.stale_refused == ["web_search"]


def test_longest_tool_name_matches_first():
    """search_memory should match before search when both tools exist."""
    result = scan_assistant_refusals(
        ["I don't have access to search_memory right now."],
        {"search", "search_memory"},
    )
    assert result.stale_refused == ["search_memory"]


def test_capped_at_five_named_tools():
    """Targeted list is capped to avoid long injected messages."""
    refusal = (
        "I cannot access any of: t1, t2, t3, t4, t5, t6, t7. "
        "None of these are available."
    )
    result = scan_assistant_refusals([refusal], {f"t{i}" for i in range(1, 8)})
    assert len(result.stale_refused) == 5


# ---------------------------------------------------------------------------
# build_tool_authority_block
# ---------------------------------------------------------------------------


def test_block_none_when_no_refusal():
    from app.services.tool_refusal_guard import RefusalScanResult
    block = build_tool_authority_block(
        RefusalScanResult(any_refusal=False, stale_refused=[])
    )
    assert block is None


def test_block_generic_when_refusal_no_tool_match():
    from app.services.tool_refusal_guard import RefusalScanResult
    block = build_tool_authority_block(
        RefusalScanResult(any_refusal=True, stale_refused=[])
    )
    assert block is not None
    assert "authoritative" in block.lower() or "current tool list" in block.lower()
    assert "reassessed" in block.lower()


def test_block_names_stale_tools():
    from app.services.tool_refusal_guard import RefusalScanResult
    block = build_tool_authority_block(
        RefusalScanResult(any_refusal=True, stale_refused=["web_search", "search_memory"])
    )
    assert block is not None
    assert "`web_search`" in block
    assert "`search_memory`" in block
    assert "stale" in block.lower()


def test_block_named_overrides_generic_when_both_apply():
    """When we have specific tool names, the named block wins."""
    from app.services.tool_refusal_guard import RefusalScanResult
    block = build_tool_authority_block(
        RefusalScanResult(any_refusal=True, stale_refused=["web_search"])
    )
    assert block is not None
    assert "`web_search`" in block
    # Named block uses "CORRECTION" header; standing uses "Note"
    assert "CORRECTION" in block
