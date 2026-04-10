"""Tier 2: Memory search depth — write-then-search, curation trigger, relevance ranking.

Deepens memory coverage beyond basic round-trips.  Tests the search pipeline
end-to-end: files written via the workspace REST API (which triggers auto-reindex),
then the REST search API surfaces the content with correct relevance ordering.

Tier 2 — server behavior (model via E2E_DEFAULT_MODEL).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _get_workspace_id(client: E2EClient) -> str | None:
    """Get the shared workspace ID for the default bot."""
    bot = await client.get_bot(client.default_bot_id)
    return bot.get("shared_workspace_id")


async def _write_memory_via_api(
    client: E2EClient, workspace_id: str, filename: str, content: str,
) -> None:
    """Write a memory file via the workspace REST API (triggers auto-reindex)."""
    ws_path = f"bots/{client.default_bot_id}/memory/{filename}"
    resp = await client.put(
        f"/api/v1/workspaces/{workspace_id}/files/content",
        params={"path": ws_path},
        json={"content": content},
    )
    assert resp.status_code == 200, (
        f"Workspace file write failed: {resp.status_code} {resp.text[:200]}"
    )


async def _search_memory(
    client: E2EClient, query: str, *, top_k: int = 10,
) -> list[dict]:
    """Call the REST search/memory endpoint and return results."""
    resp = await client.post(
        "/api/v1/search/memory",
        json={
            "query": query,
            "bot_ids": [client.default_bot_id],
            "top_k": top_k,
        },
    )
    assert resp.status_code == 200, f"Search failed: {resp.status_code} {resp.text[:200]}"
    return resp.json()["results"]


async def _poll_task_terminal(
    client: E2EClient, task_id: str, *, timeout: float = 120, interval: float = 3,
) -> dict:
    """Poll a task until it reaches a terminal status."""
    import time
    deadline = time.monotonic() + timeout
    last_status = "unknown"
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/v1/admin/tasks/{task_id}")
        if resp.status_code == 500:
            # Transient — task may be running; retry
            await asyncio.sleep(interval)
            continue
        assert resp.status_code == 200, f"Task fetch failed: {resp.status_code} {resp.text[:200]}"
        data = resp.json()
        last_status = data["status"]
        if last_status in ("complete", "completed", "failed", "error", "cancelled"):
            return data
        await asyncio.sleep(interval)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s — last status: {last_status}")


# ---------------------------------------------------------------------------
# 1. Write via REST API → search finds it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_write_then_search_finds_content(client: E2EClient) -> None:
    """Write a memory file via workspace API, wait for auto-reindex, verify search surfaces it.

    The workspace file write endpoint triggers _schedule_reindex_for_paths,
    which indexes memory files for all bots in the workspace.
    """
    workspace_id = await _get_workspace_id(client)
    if not workspace_id:
        pytest.skip("Bot has no shared_workspace_id")

    token = _unique("srch")
    filename = f"e2e-search-depth-{token}.md"
    content = f"The secret ingredient for the {token} recipe is cardamom"

    await _write_memory_via_api(client, workspace_id, filename, content)

    # Poll search — reindex fires async in the background
    import time
    deadline = time.monotonic() + 90
    results = []
    while time.monotonic() < deadline:
        results = await _search_memory(client, token)
        matching = [r for r in results if token in r.get("content", "")]
        if matching:
            hit = matching[0]
            assert hit["bot_id"] == client.default_bot_id
            assert hit["score"] > 0, "Score should be positive"
            assert "cardamom" in hit["content"], "Expected full content in result"
            return
        await asyncio.sleep(5)

    pytest.fail(
        f"Search for '{token}' never returned matching results after 90s. "
        f"Last results: {[r.get('file_path', '?') for r in results[:5]]}"
    )


# ---------------------------------------------------------------------------
# 2. Memory curation trigger → verify task completes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_curation_trigger_completes(client: E2EClient) -> None:
    """Trigger memory hygiene (curation) for the e2e bot, verify the task runs to completion.

    This doesn't check *what* the curation agent does (that depends on memory
    content), just that the pipeline works: trigger → task created → task reaches
    terminal state without error.
    """
    bot = await client.get_bot(client.default_bot_id)
    if bot.get("memory_scheme") != "workspace-files":
        pytest.skip("Bot doesn't use workspace-files memory scheme")

    resp = await client.post(
        f"/api/v1/admin/bots/{client.default_bot_id}/memory-hygiene/trigger",
    )
    assert resp.status_code == 200, f"Trigger failed: {resp.status_code} {resp.text[:200]}"
    data = resp.json()
    assert "task_id" in data, f"No task_id in response: {data}"
    task_id = data["task_id"]

    final = await _poll_task_terminal(client, task_id, timeout=120)
    assert final["status"] in ("complete", "completed"), (
        f"Hygiene task ended with status={final['status']}, "
        f"error={final.get('error', final.get('result', ''))}"
    )

    # Verify the run shows up in hygiene run history
    runs_resp = await client.get(
        f"/api/v1/admin/bots/{client.default_bot_id}/memory-hygiene/runs",
    )
    assert runs_resp.status_code == 200
    runs_data = runs_resp.json()
    assert runs_data["total"] > 0, "Expected at least one hygiene run in history"


# ---------------------------------------------------------------------------
# 3. Search relevance — two topics, verify ranking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_relevance_ranking(client: E2EClient) -> None:
    """Write two memory files on distinct topics, search for one, verify it ranks higher.

    Topic A: a unique astronomy fact.  Topic B: a unique cooking fact.
    Search for topic A's keyword — topic A should score higher than topic B.
    """
    workspace_id = await _get_workspace_id(client)
    if not workspace_id:
        pytest.skip("Bot has no shared_workspace_id")

    tag = _unique("rel")
    token_a = f"quasar-{tag}"
    token_b = f"sourdough-{tag}"

    file_a = f"e2e-relevance-astro-{tag}.md"
    file_b = f"e2e-relevance-cook-{tag}.md"

    content_a = (
        f"Observation log {token_a}: The distant quasar exhibited "
        f"rapid luminosity fluctuations consistent with gravitational lensing. "
        f"Redshift measured at z=2.4, confirming extragalactic origin."
    )
    content_b = (
        f"Recipe note {token_b}: The sourdough starter reached peak activity "
        f"after 6 hours at 78F. Hydration ratio maintained at 100 percent. "
        f"Bulk fermentation time was 4 hours with two stretch-and-folds."
    )

    await _write_memory_via_api(client, workspace_id, file_a, content_a)
    await _write_memory_via_api(client, workspace_id, file_b, content_b)

    # Wait for reindex then search for astronomy topic
    import time
    deadline = time.monotonic() + 90
    results: list[dict] = []
    while time.monotonic() < deadline:
        results = await _search_memory(client, "quasar gravitational lensing redshift")
        # Check if current run's files are in results
        has_a = any(
            token_a in r.get("file_path", "") or token_a in r.get("content", "")
            for r in results
        )
        if has_a:
            score_a = max(
                (r["score"] for r in results
                 if token_a in r.get("file_path", "") or token_a in r.get("content", "")),
                default=0,
            )
            score_b = max(
                (r["score"] for r in results
                 if token_b in r.get("file_path", "") or token_b in r.get("content", "")),
                default=0,
            )
            if score_a > 0:
                if score_b > 0:
                    assert score_a > score_b, (
                        f"Astronomy result (score={score_a}) should rank higher than "
                        f"cooking result (score={score_b}) for astronomy query"
                    )
                return
        await asyncio.sleep(5)

    pytest.fail(
        f"Astronomy file never appeared in search results after 90s. "
        f"Last results: {[r.get('file_path', '?') for r in results[:5]]}"
    )
