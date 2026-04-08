"""Search & indexing endpoint tests — deterministic, no LLM dependency.

Verifies that search, indexing diagnostics, skills, tools, and embedding
endpoints return correct shapes. All tests are read-only (GET) or safe
POST (search queries). Nothing mutates production state.
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
async def test_diagnostics_indexing_embedding_has_model(client: E2EClient) -> None:
    """Embedding subsystem reports the configured model name."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    embed = resp.json()["systems"]["embedding"]
    assert "model" in embed
    assert isinstance(embed["model"], str)
    assert len(embed["model"]) > 0


@pytest.mark.asyncio
async def test_diagnostics_indexing_file_skills_counts(client: E2EClient) -> None:
    """File skills subsystem reports skill/document counts."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    fs = resp.json()["systems"]["file_skills"]
    assert "files_on_disk" in fs
    assert "skills_in_db_total" in fs
    assert "skill_document_chunks" in fs
    assert isinstance(fs["skills_in_db_total"], int)


@pytest.mark.asyncio
async def test_diagnostics_indexing_filesystem_per_bot(client: E2EClient) -> None:
    """Filesystem indexing entries include expected per-bot fields."""
    resp = await client.get("/api/v1/admin/diagnostics/indexing")
    assert resp.status_code == 200
    fs_list = resp.json()["systems"]["filesystem_indexing"]
    if not fs_list:
        pytest.skip("No bots with filesystem indexing enabled")
    entry = fs_list[0]
    for key in ("bot_id", "workspace_root", "root_exists", "chunks_in_db",
                "chunks_with_embedding", "memory_scheme"):
        assert key in entry, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Memory search diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_memory_search_shape(client: E2EClient) -> None:
    """GET /diagnostics/memory-search/{bot_id} returns diagnostic data."""
    resp = await client.get(
        f"/api/v1/admin/diagnostics/memory-search/{client.default_bot_id}",
        params={"query": "test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "bot_id" in data
    assert data["bot_id"] == client.default_bot_id
    assert "query" in data
    assert "result_count" in data
    assert isinstance(data["result_count"], int)
    assert "diagnostics" in data


@pytest.mark.asyncio
async def test_diagnostics_memory_search_has_chunk_counts(client: E2EClient) -> None:
    """Memory search diagnostic includes chunk breakdown."""
    resp = await client.get(
        f"/api/v1/admin/diagnostics/memory-search/{client.default_bot_id}",
        params={"query": "test"},
    )
    assert resp.status_code == 200
    diag = resp.json()["diagnostics"]
    # Should have at least the chunk count fields (may be 0 if bot has no memory yet)
    for key in ("total_chunks_in_table", "matching_bot_id", "with_embedding"):
        assert key in diag, f"Missing diagnostic key: {key}"


# ---------------------------------------------------------------------------
# Search / memory API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_returns_results_shape(client: E2EClient) -> None:
    """POST /search/memory returns {results: [...]} with correct item shape."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "test", "top_k": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    # If there are results, verify shape
    if data["results"]:
        item = data["results"][0]
        for key in ("file_path", "content", "score", "bot_id", "bot_name"):
            assert key in item, f"Missing result key: {key}"


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
    """POST /search/memory with bot_ids filter doesn't error."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={"query": "hello", "bot_ids": [client.default_bot_id], "top_k": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    # All results should be from the requested bot
    for item in data["results"]:
        assert item["bot_id"] == client.default_bot_id


# ---------------------------------------------------------------------------
# Skills listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_list_shape(client: E2EClient) -> None:
    """GET /skills returns list of skills with expected fields."""
    resp = await client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        skill = data[0]
        for key in ("id", "name", "source_type", "chunk_count"):
            assert key in skill, f"Missing skill key: {key}"


@pytest.mark.asyncio
async def test_skills_filter_by_source_type(client: E2EClient) -> None:
    """GET /skills?source_type=file filters correctly."""
    resp = await client.get("/api/v1/admin/skills", params={"source_type": "file"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for skill in data:
        assert skill["source_type"] == "file"


# ---------------------------------------------------------------------------
# Tools listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_shape(client: E2EClient) -> None:
    """GET /tools returns list of indexed tools."""
    resp = await client.get("/api/v1/admin/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        tool = data[0]
        for key in ("id", "tool_name", "tool_key"):
            assert key in tool, f"Missing tool key: {key}"


@pytest.mark.asyncio
async def test_tools_list_includes_local_tools(client: E2EClient) -> None:
    """Tool index should include at least get_current_time (always present)."""
    resp = await client.get("/api/v1/admin/tools")
    assert resp.status_code == 200
    names = [t["tool_name"] for t in resp.json()]
    assert "get_current_time" in names


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
    # Should have at least one embedding model available
    assert len(data) > 0


# ---------------------------------------------------------------------------
# Tool tiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_tiers_list_shape(client: E2EClient) -> None:
    """GET /tool-policies/tiers returns tools with safety tiers."""
    resp = await client.get("/api/v1/tool-policies/tiers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        entry = data[0]
        assert "tool_name" in entry
        assert "safety_tier" in entry


# ---------------------------------------------------------------------------
# Diagnostics — operations & feature validation
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
    assert "healthy" in data
    assert isinstance(data["healthy"], bool)


@pytest.mark.asyncio
async def test_diagnostics_disk_usage_shape(client: E2EClient) -> None:
    """GET /diagnostics/disk-usage returns workspace usage report."""
    resp = await client.get("/api/v1/admin/diagnostics/disk-usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "workspaces" in data
    assert isinstance(data["workspaces"], list)
