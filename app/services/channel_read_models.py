"""Channel response projection helpers shared by public and admin routers."""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.config import settings
from app.db.models import Channel, ChannelHeartbeat, Message, Project, Session
from app.schemas.channels import (
    AdminChannelOut,
    ChannelBotMemberOut,
    ChannelOut as PublicChannelOut,
    ChannelListItemOut,
    ChannelSettingsOut,
    ProjectSummaryOut,
)
from app.services.projects import (
    PROJECT_PATH_KEY,
    PROJECT_WORKSPACE_ID_KEY,
    normalize_project_path,
    resolve_project_workspace_id,
)

GetBot = Callable[[str], Any]
_PREVIEW_MAX_LEN = 80


def resolve_workspace_id(bot_id: str, *, get_bot_fn: GetBot = get_bot) -> str | None:
    """Get the shared workspace ID for a bot, if any."""
    try:
        bot = get_bot_fn(bot_id)
        return bot.shared_workspace_id
    except Exception:
        return None


def resolve_index_segment_defaults(bot_id: str, *, get_bot_fn: GetBot = get_bot) -> dict:
    """Resolve effective default values for index segment fields from bot config."""
    try:
        bot = get_bot_fn(bot_id)
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
    return {
        "embedding_model": settings.EMBEDDING_MODEL,
        "patterns": ["**/*.py", "**/*.md", "**/*.yaml"],
        "similarity_threshold": settings.FS_INDEX_SIMILARITY_THRESHOLD,
        "top_k": settings.FS_INDEX_TOP_K,
    }


def enrich_bot_members(channel: Channel, *, get_bot_fn: GetBot = get_bot) -> list[ChannelBotMemberOut]:
    """Enrich bot member rows with bot names from the registry."""
    result: list[ChannelBotMemberOut] = []
    for member in channel.bot_members or []:
        out = ChannelBotMemberOut.model_validate(member)
        try:
            out.bot_name = get_bot_fn(member.bot_id).name
        except Exception:
            out.bot_name = member.bot_id
        result.append(out)
    return result


def _project_summary(project: Project | None) -> ProjectSummaryOut | None:
    return ProjectSummaryOut.model_validate(project) if project is not None else None


def _project_for(
    channel: Channel,
    *,
    project: Project | None = None,
    project_map: dict[uuid.UUID, Project] | None = None,
) -> Project | None:
    if project is not None:
        return project
    if channel.project_id and project_map:
        return project_map.get(channel.project_id)
    return None


def _metadata_category(channel: Channel) -> str | None:
    return (channel.metadata_ or {}).get("category")


def _metadata_tags(channel: Channel) -> list[str]:
    return (channel.metadata_ or {}).get("tags", [])


def build_public_channel_out(
    channel: Channel,
    *,
    project: Project | None = None,
    project_map: dict[uuid.UUID, Project] | None = None,
    get_bot_fn: GetBot = get_bot,
) -> PublicChannelOut:
    out = PublicChannelOut.model_validate(channel)
    out.project = _project_summary(_project_for(channel, project=project, project_map=project_map))
    ws_id_str = str(channel.workspace_id) if channel.workspace_id else None
    out.resolved_workspace_id = ws_id_str or resolve_workspace_id(channel.bot_id, get_bot_fn=get_bot_fn)
    out.category = _metadata_category(channel)
    out.tags = _metadata_tags(channel)
    out.member_bots = enrich_bot_members(channel, get_bot_fn=get_bot_fn)
    return out


def build_public_channel_list_item_out(
    channel: Channel,
    *,
    heartbeat: ChannelHeartbeat | None = None,
    project_map: dict[uuid.UUID, Project] | None = None,
    get_bot_fn: GetBot = get_bot,
) -> ChannelListItemOut:
    out = ChannelListItemOut.model_validate(
        build_public_channel_out(channel, project_map=project_map, get_bot_fn=get_bot_fn)
    )
    out.heartbeat_enabled = heartbeat.enabled if heartbeat else False
    out.heartbeat_next_run_at = heartbeat.next_run_at if heartbeat else None
    return out


def build_admin_channel_out(
    channel: Channel,
    *,
    display_name: str | None = None,
    last_message_at: datetime | None = None,
    recent_message_count_24h: int = 0,
    last_message_preview: str | None = None,
    heartbeat: ChannelHeartbeat | None = None,
    get_bot_fn: GetBot = get_bot,
) -> AdminChannelOut:
    out = AdminChannelOut.model_validate(channel)
    out.display_name = display_name
    out.resolved_workspace_id = str(channel.workspace_id) if channel.workspace_id else resolve_workspace_id(
        channel.bot_id,
        get_bot_fn=get_bot_fn,
    )
    out.category = _metadata_category(channel)
    out.tags = _metadata_tags(channel)
    out.member_bots = [member.model_dump(mode="json") for member in enrich_bot_members(channel, get_bot_fn=get_bot_fn)]
    out.last_message_at = last_message_at
    out.recent_message_count_24h = recent_message_count_24h
    out.last_message_preview = last_message_preview
    if heartbeat and heartbeat.enabled:
        from app.services.heartbeat import _is_heartbeat_in_quiet_hours

        out.heartbeat_enabled = True
        out.heartbeat_in_quiet_hours = _is_heartbeat_in_quiet_hours(heartbeat)
    return out


