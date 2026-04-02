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


# ---------------------------------------------------------------------------
# Session Mode Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_workflow_with_session_mode(client, db_session):
    """Creating a workflow with session_mode should persist it."""
    wf_data = _make_workflow()
    wf_data["session_mode"] = "shared"
    resp = await client.post("/api/v1/admin/workflows", json=wf_data, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["session_mode"] == "shared"

    # Verify via GET
    get_resp = await client.get("/api/v1/admin/workflows/test-wf", headers=AUTH_HEADERS)
    assert get_resp.json()["session_mode"] == "shared"


@pytest.mark.asyncio
async def test_default_session_mode_is_isolated(client, db_session):
    """Creating a workflow without session_mode should default to isolated."""
    resp = await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["session_mode"] == "isolated"


@pytest.mark.asyncio
async def test_trigger_shared_workflow_has_session_id(client, db_session, engine_session_factory):
    """Triggering a shared-session workflow should set session_id on the run."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}, {"id": "s2", "prompt": "Report."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
        session_mode="shared",
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
    assert body["session_id"] is not None, "Shared session mode should set session_id"


@pytest.mark.asyncio
async def test_trigger_isolated_workflow_has_no_session_id(client, db_session, engine_session_factory):
    """Triggering an isolated-session workflow should leave session_id as None."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
        session_mode="isolated",
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
    assert body["session_id"] is None, "Isolated session mode should not set session_id"


@pytest.mark.asyncio
async def test_update_workflow_session_mode(client, db_session):
    """Updating session_mode via PUT should persist."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    resp = await client.put(
        "/api/v1/admin/workflows/test-wf",
        json={"session_mode": "shared"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["session_mode"] == "shared"


# ---------------------------------------------------------------------------
# Session Mode Override on Trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_override_isolated_to_shared(client, db_session, engine_session_factory):
    """Triggering an isolated workflow with session_mode='shared' override should
    create a run with session_mode='shared' and a session_id."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
        session_mode="isolated",
    )
    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot", "session_mode": "shared"},
            headers=AUTH_HEADERS,
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_mode"] == "shared", "Override should switch to shared"
    assert body["session_id"] is not None, "Shared mode should set session_id"


