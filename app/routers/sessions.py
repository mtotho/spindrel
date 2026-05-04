import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.agent.bots import get_bot
from app.config import settings
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Channel, Message, Session, TraceEvent
from app.dependencies import get_db, require_scopes, verify_user
from app.schemas.messages import AttachmentBrief, FeedbackBlock, FeedbackTotals, MessageOut
from app.services.compaction import run_compaction_forced
from app.services import presence
from app.services.machine_control import (
    DEFAULT_LEASE_TTL_SECONDS,
    MAX_LEASE_TTL_SECONDS,
    build_session_machine_target_payload,
    clear_session_lease_row,
    grant_session_lease,
)
from app.services.plan_semantic_review import review_plan_adherence
from app.services.session_plan_mode import (
    STEP_STATUS_BLOCKED,
    STEP_STATUS_DONE,
    STEP_STATUS_IN_PROGRESS,
    STEP_STATUS_PENDING,
    build_session_plan_revision_diff,
    approve_session_plan,
    create_session_plan,
    enter_session_plan_mode,
    exit_session_plan_mode,
    get_session_plan_state,
    get_session_plan_mode,
    record_plan_question_answers,
    build_session_plan_response,
    list_session_plans,
    list_session_plan_revisions,
    load_session_plan,
    load_session_plan_revision,
    publish_session_plan_event,
    request_plan_replan,
    resume_session_plan_mode,
    update_planning_state,
    update_plan_step_status,
    update_session_plan,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionSummary(BaseModel):
    id: uuid.UUID
    client_id: str
    bot_id: str
    title: Optional[str] = None
    created_at: datetime
    last_active: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]


class PlanStepOut(BaseModel):
    id: str
    label: str
    status: str
    note: Optional[str] = None


class PlanArtifactOut(BaseModel):
    kind: str
    label: str
    ref: Optional[str] = None
    created_at: Optional[str] = None
    metadata: dict[str, Any] = {}


class PlanRevisionOut(BaseModel):
    revision: int
    title: str
    status: str
    summary: str
    path: Optional[str] = None
    created_at: Optional[str] = None
    is_active: bool
    is_accepted: bool
    source: str
    changed_sections: list[str] = []


class PlanRevisionDiffOut(BaseModel):
    from_revision: int
    to_revision: int
    changed_sections: list[str]
    diff: str


class SessionPlanOut(BaseModel):
    title: str
    status: str
    revision: int
    session_id: str
    task_slug: str
    summary: str
    scope: str
    key_changes: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    assumptions: list[str]
    assumptions_and_defaults: list[str] = Field(default_factory=list)
    open_questions: list[str]
    steps: list[PlanStepOut]
    test_plan: list[str] = Field(default_factory=list)
    artifacts: list[PlanArtifactOut]
    acceptance_criteria: list[str]
    risks: list[str] = Field(default_factory=list)
    outcome: str
    path: Optional[str] = None
    mode: str
    accepted_revision: Optional[int] = None
    revisions: list[PlanRevisionOut] = []
    planning_state: Optional[dict[str, Any]] = None
    adherence: Optional[dict[str, Any]] = None
    runtime: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None


class SessionPlanStateOut(BaseModel):
    mode: str
    has_plan: bool
    path: Optional[str] = None
    task_slug: Optional[str] = None
    revision: Optional[int] = None
    accepted_revision: Optional[int] = None
    status: Optional[str] = None
    revision_count: int = 0
    planning_state: Optional[dict[str, Any]] = None
    adherence: Optional[dict[str, Any]] = None
    runtime: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None


class SessionPlanCreateRequest(BaseModel):
    title: str
    summary: Optional[str] = None
    scope: Optional[str] = None
    key_changes: Optional[list[str]] = None
    interfaces: Optional[list[str]] = None
    assumptions: Optional[list[str]] = None
    assumptions_and_defaults: Optional[list[str]] = None
    open_questions: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None
    test_plan: Optional[list[str]] = None
    risks: Optional[list[str]] = None
    steps: Optional[list[dict[str, Any]]] = None


class SessionPlanUpdateRequest(BaseModel):
    revision: int
    title: Optional[str] = None
    summary: Optional[str] = None
    scope: Optional[str] = None
    key_changes: Optional[list[str]] = None
    interfaces: Optional[list[str]] = None
    assumptions: Optional[list[str]] = None
    assumptions_and_defaults: Optional[list[str]] = None
    open_questions: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None
    test_plan: Optional[list[str]] = None
    risks: Optional[list[str]] = None
    steps: Optional[list[dict[str, Any]]] = None
    outcome: Optional[str] = None


