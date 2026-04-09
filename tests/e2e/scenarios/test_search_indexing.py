"""Search & indexing endpoint tests — deterministic, no LLM dependency.

Verifies that search, indexing diagnostics, skills, tools, and embedding
endpoints return correct shapes AND real data. All tests are read-only
(GET) or safe POST (search queries). Nothing mutates production state.
"""

from __future__ import annotations

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Indexing diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_indexing_shape(client: E2EClient) -> None:
    """GET /diagnostics/indexing returns systems health with expected keys."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    data = resp.json()
    assert "systems" in data
    assert "healthy" in data
    assert isinstance(data["healthy"], bool)
    assert "issues" in data
    assert isinstance(data["issues"], list)
    # Core subsystems should be present
    systems = data["systems"]
    assert "embedding" in systems
    assert "healthy" in systems["embedding"]
    assert "file_skills" in systems
    assert "filesystem_indexing" in systems
    assert isinstance(systems["filesystem_indexing"], list)


@pytest.mark.asyncio
async def test_diagnostics_indexing_embedding_healthy(client: E2EClient) -> None:
    """Embedding subsystem should be healthy with a configured model."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    embed = resp.json()["systems"]["embedding"]
    assert embed["healthy"] is True, f"Embedding unhealthy: {embed.get('error')}"
    assert isinstance(embed["model"], str)
    assert len(embed["model"]) > 0


@pytest.mark.asyncio
async def test_diagnostics_indexing_file_skills_nonzero(client: E2EClient) -> None:
    """File skills subsystem should have skills on disk and in DB."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    fs = resp.json()["systems"]["file_skills"]
    assert fs["files_on_disk"] > 0, "No skill files found on disk"
    assert fs["skills_in_db_total"] > 0, "No skills in database"
    assert fs["skill_document_chunks"] > 0, "No skill document chunks indexed"


@pytest.mark.asyncio
async def test_diagnostics_indexing_filesystem_has_bots(client: E2EClient) -> None:
    """Filesystem indexing should have at least one bot with chunks."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    fs_list = resp.json()["systems"]["filesystem_indexing"]
    assert len(fs_list) > 0, "No bots with filesystem indexing"
    entry = fs_list[0]
    for key in ("bot_id", "workspace_root", "root_exists", "chunks_in_db",
                "chunks_with_embedding", "memory_scheme"):
        assert key in entry, f"Missing key: {key}"
    # At least one bot should have indexed chunks
    any_chunks = any(e["chunks_in_db"] > 0 for e in fs_list)
    assert any_chunks, f"No bots have any indexed chunks: {[(e['bot_id'], e['chunks_in_db']) for e in fs_list]}"