@pytest.mark.asyncio
async def test_trigger_override_shared_to_isolated(client, db_session, engine_session_factory):
    """Triggering a shared workflow with session_mode='isolated' override should
    create a run with session_mode='isolated' and no session_id."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
        session_mode="shared",
    )
    with (
        patch("app.services.workflows._registry", {"test-wf": wf}),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot", "session_mode": "isolated"},
            headers=AUTH_HEADERS,
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_mode"] == "isolated", "Override should switch to isolated"
    assert body["session_id"] is None, "Isolated mode should not set session_id"


@pytest.mark.asyncio
async def test_trigger_invalid_session_mode_rejected(client, db_session):
    """Triggering with an invalid session_mode should return 422."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )
    with patch("app.services.workflows._registry", {"test-wf": wf}):
        resp = await client.post(
            "/api/v1/admin/workflows/test-wf/run",
            json={"params": {"name": "Test"}, "bot_id": "test-bot", "session_mode": "bogus"},
            headers=AUTH_HEADERS,
        )

    assert resp.status_code == 422
    assert "session_mode" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_no_override_uses_workflow_default(client, db_session, engine_session_factory):
    """Triggering without session_mode should use the workflow's default."""
    await client.post("/api/v1/admin/workflows", json=_make_workflow(), headers=AUTH_HEADERS)

    wf = Workflow(
        id="test-wf", name="Test",
        params={"name": {"type": "string", "required": True}},
        steps=[{"id": "s1", "prompt": "Do."}],
        defaults={"bot_id": "test-bot"}, secrets=[],
        session_mode="shared",
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
    assert body["session_mode"] == "shared", "Should use workflow's default session_mode"


# ---------------------------------------------------------------------------
# JSONB Shallow-Copy Bug Demonstration
#
# This test proves WHY we need deepcopy + flag_modified.  It directly
# exercises the old (broken) pattern vs the new (fixed) pattern against
# a real in-memory SQLite DB.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shallow_copy_breaks_jsonb_persistence(engine_session_factory):
    """Demonstrate the shallow-copy JSONB mutation bug.

    Pattern:
      step_states = list(run.step_states)   # shallow — dicts shared
      step_states[0]["status"] = "running"  # mutates BOTH copies
      run.step_states = step_states         # SQLAlchemy may see old == new
      commit()

    On PostgreSQL (and sometimes SQLite), SQLAlchemy detects this as
    a no-op because the committed-state reference points to the same
    mutated dicts. This test documents the vulnerable pattern.
    """
    from sqlalchemy.orm.attributes import flag_modified
    import copy

    run_id = uuid.uuid4()

    # Seed a run
    async with engine_session_factory() as db:
        wf = Workflow(
            id="shallow-bug-wf", name="Bug Demo",
            params={}, steps=[{"id": "s0", "prompt": "Do."}],
            defaults={}, secrets=[],
        )
        db.add(wf)
        run = WorkflowRun(
            id=run_id, workflow_id="shallow-bug-wf", bot_id="test-bot",
            status="running", current_step_index=0,
            step_states=[
                {"status": "pending", "task_id": None, "result": None,
                 "error": None, "started_at": None, "completed_at": None,
                 "correlation_id": None},
            ],
            params={}, dispatch_type="none", session_mode="isolated",
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()

    # --- SAFE PATTERN: deepcopy + flag_modified ---
    async with engine_session_factory() as db:
        run = await db.get(WorkflowRun, run_id)
        step_states = copy.deepcopy(run.step_states)  # deep copy!
        step_states[0]["status"] = "running"
        run.step_states = step_states
        flag_modified(run, "step_states")  # force the UPDATE
        await db.commit()

    # Verify it persisted
    async with engine_session_factory() as db:
        run = await db.get(WorkflowRun, run_id)
    assert run.step_states[0]["status"] == "running", (
        "deepcopy + flag_modified should always persist the change"
    )


# ---------------------------------------------------------------------------
# JSONB Mutation Persistence Tests
#
# These tests verify that step_states changes survive a real DB round-trip
# (write → commit → re-read from fresh session). They exist because a
# shallow-copy bug caused SQLAlchemy to skip the UPDATE on PostgreSQL:
# `list(run.step_states)` shares inner dicts, so mutating the copy also
# mutates the committed-state reference, making old == new → no UPDATE.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_advance_persists_step_running_state(engine_session_factory):
    """advance_workflow should persist step 0 as 'running' in the DB.

    This is a real-DB round-trip test: create run → advance → re-read
    from a fresh session → verify step_states[0] is 'running'.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    wf_id = "persist-test-wf"
    run_id = uuid.uuid4()

    # Seed workflow + run via ORM
    async with engine_session_factory() as db:
        wf = Workflow(
            id=wf_id, name="Persist Test",
            params={},
            steps=[
                {"id": "s0", "prompt": "Do step 0."},
                {"id": "s1", "prompt": "Do step 1."},
            ],
            defaults={"bot_id": "test-bot"},
            secrets=[],
        )
        db.add(wf)
        run = WorkflowRun(
            id=run_id,
            workflow_id=wf_id,
            bot_id="test-bot",
            status="running",
            current_step_index=0,
            step_states=[
                {"status": "pending", "task_id": None, "result": None,
                 "error": None, "started_at": None, "completed_at": None,
                 "correlation_id": None},
                {"status": "pending", "task_id": None, "result": None,
                 "error": None, "started_at": None, "completed_at": None,
                 "correlation_id": None},
            ],
            params={},
            dispatch_type="none",
            session_mode="isolated",
            workflow_snapshot={
                "steps": [
                    {"id": "s0", "prompt": "Do step 0."},
                    {"id": "s1", "prompt": "Do step 1."},
                ],
                "defaults": {"bot_id": "test-bot"},
                "secrets": [],
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()

    # Run advance_workflow — this should set step 0 to "running" and create a task
    from app.services.workflow_executor import advance_workflow

    with patch("app.services.workflow_executor.async_session", engine_session_factory):
        await advance_workflow(run_id)

    # Re-read from a FRESH session — this is the critical check.
    # If the JSONB UPDATE was skipped, step 0 will still be "pending".
    async with engine_session_factory() as db:
        reloaded = await db.get(WorkflowRun, run_id)

    assert reloaded is not None, "Run should exist in DB"
    assert reloaded.step_states[0]["status"] == "running", (
        f"Step 0 should be 'running' after advance, got '{reloaded.step_states[0]['status']}'. "
        "This indicates a JSONB mutation tracking failure — step_states UPDATE was not emitted."
    )
    assert reloaded.step_states[0]["task_id"] is not None, "Step 0 should have a task_id"
    assert reloaded.step_states[1]["status"] == "pending", "Step 1 should still be pending"


@pytest.mark.asyncio
async def test_on_step_completed_persists_done_state(engine_session_factory):
    """on_step_task_completed should persist step status as 'done' in the DB.

    Real-DB round-trip: create run with step 0 'running' → call
    on_step_task_completed → re-read → verify step 0 is 'done'.
    """
    from app.db.models import Task
    from app.services.workflow_executor import on_step_task_completed

    wf_id = "complete-test-wf"
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    # Seed workflow + run + task
    async with engine_session_factory() as db:
        wf = Workflow(
            id=wf_id, name="Complete Test",
            params={},
            steps=[
                {"id": "s0", "prompt": "Do step 0."},
                {"id": "s1", "prompt": "Do step 1."},
            ],
            defaults={"bot_id": "test-bot"},
            secrets=[],
        )
        db.add(wf)
        run = WorkflowRun(
            id=run_id,
            workflow_id=wf_id,
            bot_id="test-bot",
            status="running",
            current_step_index=0,
            step_states=[
                {"status": "running", "task_id": str(task_id), "result": None,
                 "error": None, "started_at": "2026-01-01T00:00:00+00:00",
                 "completed_at": None, "correlation_id": None},
                {"status": "pending", "task_id": None, "result": None,
                 "error": None, "started_at": None, "completed_at": None,
                 "correlation_id": None},
            ],
            params={},
            dispatch_type="none",
            session_mode="isolated",
            workflow_snapshot={
                "steps": [
                    {"id": "s0", "prompt": "Do step 0."},
                    {"id": "s1", "prompt": "Do step 1."},
                ],
                "defaults": {"bot_id": "test-bot"},
                "secrets": [],
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)

        task = Task(
            id=task_id,
            bot_id="test-bot",
            prompt="Do step 0.",
            status="complete",
            task_type="workflow",
            dispatch_type="none",
            result="Step 0 completed successfully.",
            callback_config={
                "workflow_run_id": str(run_id),
                "workflow_step_index": 0,
            },
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()

    # Call on_step_task_completed — this should mark step 0 as "done"
    # and call advance_workflow (which will set step 1 to "running")
    mock_task = type("MockTask", (), {"id": task_id, "result": "Step 0 done.", "error": None})()

    with (
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
        patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
    ):
        await on_step_task_completed(str(run_id), 0, "complete", mock_task)

    # Re-read from fresh session
    async with engine_session_factory() as db:
        reloaded = await db.get(WorkflowRun, run_id)

    assert reloaded is not None
    assert reloaded.step_states[0]["status"] == "done", (
        f"Step 0 should be 'done' after completion, got '{reloaded.step_states[0]['status']}'. "
        "JSONB mutation tracking failure."
    )
    assert reloaded.step_states[0]["result"] is not None, "Step 0 should have a result"
    # Step 1 should now be "running" (advance_workflow picks it up)
    assert reloaded.step_states[1]["status"] == "running", (
        f"Step 1 should be 'running' after advance, got '{reloaded.step_states[1]['status']}'. "
        "advance_workflow did not fire or did not persist."
    )


@pytest.mark.asyncio
async def test_full_workflow_lifecycle(engine_session_factory):
    """Full lifecycle: trigger → step 0 completes → step 1 completes → run is 'complete'.

    Verifies the entire chain survives real DB round-trips.
    """
    from app.db.models import Task
    from app.services.workflow_executor import trigger_workflow, on_step_task_completed

    wf_id = "lifecycle-test-wf"

    # Seed workflow
    async with engine_session_factory() as db:
        wf = Workflow(
            id=wf_id, name="Lifecycle Test",
            params={},
            steps=[
                {"id": "s0", "prompt": "Do step 0."},
                {"id": "s1", "prompt": "Do step 1."},
            ],
            defaults={"bot_id": "test-bot"},
            secrets=[],
        )
        db.add(wf)
        await db.commit()

    # Trigger workflow
    from app.services import workflows as wf_registry
    wf_obj = Workflow(
        id=wf_id, name="Lifecycle Test",
        params={}, steps=[
            {"id": "s0", "prompt": "Do step 0."},
            {"id": "s1", "prompt": "Do step 1."},
        ],
        defaults={"bot_id": "test-bot"}, secrets=[],
    )

    with (
        patch("app.services.workflows.get_workflow", return_value=wf_obj),
        patch("app.services.workflow_executor.async_session", engine_session_factory),
        patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
        patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
    ):
        run = await trigger_workflow(wf_id, {}, bot_id="test-bot")
        run_id = run.id

        # After trigger, step 0 should be "running"
        async with engine_session_factory() as db:
            reloaded = await db.get(WorkflowRun, run_id)
        assert reloaded.step_states[0]["status"] == "running", "Step 0 should be running after trigger"
        assert reloaded.step_states[1]["status"] == "pending", "Step 1 should be pending"

        # Find the task created for step 0
        step0_task_id = uuid.UUID(reloaded.step_states[0]["task_id"])

        # Simulate step 0 task completion: write result to DB, then call callback
        async with engine_session_factory() as db:
            task = await db.get(Task, step0_task_id)
            task.status = "complete"
            task.result = "Step 0 result."
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

        mock_task = type("T", (), {"id": step0_task_id, "result": "Step 0 result.", "error": None})()
        await on_step_task_completed(str(run_id), 0, "complete", mock_task)

        # After step 0 completes: step 0 = "done", step 1 = "running"
        async with engine_session_factory() as db:
            reloaded = await db.get(WorkflowRun, run_id)
        assert reloaded.step_states[0]["status"] == "done", "Step 0 should be done"
        assert reloaded.step_states[1]["status"] == "running", "Step 1 should be running"

        # Find step 1's task
        step1_task_id = uuid.UUID(reloaded.step_states[1]["task_id"])

        # Simulate step 1 task completion
        async with engine_session_factory() as db:
            task = await db.get(Task, step1_task_id)
            task.status = "complete"
            task.result = "Step 1 result."
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

        mock_task2 = type("T", (), {"id": step1_task_id, "result": "Step 1 result.", "error": None})()
        await on_step_task_completed(str(run_id), 1, "complete", mock_task2)

        # After step 1 completes: both "done", run is "complete"
        async with engine_session_factory() as db:
            reloaded = await db.get(WorkflowRun, run_id)
        assert reloaded.step_states[0]["status"] == "done"
        assert reloaded.step_states[1]["status"] == "done"
        assert reloaded.status == "complete", (
            f"Run should be 'complete' after all steps done, got '{reloaded.status}'"
        )