class PlanStatusUpdateRequest(BaseModel):
    status: str
    note: Optional[str] = None
    revision: Optional[int] = None


class PlanApproveRequest(BaseModel):
    revision: Optional[int] = None


class PlanReplanRequest(BaseModel):
    reason: str
    affected_step_ids: Optional[list[str]] = None
    evidence: Optional[str] = None
    revision: Optional[int] = None


class PlanSemanticReviewRequest(BaseModel):
    correlation_id: Optional[str] = None


class PlanningStateUpdateRequest(BaseModel):
    decisions: Optional[list[str | dict[str, Any]]] = None
    open_questions: Optional[list[str | dict[str, Any]]] = None
    assumptions: Optional[list[str | dict[str, Any]]] = None
    constraints: Optional[list[str | dict[str, Any]]] = None
    non_goals: Optional[list[str | dict[str, Any]]] = None
    evidence: Optional[list[str | dict[str, Any]]] = None
    preference_changes: Optional[list[str | dict[str, Any]]] = None
    reason: Optional[str] = None


class PlanQuestionAnswer(BaseModel):
    question_id: Optional[str] = None
    label: str
    answer: str


class PlanQuestionAnswersRequest(BaseModel):
    title: str
    answers: list[PlanQuestionAnswer]
    source_message_id: Optional[str] = None


class SessionMachineTargetLeaseOut(BaseModel):
    lease_id: str
    provider_id: str
    target_id: str
    user_id: str
    granted_at: str
    expires_at: str
    capabilities: list[str]
    handle_id: str | None = None
    connection_id: str | None = None
    ready: bool = False
    status: str | None = None
    status_label: str | None = None
    reason: str | None = None
    checked_at: str | None = None
    connected: bool
    provider_label: str | None = None
    target_label: str


class SessionMachineTargetOut(BaseModel):
    session_id: str
    lease: SessionMachineTargetLeaseOut | None = None
    targets: list[dict[str, Any]]
    ready_target_count: int | None = None
    connected_target_count: int | None = None


class SessionMachineTargetLeaseRequest(BaseModel):
    provider_id: str
    target_id: str
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS


def _serialize_plan(session: Session) -> SessionPlanOut:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    payload = build_session_plan_response(session, plan)
    assert payload is not None
    return SessionPlanOut(**payload)


def _serialize_plan_revision(session: Session, revision: int) -> SessionPlanOut:
    plan = load_session_plan_revision(session, revision, prefer_snapshot=False, required=True)
    assert plan is not None
    payload = build_session_plan_response(session, plan)
    assert payload is not None
    return SessionPlanOut(**payload)


def _serialize_plan_state(session: Session) -> SessionPlanStateOut:
    return SessionPlanStateOut(**get_session_plan_state(session))


def _assert_expected_plan_revision(session: Session, expected_revision: int | None) -> None:
    if expected_revision is None:
        return
    plan = load_session_plan(session, required=True)
    assert plan is not None
    if expected_revision != plan.revision:
        raise HTTPException(
            status_code=409,
            detail=f"Revision mismatch. Expected {plan.revision}.",
        )