# ---------------------------------------------------------------------------
# Memory search diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_memory_search_shape(client: E2EClient) -> None:
    """GET /diagnostics/memory-search/{bot_id} returns diagnostic data with chunks."""
    resp = await client.get(
        f"/api/v1/admin/diagnostics/memory-search/{client.default_bot_id}",
        params={"query": "test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_id"] == client.default_bot_id
    assert isinstance(data["result_count"], int)
    assert "diagnostics" in data
    diag = data["diagnostics"]
    for key in ("total_chunks_in_table", "matching_bot_id", "with_embedding"):
        assert key in diag, f"Missing diagnostic key: {key}"
    # The e2e bot should have chunks in the table
    assert diag["total_chunks_in_table"] > 0, "No chunks in filesystem_chunks table at all"


@pytest.mark.asyncio
async def test_diagnostics_memory_search_nonexistent_bot(client: E2EClient) -> None:
    """Memory search diagnostic for nonexistent bot returns error message."""
    resp = await client.get(
        "/api/v1/admin/diagnostics/memory-search/e2e-nonexistent-bot-999",
        params={"query": "test"},
    )
    assert resp.status_code == 200  # endpoint returns 200 with error in body
    data = resp.json()
    assert "error" in data


# ---------------------------------------------------------------------------
# Search / memory API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_returns_real_results(client: E2EClient) -> None:
    """POST /search/memory returns actual results with correct item shape.

    Searches broadly across all bots to ensure we get real data, not empty.
    """
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "memory", "top_k": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0, (
        "Expected at least one memory search result — are any bots using workspace-files?"
    )
    item = data["results"][0]
    for key in ("file_path", "content", "score", "bot_id", "bot_name"):
        assert key in item, f"Missing result key: {key}"
    assert isinstance(item["score"], (int, float))
    assert item["score"] > 0, "Score should be positive for a real match"
    assert len(item["content"]) > 0, "Content should be non-empty"


@pytest.mark.asyncio
async def test_search_memory_empty_query_returns_empty(client: E2EClient) -> None:
    """POST /search/memory with empty query returns empty results."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "", "top_k": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_search_memory_with_bot_filter(client: E2EClient) -> None:
    """POST /search/memory filtered to e2e bot returns only that bot's results."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "memory", "bot_ids": [client.default_bot_id], "top_k": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    # Every result must be from the requested bot (vacuous truth if 0 — that's
    # acceptable since the e2e bot may not have indexed memory yet)
    for item in data["results"]:
        assert item["bot_id"] == client.default_bot_id


@pytest.mark.asyncio
async def test_search_memory_nonexistent_bot_returns_empty(client: E2EClient) -> None:
    """Searching with a nonexistent bot_id returns empty results, not an error."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "test", "bot_ids": ["e2e-nonexistent-bot-999"], "top_k": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# ---------------------------------------------------------------------------
# Skills listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_list_nonempty(client: E2EClient) -> None:
    """GET /skills returns a non-empty list with expected fields."""
    resp = await client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Expected at least one skill in the system"
    skill = data[0]
    for key in ("id", "name", "source_type", "chunk_count"):
        assert key in skill, f"Missing skill key: {key}"


@pytest.mark.asyncio
async def test_skills_have_multiple_source_types(client: E2EClient) -> None:
    """Skills should span multiple source types (file, tool, workspace, etc.)."""
    resp = await client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    source_types = {s["source_type"] for s in resp.json()}
    assert len(source_types) >= 2, (
        f"Expected multiple skill source types but got: {source_types}"
    )


@pytest.mark.asyncio
async def test_skills_filter_by_source_type(client: E2EClient) -> None:
    """GET /skills?source_type=file filters correctly and returns results."""
    resp = await client.get("/api/v1/admin/skills", params={"source_type": "file"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Expected at least one file-sourced skill"
    for skill in data:
        assert skill["source_type"] == "file"


# ---------------------------------------------------------------------------
# Tools listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_nonempty_with_fields(client: E2EClient) -> None:
    """GET /tools returns a non-empty list with expected fields."""
    resp = await client.get("/api/v1/admin/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 10, f"Expected many indexed tools but got {len(data)}"
    tool = data[0]
    for key in ("id", "tool_name", "tool_key", "indexed_at"):
        assert key in tool, f"Missing tool key: {key}"


@pytest.mark.asyncio
async def test_tools_list_includes_core_tools(client: E2EClient) -> None:
    """Tool index should include core tools that are always registered."""
    resp = await client.get("/api/v1/admin/tools")
    assert resp.status_code == 200
    names = {t["tool_name"] for t in resp.json()}
    expected_core = {"get_current_time", "file", "search_memory"}
    missing = expected_core - names
    assert not missing, f"Missing core tools from index: {missing}"


# ---------------------------------------------------------------------------
# Embedding models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_models_list(client: E2EClient) -> None:
    """GET /embedding-models returns available models."""
    resp = await client.get("/api/v1/admin/embedding-models")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Expected at least one embedding model"


# ---------------------------------------------------------------------------
# Tool tiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_tiers_nonempty_with_valid_tiers(client: E2EClient) -> None:
    """GET /tool-policies/tiers returns non-empty list with valid tier values."""
    resp = await client.get("/api/v1/tool-policies/tiers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 10, f"Expected many tool tiers but got {len(data)}"
    entry = data[0]
    assert "tool_name" in entry
    assert "safety_tier" in entry
    # All tiers should be valid values
    valid_tiers = {"safe", "moderate", "sensitive", "critical"}
    tier_values = {e["safety_tier"] for e in data}
    invalid = tier_values - valid_tiers
    assert not invalid, f"Unexpected safety tier values: {invalid}"


# ---------------------------------------------------------------------------
# Diagnostics — operations, feature validation, disk usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_operations_shape(client: E2EClient) -> None:
    """GET /diagnostics/operations returns operations list."""
    resp = await client.get("/api/v1/admin/diagnostics/operations")
    assert resp.status_code == 200
    data = resp.json()
    assert "operations" in data
    assert isinstance(data["operations"], list)


@pytest.mark.asyncio
async def test_diagnostics_feature_validation(client: E2EClient) -> None:
    """GET /diagnostics/feature-validation returns warnings and healthy flag."""
    resp = await client.get("/api/v1/admin/diagnostics/feature-validation")
    assert resp.status_code == 200
    data = resp.json()
    assert "warnings" in data
    assert "warning_count" in data
    assert isinstance(data["warning_count"], int)
    assert data["warning_count"] == len(data["warnings"])
    assert "healthy" in data
    assert isinstance(data["healthy"], bool)


@pytest.mark.asyncio
async def test_diagnostics_disk_usage_has_workspaces(client: E2EClient) -> None:
    """GET /diagnostics/disk-usage returns workspace usage with real data."""
    resp = await client.get("/api/v1/admin/diagnostics/disk-usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "workspaces" in data
    assert isinstance(data["workspaces"], list)
    assert len(data["workspaces"]) > 0, "Expected at least one workspace in disk usage"
