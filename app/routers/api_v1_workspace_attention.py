"""Workspace Attention API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import (
    acknowledge_attention_item,
    acknowledge_attention_items_bulk,
    assign_attention_item,
    actor_label,
    create_attention_triage_run,
    create_issue_intake_note,
    create_issue_intake_triage_run,
    create_manual_issue_work_pack,
    create_user_attention_item,
    get_attention_brief,
    get_attention_triage_run,
    get_attention_item,
    get_issue_intake_triage_run,
    get_issue_work_pack,
    launch_issue_work_pack_project_run,
    launch_issue_work_packs_project_runs,
    list_issue_intake_triage_runs,
    list_issue_work_packs,
    list_attention_triage_runs,
    list_attention_items,
    mark_attention_responded,
    record_attention_triage_feedback,
    resolve_attention_item,
    serialize_attention_item,
    serialize_attention_items,
    serialize_issue_work_pack,
    transition_issue_work_pack,
    unassign_attention_item,
    update_issue_work_pack,
)


router = APIRouter(prefix="/workspace/attention", tags=["workspace-attention"])


class AttentionStatusRequest(BaseModel):
    message_id: uuid.UUID | None = None


class AttentionResolveRequest(BaseModel):
    resolution: str | None = None
    note: str | None = None
    duplicate_of: uuid.UUID | None = None


class AttentionCreateRequest(BaseModel):
    channel_id: uuid.UUID | None = None
    target_kind: str = "channel"
    target_id: str | None = None
    title: str
    message: str = ""
    severity: str = "warning"
    requires_response: bool = True
    next_steps: list[str] = Field(default_factory=list)


class AttentionAssignRequest(BaseModel):
    bot_id: str
    mode: str = "next_heartbeat"
    instructions: str | None = None


class AttentionBulkAcknowledgeRequest(BaseModel):
    scope: str = "workspace_visible"
    target_kind: str | None = None
    target_id: str | None = None
    channel_id: uuid.UUID | None = None


class AttentionTriageRunRequest(BaseModel):
    scope: str = "all_active"
    model_override: str | None = None
    model_provider_id_override: str | None = None


class AttentionTriageFeedbackRequest(BaseModel):
    verdict: str
    note: str | None = None
    route: str | None = None


class AttentionTriageRunsResponse(BaseModel):
    runs: list[dict]


class IssueWorkPacksResponse(BaseModel):
    work_packs: list[dict]


class IssueIntakeCreateRequest(BaseModel):
    channel_id: uuid.UUID | None = None
    title: str
    summary: str
    observed_behavior: str | None = None
    expected_behavior: str | None = None
    steps: list[str] = Field(default_factory=list)
    severity: str = "warning"
    category_hint: str = "bug"
    project_hint: str | None = None
    tags: list[str] = Field(default_factory=list)


class IssueWorkPackCreateRequest(BaseModel):
    title: str
    summary: str = ""
    category: str = "code_bug"
    confidence: str = "medium"
    source_item_ids: list[uuid.UUID] = Field(default_factory=list)
    launch_prompt: str = ""
    project_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    metadata: dict = Field(default_factory=dict)


class IssueWorkPackLaunchRequest(BaseModel):
    project_id: uuid.UUID
    channel_id: uuid.UUID


class IssueWorkPackBatchLaunchRequest(BaseModel):
    work_pack_ids: list[uuid.UUID]
    project_id: uuid.UUID
    channel_id: uuid.UUID
    note: str | None = None


class IssueWorkPackUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    confidence: str | None = None
    source_item_ids: list[uuid.UUID] | None = None
    launch_prompt: str | None = None
    project_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None


class IssueWorkPackActionRequest(BaseModel):
    note: str | None = None


@router.post("")
async def create_attention_item_route(
    body: AttentionCreateRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_id = body.target_id or (str(body.channel_id) if body.channel_id and body.target_kind == "channel" else None)
        if not target_id:
            raise ValidationError("target_id is required unless target_kind is channel and channel_id is set.")
        item = await create_user_attention_item(
            db,
            actor=actor_label(auth) or "user",
            channel_id=body.channel_id,
            target_kind=body.target_kind,
            target_id=target_id,
            title=body.title,
            message=body.message,
            severity=body.severity,
            requires_response=body.requires_response,
            next_steps=body.next_steps,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/issue-intake", status_code=201)
async def create_issue_intake_route(
    body: IssueIntakeCreateRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await create_issue_intake_note(
            db,
            actor=actor_label(auth) or "user",
            channel_id=body.channel_id,
            title=body.title,
            summary=body.summary,
            observed_behavior=body.observed_behavior,
            expected_behavior=body.expected_behavior,
            steps=body.steps,
            severity=body.severity,
            category_hint=body.category_hint,
            project_hint=body.project_hint,
            tags=body.tags,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/acknowledge-bulk")
async def acknowledge_attention_bulk(
    body: AttentionBulkAcknowledgeRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        items = await acknowledge_attention_items_bulk(
            db,
            auth=auth,
            scope=body.scope,
            target_kind=body.target_kind,
            target_id=body.target_id,
            channel_id=body.channel_id,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    serialized = await serialize_attention_items(db, items)
    return {
        "count": len(items),
        "item_ids": [item["id"] for item in serialized],
        "items": serialized,
    }


@router.post("/triage-runs")
async def create_attention_triage_run_route(
    body: AttentionTriageRunRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    if body.scope != "all_active":
        raise HTTPException(400, "scope must be all_active.")
    try:
        return await create_attention_triage_run(
            db,
            auth=auth,
            actor=actor_label(auth),
            model_override=body.model_override,
            model_provider_id_override=body.model_provider_id_override,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/triage-runs", response_model=AttentionTriageRunsResponse)
async def list_attention_triage_runs_route(
    limit: int = 20,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return {"runs": await list_attention_triage_runs(db, auth=auth, limit=limit)}


@router.get("/triage-runs/{task_id}")
async def get_attention_triage_run_route(
    task_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_attention_triage_run(db, auth=auth, task_id=task_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/issue-triage-runs")
async def create_issue_triage_run_route(
    body: AttentionTriageRunRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    if body.scope != "all_active":
        raise HTTPException(400, "scope must be all_active.")
    try:
        return await create_issue_intake_triage_run(
            db,
            auth=auth,
            actor=actor_label(auth),
            model_override=body.model_override,
            model_provider_id_override=body.model_provider_id_override,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/issue-triage-runs", response_model=AttentionTriageRunsResponse)
async def list_issue_triage_runs_route(
    limit: int = 20,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return {"runs": await list_issue_intake_triage_runs(db, auth=auth, limit=limit)}


@router.get("/issue-triage-runs/{task_id}")
async def get_issue_triage_run_route(
    task_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_issue_intake_triage_run(db, auth=auth, task_id=task_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/issue-work-packs", response_model=IssueWorkPacksResponse)
async def list_issue_work_packs_route(
    status: str | None = None,
    limit: int = 50,
    _auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return {"work_packs": await list_issue_work_packs(db, status=status, limit=limit)}


@router.post("/issue-work-packs", status_code=201)
async def create_issue_work_pack_route(
    body: IssueWorkPackCreateRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        pack = await create_manual_issue_work_pack(
            db,
            actor=actor_label(auth),
            title=body.title,
            summary=body.summary,
            category=body.category,
            confidence=body.confidence,
            source_item_ids=[str(item_id) for item_id in body.source_item_ids],
            launch_prompt=body.launch_prompt,
            project_id=body.project_id,
            channel_id=body.channel_id,
            metadata=body.metadata,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.get("/issue-work-packs/{pack_id}")
async def get_issue_work_pack_route(
    pack_id: uuid.UUID,
    _auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        pack = await get_issue_work_pack(db, pack_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.patch("/issue-work-packs/{pack_id}")
async def update_issue_work_pack_route(
    pack_id: uuid.UUID,
    body: IssueWorkPackUpdateRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    fields = {name: getattr(body, name) for name in body.model_fields_set}
    if "source_item_ids" in fields and fields["source_item_ids"] is not None:
        fields["source_item_ids"] = [str(item_id) for item_id in fields["source_item_ids"]]
    try:
        pack = await update_issue_work_pack(db, pack_id, actor=actor_label(auth), fields=fields)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.post("/issue-work-packs/{pack_id}/dismiss")
async def dismiss_issue_work_pack_route(
    pack_id: uuid.UUID,
    body: IssueWorkPackActionRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        pack = await transition_issue_work_pack(db, pack_id, actor=actor_label(auth), action="dismiss", note=body.note)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.post("/issue-work-packs/{pack_id}/needs-info")
async def needs_info_issue_work_pack_route(
    pack_id: uuid.UUID,
    body: IssueWorkPackActionRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        pack = await transition_issue_work_pack(db, pack_id, actor=actor_label(auth), action="needs_info", note=body.note)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.post("/issue-work-packs/{pack_id}/reopen")
async def reopen_issue_work_pack_route(
    pack_id: uuid.UUID,
    body: IssueWorkPackActionRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        pack = await transition_issue_work_pack(db, pack_id, actor=actor_label(auth), action="reopen", note=body.note)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"work_pack": await serialize_issue_work_pack(db, pack)}


@router.post("/issue-work-packs/{pack_id}/launch-project-run")
async def launch_issue_work_pack_route(
    pack_id: uuid.UUID,
    body: IssueWorkPackLaunchRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await launch_issue_work_pack_project_run(
            db,
            pack_id=pack_id,
            project_id=body.project_id,
            channel_id=body.channel_id,
            actor=actor_label(auth),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/issue-work-packs/batch-launch-project-runs")
async def batch_launch_issue_work_packs_route(
    body: IssueWorkPackBatchLaunchRequest,
    auth=Depends(require_scopes("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await launch_issue_work_packs_project_runs(
            db,
            pack_ids=body.work_pack_ids,
            project_id=body.project_id,
            channel_id=body.channel_id,
            actor=actor_label(auth),
            note=body.note,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.get("")
async def get_attention_items(
    status: str | None = None,
    channel_id: uuid.UUID | None = None,
    include_resolved: bool = False,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    items = await list_attention_items(
        db,
        auth=auth,
        status=status,
        channel_id=channel_id,
        include_resolved=include_resolved,
    )
    return {"items": await serialize_attention_items(db, items)}


@router.get("/brief")
async def get_attention_brief_route(
    channel_id: uuid.UUID | None = None,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_attention_brief(db, auth=auth, channel_id=channel_id)


@router.get("/{item_id}")
async def get_attention_item_route(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await get_attention_item(db, item_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    if item.source_type == "system" and "admin" not in getattr(auth, "scopes", []) and not getattr(auth, "is_admin", False):
        raise HTTPException(404, "Attention item not found.")
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/acknowledge")
async def acknowledge_attention(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await acknowledge_attention_item(db, item_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/triage-feedback")
async def attention_triage_feedback(
    item_id: uuid.UUID,
    body: AttentionTriageFeedbackRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await record_attention_triage_feedback(
            db,
            item_id,
            verdict=body.verdict,
            actor=actor_label(auth),
            note=body.note,
            route=body.route,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/responded")
async def responded_attention(
    item_id: uuid.UUID,
    body: AttentionStatusRequest | None = None,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await mark_attention_responded(
            db,
            item_id,
            response_message_id=body.message_id if body else None,
            responded_by=actor_label(auth),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/resolve")
async def resolve_attention(
    item_id: uuid.UUID,
    body: AttentionResolveRequest | None = None,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await resolve_attention_item(
            db,
            item_id,
            resolved_by=actor_label(auth),
            resolution=body.resolution if body else None,
            note=body.note if body else None,
            duplicate_of=body.duplicate_of if body else None,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/assign")
async def assign_attention(
    item_id: uuid.UUID,
    body: AttentionAssignRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await assign_attention_item(
            db,
            item_id,
            bot_id=body.bot_id,
            mode=body.mode,
            instructions=body.instructions,
            assigned_by=actor_label(auth),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/unassign")
async def unassign_attention(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await unassign_attention_item(db, item_id, actor=actor_label(auth))
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}
