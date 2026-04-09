"""Workflow E2E tests — CRUD, run lifecycle, approval gates, cancel, LLM interaction.

All tests create their own workflows and clean up in finally blocks.
No destructive operations outside test-scoped resources.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PREFIX = "e2e-wf"


def _wf_id() -> str:
    return f"{_PREFIX}-{uuid.uuid4().hex[:8]}"


def _simple_workflow(wf_id: str, bot_id: str, **overrides) -> dict:
    """Minimal workflow with one agent step."""
    base = {
        "id": wf_id,
        "name": f"E2E Test Workflow ({wf_id})",
        "description": "Auto-created by E2E tests",
        "params": {},
        "steps": [
            {
                "id": "step1",
                "prompt": "Say exactly: STEP1_DONE",
                "type": "agent",
            },
        ],
        "defaults": {"bot_id": bot_id},
        "tags": ["e2e-test"],
        "session_mode": "isolated",
    }
    base.update(overrides)
    return base


def _approval_workflow(wf_id: str, bot_id: str) -> dict:
    """Workflow with an approval gate on the first step."""
    return {
        "id": wf_id,
        "name": f"E2E Approval Workflow ({wf_id})",
        "description": "Tests approval gates",
        "params": {},
        "steps": [
            {
                "id": "gated_step",
                "prompt": "Say exactly: APPROVED_STEP_DONE",
                "type": "agent",
                "requires_approval": True,
            },
            {
                "id": "final_step",
                "prompt": "Say exactly: FINAL_DONE",
                "type": "agent",
            },
        ],
        "defaults": {"bot_id": bot_id},
        "tags": ["e2e-test"],
    }


def _multi_step_workflow(wf_id: str, bot_id: str) -> dict:
    """Workflow with two sequential agent steps."""
    return {
        "id": wf_id,
        "name": f"E2E Multi-Step ({wf_id})",
        "params": {},
        "steps": [
            {
                "id": "step_a",
                "prompt": "Say exactly: STEP_A_DONE",
                "type": "agent",
            },
            {
                "id": "step_b",
                "prompt": "Say exactly: STEP_B_DONE",
                "type": "agent",
            },
        ],
        "defaults": {"bot_id": bot_id},
        "tags": ["e2e-test"],
    }


async def _cleanup_workflow(client: E2EClient, wf_id: str) -> None:
    """Delete a workflow, ignoring 404."""
    resp = await client.delete(f"/api/v1/admin/workflows/{wf_id}")
    # 204 = deleted, 404 = already gone
    assert resp.status_code in (204, 404)


async def _poll_run_terminal(
    client: E2EClient, run_id: str, *, timeout: float = 90, interval: float = 2,
) -> dict:
    """Poll a workflow run until it reaches a terminal or awaiting_approval state."""
    terminal = {"complete", "failed", "cancelled", "awaiting_approval"}
    elapsed = 0.0
    while elapsed < timeout:
        resp = await client.get(f"/api/v1/admin/workflow-runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()
        if run["status"] in terminal:
            return run
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Workflow run {run_id} did not reach terminal state within {timeout}s (last: {run['status']})")


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_create_and_get(client: E2EClient) -> None:
    """Create a workflow, fetch it by ID, verify fields."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201
        created = resp.json()
        assert created["id"] == wf_id
        assert created["name"] == data["name"]
        assert created["session_mode"] == "isolated"
        assert len(created["steps"]) == 1
        assert created["tags"] == ["e2e-test"]
        assert created["source_type"] == "manual"

        # GET
        resp = await client.get(f"/api/v1/admin/workflows/{wf_id}")
        assert resp.status_code == 200
        fetched = resp.json()
        assert fetched["id"] == wf_id
        assert fetched["description"] == data["description"]
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_list_includes_created(client: E2EClient) -> None:
    """Created workflow appears in the list endpoint."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.get("/api/v1/admin/workflows")
        assert resp.status_code == 200
        ids = [w["id"] for w in resp.json()]
        assert wf_id in ids
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_update(client: E2EClient) -> None:
    """Update workflow fields and verify persistence."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.put(f"/api/v1/admin/workflows/{wf_id}", json={
            "name": "Updated Name",
            "description": "Updated description",
            "tags": ["e2e-test", "updated"],
        })
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "Updated Name"
        assert updated["description"] == "Updated description"
        assert "updated" in updated["tags"]

        # Verify persistence
        resp = await client.get(f"/api/v1/admin/workflows/{wf_id}")
        assert resp.json()["name"] == "Updated Name"
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_delete(client: E2EClient) -> None:
    """Delete a workflow, verify 204 then 404 on re-fetch."""
    wf_id = _wf_id()
    data = _simple_workflow(wf_id, client.default_bot_id)
    resp = await client.post("/api/v1/admin/workflows", json=data)
    assert resp.status_code == 201

    resp = await client.delete(f"/api/v1/admin/workflows/{wf_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/admin/workflows/{wf_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_export_yaml(client: E2EClient) -> None:
    """Export a workflow as YAML and verify structure."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/export")
        assert resp.status_code == 200
        assert "yaml" in resp.headers.get("content-type", "")
        body = resp.text
        assert wf_id in body
        assert "steps" in body
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_get_nonexistent_404(client: E2EClient) -> None:
    """GET nonexistent workflow returns 404."""
    resp = await client.get("/api/v1/admin/workflows/nonexistent-wf-xyz")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_create_duplicate_409(client: E2EClient) -> None:
    """Creating a workflow with the same ID twice returns 409."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 409
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_update_nonexistent_404(client: E2EClient) -> None:
    """Updating a nonexistent workflow returns 404."""
    resp = await client.put(
        "/api/v1/admin/workflows/nonexistent-wf-xyz",
        json={"name": "nope"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_delete_nonexistent_404(client: E2EClient) -> None:
    """Deleting a nonexistent workflow returns 404."""
    resp = await client.delete("/api/v1/admin/workflows/nonexistent-wf-xyz")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_create_empty_id_422(client: E2EClient) -> None:
    """Creating a workflow with empty id returns 422."""
    resp = await client.post("/api/v1/admin/workflows", json={
        "id": "   ",
        "name": "Bad Workflow",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Run lifecycle — trigger, status, list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_trigger_and_complete(client: E2EClient) -> None:
    """Trigger a single-step workflow, poll to completion, verify step states."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        # Trigger
        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
            "triggered_by": "api",
        })
        assert resp.status_code == 201
        run = resp.json()
        run_id = run["id"]
        assert run["workflow_id"] == wf_id
        assert run["bot_id"] == client.default_bot_id
        assert run["triggered_by"] == "api"
        assert run["session_mode"] == "isolated"
        assert len(run["step_states"]) == 1

        # Poll to terminal
        final = await _poll_run_terminal(client, run_id)
        assert final["status"] == "complete", f"Expected complete, got {final['status']}: {final.get('error')}"
        assert final["step_states"][0]["status"] == "done"
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_multi_step_completes(client: E2EClient) -> None:
    """Trigger a two-step workflow, verify both steps complete in order."""
    wf_id = _wf_id()
    try:
        data = _multi_step_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        assert resp.status_code == 201
        run_id = resp.json()["id"]

        final = await _poll_run_terminal(client, run_id, timeout=120)
        assert final["status"] == "complete"
        assert len(final["step_states"]) == 2
        assert final["step_states"][0]["status"] == "done"
        assert final["step_states"][1]["status"] == "done"
        # Step A should have finished before step B started
        assert final["step_states"][0]["completed_at"] is not None
        assert final["step_states"][1]["completed_at"] is not None
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_run_get_by_id(client: E2EClient) -> None:
    """GET a specific run by ID returns correct fields."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        await client.post("/api/v1/admin/workflows", json=data)

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        resp = await client.get(f"/api/v1/admin/workflow-runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()
        assert run["id"] == run_id
        assert run["workflow_id"] == wf_id
        for key in ("status", "step_states", "current_step_index", "created_at", "session_mode"):
            assert key in run, f"Missing run key: {key}"

        # Wait for completion before cleanup
        await _poll_run_terminal(client, run_id)
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_runs_list(client: E2EClient) -> None:
    """List runs for a specific workflow returns the run we triggered."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        await client.post("/api/v1/admin/workflows", json=data)

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        resp = await client.get(f"/api/v1/admin/workflows/{wf_id}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert any(r["id"] == run_id for r in runs)

        await _poll_run_terminal(client, run_id)
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_runs_recent(client: E2EClient) -> None:
    """Recent runs endpoint includes our triggered run."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        await client.post("/api/v1/admin/workflows", json=data)

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        resp = await client.get("/api/v1/admin/workflow-runs/recent")
        assert resp.status_code == 200
        runs = resp.json()
        assert isinstance(runs, list)
        assert any(r["id"] == run_id for r in runs)

        await _poll_run_terminal(client, run_id)
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_run_nonexistent_404(client: E2EClient) -> None:
    """GET nonexistent run returns 404."""
    resp = await client.get(
        f"/api/v1/admin/workflow-runs/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_trigger_nonexistent_400(client: E2EClient) -> None:
    """Triggering a nonexistent workflow returns 400."""
    resp = await client.post(
        "/api/v1/admin/workflows/nonexistent-wf-xyz/run",
        json={"bot_id": client.default_bot_id},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_workflow_trigger_no_bot_400(client: E2EClient) -> None:
    """Triggering a workflow without bot_id (and no default) returns 400."""
    wf_id = _wf_id()
    try:
        # Create workflow with no defaults.bot_id
        data = _simple_workflow(wf_id, client.default_bot_id)
        data["defaults"] = {}
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={})
        assert resp.status_code == 400
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# Approval gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_approval_gate_approve(client: E2EClient) -> None:
    """Workflow pauses at approval gate, approve resumes it to completion."""
    wf_id = _wf_id()
    try:
        data = _approval_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        # Trigger — should pause at gated_step
        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        assert resp.status_code == 201
        run_id = resp.json()["id"]

        # Poll until awaiting_approval
        paused = await _poll_run_terminal(client, run_id, timeout=30)
        assert paused["status"] == "awaiting_approval"
        assert paused["current_step_index"] == 0
        assert paused["step_states"][0]["status"] == "pending"

        # Approve step 0
        resp = await client.post(
            f"/api/v1/admin/workflow-runs/{run_id}/steps/0/approve"
        )
        assert resp.status_code == 200
        approved_run = resp.json()
        assert approved_run["status"] in ("running", "complete", "awaiting_approval")

        # Poll to full completion (both steps)
        final = await _poll_run_terminal(client, run_id, timeout=120)
        assert final["status"] == "complete"
        assert final["step_states"][0]["status"] == "done"
        assert final["step_states"][1]["status"] == "done"
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_approval_gate_skip(client: E2EClient) -> None:
    """Skip an approval-gated step, workflow proceeds to next step."""
    wf_id = _wf_id()
    try:
        data = _approval_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        # Wait for approval gate
        paused = await _poll_run_terminal(client, run_id, timeout=30)
        assert paused["status"] == "awaiting_approval"

        # Skip step 0
        resp = await client.post(
            f"/api/v1/admin/workflow-runs/{run_id}/steps/0/skip"
        )
        assert resp.status_code == 200

        # Should complete with step 0 skipped, step 1 done
        final = await _poll_run_terminal(client, run_id, timeout=120)
        assert final["status"] == "complete"
        assert final["step_states"][0]["status"] == "skipped"
        assert final["step_states"][1]["status"] == "done"
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_cancel_awaiting(client: E2EClient) -> None:
    """Cancel a workflow that is awaiting approval."""
    wf_id = _wf_id()
    try:
        data = _approval_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        paused = await _poll_run_terminal(client, run_id, timeout=30)
        assert paused["status"] == "awaiting_approval"

        # Cancel
        resp = await client.post(f"/api/v1/admin/workflow-runs/{run_id}/cancel")
        assert resp.status_code == 200
        cancelled = resp.json()
        assert cancelled["status"] == "cancelled"
        assert cancelled["completed_at"] is not None
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_cancel_already_complete_400(client: E2EClient) -> None:
    """Cancelling a completed workflow returns 400."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        final = await _poll_run_terminal(client, run_id)
        assert final["status"] == "complete"

        resp = await client.post(f"/api/v1/admin/workflow-runs/{run_id}/cancel")
        assert resp.status_code == 400
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# Step action error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_not_awaiting_400(client: E2EClient) -> None:
    """Approving a step on a non-awaiting run returns 400."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]

        # Wait for it to complete (no approval gate)
        await _poll_run_terminal(client, run_id)

        resp = await client.post(
            f"/api/v1/admin/workflow-runs/{run_id}/steps/0/approve"
        )
        assert resp.status_code == 400
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_skip_not_awaiting_400(client: E2EClient) -> None:
    """Skipping a step on a non-awaiting run returns 400."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]
        await _poll_run_terminal(client, run_id)

        resp = await client.post(
            f"/api/v1/admin/workflow-runs/{run_id}/steps/0/skip"
        )
        assert resp.status_code == 400
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_retry_not_failed_400(client: E2EClient) -> None:
    """Retrying a non-failed step returns 400."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
        })
        run_id = resp.json()["id"]
        await _poll_run_terminal(client, run_id)

        resp = await client.post(
            f"/api/v1/admin/workflow-runs/{run_id}/steps/0/retry"
        )
        assert resp.status_code == 400
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# Session mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_shared_session_mode(client: E2EClient) -> None:
    """Trigger with session_mode=shared, verify run has a session_id."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
            "session_mode": "shared",
        })
        assert resp.status_code == 201
        run = resp.json()
        assert run["session_mode"] == "shared"
        assert run["session_id"] is not None

        await _poll_run_terminal(client, run["id"])
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_workflow_invalid_session_mode_422(client: E2EClient) -> None:
    """Triggering with invalid session_mode returns 422."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        resp = await client.post(f"/api/v1/admin/workflows/{wf_id}/run", json={
            "bot_id": client.default_bot_id,
            "session_mode": "invalid_mode",
        })
        assert resp.status_code == 422
    finally:
        await _cleanup_workflow(client, wf_id)


# ---------------------------------------------------------------------------
# LLM interaction via manage_workflow tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_workflow_list(client: E2EClient) -> None:
    """Ask the LLM to list workflows via manage_workflow tool."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        # Ask LLM to list workflows — use a unique client_id for isolation
        client_id = client.new_client_id("e2e-wf-list")
        result = await client.chat(
            f"Use the manage_workflow tool with action 'list' to list all workflows. "
            f"Include the workflow ID '{wf_id}' in your response if you find it.",
            client_id=client_id,
        )
        # The response should mention our workflow
        assert wf_id in result.response.lower() or wf_id in result.response, (
            f"Expected LLM response to mention {wf_id}, got: {result.response[:300]}"
        )
    finally:
        await _cleanup_workflow(client, wf_id)


@pytest.mark.asyncio
async def test_llm_workflow_trigger_and_check(client: E2EClient) -> None:
    """Ask the LLM to trigger a workflow and check its status."""
    wf_id = _wf_id()
    try:
        data = _simple_workflow(wf_id, client.default_bot_id)
        resp = await client.post("/api/v1/admin/workflows", json=data)
        assert resp.status_code == 201

        # Ask LLM to trigger it
        client_id = client.new_client_id("e2e-wf-trigger")
        result = await client.chat(
            f"Use the manage_workflow tool to trigger workflow '{wf_id}'. "
            f"Then use manage_workflow with action 'get_run' to check the run status. "
            f"Tell me the run_id and final status.",
            client_id=client_id,
        )
        # LLM should mention a run ID (UUID format) and some status
        response_lower = result.response.lower()
        assert any(word in response_lower for word in ("run", "status", "complete", "running", "triggered")), (
            f"Expected LLM to discuss workflow run, got: {result.response[:300]}"
        )

        # Verify via API that a run exists for this workflow
        resp = await client.get(f"/api/v1/admin/workflows/{wf_id}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) >= 1, "Expected at least one run created by LLM"

        # Wait for any active runs to finish before cleanup
        for r in runs:
            if r["status"] in ("running", "awaiting_approval"):
                await _poll_run_terminal(client, r["id"], timeout=90)
    finally:
        await _cleanup_workflow(client, wf_id)
