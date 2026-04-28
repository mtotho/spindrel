"""Channel CRUD + tab endpoints: conversations, heartbeat, memories, tasks, plans,
knowledge, enriched."""
from __future__ import annotations

import json
import logging
import time as _time
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import selectinload

from app.agent.context_assembly import assemble_for_preview
from app.agent.bots import get_bot
from app.domain.errors import DomainError
from app.db.models import (
    Channel,
    ChannelHeartbeat,
    CompactionLog,
    HeartbeatRun,
    Message,
    Session,
    Skill as SkillRow,
    Task,
    ToolCall,
    TraceEvent,
    WorkflowRun,
)
from app.config import settings
from app.dependencies import get_db, require_scopes
from app.services.channels import apply_channel_visibility
from app.services.context_preview import build_context_preview_response
from app.services.heartbeat_policy import DEFAULT_HEARTBEAT_EXECUTION_POLICY, HEARTBEAT_EXECUTION_PRESETS
from app.services.agent_harnesses.project import (
    PROJECT_PATH_KEY,
    PROJECT_WORKSPACE_ID_KEY,
    normalize_project_path,
    resolve_channel_project_directory,
    resolve_project_workspace_id,
)
from app.services.widget_themes import normalize_widget_theme_ref, resolve_widget_theme

from ._helpers import _heartbeat_correlation_ids, build_tool_call_previews
from .turns import TurnToolCall

logger = logging.getLogger(__name__)

router = APIRouter()

SectionScope = Literal["current", "all"]


def _resolve_workspace_id(bot_id: str) -> str | None:
    """Get the shared workspace ID for a bot, if any."""
    try:
        bot = get_bot(bot_id)
        return bot.shared_workspace_id
    except Exception:
        return None


def _is_harness_bot(bot_id: str | None) -> bool:
    if not bot_id:
        return False
    try:
        return bool(getattr(get_bot(bot_id), "harness_runtime", None))
    except Exception:
        return False


def _effective_heartbeat_runner_mode(
    hb: ChannelHeartbeat | None,
    *,
    channel: Channel | None,
) -> str:
    raw = getattr(hb, "runner_mode", None) if hb is not None else None
    if raw in {"harness", "spindrel"}:
        return raw
    return "harness" if _is_harness_bot(channel.bot_id if channel else None) else "spindrel"


def _validate_heartbeat_runner_model(
    hb: ChannelHeartbeat,
    *,
    channel: Channel | None,
) -> None:
    if (
        channel is not None
        and hb.enabled
        and _is_harness_bot(channel.bot_id)
        and _effective_heartbeat_runner_mode(hb, channel=channel) == "spindrel"
        and not (hb.model or "").strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="Harness channels that run heartbeats with the Spindrel agent require an explicit heartbeat model.",
        )


_PREVIEW_MAX_LEN = 80


def _format_message_preview(content: str) -> str:
    """Compact a message body for the channel-tile preview line.

    Collapses interior whitespace to single spaces, trims, and truncates
    to ``_PREVIEW_MAX_LEN`` chars with an ellipsis. Empty bodies become
    ``""`` so the caller can short-circuit.
    """
    flat = " ".join(content.split())
    if len(flat) <= _PREVIEW_MAX_LEN:
        return flat
    return flat[:_PREVIEW_MAX_LEN].rstrip() + "…"


def _resolve_index_segment_defaults(bot_id: str) -> dict:
    """Resolve effective default values for index segment fields from bot config."""
    try:
        bot = get_bot(bot_id)
        from app.services.bot_indexing import resolve_for
        plan = resolve_for(bot, scope="workspace")
        if plan is not None:
            return {
                "embedding_model": plan.embedding_model,
                "patterns": plan.patterns,
                "similarity_threshold": plan.similarity_threshold,
                "top_k": plan.top_k,
            }
    except Exception:
        pass
    from app.config import settings as _s
    return {
        "embedding_model": _s.EMBEDDING_MODEL,
        "patterns": ["**/*.py", "**/*.md", "**/*.yaml"],
        "similarity_threshold": _s.FS_INDEX_SIMILARITY_THRESHOLD,
        "top_k": _s.FS_INDEX_TOP_K,
    }


def _section_session_label(session: Session | None, active_session_id: uuid.UUID | None) -> str:
    if session is None:
        return "Legacy channel archive"
    if session.title:
        return session.title
    if session.id == active_session_id:
        return "Primary session"
    return "Untitled session"


def _section_session_kind(session: Session | None, active_session_id: uuid.UUID | None) -> str:
    if session is None:
        return "legacy"
    if session.id == active_session_id:
        return "primary"
    if session.parent_channel_id:
        return "scratch"
    return "previous"


def _section_session_out(session: Session | None, active_session_id: uuid.UUID | None) -> dict | None:
    if session is None:
        return None
    return {
        "id": str(session.id),
        "title": _section_session_label(session, active_session_id),
        "summary": session.summary,
        "kind": _section_session_kind(session, active_session_id),
        "is_current": session.id == active_session_id,
        "last_active": session.last_active.isoformat() if session.last_active else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


async def _load_section_sessions(
    db: AsyncSession,
    rows: list,
    active_session_id: uuid.UUID | None,
) -> dict[uuid.UUID, Session]:
    session_ids = {r.session_id for r in rows if r.session_id}
    if active_session_id:
        session_ids.add(active_session_id)
    if not session_ids:
        return {}
    sessions = (
        await db.execute(select(Session).where(Session.id.in_(session_ids)))
    ).scalars().all()
    return {s.id: s for s in sessions}


async def _count_eligible_messages_for_session(db: AsyncSession, session: Session | None) -> int:
    if session is None:
        return 0

    watermark_filter = True  # type: ignore[assignment]
    if session.summary_message_id:
        watermark_msg = await db.get(Message, session.summary_message_id)
        if watermark_msg:
            watermark_filter = Message.created_at <= watermark_msg.created_at

    rows = (
        await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .where(watermark_filter)
            .where(Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at)
        )
    ).scalars().all()

    count = 0
    for message in rows:
        if message.role == "user" and (message.metadata_ or {}).get("passive", False):
            continue
        if not message.content:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Channel schemas
# ---------------------------------------------------------------------------

class IntegrationBindingOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    integration_type: str
    client_id: str
    dispatch_config: Optional[dict] = None
    display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    display_name: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    member_bots: list[dict] = []
    heartbeat_enabled: bool = False
    heartbeat_in_quiet_hours: bool = False
    workspace_id: Optional[uuid.UUID] = None
    resolved_workspace_id: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = []
    last_message_at: Optional[datetime] = None
    # Spatial canvas + future activity-aware surfaces. Computed in the
    # channel-list path alongside ``last_message_at``; cheap to add since the
    # session join is already in flight.
    recent_message_count_24h: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelListOut(BaseModel):
    channels: list[ChannelOut]
    total: int
    page: int
    page_size: int


class ChannelEntitySummary(BaseModel):
    session_count: int = 0
    message_count: int = 0
    memory_count: int = 0
    task_count: int = 0
    active_session_message_count: int = 0


class ChannelDetailOut(BaseModel):
    channel: ChannelOut
    entities: ChannelEntitySummary

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: uuid.UUID
    client_id: str
    bot_id: str
    created_at: datetime
    last_active: datetime
    title: Optional[str] = None
    depth: int = 0
    locked: bool = False
    source_task_id: Optional[uuid.UUID] = None
    message_count: int = 0
    is_active: bool = False

    model_config = {"from_attributes": True}


class SessionListOut(BaseModel):
    sessions: list[SessionOut]


class EnrolledChannelSkillOut(BaseModel):
    skill_id: str
    name: str
    description: Optional[str] = None
    source: str
    enrolled_at: datetime


class EnrollChannelSkillIn(BaseModel):
    skill_id: str
    source: str = "manual"


class HeartbeatConfigOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    enabled: bool = False
    interval_minutes: int = 60
    model: str = ""
    model_provider_id: Optional[str] = None
    fallback_models: list[dict] = []
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    dispatch_mode: str = "always"
    trigger_response: bool = False
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    timezone: Optional[str] = None
    max_run_seconds: Optional[int] = None
    previous_result_max_chars: Optional[int] = None
    repetition_detection: Optional[bool] = None
    workflow_id: Optional[str] = None
    workflow_session_mode: Optional[str] = None
    skip_tool_approval: bool = False
    append_spatial_prompt: bool = False
    append_spatial_map_overview: bool = False
    include_pinned_widgets: bool = False
    execution_policy: Optional[dict] = None
    runner_mode: Optional[str] = None
    harness_effort: Optional[str] = None
    effective_runner_mode: str = "spindrel"
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("quiet_start", "quiet_end", mode="before")
    @classmethod
    def _coerce_time_to_str(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, dt_time):
            return v.strftime("%H:%M")
        return str(v)

    @classmethod
    def from_orm_heartbeat(cls, hb: ChannelHeartbeat) -> "HeartbeatConfigOut":
        data = {c: getattr(hb, c) for c in [
            "id", "channel_id", "enabled", "interval_minutes", "model",
            "model_provider_id", "fallback_models", "prompt", "prompt_template_id",
            "workspace_file_path", "workspace_id",
            "dispatch_results", "dispatch_mode", "trigger_response",
            "timezone", "max_run_seconds", "previous_result_max_chars", "repetition_detection",
            "workflow_id", "workflow_session_mode", "skip_tool_approval",
            "append_spatial_prompt", "append_spatial_map_overview",
            "include_pinned_widgets", "execution_policy",
            "runner_mode", "harness_effort",
            "last_run_at", "next_run_at", "created_at", "updated_at",
        ]}
        data["effective_runner_mode"] = "spindrel"
        data["quiet_start"] = hb.quiet_start.strftime("%H:%M") if hb.quiet_start else None
        data["quiet_end"] = hb.quiet_end.strftime("%H:%M") if hb.quiet_end else None
        return cls(**data)


class HeartbeatHistoryRunOut(BaseModel):
    id: uuid.UUID
    status: str
    run_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None
    repetition_detected: Optional[bool] = None
    tool_calls: list[TurnToolCall] = []
    total_tokens: int = 0
    iterations: int = 0
    duration_ms: Optional[int] = None

    model_config = {"from_attributes": True}


