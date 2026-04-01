"""Integration tests for workflows API — CRUD, triggering, approval, failure handling."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Workflow, WorkflowRun
from tests.integration.conftest import AUTH_HEADERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(wid="test-wf", **overrides):
    base = {
        "id": wid,
        "name": "Test Workflow",
        "description": "A test workflow",
        "params": {"name": {"type": "string", "required": True}},
        "steps": [
            {"id": "step1", "prompt": "Do thing with {{name}}."},
            {"id": "step2", "prompt": "Report on {{steps.step1.result}}."},
        ],
        "defaults": {"bot_id": "test-bot"},
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def engine_session_factory(engine):
    """Create an async_sessionmaker bound to the test engine (not the app engine)."""
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_workflow(client, db_session):
    data = _make_workflow()
    resp = await client.post("/api/v1/admin/workflows", json=data, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "test-wf"
    assert body["name"] == "Test Workflow"
    assert len(body["steps"]) == 2


@pytest.mark.asyncio
async def test_list_workflows(client, db_session):
    await client.post("/api/v1/admin/workflows", json=_make_workflow("wf-a", name="A"), headers=AUTH_HEADERS)
    await client.post("/api/v1/admin/workflows", json=_make_workflow("wf-b", name="B"), headers=AUTH_HEADERS)
    resp = await client.get("/api/v1/admin/workflows", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    ids = {w["id"] for w in resp.json()}
    assert "wf-a" in ids
    assert "wf-b" in ids


@pytest.mark.asyncio
async def test_get_workflow(client, db_session):
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    resp = await client.get("/api/v1/admin/workflows/test-wf", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["id"] == "test-wf"


@pytest.mark.asyncio
async def test_get_workflow_not_found(client, db_session):
    resp = await client.get("/api/v1/admin/workflows/nonexistent", headers=AUTH_HEADERS)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_workflow(client, db_session):
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    resp = await client.put(
        "/api/v1/admin/workflows/test-wf",
        json={"name": "Updated Name"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_workflow(client, db_session):
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    resp = await client.delete("/api/v1/admin/workflows/test-wf", headers=AUTH_HEADERS)
    assert resp.status_code == 204
    resp2 = await client.get("/api/v1/admin/workflows/test-wf", headers=AUTH_HEADERS)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_workflow(client, db_session):
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    resp = await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Trigger + Run Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_workflow_missing_params(client, db_session):
    """Triggering with missing required params should fail."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    wf = Workflow(
        id="test-wf", name="Test Workflow",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "step1", "prompt": "Do thing."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )
    with patch("app.services.workflows._registry", {"test-wf": wf}):
        resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {}},
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 400
    assert "Required parameter" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_workflow_creates_run(client, db_session, engine_session_factory):
    """Triggering should create a workflow run with initialized step states."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test Workflow",
        params={"name": {"type": "string", "required": True}},
        steps=[
            {"id": "step1", "prompt": "Do thing with {{name}}."},
            {"id": "step2", "prompt": "Report."},
        ],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )

    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["workflow_id"] == "test-wf"
    assert body["status"] == "running"
    assert len(body["step_states"]) == 2
    assert body["step_states"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Workflow Run Detail + Cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_workflow_run(client, db_session, engine_session_factory):
    """Get workflow run by ID."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )
    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        create_resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
    run_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/admin/workflow-runs/{run_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id


@pytest.mark.asyncio
async def test_cancel_workflow_run(client, db_session, engine_session_factory):
    """Cancel a running workflow."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )
    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        create_resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
    run_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/admin/workflow-runs/{run_id}/cancel", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# List Runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_workflow_runs(client, db_session, engine_session_factory):
    """List runs for a workflow."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )
    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "A"}, "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "B"}, "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )

    resp = await client.get("/api/v1/admin/workflows/test-wf/runs", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert len(resp.json()) == 2