def _require_admin_user(user) -> None:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    client_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    stmt = select(Session).order_by(Session.last_active.desc())
    if client_id:
        stmt = stmt.where(Session.client_id == client_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    messages = [m for m in messages if not (m.metadata_ or {}).get("ui_hidden")]
    if session.channel_id:
        await _recover_orphan_attachments(db, session.channel_id, messages)
    return SessionDetail(session=session, messages=[MessageOut.from_orm(m) for m in messages])


@router.get("/{session_id}/plans")
async def get_session_plans(
    session_id: uuid.UUID,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return list_session_plans(session, status=status)


@router.get("/{session_id}/plan", response_model=SessionPlanOut)
async def get_session_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize_plan(session)


@router.get("/{session_id}/plan/revisions", response_model=list[PlanRevisionOut])
async def get_session_plan_revisions(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return [PlanRevisionOut(**entry) for entry in list_session_plan_revisions(session)]


@router.get("/{session_id}/plan/revisions/{revision}", response_model=SessionPlanOut)
async def get_session_plan_revision(
    session_id: uuid.UUID,
    revision: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize_plan_revision(session, revision)


@router.get("/{session_id}/plan/diff", response_model=PlanRevisionDiffOut)
async def get_session_plan_diff(
    session_id: uuid.UUID,
    from_revision: int,
    to_revision: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return PlanRevisionDiffOut(**build_session_plan_revision_diff(
        session,
        from_revision=from_revision,
        to_revision=to_revision,
    ))


@router.get("/{session_id}/plan-state", response_model=SessionPlanStateOut)
async def get_session_plan_state_route(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize_plan_state(session)


@router.patch("/{session_id}/plan/planning-state", response_model=SessionPlanStateOut)
async def patch_session_planning_state(
    session_id: uuid.UUID,
    body: PlanningStateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    update_planning_state(
        session,
        decisions=body.decisions,
        open_questions=body.open_questions,
        assumptions=body.assumptions,
        constraints=body.constraints,
        non_goals=body.non_goals,
        evidence=body.evidence,
        preference_changes=body.preference_changes,
        reason=body.reason or "planning_state_route",
    )
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "planning_state")
    return _serialize_plan_state(session)


@router.post("/{session_id}/plan/question-answers", response_model=SessionPlanStateOut)
async def submit_plan_question_answers(
    session_id: uuid.UUID,
    body: PlanQuestionAnswersRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    record_plan_question_answers(
        session,
        title=body.title,
        answers=[answer.model_dump() for answer in body.answers],
        source_message_id=body.source_message_id,
    )
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "question_answers")
    return _serialize_plan_state(session)


@router.post("/{session_id}/plan/start", response_model=SessionPlanStateOut)
async def start_session_plan_mode(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    enter_session_plan_mode(session)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "start")
    return _serialize_plan_state(session)


@router.post("/{session_id}/plans", response_model=SessionPlanOut)
async def start_session_plan(
    session_id: uuid.UUID,
    body: SessionPlanCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    create_session_plan(
        session,
        title=body.title,
        summary=body.summary,
        scope=body.scope,
        key_changes=body.key_changes,
        interfaces=body.interfaces,
        assumptions=body.assumptions,
        assumptions_and_defaults=body.assumptions_and_defaults,
        open_questions=body.open_questions,
        acceptance_criteria=body.acceptance_criteria,
        test_plan=body.test_plan,
        risks=body.risks,
        steps=body.steps,
    )
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "create")
    return _serialize_plan(session)


@router.patch("/{session_id}/plan", response_model=SessionPlanOut)
async def patch_session_plan(
    session_id: uuid.UUID,
    body: SessionPlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    update_session_plan(
        session,
        revision=body.revision,
        title=body.title,
        summary=body.summary,
        scope=body.scope,
        key_changes=body.key_changes,
        interfaces=body.interfaces,
        assumptions=body.assumptions,
        assumptions_and_defaults=body.assumptions_and_defaults,
        open_questions=body.open_questions,
        acceptance_criteria=body.acceptance_criteria,
        test_plan=body.test_plan,
        risks=body.risks,
        steps=body.steps,
        outcome=body.outcome,
    )
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "revise")
    return _serialize_plan(session)


@router.post("/{session_id}/plan/approve", response_model=SessionPlanOut)
async def approve_plan(
    session_id: uuid.UUID,
    body: PlanApproveRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_expected_plan_revision(session, body.revision if body else None)
    approve_session_plan(session)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "approve")
    return _serialize_plan(session)


@router.post("/{session_id}/plan/replan", response_model=SessionPlanOut)
async def replan(
    session_id: uuid.UUID,
    body: PlanReplanRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    request_plan_replan(
        session,
        reason=body.reason,
        affected_step_ids=body.affected_step_ids,
        evidence=body.evidence,
        revision=body.revision,
    )
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "replan")
    return _serialize_plan(session)


@router.post("/{session_id}/plan/review-adherence", response_model=SessionPlanOut)
async def review_adherence(
    session_id: uuid.UUID,
    body: PlanSemanticReviewRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await review_plan_adherence(db, session, correlation_id=body.correlation_id)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "semantic_review")
    return _serialize_plan(session)


@router.post("/{session_id}/plan/exit", response_model=dict)
async def exit_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    exit_session_plan_mode(session)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "exit")
    return {"ok": True, "mode": get_session_plan_mode(session)}


@router.post("/{session_id}/plan/resume", response_model=SessionPlanOut)
async def resume_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    resume_session_plan_mode(session)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "resume")
    return _serialize_plan(session)


@router.post("/{session_id}/plans/{plan_id}/status", response_model=SessionPlanOut)
async def update_plan_status_legacy(
    session_id: uuid.UUID,
    plan_id: str,
    body: PlanStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    plan = load_session_plan(session, required=False)
    if plan is None or plan.task_slug != plan_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    if body.status == "complete":
        status = STEP_STATUS_DONE
        for step in plan.steps:
            if step.status != STEP_STATUS_DONE:
                update_plan_step_status(session, step_id=step.id, status=STEP_STATUS_DONE)
    elif body.status == "blocked":
        active = next((step for step in plan.steps if step.status == STEP_STATUS_IN_PROGRESS), None)
        if active is None:
            raise HTTPException(status_code=404, detail="Plan has no active step")
        update_plan_step_status(session, step_id=active.id, status=STEP_STATUS_BLOCKED, note=body.note)
    else:
        raise HTTPException(status_code=422, detail="Unsupported plan status update.")
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "step_status")
    return _serialize_plan(session)


@router.post("/{session_id}/plans/{plan_id}/items/{item_id}/status", response_model=SessionPlanOut)
async def update_plan_item_status_legacy(
    session_id: uuid.UUID,
    plan_id: str,
    item_id: str,
    body: PlanStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    plan = load_session_plan(session, required=False)
    if plan is None or plan.task_slug != plan_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    mapping = {
        "pending": STEP_STATUS_PENDING,
        "in_progress": STEP_STATUS_IN_PROGRESS,
        "done": STEP_STATUS_DONE,
        "blocked": STEP_STATUS_BLOCKED,
    }
    status = mapping.get(body.status)
    if status is None:
        raise HTTPException(status_code=422, detail="Unsupported plan item status.")
    _assert_expected_plan_revision(session, body.revision)
    update_plan_step_status(session, step_id=item_id, status=status, note=body.note)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "step_status")
    return _serialize_plan(session)


@router.post("/{session_id}/plan/steps/{step_id}/status", response_model=SessionPlanOut)
async def update_plan_step_status_route(
    session_id: uuid.UUID,
    step_id: str,
    body: PlanStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_expected_plan_revision(session, body.revision)
    update_plan_step_status(session, step_id=step_id, status=body.status, note=body.note)
    await db.commit()
    await db.refresh(session)
    publish_session_plan_event(session, "step_status")
    return _serialize_plan(session)


class MessagePage(BaseModel):
    messages: list[MessageOut]
    has_more: bool


import logging
_logger = logging.getLogger(__name__)


def _should_hide_from_session_history(message: "Message") -> bool:
    meta = message.metadata_ or {}
    return bool(meta.get("hidden")) and not bool(meta.get("pipeline_step"))


async def _recover_orphan_attachments(
    db: AsyncSession,
    channel_id: uuid.UUID,
    messages: list["Message"],
) -> None:
    """Find attachments with message_id=NULL in this channel and link them to
    the nearest assistant message.  This is a fallback for when persist_turn's
    orphan-linking step fails silently (try/except swallows errors)."""
    orphan_result = await db.execute(
        select(Attachment)
        .where(
            Attachment.channel_id == channel_id,
            Attachment.message_id.is_(None),
        )
    )
    orphans = list(orphan_result.scalars().all())
    if not orphans:
        return

    _logger.warning(
        "Found %d orphaned attachment(s) in channel %s — recovering",
        len(orphans), channel_id,
    )

    # Build time-sorted list of assistant messages from the loaded set
    assistant_msgs = [
        m for m in messages if m.role == "assistant"
    ]
    if not assistant_msgs:
        return

    linked = 0
    for att in orphans:
        # Find the closest assistant message by time (prefer one created AFTER the attachment)
        best = None
        for m in assistant_msgs:
            if m.created_at >= att.created_at:
                best = m
                break
        if best is None:
            # Fallback: use the last assistant message
            best = assistant_msgs[-1]
        att.message_id = best.id
        # Also populate the in-memory relationship so the current response includes it
        if not hasattr(best, "attachments") or best.attachments is None:
            best.attachments = []
        best.attachments.append(att)
        linked += 1

    if linked:
        await db.commit()
        _logger.info("Recovered %d orphan attachment(s) in channel %s", linked, channel_id)


async def _hydrate_turn_feedback(
    db: AsyncSession,
    *,
    messages: list["Message"],
    serialized: list[MessageOut],
    user_id: uuid.UUID | None,
) -> None:
    correlation_ids = [
        m.correlation_id for m in messages
        if m.role == "assistant" and m.correlation_id is not None
    ]
    if not correlation_ids:
        return

    from app.services.turn_feedback import (
        anchor_message_ids_for_correlations,
        feedback_for_correlation_ids,
    )

    unique_cids = list({c for c in correlation_ids})
    summaries = await feedback_for_correlation_ids(
        db,
        correlation_ids=unique_cids,
        user_id=user_id,
    )
    anchor_by_cid = await anchor_message_ids_for_correlations(db, unique_cids)
    anchor_ids = set(anchor_by_cid.values())

    for message_out in serialized:
        if message_out.id not in anchor_ids or message_out.correlation_id is None:
            continue
        summary = summaries.get(message_out.correlation_id)
        if summary is None:
            continue
        message_out.feedback = FeedbackBlock(
            mine=summary.mine,
            totals=FeedbackTotals(**summary.totals),
            comment_mine=summary.comment_mine,
        )


@router.get("/{session_id}/messages", response_model=MessagePage)
async def get_session_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    before: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Cursor-based paginated messages. Returns newest first. Use `before` with the oldest message id to load older messages."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    cursor_created_at: datetime | None = None
    if before:
        cursor_msg = await db.get(Message, before)
        if cursor_msg:
            cursor_created_at = cursor_msg.created_at

    visible_rows: list[Message] = []
    has_more = False

    while len(visible_rows) < limit + 1:
        stmt = (
            select(Message)
            .options(selectinload(Message.attachments))
            .where(Message.session_id == session_id)
        )
        if cursor_created_at is not None:
            stmt = stmt.where(Message.created_at < cursor_created_at)
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit + 1)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            break

        for row in rows:
            if _should_hide_from_session_history(row):
                continue
            visible_rows.append(row)
            if len(visible_rows) > limit:
                has_more = True
                break

        if has_more:
            break

        if len(rows) <= limit:
            break

        cursor_created_at = rows[-1].created_at

    messages = visible_rows[:limit]
    # Reverse to chronological order
    messages.reverse()
    messages = [m for m in messages if not (m.metadata_ or {}).get("ui_hidden")]

    # Recover orphaned attachments: if persist_turn's orphan linking failed,
    # attachments created by send_file have message_id=NULL.  Link them now.
    if session.channel_id:
        await _recover_orphan_attachments(db, session.channel_id, messages)

    out = [MessageOut.from_orm(m) for m in messages]
    user_id = getattr(_auth, "id", None)
    await _hydrate_turn_feedback(
        db,
        messages=messages,
        serialized=out,
        user_id=user_id,
    )
    return MessagePage(messages=out, has_more=has_more)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


@router.get("/{session_id}/context")
async def get_session_context(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return the most recent context_breakdown trace event for the session,
    plus last compression info if available."""
    result = await db.execute(
        select(TraceEvent)
        .where(TraceEvent.session_id == session_id, TraceEvent.event_type == "context_breakdown")
        .order_by(TraceEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is None or not event.data:
        return {"breakdown": None, "total_chars": 0, "total_messages": 0, "iteration": None, "created_at": None}

    return {
        "breakdown": event.data.get("breakdown"),
        "total_chars": event.data.get("total_chars", 0),
        "total_messages": event.data.get("total_messages", 0),
        "iteration": event.data.get("iteration"),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.get("/{session_id}/context/contents")
async def get_session_context_contents(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Dump the actual messages that would go to the model."""
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    messages = await _load_messages(db, session)

    # Sanitize messages for display — strip huge binary content
    display_messages = []
    for m in messages:
        dm = {"role": m.get("role", "?"), "content": m.get("content")}
        if m.get("tool_calls"):
            dm["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            dm["tool_call_id"] = m["tool_call_id"]
        display_messages.append(dm)

    return {
        "session_id": str(session_id),
        "total_messages": len(display_messages),
        "total_chars": sum(
            len(str(m.get("content", ""))) for m in display_messages
        ),
        "messages": display_messages,
    }


@router.get("/{session_id}/context/diagnostics")
async def get_session_context_diagnostics(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return compaction diagnostic info for a session."""
    from app.services.compaction import (
        _get_compaction_interval,
        _get_compaction_keep_turns,
        _is_compaction_enabled,
    )

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    channel: Channel | None = None
    if session.channel_id:
        channel = await db.get(Channel, session.channel_id)

    # Count total messages and user messages in session
    total_msg_count = (await db.execute(
        select(func.count()).where(Message.session_id == session_id)
    )).scalar() or 0

    total_user_count = (await db.execute(
        select(func.count())
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
    )).scalar() or 0

    # Count user messages since watermark (what compaction checks)
    if session.summary_message_id:
        watermark_msg = await db.get(Message, session.summary_message_id)
        watermark_created = watermark_msg.created_at if watermark_msg else None
        if watermark_msg:
            user_since_watermark = (await db.execute(
                select(func.count())
                .where(Message.session_id == session_id)
                .where(Message.role == "user")
                .where(Message.created_at > watermark_msg.created_at)
            )).scalar() or 0
            msgs_since_watermark = (await db.execute(
                select(func.count())
                .where(Message.session_id == session_id)
                .where(Message.created_at > watermark_msg.created_at)
            )).scalar() or 0
        else:
            user_since_watermark = total_user_count
            msgs_since_watermark = total_msg_count
            watermark_created = None
    else:
        user_since_watermark = total_user_count
        msgs_since_watermark = total_msg_count
        watermark_created = None

    # Last compaction trace event
    last_compaction = (await db.execute(
        select(TraceEvent)
        .where(TraceEvent.session_id == session_id)
        .where(TraceEvent.event_type == "compaction_done")
        .order_by(TraceEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    compaction_enabled = _is_compaction_enabled(bot, channel)
    compaction_interval = _get_compaction_interval(bot, channel) if compaction_enabled else None
    compaction_keep_turns = _get_compaction_keep_turns(bot, channel) if compaction_enabled else None

    return {
        "session_id": str(session_id),
        "total_messages": total_msg_count,
        "total_user_turns": total_user_count,
        "compaction": {
            "enabled": compaction_enabled,
            "interval": compaction_interval,
            "keep_turns": compaction_keep_turns,
            "has_summary": bool(session.summary),
            "has_watermark": bool(session.summary_message_id),
            "watermark_created_at": watermark_created.isoformat() if watermark_created else None,
            "user_turns_since_watermark": user_since_watermark,
            "msgs_since_watermark": msgs_since_watermark,
            "turns_until_next": (
                max(0, compaction_interval - user_since_watermark)
                if compaction_enabled and compaction_interval else None
            ),
            "last_compaction_at": (
                last_compaction.created_at.isoformat() if last_compaction else None
            ),
        },
    }


class SummarizeResponse(BaseModel):
    title: str
    summary: str


@router.get("/{session_id}/machine-target", response_model=SessionMachineTargetOut)
async def get_session_machine_target(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    presence.mark_active(user.id)
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.post("/{session_id}/machine-target/lease", response_model=SessionMachineTargetOut)
async def grant_session_machine_target_lease(
    session_id: uuid.UUID,
    body: SessionMachineTargetLeaseRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    presence.mark_active(user.id)
    try:
        await grant_session_lease(
            db,
            session=session,
            user=user,
            provider_id=body.provider_id,
            target_id=body.target_id,
            ttl_seconds=max(30, min(body.ttl_seconds, MAX_LEASE_TTL_SECONDS)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.delete("/{session_id}/machine-target/lease", response_model=SessionMachineTargetOut)
async def clear_session_machine_target_lease(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _require_admin_user(user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await clear_session_lease_row(db, session)
    await db.commit()
    await db.refresh(session)
    payload = await build_session_machine_target_payload(db, session=session)
    return SessionMachineTargetOut(**payload)


@router.post("/{session_id}/summarize", response_model=SummarizeResponse)
async def summarize_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    """Force full compaction: memory phase (if bot has memory/persona/knowledge) then summary. Sets watermark so the summary is used on next load."""
    try:
        session = await db.get(Session, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bot = get_bot(session.bot_id)
        title, summary = await run_compaction_forced(session_id, bot, db)
        await db.commit()
        return SummarizeResponse(title=title, summary=summary)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Session not found")
        if "no conversation" in str(e).lower():
            raise HTTPException(status_code=400, detail="No conversation content to summarize")
        if "no messages" in str(e).lower():
            raise HTTPException(status_code=400, detail="No messages in session")
        raise HTTPException(status_code=400, detail=str(e))