class HeartbeatOut(BaseModel):
    config: Optional[HeartbeatConfigOut] = None
    history: list[HeartbeatHistoryRunOut] = []
    total_history: int = 0
    default_max_run_seconds: int = settings.TASK_MAX_RUN_SECONDS
    default_previous_result_chars: int = settings.HEARTBEAT_PREVIOUS_CONCLUSION_CHARS
    default_repetition_detection: bool = settings.HEARTBEAT_REPETITION_DETECTION
    default_execution_policy: dict = Field(default_factory=lambda: dict(DEFAULT_HEARTBEAT_EXECUTION_POLICY))
    execution_policy_presets: dict = Field(default_factory=lambda: {k: dict(v) for k, v in HEARTBEAT_EXECUTION_PRESETS.items()})
    default_quiet_hours: Optional[str] = settings.HEARTBEAT_QUIET_HOURS or None
    default_timezone: str = settings.TIMEZONE
    channel_name: Optional[str] = None
    has_dispatch_config: bool = False


class HeartbeatUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: int = Field(60, ge=1)
    model: str = ""
    model_provider_id: Optional[str] = None
    fallback_models: list[dict] = []
    prompt: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    workspace_file_path: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    dispatch_results: bool = True
    dispatch_mode: str = "always"
    trigger_response: bool = False
    quiet_start: Optional[str] = None  # "HH:MM" or null
    quiet_end: Optional[str] = None    # "HH:MM" or null
    timezone: Optional[str] = None
    max_run_seconds: Optional[int] = None
    previous_result_max_chars: Optional[int] = None
    repetition_detection: Optional[bool] = None
    workflow_id: Optional[str] = None
    workflow_session_mode: Optional[str] = None
    skip_tool_approval: bool = False
    append_spatial_prompt: bool = False
    append_spatial_map_overview: bool = False
    include_pinned_widgets: bool = False
    execution_policy: Optional[dict] = None
    runner_mode: Optional[Literal["harness", "spindrel"]] = None
    harness_effort: Optional[str] = None


class TaskOut(BaseModel):
    id: uuid.UUID
    status: str
    bot_id: str
    prompt: str
    title: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    dispatch_type: str = "none"
    task_type: str = "agent"
    recurrence: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskListOut(BaseModel):
    tasks: list[TaskOut]


class ChannelSettingsOut(BaseModel):
    """All channel settings — superset of ChannelOut."""
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    allow_bot_messages: bool = False
    workspace_rag: bool = True
    thinking_display: str = "append"
    tool_output_display: str = "compact"
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    channel_prompt: Optional[str] = None
    channel_prompt_workspace_file_path: Optional[str] = None
    channel_prompt_workspace_id: Optional[uuid.UUID] = None
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_workspace_file_path: Optional[str] = None
    compaction_workspace_id: Optional[uuid.UUID] = None
    history_mode: Optional[str] = None
    compaction_model: Optional[str] = None
    compaction_model_provider_id: Optional[str] = None
    trigger_heartbeat_before_compaction: Optional[bool] = None
    # Memory flush (dedicated pre-compaction memory save)
    memory_flush_enabled: Optional[bool] = None
    memory_flush_model: Optional[str] = None
    memory_flush_model_provider_id: Optional[str] = None
    memory_flush_prompt: Optional[str] = None
    memory_flush_prompt_template_id: Optional[uuid.UUID] = None
    memory_flush_workspace_file_path: Optional[str] = None
    memory_flush_workspace_id: Optional[uuid.UUID] = None
    section_index_count: Optional[int] = None
    section_index_verbosity: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Tool / skill restrictions
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    # Workspace overrides (null = inherit from workspace)
    workspace_base_prompt_enabled: Optional[bool] = None
    workspace_schema_template_id: Optional[uuid.UUID] = None
    workspace_schema_content: Optional[str] = None
    index_segments: list[dict] = []
    # Model tier overrides (sparse — only override tiers you want to change)
    model_tier_overrides: dict = {}
    # Resolved defaults for index segment fields (computed, not stored)
    index_segment_defaults: Optional[dict] = None
    # Workspace scope
    workspace_id: Optional[uuid.UUID] = None
    # Resolved workspace ID from bot config (computed, not stored)
    resolved_workspace_id: Optional[str] = None
    # Harness/project file scope. project_path is workspace-relative.
    project_workspace_id: Optional[str] = None
    project_path: Optional[str] = None
    resolved_project_workspace_id: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = []
    # Phase 5: pipeline_mode controls launchpad/findings visibility for the
    # channel. "auto" (default) → visible when subscriptions exist. Stored
    # in the JSONB config column; surfaced at the top level for UI.
    pipeline_mode: str = "auto"
    # Chat-screen layout mode. Controls which dashboard zones render on the
    # chat screen. Stored in channel.config["layout_mode"]; default "full".
    layout_mode: str = "full"
    # Chat presentation mode for the main channel surface. Stored in
    # channel.config["chat_mode"]; default "default".
    chat_mode: str = "default"
    # Header strip shell treatment for header-zone widgets. Stored in
    # channel.config["header_backdrop_mode"]; unset/default resolves to glass.
    header_backdrop_mode: str = "glass"
    widget_theme_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class ChannelSettingsUpdate(BaseModel):
    """Writable channel settings."""
    name: Optional[str] = None
    bot_id: Optional[str] = None
    require_mention: Optional[bool] = None
    passive_memory: Optional[bool] = None
    private: Optional[bool] = None
    user_id: Optional[uuid.UUID] = None
    allow_bot_messages: Optional[bool] = None
    workspace_rag: Optional[bool] = None
    thinking_display: Optional[str] = None
    tool_output_display: Optional[str] = None
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    channel_prompt: Optional[str] = None
    channel_prompt_workspace_file_path: Optional[str] = None
    channel_prompt_workspace_id: Optional[uuid.UUID] = None
    context_compaction: Optional[bool] = None
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_workspace_file_path: Optional[str] = None
    compaction_workspace_id: Optional[uuid.UUID] = None
    history_mode: Optional[str] = None
    compaction_model: Optional[str] = None
    compaction_model_provider_id: Optional[str] = None
    trigger_heartbeat_before_compaction: Optional[bool] = None
    # Memory flush (dedicated pre-compaction memory save)
    memory_flush_enabled: Optional[bool] = None
    memory_flush_model: Optional[str] = None
    memory_flush_model_provider_id: Optional[str] = None
    memory_flush_prompt: Optional[str] = None
    memory_flush_prompt_template_id: Optional[uuid.UUID] = None
    memory_flush_workspace_file_path: Optional[str] = None
    memory_flush_workspace_id: Optional[uuid.UUID] = None
    section_index_count: Optional[int] = None
    section_index_verbosity: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    # Tool / skill restrictions (set to null to clear → revert to inherit)
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    # Workspace overrides (null = inherit from workspace)
    workspace_base_prompt_enabled: Optional[bool] = None
    workspace_schema_template_id: Optional[uuid.UUID] = None
    workspace_schema_content: Optional[str] = None
    index_segments: Optional[list[dict]] = None
    # Model tier overrides
    model_tier_overrides: Optional[dict] = None
    # Workspace scope
    workspace_id: Optional[str] = None
    # Harness/project file scope. project_path is workspace-relative.
    project_workspace_id: Optional[str] = None
    project_path: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    # Phase 5: pipeline_mode override. "auto" (default) | "on" | "off".
    pipeline_mode: Optional[str] = None
    # Chat-screen layout mode. "full" (default) | "rail-header-chat" |
    # "rail-chat" | "dashboard-only". Stored inside channel.config JSONB.
    layout_mode: Optional[str] = None
    # Chat presentation mode. "default" (default) | "terminal". Stored
    # inside channel.config JSONB.
    chat_mode: Optional[str] = None
    # Header strip shell treatment. "glass" is the resolved default;
    # "default" remains the solid Surface compatibility value.
    # Stored inside channel.config JSONB.
    header_backdrop_mode: Optional[str] = None
    widget_theme_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# Orchestrator channel setup
# ---------------------------------------------------------------------------

@router.post("/channels/ensure-orchestrator")
async def ensure_orchestrator(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:write")),
):
    """Create orchestrator bot + channel if they don't exist.

    Creates the bot directly in DB if needed (no YAML dependency),
    reloads the bot registry, then ensures the orchestrator channel exists.
    """
    from app.services.channels import ensure_orchestrator_channel

    await ensure_orchestrator_channel()

    # Return the channel
    from app.db.models import Channel as ChannelModel
    ch = (await db.execute(
        select(ChannelModel).where(ChannelModel.client_id == "orchestrator:home")
    )).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=500, detail="Orchestrator channel could not be created")

    return {"id": str(ch.id), "name": ch.name, "client_id": ch.client_id}


# ---------------------------------------------------------------------------
# Channel list / detail
# ---------------------------------------------------------------------------

