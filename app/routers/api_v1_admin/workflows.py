"""Workflows CRUD + run management: /workflows, /workflow-runs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow, WorkflowRun
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WorkflowOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    params: dict = {}
    secrets: list[str] = []
    defaults: dict = {}
    steps: list[dict] = []
    triggers: dict = {}
    tags: list = []
    source_type: str = "manual"
    source_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowCreateIn(BaseModel):
    id: str
    name: str
    description: str | None = None
    params: dict = {}
    secrets: list[str] = []
    defaults: dict = {}
    steps: list[dict] = []
    triggers: dict = {}
    tags: list = []


class WorkflowUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    params: dict | None = None
    secrets: list[str] | None = None
    defaults: dict | None = None
    steps: list[dict] | None = None
    triggers: dict | None = None
    tags: list | None = None


class WorkflowRunOut(BaseModel):
    id: uuid.UUID
    workflow_id: str
    bot_id: str
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    params: dict = {}
    status: str
    current_step_index: int = 0
    step_states: list[dict] = []
    dispatch_type: str = "none"
    dispatch_config: dict | None = None
    triggered_by: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class TriggerWorkflowIn(BaseModel):
    params: dict = {}
    bot_id: str | None = None
    channel_id: uuid.UUID | None = None
    triggered_by: str = "api"


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:read")),
):
    rows = (await db.execute(select(Workflow).order_by(Workflow.name))).scalars().all()
    return [WorkflowOut.model_validate(r) for r in rows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:read")),
):
    row = await db.get(Workflow, workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowOut.model_validate(row)


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    body: WorkflowCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    wid = body.id.strip().lower().replace(" ", "-")
    if not wid or not body.name.strip():
        raise HTTPException(status_code=422, detail="id and name are required")

    existing = await db.get(Workflow, wid)
    if existing:
        raise HTTPException(status_code=409, detail=f"Workflow '{wid}' already exists")

    now = datetime.now(timezone.utc)
    row = Workflow(
        id=wid,
        name=body.name,
        description=body.description,
        params=body.params,
        secrets=body.secrets,
        defaults=body.defaults,
        steps=body.steps,
        triggers=body.triggers,
        tags=body.tags,
        source_type="manual",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    # Update in-memory registry
    from app.services.workflows import _registry
    _registry[row.id] = row
    return WorkflowOut.model_validate(row)


@router.put("/workflows/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    row = await db.get(Workflow, workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if row.source_type == "file":
        raise HTTPException(status_code=400, detail="Cannot update file-sourced workflows via API")

    data = body.model_dump(exclude_none=True)
    for field in ("name", "description", "params", "secrets", "defaults",
                   "steps", "triggers", "tags"):
        if field in data:
            setattr(row, field, data[field])
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    from app.services.workflows import _registry
    _registry[workflow_id] = row
    return WorkflowOut.model_validate(row)


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    row = await db.get(Workflow, workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(row)
    await db.commit()
    from app.services.workflows import _registry
    _registry.pop(workflow_id, None)


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------

@router.post("/workflows/{workflow_id}/run", response_model=WorkflowRunOut, status_code=201)
async def trigger_workflow_run(
    workflow_id: str,
    body: TriggerWorkflowIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    from app.services.workflow_executor import trigger_workflow
    try:
        run = await trigger_workflow(
            workflow_id,
            body.params,
            bot_id=body.bot_id,
            channel_id=body.channel_id,
            triggered_by=body.triggered_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Re-fetch to get latest state after advancement
    refreshed = await db.get(WorkflowRun, run.id)
    return WorkflowRunOut.model_validate(refreshed or run)


@router.get("/workflows/{workflow_id}/runs", response_model=list[WorkflowRunOut])
async def list_workflow_runs(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:read")),
    limit: int = 50,
):
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id)
        .order_by(desc(WorkflowRun.created_at))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [WorkflowRunOut.model_validate(r) for r in rows]


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunOut)
async def get_workflow_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:read")),
):
    row = await db.get(WorkflowRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return WorkflowRunOut.model_validate(row)


@router.post("/workflow-runs/{run_id}/cancel", response_model=WorkflowRunOut)
async def cancel_workflow_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in ("complete", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Run is already {run.status}")
    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return WorkflowRunOut.model_validate(run)


@router.post("/workflow-runs/{run_id}/steps/{step_index}/approve", response_model=WorkflowRunOut)
async def approve_workflow_step(
    run_id: uuid.UUID,
    step_index: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    from app.services.workflow_executor import approve_step
    try:
        run = await approve_step(run_id, step_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refreshed = await db.get(WorkflowRun, run.id)
    return WorkflowRunOut.model_validate(refreshed or run)


@router.post("/workflow-runs/{run_id}/steps/{step_index}/skip", response_model=WorkflowRunOut)
async def skip_workflow_step(
    run_id: uuid.UUID,
    step_index: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    from app.services.workflow_executor import skip_step
    try:
        run = await skip_step(run_id, step_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refreshed = await db.get(WorkflowRun, run.id)
    return WorkflowRunOut.model_validate(refreshed or run)


@router.post("/workflow-runs/{run_id}/steps/{step_index}/retry", response_model=WorkflowRunOut)
async def retry_workflow_step(
    run_id: uuid.UUID,
    step_index: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workflows:write")),
):
    from app.services.workflow_executor import retry_step
    try:
        run = await retry_step(run_id, step_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refreshed = await db.get(WorkflowRun, run.id)
    return WorkflowRunOut.model_validate(refreshed or run)
