"""Tests for the search_tools LLM-callable — semantic search over the full tool pool."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.local.discovery import search_tools


@pytest.mark.asyncio
async def test_returns_ranked_matches():
    """A query that matches a known tool returns it with similarity."""
    tools = [
        {"type": "function", "function": {"name": "web_search", "description": "Search the web"}},
        {"type": "function", "function": {"name": "search_memory", "description": "Search memory"}},
    ]
    candidates = [
        {"name": "web_search", "sim": 0.42},
        {"name": "search_memory", "sim": 0.31},
    ]
    with patch(
        "app.agent.tools.retrieve_tools",
        new=AsyncMock(return_value=(tools, 0.42, candidates)),
    ):
        out = await search_tools(query="look up something on the web")

    data = json.loads(out)
    assert data["query"] == "look up something on the web"
    names = [m["name"] for m in data["matches"]]
    assert "web_search" in names
    assert data["matches"][0]["similarity"] == 0.42


@pytest.mark.asyncio
async def test_empty_result_gives_explicit_hint():
    """No matches → hint explains the loose floor rather than returning nothing."""
    with patch(
        "app.agent.tools.retrieve_tools",
        new=AsyncMock(return_value=([], 0.0, [])),
    ):
        out = await search_tools(query="something nobody has a tool for")

    data = json.loads(out)
    assert data["matches"] == []
    assert "No tools matched" in data["hint"]


@pytest.mark.asyncio
async def test_empty_query_rejected():
    """Empty / whitespace query returns an error without calling retrieve_tools."""
    mock_retrieve = AsyncMock()
    with patch("app.agent.tools.retrieve_tools", new=mock_retrieve):
        out = await search_tools(query="   ")

    data = json.loads(out)
    assert "error" in data
    mock_retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_limit_clamped():
    """limit is coerced to [1, 25]; falsy/invalid → default 10."""
    mock_retrieve = AsyncMock(return_value=([], 0.0, []))
    with patch("app.agent.tools.retrieve_tools", new=mock_retrieve):
        await search_tools(query="test", limit=999)   # clamped high
        await search_tools(query="test", limit=0)     # falsy → default
        await search_tools(query="test", limit="abc")  # type: ignore[arg-type]  # non-int → default
        await search_tools(query="test", limit=3)     # in range

    top_ks = [call.kwargs["top_k"] for call in mock_retrieve.call_args_list]
    assert top_ks == [25, 10, 10, 3]


@pytest.mark.asyncio
async def test_uses_loose_threshold_and_discover_all():
    """search_tools must hit the full pool with a loose threshold."""
    mock_retrieve = AsyncMock(return_value=([], 0.0, []))
    with patch("app.agent.tools.retrieve_tools", new=mock_retrieve):
        await search_tools(query="anything")

    call = mock_retrieve.call_args
    assert call.kwargs["discover_all"] is True
    assert call.kwargs["threshold"] == 0.2
    # No declared-tools bias — full pool
    assert call.args[1] == [] and call.args[2] == []


@pytest.mark.asyncio
async def test_description_truncated_and_single_line():
    """Long multi-line descriptions come back as single-line, <=200 chars."""
    long_desc = "First line — important\n" + ("second line " * 40)
    tools = [{"type": "function", "function": {"name": "longtool", "description": long_desc}}]
    candidates = [{"name": "longtool", "sim": 0.3}]
    with patch(
        "app.agent.tools.retrieve_tools",
        new=AsyncMock(return_value=(tools, 0.3, candidates)),
    ):
        out = await search_tools(query="x")

    data = json.loads(out)
    desc = data["matches"][0]["description"]
    assert "\n" not in desc
    assert len(desc) <= 200
    assert desc.startswith("First line")