@router.get("/channels", response_model=ChannelListOut)
async def admin_channels_list(
    integration: Optional[str] = Query(None, description="Filter by integration type"),
    bot_id: Optional[str] = Query(None, description="Filter by bot_id"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:read")),
):
    """List channels with pagination and optional filters."""
    stmt = select(Channel).order_by(Channel.name.asc())
    stmt = apply_channel_visibility(stmt, auth_result)
    if integration:
        stmt = stmt.where(Channel.integration == integration)
    if bot_id:
        stmt = stmt.where(Channel.bot_id == bot_id)

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()

    offset = (page - 1) * page_size
    channels = (await db.execute(
        stmt.options(selectinload(Channel.integrations)).offset(offset).limit(page_size)
    )).scalars().all()

    return ChannelListOut(
        channels=[ChannelOut.model_validate(ch) for ch in channels],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/channels/categories")
async def list_channel_categories(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """List distinct channel categories (for autocomplete)."""
    from sqlalchemy import func, text
    result = await db.execute(
        select(func.distinct(Channel.metadata_["category"].astext))
        .where(Channel.metadata_["category"].astext.isnot(None))
        .where(Channel.metadata_["category"].astext != "")
    )
    return sorted(row[0] for row in result.all())


@router.get("/channels/{channel_id}", response_model=ChannelDetailOut)
async def admin_channel_detail(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Channel detail with linked entity counts."""
    channel = (await db.execute(
        select(Channel)
        .options(selectinload(Channel.integrations), selectinload(Channel.bot_members))
        .where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    session_count = (await db.execute(
        select(func.count()).select_from(Session)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    message_count = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Session, Message.session_id == Session.id)
        .where(Session.channel_id == channel_id)
    )).scalar_one()

    memory_count = 0  # memories table is deprecated

    task_count = (await db.execute(
        select(func.count()).select_from(Task)
        .where(Task.channel_id == channel_id)
    )).scalar_one()

    active_msg_count = 0
    if channel.active_session_id:
        active_msg_count = (await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.session_id == channel.active_session_id)
        )).scalar_one()

    from app.routers.api_v1_channels import _enrich_bot_members
    channel_out = ChannelOut.model_validate(channel)
    channel_out.member_bots = _enrich_bot_members(channel)
    return ChannelDetailOut(
        channel=channel_out,
        entities=ChannelEntitySummary(
            session_count=session_count,
            message_count=message_count,
            memory_count=memory_count,
            task_count=task_count,
            active_session_message_count=active_msg_count,
        ),
    )


# ---------------------------------------------------------------------------
# Channel settings
# ---------------------------------------------------------------------------

def _fill_channel_project_settings(out: ChannelSettingsOut, channel: Channel) -> None:
    cfg = channel.config or {}
    out.project_workspace_id = (
        str(cfg.get(PROJECT_WORKSPACE_ID_KEY))
        if cfg.get(PROJECT_WORKSPACE_ID_KEY)
        else None
    )
    try:
        out.project_path = normalize_project_path(cfg.get(PROJECT_PATH_KEY))
    except ValueError:
        out.project_path = None
    try:
        bot = get_bot(channel.bot_id)
    except Exception:
        bot = None
    out.resolved_project_workspace_id = resolve_project_workspace_id(channel, bot)


@router.get("/channels/{channel_id}/settings", response_model=ChannelSettingsOut)
async def admin_channel_settings(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.config:read")),
):
    """Get full channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    out = ChannelSettingsOut.model_validate(channel)
    out.index_segment_defaults = _resolve_index_segment_defaults(channel.bot_id)
    ws_id_str = str(channel.workspace_id) if channel.workspace_id else None
    out.resolved_workspace_id = ws_id_str or _resolve_workspace_id(channel.bot_id)
    out.category = (channel.metadata_ or {}).get("category")
    out.tags = (channel.metadata_ or {}).get("tags", [])
    out.pipeline_mode = (channel.config or {}).get("pipeline_mode") or "auto"
    out.layout_mode = (channel.config or {}).get("layout_mode") or "full"
    out.chat_mode = (channel.config or {}).get("chat_mode") or "default"
    out.header_backdrop_mode = (channel.config or {}).get("header_backdrop_mode") or "glass"
    out.widget_theme_ref = (channel.config or {}).get("widget_theme_ref")
    _fill_channel_project_settings(out, channel)
    return out


@router.api_route("/channels/{channel_id}/settings", methods=["PUT", "PATCH"], response_model=ChannelSettingsOut)
async def admin_channel_settings_update(
    channel_id: uuid.UUID,
    body: ChannelSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.config:write")),
):
    """Update channel settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    updates = body.model_dump(exclude_unset=True)
    if "bot_id" in updates:
        try:
            get_bot(updates["bot_id"])
        except (HTTPException, DomainError):
            raise HTTPException(status_code=400, detail=f"Unknown bot: {updates['bot_id']}")

    # Handle metadata_ fields (category, tags) — share single dict to avoid race
    meta_dirty = False
    meta = dict(channel.metadata_ or {})
    if "category" in updates:
        cat_value = (updates.pop("category") or "").strip()
        if cat_value:
            meta["category"] = cat_value
        else:
            meta.pop("category", None)
        meta_dirty = True
    if "tags" in updates:
        meta["tags"] = updates.pop("tags") or []
        meta_dirty = True
    if meta_dirty:
        channel.metadata_ = meta

    # Handle workspace_id — convert string to UUID or clear
    if "workspace_id" in updates:
        ws_val = updates.pop("workspace_id")
        channel.workspace_id = uuid.UUID(ws_val) if ws_val else None

    if "project_workspace_id" in updates or "project_path" in updates:
        cfg = dict(channel.config or {})
        if "project_workspace_id" in updates:
            raw_ws = updates.pop("project_workspace_id")
            if raw_ws:
                try:
                    cfg[PROJECT_WORKSPACE_ID_KEY] = str(uuid.UUID(str(raw_ws)))
                except ValueError:
                    raise HTTPException(status_code=422, detail="project_workspace_id must be a UUID")
            else:
                cfg.pop(PROJECT_WORKSPACE_ID_KEY, None)
        if "project_path" in updates:
            raw_path = updates.pop("project_path")
            try:
                project_path = normalize_project_path(raw_path)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            if project_path:
                cfg[PROJECT_PATH_KEY] = project_path
            else:
                cfg.pop(PROJECT_PATH_KEY, None)
        channel.config = cfg
        flag_modified(channel, "config")
        if cfg.get(PROJECT_PATH_KEY):
            try:
                bot = get_bot(updates.get("bot_id") or channel.bot_id)
                resolve_channel_project_directory(channel, bot)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"could not resolve project directory: {exc}")

    # Handle pipeline_mode — shallow-merge into channel.config JSONB.
    if "pipeline_mode" in updates:
        mode = updates.pop("pipeline_mode")
        if mode is not None and mode not in ("auto", "on", "off"):
            raise HTTPException(
                status_code=422,
                detail="pipeline_mode must be one of: auto, on, off",
            )
        cfg = dict(channel.config or {})
        if mode in (None, "auto"):
            cfg.pop("pipeline_mode", None)
        else:
            cfg["pipeline_mode"] = mode
        channel.config = cfg
        flag_modified(channel, "config")

    # Handle layout_mode — shallow-merge into channel.config JSONB (same
    # storage pattern as pipeline_mode). "full" clears the key so the
    # config stays lean when running on defaults.
    if "layout_mode" in updates:
        lm = updates.pop("layout_mode")
        _valid_layout = {"full", "rail-header-chat", "rail-chat", "dashboard-only"}
        if lm is not None and lm not in _valid_layout:
            raise HTTPException(
                status_code=422,
                detail=f"layout_mode must be one of: {sorted(_valid_layout)}",
            )
        cfg = dict(channel.config or {})
        if lm in (None, "full"):
            cfg.pop("layout_mode", None)
        else:
            cfg["layout_mode"] = lm
        channel.config = cfg
        flag_modified(channel, "config")

    if "chat_mode" in updates:
        cm = updates.pop("chat_mode")
        _valid_chat_mode = {"default", "terminal"}
        if cm is not None and cm not in _valid_chat_mode:
            raise HTTPException(
                status_code=422,
                detail=f"chat_mode must be one of: {sorted(_valid_chat_mode)}",
            )
        cfg = dict(channel.config or {})
        if cm in (None, "default"):
            cfg.pop("chat_mode", None)
        else:
            cfg["chat_mode"] = cm
        channel.config = cfg
        flag_modified(channel, "config")

    if "header_backdrop_mode" in updates:
        hbm = updates.pop("header_backdrop_mode")
        _valid_header_backdrop = {"default", "glass", "clear"}
        if hbm is not None and hbm not in _valid_header_backdrop:
            raise HTTPException(
                status_code=422,
                detail=f"header_backdrop_mode must be one of: {sorted(_valid_header_backdrop)}",
            )
        cfg = dict(channel.config or {})
        if hbm in (None, "default"):
            cfg.pop("header_backdrop_mode", None)
        else:
            cfg["header_backdrop_mode"] = hbm
        channel.config = cfg
        flag_modified(channel, "config")

    if "widget_theme_ref" in updates:
        wtr = updates.pop("widget_theme_ref")
        if wtr is not None:
            try:
                await resolve_widget_theme(db, wtr)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        cfg = dict(channel.config or {})
        normalized = normalize_widget_theme_ref(wtr)
        if normalized == "builtin/default":
            cfg.pop("widget_theme_ref", None)
        else:
            cfg["widget_theme_ref"] = normalized
        channel.config = cfg
        flag_modified(channel, "config")

    # Validate model tier override names
    if updates.get("model_tier_overrides"):
        from app.services.server_config import VALID_TIER_NAMES
        invalid = set(updates["model_tier_overrides"].keys()) - VALID_TIER_NAMES
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid tier names: {sorted(invalid)}. Valid: {sorted(VALID_TIER_NAMES)}")

    for field, value in updates.items():
        setattr(channel, field, value)

    # When heartbeat trigger is enabled, clear the memory phase prompt fields
    if updates.get("trigger_heartbeat_before_compaction"):
        channel.memory_knowledge_compaction_prompt = None
        channel.compaction_workspace_file_path = None
        channel.compaction_workspace_id = None
        channel.compaction_prompt_template_id = None

    # Refresh .channel_info on rename so the workspace dir mirrors the channel name.
    if "name" in updates:
        try:
            bot = get_bot(channel.bot_id)
            from app.services.channel_workspace import ensure_channel_workspace
            ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)
        except Exception:
            pass

    channel.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(channel)
    out = ChannelSettingsOut.model_validate(channel)
    out.index_segment_defaults = _resolve_index_segment_defaults(channel.bot_id)
    ws_id_str = str(channel.workspace_id) if channel.workspace_id else None
    out.resolved_workspace_id = ws_id_str or _resolve_workspace_id(channel.bot_id)
    out.category = (channel.metadata_ or {}).get("category")
    out.tags = (channel.metadata_ or {}).get("tags", [])
    out.pipeline_mode = (channel.config or {}).get("pipeline_mode") or "auto"
    out.layout_mode = (channel.config or {}).get("layout_mode") or "full"
    out.chat_mode = (channel.config or {}).get("chat_mode") or "default"
    out.header_backdrop_mode = (channel.config or {}).get("header_backdrop_mode") or "glass"
    out.widget_theme_ref = (channel.config or {}).get("widget_theme_ref")
    _fill_channel_project_settings(out, channel)
    return out


@router.get("/channels/{channel_id}/enrolled-skills", response_model=list[EnrolledChannelSkillOut])
async def admin_channel_enrolled_skills_list(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    from app.db.models import ChannelSkillEnrollment

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    rows = (await db.execute(
        select(
            ChannelSkillEnrollment.skill_id,
            ChannelSkillEnrollment.source,
            ChannelSkillEnrollment.enrolled_at,
            SkillRow.name,
            SkillRow.description,
        )
        .join(SkillRow, SkillRow.id == ChannelSkillEnrollment.skill_id)
        .where(ChannelSkillEnrollment.channel_id == channel_id)
        .order_by(ChannelSkillEnrollment.enrolled_at.desc())
    )).all()

    return [
        EnrolledChannelSkillOut(
            skill_id=row.skill_id,
            name=row.name,
            description=row.description,
            source=row.source,
            enrolled_at=row.enrolled_at,
        )
        for row in rows
    ]


@router.post("/channels/{channel_id}/enrolled-skills", status_code=201)
async def admin_channel_enrolled_skill_add(
    channel_id: uuid.UUID,
    body: EnrollChannelSkillIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.config:write")),
):
    from app.services.channel_skill_enrollment import enroll

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    skill_row = await db.get(SkillRow, body.skill_id)
    if not skill_row:
        raise HTTPException(status_code=404, detail=f"Skill not found: {body.skill_id}")

    if body.skill_id.startswith("bots/") and not body.skill_id.startswith(f"bots/{channel.bot_id}/"):
        raise HTTPException(status_code=400, detail="Cannot enroll another bot's authored skill")

    inserted = await enroll(str(channel_id), body.skill_id, source=body.source or "manual", db=db)
    await db.commit()
    return {"status": "ok", "skill_id": body.skill_id, "inserted": inserted}


@router.delete("/channels/{channel_id}/enrolled-skills/{skill_id:path}", status_code=204)
async def admin_channel_enrolled_skill_remove(
    channel_id: uuid.UUID,
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.config:write")),
):
    from app.services.channel_skill_enrollment import unenroll

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    deleted = await unenroll(str(channel_id), skill_id, db=db)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Enrollment not found: {channel_id}/{skill_id}")
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Effective tools (resolved with channel overrides)
# ---------------------------------------------------------------------------

class EffectiveToolsOut(BaseModel):
    local_tools: list[str]
    mcp_servers: list[str]
    client_tools: list[str]
    pinned_tools: list[str]
    skills: list[dict]
    mode: dict  # per-category mode: "inherit" | "disabled"
    disabled: dict = {}  # per-category disabled lists


@router.get("/channels/{channel_id}/effective-tools", response_model=EffectiveToolsOut)
async def admin_channel_effective_tools(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Return the resolved tool/skill lists after applying channel overrides."""
    from app.agent.channel_overrides import resolve_effective_tools
    from app.db.models import ChannelIntegration, ChannelSkillEnrollment

    result = await db.execute(
        select(Channel).where(Channel.id == channel_id).options(selectinload(Channel.integrations))
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    bot = get_bot(channel.bot_id)
    channel_skill_ids = (await db.execute(
        select(ChannelSkillEnrollment.skill_id).where(ChannelSkillEnrollment.channel_id == channel_id)
    )).scalars().all()
    setattr(channel, "_channel_skill_enrollment_ids", list(channel_skill_ids))

    from app.agent.channel_overrides import apply_auto_injections
    eff = resolve_effective_tools(bot, channel)
    eff = apply_auto_injections(eff, bot)

    def _mode(disabled):
        if disabled is not None:
            return "disabled"
        return "inherit"

    # Enrich skill entries with names from DB
    skill_ids = [s.id for s in eff.skills]
    skill_names: dict[str, str] = {}
    if skill_ids:
        rows = (await db.execute(
            select(SkillRow.id, SkillRow.name).where(SkillRow.id.in_(skill_ids))
        )).all()
        skill_names = {r.id: r.name for r in rows}

    return EffectiveToolsOut(
        local_tools=eff.local_tools,
        mcp_servers=eff.mcp_servers,
        client_tools=eff.client_tools,
        pinned_tools=eff.pinned_tools,
        skills=[{
            "id": s.id, "mode": s.mode,
            "name": skill_names.get(s.id, s.id),
        } for s in eff.skills],
        mode={
            "local_tools": _mode(channel.local_tools_disabled),
            "mcp_servers": _mode(channel.mcp_servers_disabled),
            "client_tools": _mode(channel.client_tools_disabled),
            "pinned_tools": "inherit",
            "skills": "inherit",
        },
        disabled={
            "local_tools": channel.local_tools_disabled or [],
            "mcp_servers": channel.mcp_servers_disabled or [],
            "client_tools": channel.client_tools_disabled or [],
        },
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sessions", response_model=SessionListOut)
async def admin_channel_sessions(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """List conversations for a channel (last 20, ordered by last_active desc, with message counts)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    sessions = (await db.execute(
        select(Session)
        .where(Session.channel_id == channel_id)
        .order_by(Session.last_active.desc())
        .limit(20)
    )).scalars().all()

    msg_counts: dict[uuid.UUID, int] = {}
    if sessions:
        sids = [s.id for s in sessions]
        rows = (await db.execute(
            select(Message.session_id, func.count())
            .where(Message.session_id.in_(sids))
            .group_by(Message.session_id)
        )).all()
        msg_counts = {r[0]: r[1] for r in rows}

    return SessionListOut(
        sessions=[
            SessionOut(
                id=s.id,
                client_id=s.client_id,
                bot_id=s.bot_id,
                created_at=s.created_at,
                last_active=s.last_active,
                title=s.title,
                depth=s.depth,
                locked=s.locked,
                message_count=msg_counts.get(s.id, 0),
                is_active=(s.id == channel.active_session_id),
            )
            for s in sessions
        ],
    )


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/heartbeat", response_model=HeartbeatOut)
async def admin_channel_heartbeat_get(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.heartbeat:read")),
):
    """Get heartbeat config and recent history for a channel."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    config_out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat) if heartbeat else None
    if config_out is not None:
        config_out.effective_runner_mode = _effective_heartbeat_runner_mode(
            heartbeat,
            channel=channel,
        )

    # Read from heartbeat_runs table (new), fall back to legacy Task rows
    history_out: list[HeartbeatHistoryRunOut] = []
    total_history = 0

    if heartbeat:
        runs_stmt = (
            select(HeartbeatRun)
            .where(HeartbeatRun.heartbeat_id == heartbeat.id)
            .order_by(HeartbeatRun.run_at.desc())
            .limit(10)
        )
        runs = list((await db.execute(runs_stmt)).scalars().all())
        total_history = (await db.execute(
            select(func.count()).select_from(
                select(HeartbeatRun.id)
                .where(HeartbeatRun.heartbeat_id == heartbeat.id)
                .subquery()
            )
        )).scalar_one()

        if runs:
            history_out = [
                HeartbeatHistoryRunOut(
                    id=r.id,
                    status=r.status,
                    run_at=r.run_at,
                    completed_at=r.completed_at,
                    result=r.result[:500] if r.result else None,
                    error=r.error,
                    correlation_id=r.correlation_id,
                    repetition_detected=r.repetition_detected,
                )
                for r in runs
            ]
        else:
            # Fallback: read from legacy Task rows for historical data
            history_stmt = (
                select(Task)
                .where(Task.channel_id == channel_id)
                .where(Task.callback_config["source"].astext == "heartbeat")
                .order_by(Task.created_at.desc())
                .limit(10)
            )
            legacy_history = list((await db.execute(history_stmt)).scalars().all())
            corr_map = await _heartbeat_correlation_ids(db, legacy_history)
            total_history = (await db.execute(
                select(func.count()).select_from(
                    select(Task.id)
                    .where(Task.channel_id == channel_id)
                    .where(Task.callback_config["source"].astext == "heartbeat")
                    .subquery()
                )
            )).scalar_one()
            history_out = [
                HeartbeatHistoryRunOut(
                    id=t.id,
                    status=t.status,
                    run_at=t.run_at or t.created_at,
                    completed_at=t.completed_at,
                    result=t.result[:500] if t.result else None,
                    error=t.error,
                    correlation_id=corr_map.get(t.id),
                )
                for t in legacy_history
            ]

    # Enrich history entries with tool calls and stats
    correlation_ids = [h.correlation_id for h in history_out if h.correlation_id]
    if correlation_ids:
        tc_rows = (await db.execute(
            select(ToolCall)
            .where(ToolCall.correlation_id.in_(correlation_ids))
            .order_by(ToolCall.created_at)
        )).scalars().all()
        tc_by_corr: dict[uuid.UUID, list] = {}
        for tc in tc_rows:
            tc_by_corr.setdefault(tc.correlation_id, []).append(tc)

        te_rows = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.correlation_id.in_(correlation_ids),
                TraceEvent.event_type == "token_usage",
            )
        )).scalars().all()

        # Aggregate tokens + iterations per correlation_id
        stats_by_corr: dict[uuid.UUID, dict] = {}
        for te in te_rows:
            s = stats_by_corr.setdefault(te.correlation_id, {"tokens": 0, "iterations": 0})
            if te.data:
                s["tokens"] += te.data.get("total_tokens", 0)
                s["iterations"] = max(s["iterations"], te.data.get("iteration", 0))

        for h in history_out:
            if not h.correlation_id:
                continue
            tcs = tc_by_corr.get(h.correlation_id, [])
            if tcs:
                h.tool_calls = [TurnToolCall(**d) for d in build_tool_call_previews(tcs)]
            stats = stats_by_corr.get(h.correlation_id)
            if stats:
                h.total_tokens = stats["tokens"]
                h.iterations = stats["iterations"]
            # Compute duration from run_at → completed_at if available
            if h.completed_at and h.run_at:
                h.duration_ms = int((h.completed_at - h.run_at).total_seconds() * 1000)

    return HeartbeatOut(
        config=config_out,
        history=history_out,
        total_history=total_history,
        channel_name=channel.name if channel else None,
        has_dispatch_config=bool(channel.dispatch_config) if channel else False,
    )


@router.api_route("/channels/{channel_id}/heartbeat", methods=["PUT", "PATCH"], response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_update(
    channel_id: uuid.UUID,
    body: HeartbeatUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.heartbeat:write")),
):
    """Update heartbeat settings."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    now = datetime.now(timezone.utc)

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if heartbeat is None:
        heartbeat = ChannelHeartbeat(
            channel_id=channel_id,
            enabled=False,
        )
        db.add(heartbeat)

    updates = body.model_dump(exclude_unset=True)
    if "enabled" in updates:
        heartbeat.enabled = updates["enabled"]
    if "interval_minutes" in updates:
        heartbeat.interval_minutes = max(1, updates["interval_minutes"])
    if "model" in updates:
        heartbeat.model = updates["model"].strip() if updates["model"] else ""
        if not heartbeat.model:
            heartbeat.model_provider_id = None
    if "model_provider_id" in updates:
        heartbeat.model_provider_id = updates["model_provider_id"].strip() if updates["model_provider_id"] else None
    if heartbeat.model and not heartbeat.model_provider_id:
        try:
            from app.services.providers import resolve_provider_for_model

            heartbeat.model_provider_id = resolve_provider_for_model(heartbeat.model)
        except Exception:
            logger.debug(
                "Failed to infer provider for heartbeat model %s on channel %s",
                heartbeat.model,
                channel_id,
                exc_info=True,
            )
    if "prompt" in updates:
        heartbeat.prompt = updates["prompt"].strip() if updates["prompt"] else ""
    if "prompt_template_id" in updates:
        heartbeat.prompt_template_id = updates["prompt_template_id"]
    if "workspace_file_path" in updates:
        heartbeat.workspace_file_path = updates["workspace_file_path"]
    if "workspace_id" in updates:
        heartbeat.workspace_id = updates["workspace_id"]
    if "dispatch_results" in updates:
        heartbeat.dispatch_results = updates["dispatch_results"]
    if "trigger_response" in updates:
        heartbeat.trigger_response = updates["trigger_response"]
    if "quiet_start" in updates:
        heartbeat.quiet_start = dt_time.fromisoformat(updates["quiet_start"]) if updates["quiet_start"] else None
    if "quiet_end" in updates:
        heartbeat.quiet_end = dt_time.fromisoformat(updates["quiet_end"]) if updates["quiet_end"] else None
    if "timezone" in updates:
        heartbeat.timezone = updates["timezone"]
    if "max_run_seconds" in updates:
        heartbeat.max_run_seconds = updates["max_run_seconds"]
    if "dispatch_mode" in updates:
        heartbeat.dispatch_mode = updates["dispatch_mode"] if updates["dispatch_mode"] in ("always", "optional") else "always"
    if "previous_result_max_chars" in updates:
        heartbeat.previous_result_max_chars = updates["previous_result_max_chars"]
    if "repetition_detection" in updates:
        heartbeat.repetition_detection = updates["repetition_detection"]
    if "workflow_id" in updates:
        wf_id = updates["workflow_id"]
        if wf_id:
            from app.services.workflows import get_workflow
            if not get_workflow(wf_id):
                raise HTTPException(status_code=400, detail=f"Workflow '{wf_id}' not found")
        heartbeat.workflow_id = wf_id
    if "workflow_session_mode" in updates:
        val = updates["workflow_session_mode"]
        heartbeat.workflow_session_mode = val if val in ("shared", "isolated") else None
    if "skip_tool_approval" in updates:
        heartbeat.skip_tool_approval = updates["skip_tool_approval"]
    if "execution_policy" in updates:
        from app.services.heartbeat_policy import normalize_heartbeat_execution_policy
        heartbeat.execution_policy = normalize_heartbeat_execution_policy(updates["execution_policy"])
    if "runner_mode" in updates:
        heartbeat.runner_mode = updates["runner_mode"]
    if "harness_effort" in updates:
        value = updates["harness_effort"]
        heartbeat.harness_effort = value.strip() if isinstance(value, str) and value.strip() else None
    if "append_spatial_prompt" in updates:
        heartbeat.append_spatial_prompt = bool(updates["append_spatial_prompt"])
        if heartbeat.append_spatial_prompt:
            from app.services.workspace_spatial import (
                DEFAULT_SPATIAL_POLICY,
                SPATIAL_POLICY_KEY,
                normalize_spatial_policy,
            )

            cfg = dict(channel.config or {})
            policies = dict(cfg.get(SPATIAL_POLICY_KEY) or {})
            if channel.bot_id not in policies:
                policies[channel.bot_id] = normalize_spatial_policy({
                    **DEFAULT_SPATIAL_POLICY,
                    "enabled": True,
                    "allow_nearby_inspect": True,
                })
                cfg[SPATIAL_POLICY_KEY] = policies
                channel.config = cfg
                flag_modified(channel, "config")
    if "include_pinned_widgets" in updates:
        heartbeat.include_pinned_widgets = bool(updates["include_pinned_widgets"])
    if "append_spatial_map_overview" in updates:
        heartbeat.append_spatial_map_overview = bool(updates["append_spatial_map_overview"])
        if heartbeat.append_spatial_map_overview:
            from app.services.workspace_spatial import (
                DEFAULT_SPATIAL_POLICY,
                SPATIAL_POLICY_KEY,
                normalize_spatial_policy,
            )

            cfg = dict(channel.config or {})
            policies = dict(cfg.get(SPATIAL_POLICY_KEY) or {})
            current = policies.get(channel.bot_id)
            policies[channel.bot_id] = normalize_spatial_policy({
                **DEFAULT_SPATIAL_POLICY,
                **(current if isinstance(current, dict) else {}),
                "enabled": True,
                "allow_map_view": True,
            })
            cfg[SPATIAL_POLICY_KEY] = policies
            channel.config = cfg
            flag_modified(channel, "config")
    _validate_heartbeat_runner_model(heartbeat, channel=channel)
    heartbeat.updated_at = now

    if heartbeat.enabled:
        if heartbeat.next_run_at is None or "interval_minutes" in updates:
            from app.services.heartbeat import next_aligned_time
            heartbeat.next_run_at = next_aligned_time(now, heartbeat.interval_minutes)
    else:
        heartbeat.next_run_at = None

    await db.commit()
    await db.refresh(heartbeat)
    out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat)
    out.effective_runner_mode = _effective_heartbeat_runner_mode(heartbeat, channel=channel)
    return out


@router.post("/channels/{channel_id}/heartbeat/toggle", response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_toggle(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.heartbeat:write")),
):
    """Toggle heartbeat enabled state."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    now = datetime.now(timezone.utc)

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if heartbeat is None:
        heartbeat = ChannelHeartbeat(
            channel_id=channel_id,
            enabled=True,
        )
        db.add(heartbeat)
    else:
        heartbeat.enabled = not heartbeat.enabled

    heartbeat.updated_at = now

    if heartbeat.enabled and heartbeat.next_run_at is None:
        from app.services.heartbeat import next_aligned_time
        heartbeat.next_run_at = next_aligned_time(now, heartbeat.interval_minutes or 30)
    elif not heartbeat.enabled:
        heartbeat.next_run_at = None

    _validate_heartbeat_runner_model(heartbeat, channel=channel)

    await db.commit()
    await db.refresh(heartbeat)
    out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat)
    out.effective_runner_mode = _effective_heartbeat_runner_mode(heartbeat, channel=channel)
    return out


@router.post("/channels/{channel_id}/heartbeat/fire", response_model=HeartbeatConfigOut)
async def admin_channel_heartbeat_fire(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.heartbeat:write")),
):
    """Fire heartbeat immediately (non-blocking — spawns in background)."""
    import asyncio
    from app.services.heartbeat import _safe_fire_heartbeat

    heartbeat = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()

    if not heartbeat:
        raise HTTPException(status_code=404, detail="No heartbeat configured")

    channel = await db.get(Channel, channel_id)
    _validate_heartbeat_runner_model(heartbeat, channel=channel)

    asyncio.create_task(_safe_fire_heartbeat(heartbeat))

    out = HeartbeatConfigOut.from_orm_heartbeat(heartbeat)
    out.effective_runner_mode = _effective_heartbeat_runner_mode(heartbeat, channel=channel)
    return out


class InferHeartbeatOut(BaseModel):
    prompt: str
    workspace_file_path: str | None = None
    workspace_id: str | None = None


@router.post("/channels/{channel_id}/heartbeat/infer", response_model=InferHeartbeatOut)
async def admin_channel_heartbeat_infer(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels.heartbeat:write")),
):
    """Infer a tailored heartbeat prompt from channel context and write it to a workspace file."""
    import traceback
    from app.routers.api_v1_admin.prompts import GeneratePromptIn, generate_prompt

    try:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        bot = get_bot(channel.bot_id)
        if not bot:
            raise HTTPException(status_code=400, detail="Bot not found")

        # Use unified prompt generator
        result = await generate_prompt(GeneratePromptIn(
            field_type="heartbeat",
            bot_id=channel.bot_id,
            channel_id=str(channel_id),
        ))
        prompt_text = result.prompt

        # Write to channel workspace data/heartbeat.md
        ws_file_path = None
        ws_id = None
        try:
            from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
            ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)
            write_workspace_file(str(channel_id), bot, "data/heartbeat.md", prompt_text)
            ws_file_path = f"channels/{channel_id}/data/heartbeat.md"
            ws_id = bot.shared_workspace_id
        except Exception:
            logger.warning("Failed to write heartbeat.md for channel %s", channel_id, exc_info=True)

        return InferHeartbeatOut(
            prompt=prompt_text,
            workspace_file_path=ws_file_path,
            workspace_id=ws_id,
        )
    except (HTTPException, DomainError):
        raise
    except Exception:
        traceback.print_exc()
        logger.error("Heartbeat infer failed for channel %s", channel_id, exc_info=True)
        raise HTTPException(status_code=500, detail=traceback.format_exc())


# ---------------------------------------------------------------------------
# Reindex segments
# ---------------------------------------------------------------------------

@router.post("/channels/{channel_id}/reindex-segments")
async def admin_channel_reindex_segments(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:write")),
):
    """Trigger re-indexing of channel workspace index segments."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    segments = channel.index_segments or []
    if not segments:
        return {"status": "no_segments", "stats": None}

    bot = get_bot(channel.bot_id)

    from app.services.channel_workspace_indexing import index_channel_workspace
    stats = await index_channel_workspace(
        str(channel_id), bot, force=True, channel_segments=segments,
    )
    return {"status": "ok", "stats": stats}


# ---------------------------------------------------------------------------
# Tasks (channel-scoped)
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/tasks", response_model=TaskListOut)
async def admin_channel_tasks(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """List recent tasks for a channel (10, ordered by created_at desc)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    tasks = (await db.execute(
        select(Task)
        .where(Task.channel_id == channel_id)
        .order_by(Task.created_at.desc())
        .limit(10)
    )).scalars().all()

    return TaskListOut(
        tasks=[
            TaskOut(
                id=t.id,
                status=t.status,
                bot_id=t.bot_id,
                prompt=t.prompt,
                title=t.title,
                result=t.result,
                error=t.error,
                dispatch_type=t.dispatch_type,
                task_type=t.task_type,
                recurrence=t.recurrence,
                correlation_id=str(t.correlation_id) if t.correlation_id else None,
                created_at=t.created_at,
                scheduled_at=t.scheduled_at,
                run_at=t.run_at,
                completed_at=t.completed_at,
            )
            for t in tasks
        ],
    )


# ---------------------------------------------------------------------------
# Workflow runs
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/workflow-runs")
async def admin_channel_workflow_runs(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
    all: bool = False,
):
    """List workflow runs for a channel. By default only active runs."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    stmt = select(WorkflowRun).where(WorkflowRun.channel_id == channel_id)
    if not all:
        stmt = stmt.where(WorkflowRun.status.in_(("running", "awaiting_approval")))
    stmt = stmt.order_by(WorkflowRun.created_at.desc()).limit(20)
    rows = (await db.execute(stmt)).scalars().all()

    from app.routers.api_v1_admin.workflows import WorkflowRunOut
    return [WorkflowRunOut.model_validate(r) for r in rows]


@router.get("/channels/{channel_id}/workflow-connections")
async def admin_channel_workflow_connections(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """List workflow connections for a channel: heartbeats and scheduled tasks that trigger workflows."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    connections: list[dict] = []

    # Heartbeat connections
    hb = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one_or_none()
    if hb and hb.workflow_id:
        connections.append({
            "type": "heartbeat",
            "workflow_id": hb.workflow_id,
            "workflow_session_mode": getattr(hb, "workflow_session_mode", None),
            "enabled": hb.enabled,
            "interval_minutes": hb.interval_minutes,
            "bot_id": channel.bot_id,
        })

    # Scheduled task connections
    task_stmt = (
        select(Task)
        .where(
            Task.channel_id == channel_id,
            Task.workflow_id.isnot(None),
            Task.recurrence.isnot(None),
            Task.status.in_(["active", "cancelled"]),
        )
        .order_by(Task.created_at.desc())
    )
    task_rows = (await db.execute(task_stmt)).scalars().all()
    for t in task_rows:
        connections.append({
            "type": "scheduled_task",
            "task_id": str(t.id),
            "workflow_id": t.workflow_id,
            "workflow_session_mode": t.workflow_session_mode,
            "recurrence": t.recurrence,
            "status": t.status,
            "title": t.title,
            "bot_id": t.bot_id,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
        })

    return connections


# ---------------------------------------------------------------------------
# Backfill sections
# ---------------------------------------------------------------------------

class BackfillRequest(BaseModel):
    chunk_size: int = Field(50, ge=1, le=500, description="Messages per section (user+assistant only)")
    model: Optional[str] = None
    provider_id: Optional[str] = None
    history_mode: Optional[str] = None  # "file" or "structured"; default: resolve from channel/bot
    clear_existing: bool = False  # delete all existing sections before backfilling


@router.post("/channels/{channel_id}/backfill-sections")
async def admin_channel_backfill_sections(
    channel_id: uuid.UUID,
    body: BackfillRequest = BackfillRequest(),
    _auth: str = Depends(require_scopes("channels:write")),
):
    """Fire-and-forget backfill — returns a task_id for polling progress."""
    import asyncio
    from app.services.compaction import _drain_backfill

    task_id = str(uuid.uuid4())
    asyncio.create_task(_drain_backfill(
        channel_id=channel_id,
        task_id=task_id,
        chunk_size=body.chunk_size,
        model=body.model,
        provider_id=body.provider_id,
        history_mode=body.history_mode,
        clear_existing=body.clear_existing,
    ))
    return {"task_id": task_id}


@router.get("/channels/{channel_id}/backfill-status/{task_id}")
async def admin_channel_backfill_status(
    channel_id: uuid.UUID,
    task_id: str,
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Poll backfill progress by task_id."""
    from app.services.compaction import _BACKFILL_JOBS

    job = _BACKFILL_JOBS.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    return job


@router.post("/channels/{channel_id}/repair-section-periods")
async def admin_repair_section_periods(
    channel_id: uuid.UUID,
    _auth: str = Depends(require_scopes("channels:write")),
):
    """Backfill missing period_start/period_end on sections from message timestamps."""
    from app.services.compaction import repair_section_periods
    repaired = await repair_section_periods(channel_id)
    return {"repaired": repaired}


@router.post("/channels/{channel_id}/backfill-transcripts")
async def admin_backfill_section_transcripts(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:write")),
):
    """Populate transcript DB column from existing files for sections that have files but no DB transcript."""
    import os
    from app.db.models import ConversationSection
    from app.services.compaction import _get_workspace_root
    from app.services.channel_workspace import _get_ws_root

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    ws_root = None
    channel_ws_root = None
    try:
        bot = get_bot(channel.bot_id)
        ws_root = _get_workspace_root(bot)
        channel_ws_root = _get_ws_root(bot)
    except Exception:
        pass

    rows = (await db.execute(
        select(ConversationSection)
        .where(
            ConversationSection.channel_id == channel_id,
            ConversationSection.transcript.is_(None),
            ConversationSection.transcript_path.is_not(None),
        )
    )).scalars().all()

    populated = 0
    errors = 0
    for sec in rows:
        try:
            if sec.transcript_path.startswith("channels/") and channel_ws_root:
                filepath = os.path.join(channel_ws_root, sec.transcript_path)
            elif ws_root:
                filepath = os.path.join(ws_root, sec.transcript_path)
            else:
                continue
            if not os.path.isfile(filepath):
                continue
            with open(filepath) as f:
                sec.transcript = f.read()
            populated += 1
        except Exception:
            errors += 1

    if populated:
        await db.commit()

    return {"populated": populated, "errors": errors, "total_missing": len(rows)}


# ---------------------------------------------------------------------------
# Conversation sections list
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/sections")
async def admin_channel_sections(
    channel_id: uuid.UUID,
    scope: SectionScope = Query("current"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """List conversation sections for the active session or all channel sessions."""
    import math
    import os
    from sqlalchemy.orm import defer
    from app.db.models import ConversationSection
    from app.services.compaction import _get_workspace_root

    if scope not in ("current", "all"):
        raise HTTPException(status_code=400, detail="scope must be current or all")

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    active_session = await db.get(Session, channel.active_session_id) if channel.active_session_id else None

    query = select(ConversationSection).where(ConversationSection.channel_id == channel_id)
    if scope == "current":
        if not active_session:
            query = query.where(ConversationSection.session_id.is_(None), ConversationSection.id.is_(None))
        else:
            query = query.where(ConversationSection.session_id == active_session.id)

    rows = (
        await db.execute(
            query
            .order_by(
                ConversationSection.sequence if scope == "current" else ConversationSection.period_start,
                ConversationSection.created_at,
                ConversationSection.sequence,
            )
            .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
        )
    ).scalars().all()
    row_ids = [s.id for s in rows]
    transcript_section_ids = set(
        (
            await db.execute(
                select(ConversationSection.id)
                .where(ConversationSection.id.in_(row_ids))
                .where(ConversationSection.transcript.is_not(None))
            )
        ).scalars().all()
    ) if row_ids else set()

    all_section_count = (
        await db.execute(
            select(func.count())
            .select_from(ConversationSection)
            .where(ConversationSection.channel_id == channel_id)
        )
    ).scalar_one()
    other_session_section_count = all_section_count - len(rows) if scope == "current" else 0
    session_by_id = await _load_section_sessions(db, rows, channel.active_session_id)

    # Resolve workspace root for file existence checks
    ws_root = None
    channel_ws_root = None
    try:
        bot = get_bot(channel.bot_id)
        ws_root = _get_workspace_root(bot)
        from app.services.channel_workspace import _get_ws_root
        channel_ws_root = _get_ws_root(bot)
    except Exception:
        pass

    def _file_exists(s) -> bool | None:
        if not s.transcript_path:
            return None
        if s.transcript_path.startswith("channels/") and channel_ws_root:
            return os.path.isfile(os.path.join(channel_ws_root, s.transcript_path))
        if not ws_root:
            return None
        return os.path.isfile(os.path.join(ws_root, s.transcript_path))

    sections_out = []
    files_ok = 0
    files_missing = 0
    files_none = 0
    periods_missing = 0
    for s in rows:
        fe = _file_exists(s)
        if fe is True:
            files_ok += 1
        elif fe is False:
            files_missing += 1
        else:
            files_none += 1
        if not s.period_start:
            periods_missing += 1
        sections_out.append({
            "id": str(s.id),
            "sequence": s.sequence,
            "title": s.title,
            "summary": s.summary,
            "transcript_path": s.transcript_path,
            "message_count": s.message_count,
            "chunk_size": s.chunk_size,
            "period_start": s.period_start.isoformat() if s.period_start else None,
            "period_end": s.period_end.isoformat() if s.period_end else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "view_count": s.view_count,
            "last_viewed_at": s.last_viewed_at.isoformat() if s.last_viewed_at else None,
            "tags": s.tags or [],
            "file_exists": fe,
            "has_transcript": s.id in transcript_section_ids,
            "session": _section_session_out(session_by_id.get(s.session_id), channel.active_session_id),
        })

    # Coverage stats
    total_messages = await _count_eligible_messages_for_session(db, active_session) if scope == "current" else 0
    covered_messages = sum(s.message_count for s in rows)
    remaining_messages = max(0, total_messages - covered_messages) if scope == "current" else 0
    last_chunk = rows[-1].chunk_size if rows else 50
    estimated_remaining = math.ceil(remaining_messages / last_chunk) if remaining_messages > 0 else 0

    return {
        "sections": sections_out,
        "total": len(rows),
        "scope": scope,
        "stats": {
            "scope": scope,
            "coverage_mode": "current" if scope == "current" else "inventory",
            "total_messages": total_messages,
            "covered_messages": covered_messages,
            "estimated_remaining": estimated_remaining,
            "all_section_count": all_section_count,
            "other_session_section_count": other_session_section_count,
            "files_ok": files_ok,
            "files_missing": files_missing,
            "files_none": files_none,
            "periods_missing": periods_missing,
        },
    }


@router.get("/channels/{channel_id}/sections/search")
async def admin_channel_section_search(
    channel_id: uuid.UUID,
    q: str = Query(..., min_length=1),
    scope: SectionScope = Query("current"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Search conversation sections by topic, content, or semantic similarity."""
    from app.db.models import ConversationSection
    from app.tools.local.conversation_history import search_sections

    if scope not in ("current", "all"):
        raise HTTPException(status_code=400, detail="scope must be current or all")

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if scope == "current":
        session_ids = [channel.active_session_id] if channel.active_session_id else []
    else:
        session_ids = (
            await db.execute(
                select(ConversationSection.session_id)
                .where(ConversationSection.channel_id == channel_id)
                .where(ConversationSection.session_id.is_not(None))
                .distinct()
            )
        ).scalars().all()

    sessions = (
        await db.execute(select(Session).where(Session.id.in_(session_ids)))
    ).scalars().all() if session_ids else []
    session_by_id = {s.id: s for s in sessions}

    results = []
    for session_id in session_ids:
        if not session_id:
            continue
        for result in await search_sections(session_id, q):
            result["session"] = session_by_id.get(session_id)
            results.append(result)

    return {
        "scope": scope,
        "results": [
            {
                "section": {
                    "id": str(r["section"].id),
                    "sequence": r["section"].sequence,
                    "title": r["section"].title,
                    "summary": r["section"].summary,
                    "message_count": r["section"].message_count,
                    "period_start": r["section"].period_start.isoformat() if r["section"].period_start else None,
                    "tags": r["section"].tags or [],
                },
                "session": _section_session_out(r.get("session"), channel.active_session_id),
                "source": r["source"],
                "snippet": r.get("snippet"),
            }
            for r in results
        ],
    }


@router.get("/channels/{channel_id}/section-index-preview")
async def admin_section_index_preview(
    channel_id: uuid.UUID,
    count: int = Query(10, ge=0, le=100),
    verbosity: str = Query("standard"),
    scope: SectionScope = Query("current"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Preview the section index that would be injected into context."""
    from app.db.models import ConversationSection
    from app.services.compaction import format_section_index

    if verbosity not in ("compact", "standard", "detailed"):
        raise HTTPException(status_code=400, detail="verbosity must be compact, standard, or detailed")
    if scope not in ("current", "all"):
        raise HTTPException(status_code=400, detail="scope must be current or all")

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    query = select(ConversationSection).where(ConversationSection.channel_id == channel_id)
    if scope == "current":
        if not channel.active_session_id:
            query = query.where(ConversationSection.session_id.is_(None), ConversationSection.id.is_(None))
        else:
            query = query.where(ConversationSection.session_id == channel.active_session_id)

    rows = (
        await db.execute(
            query
            .order_by(ConversationSection.sequence.desc())
            .limit(count)
        )
    ).scalars().all()

    if not rows:
        return {"content": "", "section_count": 0, "chars": 0, "scope": scope}

    content = format_section_index(rows, verbosity=verbosity)
    return {"content": content, "section_count": len(rows), "chars": len(content), "scope": scope}


# ---------------------------------------------------------------------------
# Compaction logs
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/compaction-logs")
async def admin_channel_compaction_logs(
    channel_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Return recent compaction log entries for a channel."""
    total_result = await db.execute(
        select(func.count())
        .select_from(CompactionLog)
        .where(CompactionLog.channel_id == channel_id)
    )
    total = total_result.scalar() or 0

    result = await db.execute(
        select(CompactionLog)
        .where(CompactionLog.channel_id == channel_id)
        .order_by(CompactionLog.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    # Enrich logs that have a correlation_id with tool calls + token stats
    correlation_ids = [r.correlation_id for r in rows if r.correlation_id]
    tc_by_corr: dict[uuid.UUID, list] = {}
    stats_by_corr: dict[uuid.UUID, dict] = {}
    if correlation_ids:
        tc_rows = (await db.execute(
            select(ToolCall)
            .where(ToolCall.correlation_id.in_(correlation_ids))
            .order_by(ToolCall.created_at)
        )).scalars().all()
        for tc in tc_rows:
            tc_by_corr.setdefault(tc.correlation_id, []).append(tc)

        te_rows = (await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.correlation_id.in_(correlation_ids),
                TraceEvent.event_type == "token_usage",
            )
        )).scalars().all()
        for te in te_rows:
            s = stats_by_corr.setdefault(te.correlation_id, {"tokens": 0, "iterations": 0})
            if te.data:
                s["tokens"] += te.data.get("total_tokens", 0)
                s["iterations"] = max(s["iterations"], te.data.get("iteration", 0))

    logs = []
    for r in rows:
        prompt = r.prompt_tokens or 0
        completion = r.completion_tokens or 0
        entry: dict = {
            "id": str(r.id),
            "model": r.model,
            "history_mode": r.history_mode,
            "tier": r.tier,
            "forced": r.forced,
            "memory_flush": r.memory_flush,
            "messages_archived": r.messages_archived,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": prompt + completion if (r.prompt_tokens or r.completion_tokens) else None,
            "duration_ms": r.duration_ms,
            "section_id": str(r.section_id) if r.section_id else None,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        if r.flush_result:
            entry["flush_result"] = r.flush_result
        if r.correlation_id:
            entry["correlation_id"] = str(r.correlation_id)
            tcs = tc_by_corr.get(r.correlation_id, [])
            if tcs:
                entry["tool_calls"] = build_tool_call_previews(tcs)
            stats = stats_by_corr.get(r.correlation_id)
            if stats:
                entry["flush_tokens"] = stats["tokens"]
                entry["flush_iterations"] = stats["iterations"]
        logs.append(entry)

    return {"logs": logs, "total": total}


# ---------------------------------------------------------------------------
# Context breakdown
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/context-breakdown")
async def admin_channel_context_breakdown(
    channel_id: uuid.UUID,
    mode: str = "last_turn",
    session_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Detailed context breakdown for the channel's active conversation.

    ``mode=last_turn`` (default) — the headline ``total_tokens_approx`` is
    the API-reported ``prompt_tokens`` from the most recent turn, so the
    dev panel agrees with the chat header.

    ``mode=next_turn`` — the headline total is a forecast over the channel's
    current static configuration. May differ from the chat header by design.
    """
    from app.services.context_breakdown import compute_context_breakdown
    from dataclasses import asdict

    if mode not in {"last_turn", "next_turn"}:
        raise HTTPException(status_code=422, detail="mode must be 'last_turn' or 'next_turn'")

    try:
        result = await compute_context_breakdown(
            str(channel_id),
            db,
            mode=mode,
            session_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "channel_id": result.channel_id,
        "session_id": result.session_id,
        "bot_id": result.bot_id,
        "context_profile": result.context_profile,
        "context_origin": result.context_origin,
        "live_history_turns": result.live_history_turns,
        "mandatory_static_injections": result.mandatory_static_injections,
        "optional_static_injections": result.optional_static_injections,
        "categories": [asdict(c) for c in result.categories],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "compaction": asdict(result.compaction),
        "reranking": asdict(result.reranking),
        "effective_settings": {
            k: {"value": v.value, "source": v.source}
            for k, v in result.effective_settings.items()
        },
        "context_budget": result.context_budget,
        "mode": mode,
        "disclaimer": result.disclaimer,
    }


@router.get("/channels/{channel_id}/config-overhead")
async def admin_channel_config_overhead(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Estimate configuration overhead (tools, skills, system prompt) before any conversation."""
    from dataclasses import asdict
    from app.agent.context_budget import get_model_context_window
    from app.services.context_estimate import estimate_bot_context
    from app.services.widget_context import fetch_channel_pin_dicts

    channel = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel_pinned_widgets = await fetch_channel_pin_dicts(db, channel.id)

    bot = get_bot(channel.bot_id)

    # Apply channel overrides to tool/skill lists
    local_tools = list(bot.local_tools)
    mcp_servers = list(bot.mcp_servers)
    client_tools = list(bot.client_tools or [])
    skills = [{"id": s.id, "mode": s.mode or "on_demand"} for s in bot.skills]

    disabled_local = set(channel.local_tools_disabled or [])
    disabled_mcp = set(channel.mcp_servers_disabled or [])
    disabled_client = set(channel.client_tools_disabled or [])

    if disabled_local:
        local_tools = [t for t in local_tools if t not in disabled_local]
    if disabled_mcp:
        mcp_servers = [s for s in mcp_servers if s not in disabled_mcp]
    if disabled_client:
        client_tools = [t for t in client_tools if t not in disabled_client]

    # Build a draft dict from the resolved bot config + channel overrides
    draft: dict = {
        "name": bot.name,
        "model": channel.model_override or bot.model,
        "system_prompt": bot.system_prompt or "",
        "persona": bool(bot.persona),
        "persona_content": "",  # persona loaded at runtime from DB/files; omit from static estimate
        "local_tools": local_tools,
        "mcp_servers": mcp_servers,
        "client_tools": client_tools,
        "pinned_tools": list(bot.pinned_tools or []),
        "skills": skills,
        "tool_retrieval": bot.tool_retrieval if bot.tool_retrieval is not None else True,
        "tool_similarity_threshold": bot.tool_similarity_threshold,
        "memory_enabled": bot.memory.enabled if bot.memory else False,
        "memory_similarity_threshold": getattr(bot.memory, "similarity_threshold", None),
        "memory_max_inject_chars": getattr(bot.memory, "max_inject_chars", None),
        "filesystem_indexes": bot.filesystem_indexes or [],
        "delegation_config": {"delegate_bots": list(bot.delegate_bots)} if bot.delegate_bots else {},
        "history_mode": bot.history_mode,
        "context_pruning": bot.context_pruning,
        "audio_input": bot.audio_input or "transcribe",
        "pinned_widgets": channel_pinned_widgets,
        "channel_config": channel.config or {},
    }

    result = await estimate_bot_context(draft=draft, bot_id=bot.id)

    # Resolve model context window for overhead percentage
    effective_model = channel.model_override or bot.model
    provider_id = None
    if "/" in effective_model:
        provider_id, _ = effective_model.split("/", 1)
    context_window = get_model_context_window(effective_model, provider_id)

    return {
        "lines": [asdict(line) for line in result.lines],
        "total_chars": result.total_chars,
        "approx_tokens": result.approx_tokens,
        "context_window": context_window,
        "overhead_pct": round(result.approx_tokens / context_window, 4) if context_window else None,
        "disclaimer": result.disclaimer,
    }


@router.get("/channels/{channel_id}/context-budget")
async def admin_channel_context_budget(
    channel_id: uuid.UUID,
    session_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Return the latest context budget for this channel (from trace events).

    Thin alias over :func:`fetch_latest_context_budget`. The admin UI already
    consumes this path; the public mirror lives at
    ``/api/v1/channels/{id}/context-budget``.
    """
    from app.services.context_breakdown import fetch_latest_context_budget

    return await fetch_latest_context_budget(channel_id, db, session_id=session_id)


@router.get("/channels/{channel_id}/context-preview")
async def admin_channel_context_preview(
    channel_id: uuid.UUID,
    include_history: bool = Query(False, description="Include conversation messages from the active conversation"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("channels:read")),
):
    """Render a preview of all system messages that would be injected before a user message."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    preview = await assemble_for_preview(channel_id, user_message="")
    return build_context_preview_response(preview, include_history=include_history)


# ---------------------------------------------------------------------------
# Enriched (display name resolution)
# ---------------------------------------------------------------------------

async def _resolve_display_names(channels: list) -> dict[uuid.UUID, str]:
    """Resolve display names for channels via integration hooks."""
    from app.agent.hooks import resolve_all_display_names
    return await resolve_all_display_names(channels)


@router.get("/channels-enriched", response_model=ChannelListOut)
async def admin_channels_enriched(
    integration: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace_id (use 'none' for unassigned)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth_result=Depends(require_scopes("channels:read")),
):
    """List channels with integration-resolved display names."""
    stmt_base = select(Channel).order_by(Channel.name.asc())
    stmt_base = apply_channel_visibility(stmt_base, auth_result)
    if integration:
        stmt_base = stmt_base.where(Channel.integration == integration)
    if bot_id:
        stmt_base = stmt_base.where(Channel.bot_id == bot_id)
    if workspace_id is not None:
        from sqlalchemy import or_
        # Always include orchestrator channel regardless of workspace filter
        orchestrator_clause = Channel.client_id == "orchestrator:home"
        if workspace_id == "none":
            stmt_base = stmt_base.where(or_(Channel.workspace_id.is_(None), orchestrator_clause))
        else:
            try:
                ws_uuid = uuid.UUID(workspace_id)
            except ValueError:
                raise HTTPException(400, f"Invalid workspace_id: {workspace_id}")
            stmt_base = stmt_base.where(or_(Channel.workspace_id == ws_uuid, orchestrator_clause))

    total = (await db.execute(
        select(func.count()).select_from(stmt_base.subquery())
    )).scalar_one()

    stmt = stmt_base.options(selectinload(Channel.integrations))

    offset = (page - 1) * page_size
    channels = (await db.execute(
        stmt.offset(offset).limit(page_size)
    )).scalars().all()

    display_names = await _resolve_display_names(channels)

    # Batch-load heartbeat rows for all channels
    channel_ids = [ch.id for ch in channels]
    hb_map: dict[uuid.UUID, ChannelHeartbeat] = {}
    last_active_map: dict[uuid.UUID, datetime] = {}
    recent_count_map: dict[uuid.UUID, int] = {}
    preview_map: dict[uuid.UUID, str] = {}
    if channel_ids:
        hb_rows = (await db.execute(
            select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id.in_(channel_ids))
        )).scalars().all()
        hb_map = {hb.channel_id: hb for hb in hb_rows}

        # Per-channel last activity via most recent session. Session.last_active
        # is updated whenever a message is persisted (see app/services/sessions.py),
        # so it tracks "last message time" without hitting the messages table.
        activity_rows = (await db.execute(
            select(
                Session.channel_id,
                func.max(Session.last_active).label("last_active"),
            )
            .where(Session.channel_id.in_(channel_ids))
            .group_by(Session.channel_id)
        )).all()
        last_active_map = {r.channel_id: r.last_active for r in activity_rows if r.channel_id}

        # Recent-message count over the last 24h, grouped by channel. Used by
        # the spatial canvas channel tile + any future "is this channel hot?"
        # surface. Joins through Session because ``Message.channel_id`` does
        # not exist; the FK lives on the session row.
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_count_rows = (await db.execute(
            select(
                Session.channel_id.label("channel_id"),
                func.count(Message.id).label("cnt"),
            )
            .join(Message, Message.session_id == Session.id)
            .where(Session.channel_id.in_(channel_ids))
            .where(Message.created_at >= cutoff_24h)
            .where(Message.role.in_(("user", "assistant")))
            .group_by(Session.channel_id)
        )).all()
        recent_count_map = {r.channel_id: int(r.cnt) for r in recent_count_rows if r.channel_id}

        # Latest message body per channel for the snapshot-tier preview text.
        # ROW_NUMBER window keeps it to one query — works on PostgreSQL and
        # SQLite (the test backend) alike. Tool-call-only assistant messages
        # have NULL content and are excluded.
        rn = func.row_number().over(
            partition_by=Session.channel_id,
            order_by=Message.created_at.desc(),
        ).label("rn")
        preview_subq = (
            select(
                Session.channel_id.label("channel_id"),
                Message.content.label("content"),
                rn,
            )
            .join(Message, Message.session_id == Session.id)
            .where(Session.channel_id.in_(channel_ids))
            .where(Message.role.in_(("user", "assistant")))
            .where(Message.content.isnot(None))
            .subquery()
        )
        preview_rows = (await db.execute(
            select(preview_subq.c.channel_id, preview_subq.c.content)
            .where(preview_subq.c.rn == 1)
        )).all()
        for r in preview_rows:
            if not r.channel_id or not r.content:
                continue
            preview_map[r.channel_id] = _format_message_preview(r.content)

    from app.services.heartbeat import _is_heartbeat_in_quiet_hours

    enriched = []
    for ch in channels:
        out = ChannelOut.model_validate(ch)
        out.display_name = display_names.get(ch.id)
        ws_id_str = str(ch.workspace_id) if ch.workspace_id else None
        out.resolved_workspace_id = ws_id_str or _resolve_workspace_id(ch.bot_id)
        out.category = (ch.metadata_ or {}).get("category")
        out.tags = (ch.metadata_ or {}).get("tags", [])
        out.last_message_at = last_active_map.get(ch.id)
        out.recent_message_count_24h = recent_count_map.get(ch.id, 0)
        out.last_message_preview = preview_map.get(ch.id)
        hb = hb_map.get(ch.id)
        if hb and hb.enabled:
            out.heartbeat_enabled = True
            out.heartbeat_in_quiet_hours = _is_heartbeat_in_quiet_hours(hb)
        enriched.append(out)

    return ChannelListOut(
        channels=enriched,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Global activatable integrations (no channel required — for wizard)
# ---------------------------------------------------------------------------

@router.get("/integrations/activatable")
async def list_activatable_integrations_global(
    _auth=Depends(require_scopes("channels.integrations:read")),
):
    """List all integrations with activation manifests (no channel context).

    Used by the channel creation wizard to show what can be activated.
    All items returned with activated=False since there's no channel yet.
    """
    from integrations import get_activation_manifests

    manifests = get_activation_manifests()
    result = []
    for itype, manifest in manifests.items():
        result.append({
            "integration_type": itype,
            "description": manifest.get("description", ""),
            "requires_workspace": manifest.get("requires_workspace", False),
            "activated": False,
            "tools": list(manifest.get("tools", []) or []),
            "has_system_prompt": bool(manifest.get("system_prompt")),
            "version": manifest.get("version"),
            "includes": manifest.get("includes", []),
        })
    return result


# ---------------------------------------------------------------------------
# Available integrations
# ---------------------------------------------------------------------------

@router.get("/channels/integrations/available")
async def available_integrations(
    _auth=Depends(require_scopes("channels.integrations:read")),
):
    """List registered integration types with binding metadata."""
    from app.integrations import renderer_registry
    from integrations import discover_binding_metadata, discover_integrations

    # Collect from renderer registry — Phase G replaced the legacy
    # dispatcher registry. The "core" renderers (none/web/webhook/
    # internal) are infrastructure, not user-facing integration types,
    # so they're filtered out the same way the legacy code did.
    types = set(renderer_registry.all_renderers().keys()) - {
        "none", "web", "webhook", "internal",
    }

    # Collect from integration discovery (an integration may have a
    # router/hooks but no renderer yet — still surface it).
    for integration_id, _ in discover_integrations():
        types.add(integration_id)

    # Attach binding metadata from setup.py
    binding_meta = discover_binding_metadata()

    return [
        {
            "type": t,
            "binding": binding_meta.get(t),
        }
        for t in sorted(types)
    ]