def format_message_preview(content: str) -> str:
    """Compact a message body for the channel-tile preview line."""
    flat = " ".join(content.split())
    if len(flat) <= _PREVIEW_MAX_LEN:
        return flat
    return flat[:_PREVIEW_MAX_LEN].rstrip() + "\u2026"


async def load_project_map(db: AsyncSession, channels: Iterable[Channel]) -> dict[uuid.UUID, Project]:
    project_ids = [channel.project_id for channel in channels if channel.project_id]
    if not project_ids:
        return {}
    projects = (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
    return {project.id: project for project in projects}


async def load_heartbeat_map(db: AsyncSession, channel_ids: list[uuid.UUID]) -> dict[uuid.UUID, ChannelHeartbeat]:
    if not channel_ids:
        return {}
    rows = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id.in_(channel_ids))
    )).scalars().all()
    return {heartbeat.channel_id: heartbeat for heartbeat in rows}


async def load_admin_activity_maps(
    db: AsyncSession,
    channel_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, datetime], dict[uuid.UUID, int], dict[uuid.UUID, str]]:
    if not channel_ids:
        return {}, {}, {}

    activity_rows = (await db.execute(
        select(
            Session.channel_id,
            func.max(Session.last_active).label("last_active"),
        )
        .where(Session.channel_id.in_(channel_ids))
        .group_by(Session.channel_id)
    )).all()
    last_active_map = {row.channel_id: row.last_active for row in activity_rows if row.channel_id}

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
    recent_count_map = {row.channel_id: int(row.cnt) for row in recent_count_rows if row.channel_id}

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
        select(preview_subq.c.channel_id, preview_subq.c.content).where(preview_subq.c.rn == 1)
    )).all()
    preview_map = {
        row.channel_id: format_message_preview(row.content)
        for row in preview_rows
        if row.channel_id and row.content
    }
    return last_active_map, recent_count_map, preview_map


async def build_admin_channel_settings_out(
    db: AsyncSession,
    channel: Channel,
    *,
    get_bot_fn: GetBot = get_bot,
) -> ChannelSettingsOut:
    out = ChannelSettingsOut.model_validate(channel)
    out.index_segment_defaults = resolve_index_segment_defaults(channel.bot_id, get_bot_fn=get_bot_fn)
    ws_id_str = str(channel.workspace_id) if channel.workspace_id else None
    out.resolved_workspace_id = ws_id_str or resolve_workspace_id(channel.bot_id, get_bot_fn=get_bot_fn)
    out.category = _metadata_category(channel)
    out.tags = _metadata_tags(channel)
    cfg = channel.config or {}
    out.pipeline_mode = cfg.get("pipeline_mode") or "auto"
    out.layout_mode = cfg.get("layout_mode") or "full"
    out.chat_mode = cfg.get("chat_mode") or "default"
    out.native_context_policy = cfg.get("native_context_policy") or "default"
    try:
        from app.agent.context_profiles import resolve_native_context_policy

        out.effective_native_context_policy = resolve_native_context_policy(channel=channel)
    except Exception:
        out.effective_native_context_policy = "standard"
    out.native_context_live_history_ratio = cfg.get("native_context_live_history_ratio")
    out.native_context_min_recent_turns = cfg.get("native_context_min_recent_turns")
    out.native_context_warning_utilization = cfg.get("native_context_warning_utilization")
    out.native_context_compaction_utilization = cfg.get("native_context_compaction_utilization")
    out.header_backdrop_mode = cfg.get("header_backdrop_mode") or "glass"
    out.plan_mode_control = cfg.get("plan_mode_control") or "auto"
    out.widget_theme_ref = cfg.get("widget_theme_ref")
    out.widget_agency_mode = cfg.get("widget_agency_mode") or "propose"
    out.pinned_widget_context_enabled = cfg.get("pinned_widget_context_enabled", True)
    await fill_channel_project_settings(db, out, channel, get_bot_fn=get_bot_fn)
    return out


async def fill_channel_project_settings(
    db: AsyncSession,
    out: ChannelSettingsOut,
    channel: Channel,
    *,
    get_bot_fn: GetBot = get_bot,
) -> None:
    out.project_id = channel.project_id
    if channel.project_id:
        project = await db.get(Project, channel.project_id)
        if project is not None:
            out.project = ProjectSummaryOut.model_validate(project)
            out.project_workspace_id = str(project.workspace_id)
            out.project_path = project.root_path
            out.resolved_project_workspace_id = str(project.workspace_id)
            return
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
        bot = get_bot_fn(channel.bot_id)
    except Exception:
        bot = None
    out.resolved_project_workspace_id = resolve_project_workspace_id(channel, bot)
