"""Usage anomaly and agent-smell read models."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Bot, BotSkillEnrollment, BotToolEnrollment, Channel, ProviderConfig,
    Skill, Task, ToolCall, TraceEvent,
)
from app.services.usage_costs import (
    _fetch_token_usage_events,
    _get_provider_type_map,
    _is_plan_billed,
    _load_pricing_map,
    _parse_time,
    _resolve_event_cost,
)
from app.schemas.usage import (
    CostByDimension, UsageSummaryOut, UsageLogEntry, UsageLogsOut, BreakdownGroup, UsageBreakdownOut, TimeseriesPoint, UsageTimeseriesOut, UsageAnomalyMetric, UsageAnomalySource, UsageAnomalySignal, UsageAnomaliesOut, AgentSmellReason, AgentSmellMetrics, AgentSmellTraceEvidence, AgentSmellBot, AgentSmellSummary, AgentSmellOut, ForecastComponent, LimitForecast, UsageForecastOut, ProviderHealthRow, ProviderHealthOut
)


def _metric_from_events(
    events: list[TraceEvent],
    pricing: dict,
    ptype_map: dict[str | None, str],
) -> UsageAnomalyMetric:
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    calls = 0
    cost_total = 0.0
    has_cost_data = True
    for ev in events:
        d = ev.data or {}
        pt = int(d.get("prompt_tokens") or 0)
        ct = int(d.get("completion_tokens") or 0)
        tt = int(d.get("total_tokens") or (pt + ct))
        total_tokens += tt
        prompt_tokens += pt
        completion_tokens += ct
        calls += 1
        cost = _resolve_event_cost(d, pricing, ptype_map)
        if cost is None:
            has_cost_data = False
        else:
            cost_total += cost
    return UsageAnomalyMetric(
        tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        calls=calls,
        cost=round(cost_total, 6) if cost_total > 0 else None,
        has_cost_data=has_cost_data,
    )


def _metric_ratio(current: UsageAnomalyMetric, baseline: UsageAnomalyMetric | None) -> float | None:
    if not baseline or baseline.tokens <= 0:
        return None
    return round(current.tokens / baseline.tokens, 2)


def _severity(metric: UsageAnomalyMetric, ratio: float | None) -> str:
    if metric.tokens >= 100_000 or (ratio is not None and ratio >= 5):
        return "danger"
    if metric.tokens >= 25_000 or (ratio is not None and ratio >= 2):
        return "warning"
    return "info"


def _source_type_for_trace(correlation_id: uuid.UUID | None, task_by_corr: dict[str, Task]) -> str:
    if not correlation_id:
        return "agent"
    task = task_by_corr.get(str(correlation_id))
    if not task:
        return "agent"
    if task.task_type == "heartbeat":
        return "heartbeat"
    if task.task_type in ("memory_hygiene", "skill_review"):
        return "maintenance"
    if task.parent_task_id or task.recurrence:
        return "task"
    return task.task_type or "task"


def _cost_confidence_for_events(
    events: list[TraceEvent],
    pricing: dict,
    provider_type_map: dict[str | None, str],
) -> str:
    if not events:
        return "unknown"
    states: set[str] = set()
    for ev in events:
        d = ev.data or {}
        provider_id = d.get("provider_id")
        model = d.get("model")
        if _is_plan_billed(provider_id, model):
            states.add("plan")
            continue
        ptype = provider_type_map.get(provider_id)
        if ptype in {"ollama", "local"} or (model and str(model).startswith("ollama/")):
            states.add("local")
            continue
        if _resolve_event_cost(d, pricing, provider_type_map) is not None:
            states.add("metered")
        else:
            states.add("missing")
    if "metered" in states:
        return "metered"
    if "plan" in states:
        return "plan"
    if "local" in states:
        return "local"
    if "missing" in states:
        return "missing"
    return "unknown"


async def _usage_source_maps(
    db: AsyncSession,
    events: list[TraceEvent],
) -> tuple[dict[str, Task], dict[str, str], dict[str, str]]:
    corr_ids = [ev.correlation_id for ev in events if ev.correlation_id]
    tasks_by_corr: dict[str, Task] = {}
    if corr_ids:
        task_rows = (await db.execute(
            select(Task).where(Task.correlation_id.in_(corr_ids))
        )).scalars().all()
        tasks_by_corr = {str(task.correlation_id): task for task in task_rows if task.correlation_id}

    channel_ids: set[str] = set()
    for ev in events:
        cid = (ev.data or {}).get("channel_id")
        if cid:
            channel_ids.add(str(cid))
    for task in tasks_by_corr.values():
        if task.channel_id:
            channel_ids.add(str(task.channel_id))

    channel_name_map: dict[str, str] = {}
    valid_channel_ids: list[uuid.UUID] = []
    for cid in channel_ids:
        try:
            valid_channel_ids.append(uuid.UUID(cid))
        except ValueError:
            pass
    if valid_channel_ids:
        rows = (await db.execute(
            select(Channel.id, Channel.name).where(Channel.id.in_(valid_channel_ids))
        )).all()
        channel_name_map = {str(row.id): row.name for row in rows}

    provider_names: dict[str, str] = {}
    provider_rows = (await db.execute(
        select(ProviderConfig.id, ProviderConfig.display_name)
    )).all()
    for row in provider_rows:
        provider_names[row.id] = row.display_name

    return tasks_by_corr, channel_name_map, provider_names


def _source_for_events(
    events: list[TraceEvent],
    task_by_corr: dict[str, Task],
    channel_names: dict[str, str],
    provider_names: dict[str, str],
) -> UsageAnomalySource:
    first = events[0] if events else None
    if not first:
        return UsageAnomalySource()
    d = first.data or {}
    corr = str(first.correlation_id) if first.correlation_id else None
    task = task_by_corr.get(corr or "")
    channel_id = str(task.channel_id) if task and task.channel_id else d.get("channel_id")
    source_type = _source_type_for_trace(first.correlation_id, task_by_corr)
    title = None
    if task:
        title = task.title or task.task_type
    return UsageAnomalySource(
        source_type=source_type,
        title=title,
        task_id=str(task.id) if task else None,
        task_type=task.task_type if task else None,
        bot_id=first.bot_id or (task.bot_id if task else None),
        channel_id=str(channel_id) if channel_id else None,
        channel_name=channel_names.get(str(channel_id)) if channel_id else None,
        model=d.get("model"),
        provider_id=d.get("provider_id"),
        provider_name=provider_names.get(d.get("provider_id")) if d.get("provider_id") else None,
    )


def _bucket_key(created_at: datetime, bucket_seconds: int) -> str:
    bucket_ts = datetime.fromtimestamp(
        (int(created_at.timestamp()) // bucket_seconds) * bucket_seconds,
        tz=timezone.utc,
    )
    return bucket_ts.isoformat()


def _representative_correlation_id(events: list[TraceEvent]) -> str | None:
    """Pick the highest-token trace inside a grouped signal."""
    by_trace: dict[str, list[TraceEvent]] = {}
    for ev in events:
        if ev.correlation_id:
            by_trace.setdefault(str(ev.correlation_id), []).append(ev)
    if not by_trace:
        return None

    def trace_tokens(trace_events: list[TraceEvent]) -> int:
        total = 0
        for ev in trace_events:
            d = ev.data or {}
            total += int(d.get("total_tokens") or ((d.get("prompt_tokens") or 0) + (d.get("completion_tokens") or 0)))
        return total

    trace_id, _trace_events = max(by_trace.items(), key=lambda item: trace_tokens(item[1]))
    return trace_id


def _token_count(ev: TraceEvent) -> int:
    d = ev.data or {}
    return int(d.get("total_tokens") or ((d.get("prompt_tokens") or 0) + (d.get("completion_tokens") or 0)))


def _trace_key(value: uuid.UUID | None, fallback: uuid.UUID) -> str:
    return str(value) if value else str(fallback)


def _tool_signature(call: ToolCall) -> str:
    args = call.arguments or {}
    try:
        normalized = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        normalized = str(args)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{call.tool_type}:{call.server_name or ''}:{call.tool_name}:{digest}"


async def _fetch_tool_calls(
    db: AsyncSession,
    *,
    after: datetime,
    before: datetime,
    bot_id: str | None = None,
) -> list[ToolCall]:
    q = select(ToolCall).where(
        ToolCall.created_at >= after,
        ToolCall.created_at <= before,
    )
    if bot_id:
        q = q.where(ToolCall.bot_id == bot_id)
    q = q.order_by(ToolCall.created_at.desc())
    return list((await db.execute(q)).scalars().all())


async def _fetch_error_events(
    db: AsyncSession,
    *,
    after: datetime,
    before: datetime,
    bot_id: str | None = None,
) -> list[TraceEvent]:
    q = select(TraceEvent).where(
        TraceEvent.event_type.in_(("error", "llm_error")),
        TraceEvent.created_at >= after,
        TraceEvent.created_at <= before,
    )
    if bot_id:
        q = q.where(TraceEvent.bot_id == bot_id)
    q = q.order_by(TraceEvent.created_at.desc())
    return list((await db.execute(q)).scalars().all())


async def _load_bot_map(db: AsyncSession, bot_ids: set[str]) -> dict[str, Bot]:
    if not bot_ids:
        return {}
    rows = (await db.execute(select(Bot).where(Bot.id.in_(bot_ids)))).scalars().all()
    return {row.id: row for row in rows}


async def _extend_task_map_for_tool_calls(
    db: AsyncSession,
    task_by_corr: dict[str, Task],
    tool_calls: list[ToolCall],
) -> None:
    missing = [
        call.correlation_id
        for call in tool_calls
        if call.correlation_id and str(call.correlation_id) not in task_by_corr
    ]
    if not missing:
        return
    rows = (await db.execute(select(Task).where(Task.correlation_id.in_(missing)))).scalars().all()
    for task in rows:
        if task.correlation_id:
            task_by_corr[str(task.correlation_id)] = task


def _smell_severity(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "smelly"
    if score >= 25:
        return "watch"
    return "clean"


def _reason_severity(points: int) -> str:
    if points >= 20:
        return "critical"
    if points >= 12:
        return "smelly"
    return "watch"


# ---------------------------------------------------------------------------
# Context bloat — working-set hygiene signal
# ---------------------------------------------------------------------------
#
# Underutilized tools and skills inflate every turn's prompt by 100-400 tokens
# of unused schema each. The bloat signal joins persistent enrollments
# (BotToolEnrollment / BotSkillEnrollment) against pinned lists (Bot.pinned_tools /
# Bot.skills) and the most recent tool_surface_summary trace event to score
# how much of a bot's working set is dead weight.

# Heuristic: an average tool schema is ~200 tokens. Tracks the actual measured
# value from tool_surface_summary when available; otherwise per-tool estimate.
_AVG_TOOL_SCHEMA_TOKENS = 200
_AVG_SKILL_OVERHEAD_TOKENS = 80
_BLOAT_GRACE_DAYS = 7  # don't flag tools enrolled in the last week as unused


class _BotBloatData(BaseModel):
    """Per-bot working-set hygiene snapshot."""
    enrolled_tools_count: int = 0
    unused_tools_count: int = 0
    pinned_unused_tools: list[str] = Field(default_factory=list)
    enrolled_skills_count: int = 0
    unused_skills_count: int = 0
    pinned_unused_skills: list[str] = Field(default_factory=list)
    tool_schema_tokens_estimate: int = 0
    estimated_bloat_tokens: int = 0


async def _fetch_agent_bloat_data(
    db: AsyncSession,
    *,
    bot_ids: set[str],
    after: datetime,
) -> dict[str, _BotBloatData]:
    """Build per-bot context-bloat snapshots.

    "Unused" is conservative: source='fetched', fetch_count == 0, and the
    enrollment is older than the grace window. Pinned items get reported
    separately so the bot/operator sees user intent that isn't paying off.
    """
    if not bot_ids:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=_BLOAT_GRACE_DAYS)

    tool_rows = (await db.execute(
        select(BotToolEnrollment).where(BotToolEnrollment.bot_id.in_(bot_ids))
    )).scalars().all()
    skill_rows = (await db.execute(
        select(BotSkillEnrollment).where(BotSkillEnrollment.bot_id.in_(bot_ids))
    )).scalars().all()
    bot_rows = (await db.execute(
        select(Bot.id, Bot.pinned_tools, Bot.skills).where(Bot.id.in_(bot_ids))
    )).all()
    pin_tools_by_bot: dict[str, list[str]] = {}
    pin_skills_by_bot: dict[str, list[str]] = {}
    for row in bot_rows:
        pin_tools_by_bot[row.id] = [t for t in (row.pinned_tools or []) if isinstance(t, str)]
        # Bot.skills is a list of {"id": ..., ...} dicts (legacy JSONB shape).
        # Extract the id; tolerate plain-string lists for forward-compat.
        pinned_skill_ids: list[str] = []
        for entry in (row.skills or []):
            if isinstance(entry, dict):
                sid = entry.get("id")
                if isinstance(sid, str) and sid:
                    pinned_skill_ids.append(sid)
            elif isinstance(entry, str) and entry:
                pinned_skill_ids.append(entry)
        pin_skills_by_bot[row.id] = pinned_skill_ids

    skill_ids_referenced: set[str] = set()
    for row in skill_rows:
        skill_ids_referenced.add(row.skill_id)
    for ids in pin_skills_by_bot.values():
        skill_ids_referenced.update(ids)
    skill_name_by_id: dict[str, str] = {}
    if skill_ids_referenced:
        skill_id_rows = (await db.execute(
            select(Skill.id, Skill.name).where(Skill.id.in_(skill_ids_referenced))
        )).all()
        skill_name_by_id = {row.id: row.name for row in skill_id_rows}

    # Most recent tool_surface_summary per bot (within window).
    surface_events = (await db.execute(
        select(TraceEvent)
        .where(
            TraceEvent.event_type == "tool_surface_summary",
            TraceEvent.bot_id.in_(bot_ids),
            TraceEvent.created_at >= after,
        )
        .order_by(TraceEvent.created_at.desc())
    )).scalars().all()
    schema_tokens_by_bot: dict[str, int] = {}
    for ev in surface_events:
        if ev.bot_id and ev.bot_id not in schema_tokens_by_bot:
            est = int((ev.data or {}).get("tool_schema_tokens_estimate") or 0)
            if est > 0:
                schema_tokens_by_bot[ev.bot_id] = est

    tools_by_bot: dict[str, list[BotToolEnrollment]] = {}
    for row in tool_rows:
        tools_by_bot.setdefault(row.bot_id, []).append(row)
    skills_by_bot: dict[str, list[BotSkillEnrollment]] = {}
    for row in skill_rows:
        skills_by_bot.setdefault(row.bot_id, []).append(row)

    out: dict[str, _BotBloatData] = {}
    for bot_id in bot_ids:
        tool_enrollments = tools_by_bot.get(bot_id, [])
        skill_enrollments = skills_by_bot.get(bot_id, [])
        pinned_tool_names = set(pin_tools_by_bot.get(bot_id, []))
        pinned_skill_ids = set(pin_skills_by_bot.get(bot_id, []))

        unused_tools = 0
        for row in tool_enrollments:
            if row.tool_name in pinned_tool_names:
                continue  # pinned-unused reported separately
            if (row.source or "").lower() != "fetched":
                continue
            if row.fetch_count and row.fetch_count > 0:
                continue
            enrolled_at = row.enrolled_at
            if enrolled_at and enrolled_at.tzinfo is None:
                enrolled_at = enrolled_at.replace(tzinfo=timezone.utc)
            if enrolled_at and enrolled_at > cutoff:
                continue  # within grace window
            unused_tools += 1

        # Pinned-but-never-used: pinned name with no enrollment row OR fetch_count == 0.
        tool_use_by_name = {row.tool_name: row for row in tool_enrollments}
        pinned_unused_tools: list[str] = []
        for name in pin_tools_by_bot.get(bot_id, []):
            row = tool_use_by_name.get(name)
            if row is None or not row.fetch_count:
                pinned_unused_tools.append(name)

        unused_skills = 0
        for row in skill_enrollments:
            if row.skill_id in pinned_skill_ids:
                continue
            if (row.source or "").lower() != "fetched":
                continue
            if (row.fetch_count or 0) > 0 or (row.auto_inject_count or 0) > 0:
                continue
            enrolled_at = row.enrolled_at
            if enrolled_at and enrolled_at.tzinfo is None:
                enrolled_at = enrolled_at.replace(tzinfo=timezone.utc)
            if enrolled_at and enrolled_at > cutoff:
                continue
            unused_skills += 1

        skill_use_by_id = {row.skill_id: row for row in skill_enrollments}
        pinned_unused_skills: list[str] = []
        for sid in pin_skills_by_bot.get(bot_id, []):
            row = skill_use_by_id.get(sid)
            used = bool(row and ((row.fetch_count or 0) > 0 or (row.auto_inject_count or 0) > 0))
            if not used:
                pinned_unused_skills.append(skill_name_by_id.get(sid, sid))

        bloat_tokens = (
            unused_tools * _AVG_TOOL_SCHEMA_TOKENS
            + len(pinned_unused_tools) * _AVG_TOOL_SCHEMA_TOKENS
            + unused_skills * _AVG_SKILL_OVERHEAD_TOKENS
        )

        out[bot_id] = _BotBloatData(
            enrolled_tools_count=len(tool_enrollments),
            unused_tools_count=unused_tools,
            pinned_unused_tools=pinned_unused_tools,
            enrolled_skills_count=len(skill_enrollments),
            unused_skills_count=unused_skills,
            pinned_unused_skills=pinned_unused_skills,
            tool_schema_tokens_estimate=schema_tokens_by_bot.get(bot_id, 0),
            estimated_bloat_tokens=bloat_tokens,
        )
    return out


def _bloat_severity_points(metrics: AgentSmellMetrics) -> tuple[int, str | None]:
    """Score context-bloat contribution; cap at 20.

    Treats unused enrollments and pinned-but-never-used items as the
    primary cost signal. Returns (points, detail).
    """
    unused = metrics.unused_tools_count
    pinned_unused = len(metrics.pinned_unused_tools)
    skill_bloat = metrics.unused_skills_count + len(metrics.pinned_unused_skills)
    if unused == 0 and pinned_unused == 0 and skill_bloat == 0:
        return 0, None

    points = 0
    points += min(12, unused * 2)
    points += min(6, pinned_unused * 1)
    points += min(6, skill_bloat * 1)
    if metrics.tool_schema_tokens_estimate >= 8000:
        points += 4
    elif metrics.tool_schema_tokens_estimate >= 5000:
        points += 2
    points = min(20, points)

    parts: list[str] = []
    if unused:
        parts.append(f"{unused} unused tool{'s' if unused != 1 else ''}")
    if pinned_unused:
        parts.append(f"{pinned_unused} pinned-but-unused")
    if metrics.unused_skills_count:
        parts.append(f"{metrics.unused_skills_count} unused skill{'s' if metrics.unused_skills_count != 1 else ''}")
    if metrics.pinned_unused_skills:
        parts.append(f"{len(metrics.pinned_unused_skills)} pinned-unused skill{'s' if len(metrics.pinned_unused_skills) != 1 else ''}")
    if metrics.tool_schema_tokens_estimate >= 5000:
        parts.append(f"~{metrics.tool_schema_tokens_estimate // 1000}k schema tokens/turn")
    return points, ", ".join(parts) or None


def _agent_smell_score(
    *,
    metrics: AgentSmellMetrics,
) -> tuple[int, list[AgentSmellReason]]:
    loop_points = min(
        40,
        metrics.repeated_tool_calls * 8
        + max(0, metrics.max_tool_calls_per_trace - 8) * 3
        + max(0, metrics.max_iterations - 4) * 5,
    )
    failure_points = min(
        25,
        metrics.tool_error_count * 8
        + (metrics.tool_denied_count + metrics.tool_expired_count) * 6
        + metrics.error_events * 10,
    )
    ratio_points = 0
    if metrics.token_ratio is not None:
        if metrics.token_ratio >= 5:
            ratio_points = 12
        elif metrics.token_ratio >= 2:
            ratio_points = 8
        elif metrics.token_ratio >= 1.5:
            ratio_points = 4
    volume_points = 0
    if metrics.total_tokens >= 100_000:
        volume_points = 8
    elif metrics.total_tokens >= 25_000:
        volume_points = 5
    elif metrics.total_tokens >= 10_000:
        volume_points = 2
    trace_points = 4 if metrics.max_trace_tokens >= 25_000 else 0
    token_points = min(20, ratio_points + volume_points + trace_points)
    slow_points = min(
        15,
        metrics.slow_trace_count * 5
        + (8 if metrics.max_trace_duration_ms >= 30 * 60 * 1000 else 4 if metrics.max_trace_duration_ms >= 10 * 60 * 1000 else 0),
    )

    reasons: list[AgentSmellReason] = []
    if loop_points:
        parts = []
        if metrics.repeated_tool_calls:
            parts.append(f"{metrics.repeated_tool_calls} repeated tool calls")
        if metrics.max_tool_calls_per_trace > 8:
            parts.append(f"{metrics.max_tool_calls_per_trace} tools in one trace")
        if metrics.max_iterations > 4:
            parts.append(f"{metrics.max_iterations} iterations")
        reasons.append(AgentSmellReason(
            key="loop_friction",
            label="Loop/friction",
            detail=", ".join(parts) or "Repeated execution pattern",
            severity=_reason_severity(loop_points),
            points=loop_points,
        ))
    if failure_points:
        parts = []
        if metrics.tool_error_count:
            parts.append(f"{metrics.tool_error_count} tool errors")
        if metrics.tool_denied_count:
            parts.append(f"{metrics.tool_denied_count} denied approvals")
        if metrics.tool_expired_count:
            parts.append(f"{metrics.tool_expired_count} expired approvals")
        if metrics.error_events:
            parts.append(f"{metrics.error_events} trace errors")
        reasons.append(AgentSmellReason(
            key="failures",
            label="Failures",
            detail=", ".join(parts) or "Execution failures",
            severity=_reason_severity(failure_points),
            points=failure_points,
        ))
    if token_points:
        if metrics.token_ratio is not None and metrics.token_ratio >= 1.5:
            detail = f"{metrics.token_ratio}x baseline, {metrics.total_tokens:,} tokens"
        else:
            detail = f"{metrics.total_tokens:,} tokens"
        reasons.append(AgentSmellReason(
            key="token_pressure",
            label="Token pressure",
            detail=detail,
            severity=_reason_severity(token_points),
            points=token_points,
        ))
    if slow_points:
        reasons.append(AgentSmellReason(
            key="long_running",
            label="Long-running traces",
            detail=f"{metrics.slow_trace_count} slow traces, max {round(metrics.max_trace_duration_ms / 1000)}s",
            severity=_reason_severity(slow_points),
            points=slow_points,
        ))

    bloat_points, bloat_detail = _bloat_severity_points(metrics)
    if bloat_points and bloat_detail:
        reasons.append(AgentSmellReason(
            key="context_bloat",
            label="Context bloat",
            detail=bloat_detail,
            severity=_reason_severity(bloat_points),
            points=bloat_points,
        ))

    score = min(100, int(loop_points + failure_points + token_points + slow_points + bloat_points))
    reasons.sort(key=lambda reason: reason.points, reverse=True)
    return score, reasons[:4]


def _build_agent_smell_rows(
    *,
    events: list[TraceEvent],
    baseline_events: list[TraceEvent],
    tool_calls: list[ToolCall],
    error_events: list[TraceEvent],
    bot_map: dict[str, Bot],
    bloat_by_bot: dict[str, _BotBloatData] | None,
    limit: int,
    window: timedelta,
    baseline: timedelta,
) -> list[AgentSmellBot]:
    bot_ids: set[str] = {
        row.bot_id
        for row in [*events, *tool_calls, *error_events]
        if row.bot_id
    }
    # Include any bot that has bloat data even if it had no trace activity
    # in the window — a bot with 18 stale enrollments but no recent calls
    # still ranks as smelly.
    if bloat_by_bot:
        bot_ids.update(b for b, data in bloat_by_bot.items() if data.unused_tools_count or data.pinned_unused_tools or data.unused_skills_count or data.pinned_unused_skills)
    events_by_bot: dict[str, list[TraceEvent]] = {bot_id: [] for bot_id in bot_ids}
    baseline_by_bot: dict[str, list[TraceEvent]] = {bot_id: [] for bot_id in bot_ids}
    tools_by_bot: dict[str, list[ToolCall]] = {bot_id: [] for bot_id in bot_ids}
    errors_by_bot: dict[str, list[TraceEvent]] = {bot_id: [] for bot_id in bot_ids}
    for ev in events:
        if ev.bot_id:
            events_by_bot.setdefault(ev.bot_id, []).append(ev)
    for ev in baseline_events:
        if ev.bot_id:
            baseline_by_bot.setdefault(ev.bot_id, []).append(ev)
    for call in tool_calls:
        if call.bot_id:
            tools_by_bot.setdefault(call.bot_id, []).append(call)
    for ev in error_events:
        if ev.bot_id:
            errors_by_bot.setdefault(ev.bot_id, []).append(ev)

    window_seconds = max(1, int(window.total_seconds()))
    baseline_seconds = max(1, int(baseline.total_seconds()))
    rows: list[AgentSmellBot] = []
    for bot_id in bot_ids:
        bot_events = events_by_bot.get(bot_id, [])
        bot_baseline = baseline_by_bot.get(bot_id, [])
        bot_tools = tools_by_bot.get(bot_id, [])
        bot_errors = errors_by_bot.get(bot_id, [])

        trace_tokens: Counter[str] = Counter()
        trace_times: dict[str, list[datetime]] = {}
        trace_iterations: Counter[str] = Counter()
        for ev in bot_events:
            key = _trace_key(ev.correlation_id, ev.id)
            trace_tokens[key] += _token_count(ev)
            trace_times.setdefault(key, []).append(ev.created_at)
            iteration = int((ev.data or {}).get("iteration") or 0)
            trace_iterations[key] = max(trace_iterations[key], iteration)
        trace_tools: dict[str, list[ToolCall]] = {}
        for call in bot_tools:
            key = _trace_key(call.correlation_id, call.id)
            trace_tools.setdefault(key, []).append(call)
            trace_times.setdefault(key, []).append(call.created_at)
            if call.completed_at:
                trace_times.setdefault(key, []).append(call.completed_at)
            if call.iteration is not None:
                trace_iterations[key] = max(trace_iterations[key], int(call.iteration or 0))
        trace_errors: Counter[str] = Counter()
        for ev in bot_errors:
            key = _trace_key(ev.correlation_id, ev.id)
            trace_errors[key] += 1
            trace_times.setdefault(key, []).append(ev.created_at)

        repeated_tool_calls = 0
        max_repeated = 0
        trace_repeats: Counter[str] = Counter()
        for trace_id, calls in trace_tools.items():
            signatures = Counter(_tool_signature(call) for call in calls)
            for count in signatures.values():
                if count > 1:
                    repeated_tool_calls += count - 1
                    trace_repeats[trace_id] += count - 1
                    max_repeated = max(max_repeated, count)

        durations: dict[str, int] = {}
        for trace_id, times in trace_times.items():
            if len(times) < 2:
                durations[trace_id] = 0
                continue
            durations[trace_id] = int((max(times) - min(times)).total_seconds() * 1000)

        total_tokens = sum(_token_count(ev) for ev in bot_events)
        baseline_tokens_raw = sum(_token_count(ev) for ev in bot_baseline)
        baseline_tokens = int(baseline_tokens_raw * (window_seconds / baseline_seconds))
        token_ratio = round(total_tokens / baseline_tokens, 2) if baseline_tokens > 0 else None
        max_trace_tokens = max(trace_tokens.values(), default=0)
        tool_statuses = Counter((call.status or "").lower() for call in bot_tools)
        tool_errors = sum(1 for call in bot_tools if (call.status or "").lower() == "error" or call.error)
        max_duration = max(durations.values(), default=0)
        bloat = (bloat_by_bot or {}).get(bot_id) or _BotBloatData()
        metrics = AgentSmellMetrics(
            traces=len(set(trace_times.keys()) | set(trace_tokens.keys())),
            calls=len(bot_events),
            total_tokens=total_tokens,
            baseline_tokens=baseline_tokens,
            token_ratio=token_ratio,
            max_trace_tokens=max_trace_tokens,
            tool_calls=len(bot_tools),
            repeated_tool_calls=repeated_tool_calls,
            max_repeated_tool_signature=max_repeated,
            max_tool_calls_per_trace=max((len(calls) for calls in trace_tools.values()), default=0),
            max_iterations=max(trace_iterations.values(), default=0),
            tool_error_count=tool_errors,
            tool_denied_count=tool_statuses.get("denied", 0),
            tool_expired_count=tool_statuses.get("expired", 0),
            error_events=len(bot_errors),
            slow_trace_count=sum(1 for ms in durations.values() if ms >= 10 * 60 * 1000),
            max_trace_duration_ms=max_duration,
            enrolled_tools_count=bloat.enrolled_tools_count,
            unused_tools_count=bloat.unused_tools_count,
            pinned_unused_tools=bloat.pinned_unused_tools,
            enrolled_skills_count=bloat.enrolled_skills_count,
            unused_skills_count=bloat.unused_skills_count,
            pinned_unused_skills=bloat.pinned_unused_skills,
            tool_schema_tokens_estimate=bloat.tool_schema_tokens_estimate,
            estimated_bloat_tokens=bloat.estimated_bloat_tokens,
        )
        score, reasons = _agent_smell_score(metrics=metrics)

        trace_rows: list[AgentSmellTraceEvidence] = []
        for trace_id in set(trace_times.keys()) | set(trace_tokens.keys()):
            if not trace_id:
                continue
            trace_tool_calls = trace_tools.get(trace_id, [])
            evidence_score = (
                trace_repeats.get(trace_id, 0) * 8
                + trace_errors.get(trace_id, 0) * 10
                + min(20, math.ceil(trace_tokens.get(trace_id, 0) / 5000))
                + (5 if durations.get(trace_id, 0) >= 10 * 60 * 1000 else 0)
            )
            if evidence_score <= 0:
                continue
            reason_parts = []
            if trace_repeats.get(trace_id, 0):
                reason_parts.append(f"{trace_repeats[trace_id]} repeats")
            if trace_errors.get(trace_id, 0):
                reason_parts.append(f"{trace_errors[trace_id]} errors")
            if trace_tokens.get(trace_id, 0) >= 10_000:
                reason_parts.append(f"{trace_tokens[trace_id]:,} tokens")
            if durations.get(trace_id, 0) >= 10 * 60 * 1000:
                reason_parts.append("long-running")
            created = min(trace_times.get(trace_id, []), default=None)
            trace_rows.append(AgentSmellTraceEvidence(
                correlation_id=trace_id if trace_id in {str(ev.correlation_id) for ev in bot_events if ev.correlation_id} else None,
                created_at=created.isoformat() if created else None,
                reason=", ".join(reason_parts) or "Smell evidence",
                tokens=trace_tokens.get(trace_id, 0),
                tool_calls=len(trace_tool_calls),
                repeated_tool_calls=trace_repeats.get(trace_id, 0),
                errors=trace_errors.get(trace_id, 0) + sum(1 for call in trace_tool_calls if (call.status or "").lower() == "error" or call.error),
                duration_ms=durations.get(trace_id, 0),
            ))
        trace_rows.sort(
            key=lambda trace: (
                trace.repeated_tool_calls * 8
                + trace.errors * 10
                + min(20, math.ceil(trace.tokens / 5000))
                + (5 if trace.duration_ms >= 10 * 60 * 1000 else 0)
            ),
            reverse=True,
        )

        bot = bot_map.get(bot_id)
        rows.append(AgentSmellBot(
            bot_id=bot_id,
            name=bot.name if bot else bot_id,
            display_name=bot.display_name if bot else None,
            model=bot.model if bot else None,
            avatar_url=bot.avatar_url if bot else None,
            avatar_emoji=bot.avatar_emoji if bot else None,
            score=score,
            severity=_smell_severity(score),
            reasons=reasons,
            metrics=metrics,
            traces=trace_rows[:3],
        ))
    rows.sort(key=lambda row: (row.score, row.metrics.total_tokens, row.metrics.tool_calls), reverse=True)
    ranked = rows[:limit]
    for idx, row in enumerate(ranked, start=1):
        row.rank = idx
    return ranked


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def build_usage_anomalies(
    after: Optional[str] = "24h",
    before: Optional[str] = None,
    bot_id: Optional[str] = None,
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    source_type: Optional[str] = None,
    db: AsyncSession = None,
):
    """Compute high-signal usage anomalies for the selected window.

    The endpoint is intentionally read-only and stateless: anomalies are
    recalculated from token_usage trace events for the current window and the
    immediately previous matching baseline window.
    """
    now = datetime.now(timezone.utc)
    after_dt = _parse_time(after) if after else now - timedelta(hours=24)
    before_dt = _parse_time(before) if before else now
    if after_dt is None:
        after_dt = now - timedelta(hours=24)
    if before_dt is None:
        before_dt = now
    if after_dt >= before_dt:
        after_dt = before_dt - timedelta(hours=24)

    span = before_dt - after_dt
    baseline_start = after_dt - span
    baseline_end = after_dt

    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

    events, _ = await _fetch_token_usage_events(
        db,
        after=after_dt,
        before=before_dt,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
    )
    baseline_events, _ = await _fetch_token_usage_events(
        db,
        after=baseline_start,
        before=baseline_end,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
    )

    task_by_corr, channel_names, provider_names = await _usage_source_maps(db, events + baseline_events)

    if source_type:
        events = [
            ev for ev in events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]
        baseline_events = [
            ev for ev in baseline_events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]

    span_seconds = max(1, int(span.total_seconds()))
    if span_seconds <= 36 * 3600:
        bucket_seconds = 3600
        bucket_size = "1h"
    elif span_seconds <= 7 * 86400:
        bucket_seconds = 6 * 3600
        bucket_size = "6h"
    else:
        bucket_seconds = 86400
        bucket_size = "1d"

    current_buckets: dict[str, list[TraceEvent]] = {}
    for ev in events:
        current_buckets.setdefault(_bucket_key(ev.created_at, bucket_seconds), []).append(ev)
    baseline_buckets: dict[str, list[TraceEvent]] = {}
    for ev in baseline_events:
        baseline_buckets.setdefault(_bucket_key(ev.created_at + span, bucket_seconds), []).append(ev)

    time_spikes: list[UsageAnomalySignal] = []
    for bucket, bucket_events in current_buckets.items():
        metric = _metric_from_events(bucket_events, pricing, ptype_map)
        baseline_metric = _metric_from_events(baseline_buckets.get(bucket, []), pricing, ptype_map)
        ratio = _metric_ratio(metric, baseline_metric)
        if metric.tokens < 5_000 and (ratio is None or ratio < 2):
            continue
        if ratio is not None and ratio < 1.5 and metric.tokens < 25_000:
            continue
        time_spikes.append(UsageAnomalySignal(
            id=f"time:{bucket}",
            kind="time_spike",
            label=f"Spike around {bucket}",
            severity=_severity(metric, ratio),
            reason=f"{ratio}x previous window" if ratio is not None else "High token bucket",
            created_at=bucket,
            bucket=bucket,
            correlation_id=_representative_correlation_id(bucket_events),
            metric=metric,
            baseline=baseline_metric,
            ratio=ratio,
            cost_confidence=_cost_confidence_for_events(bucket_events, pricing, ptype_map),
            source=_source_for_events(bucket_events, task_by_corr, channel_names, provider_names),
        ))
    time_spikes.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    by_trace: dict[str, list[TraceEvent]] = {}
    for ev in events:
        key = str(ev.correlation_id) if ev.correlation_id else str(ev.id)
        by_trace.setdefault(key, []).append(ev)
    trace_baseline_tokens = _metric_from_events(baseline_events, pricing, ptype_map).tokens
    average_baseline_trace = max(1, trace_baseline_tokens // max(1, len({str(ev.correlation_id) for ev in baseline_events if ev.correlation_id})))

    trace_bursts: list[UsageAnomalySignal] = []
    for trace_id, trace_events in by_trace.items():
        metric = _metric_from_events(trace_events, pricing, ptype_map)
        iterations = max(int((ev.data or {}).get("iteration") or 0) for ev in trace_events)
        ratio = round(metric.tokens / average_baseline_trace, 2) if average_baseline_trace > 0 else None
        if metric.tokens < 10_000 and iterations < 4 and (ratio is None or ratio < 2):
            continue
        first = min(trace_events, key=lambda ev: ev.created_at)
        reason_parts = []
        if metric.tokens >= 10_000:
            reason_parts.append("large token trace")
        if iterations >= 4:
            reason_parts.append(f"{iterations} iterations")
        if ratio is not None and ratio >= 2:
            reason_parts.append(f"{ratio}x baseline trace")
        trace_bursts.append(UsageAnomalySignal(
            id=f"trace:{trace_id}",
            kind="trace_burst",
            label=_source_for_events(trace_events, task_by_corr, channel_names, provider_names).title or "High-usage trace",
            severity=_severity(metric, ratio),
            reason=", ".join(reason_parts) or "High trace usage",
            created_at=first.created_at.isoformat() if first.created_at else None,
            correlation_id=trace_id if trace_events[0].correlation_id else None,
            metric=metric,
            ratio=ratio,
            cost_confidence=_cost_confidence_for_events(trace_events, pricing, ptype_map),
            source=_source_for_events(trace_events, task_by_corr, channel_names, provider_names),
        ))
    trace_bursts.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    def _contributors(dimension: str) -> list[UsageAnomalySignal]:
        current: dict[str, list[TraceEvent]] = {}
        previous: dict[str, list[TraceEvent]] = {}
        for ev in events:
            d = ev.data or {}
            if dimension == "bot":
                key = ev.bot_id or "unknown"
            elif dimension == "channel":
                key = d.get("channel_id") or "unknown"
            elif dimension == "provider":
                key = d.get("provider_id") or "default"
            else:
                key = d.get("model") or "unknown"
            current.setdefault(str(key), []).append(ev)
        for ev in baseline_events:
            d = ev.data or {}
            if dimension == "bot":
                key = ev.bot_id or "unknown"
            elif dimension == "channel":
                key = d.get("channel_id") or "unknown"
            elif dimension == "provider":
                key = d.get("provider_id") or "default"
            else:
                key = d.get("model") or "unknown"
            previous.setdefault(str(key), []).append(ev)
        signals: list[UsageAnomalySignal] = []
        for key, group_events in current.items():
            metric = _metric_from_events(group_events, pricing, ptype_map)
            baseline_metric = _metric_from_events(previous.get(key, []), pricing, ptype_map)
            ratio = _metric_ratio(metric, baseline_metric)
            if metric.tokens < 10_000 and (ratio is None or ratio < 2):
                continue
            label = channel_names.get(key, key) if dimension == "channel" else key
            signals.append(UsageAnomalySignal(
                id=f"{dimension}:{key}",
                kind="contributor",
                label=label,
                severity=_severity(metric, ratio),
                reason=f"{ratio}x previous window" if ratio is not None else f"Top {dimension} by tokens",
                dimension=dimension,
                dimension_value=key,
                metric=metric,
                baseline=baseline_metric,
                ratio=ratio,
                cost_confidence=_cost_confidence_for_events(group_events, pricing, ptype_map),
                source=_source_for_events(group_events, task_by_corr, channel_names, provider_names),
            ))
        return signals

    contributors = (
        _contributors("bot") +
        _contributors("channel") +
        _contributors("model") +
        _contributors("provider")
    )
    contributors.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    return UsageAnomaliesOut(
        window_start=after_dt.isoformat(),
        window_end=before_dt.isoformat(),
        baseline_start=baseline_start.isoformat(),
        baseline_end=baseline_end.isoformat(),
        bucket_size=bucket_size,
        time_spikes=time_spikes[:8],
        trace_bursts=trace_bursts[:10],
        contributors=contributors[:12],
    )


async def build_agent_smell(
    hours: int = 24,
    baseline_days: int = 7,
    bot_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = None,
):
    """Rank bots by suspicious trace/tool behavior in a live time window."""
    now = datetime.now(timezone.utc)
    window = timedelta(hours=hours)
    baseline = timedelta(days=baseline_days)
    after_dt = now - window
    baseline_start = after_dt - baseline
    baseline_end = after_dt

    events, _ = await _fetch_token_usage_events(
        db,
        after=after_dt,
        before=now,
        bot_id=bot_id,
    )
    baseline_events, _ = await _fetch_token_usage_events(
        db,
        after=baseline_start,
        before=baseline_end,
        bot_id=bot_id,
    )
    tool_calls = await _fetch_tool_calls(
        db,
        after=after_dt,
        before=now,
        bot_id=bot_id,
    )
    error_events = await _fetch_error_events(
        db,
        after=after_dt,
        before=now,
        bot_id=bot_id,
    )

    task_by_corr, _channel_names, _provider_names = await _usage_source_maps(
        db,
        events + baseline_events + error_events,
    )
    await _extend_task_map_for_tool_calls(db, task_by_corr, tool_calls)

    if source_type:
        events = [
            ev for ev in events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]
        baseline_events = [
            ev for ev in baseline_events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]
        error_events = [
            ev for ev in error_events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]
        tool_calls = [
            call for call in tool_calls
            if _source_type_for_trace(call.correlation_id, task_by_corr) == source_type
        ]

    bot_ids = {
        row.bot_id
        for row in [*events, *baseline_events, *tool_calls, *error_events]
        if row.bot_id
    }
    # Pull every bot that has any enrollment row so bloat-only offenders
    # (no recent trace activity, but a stale 18-tool working set) still rank.
    bloat_bot_rows = (await db.execute(
        select(BotToolEnrollment.bot_id).distinct().union(
            select(BotSkillEnrollment.bot_id).distinct()
        )
    )).all()
    for row in bloat_bot_rows:
        if row[0]:
            bot_ids.add(row[0])

    bot_map = await _load_bot_map(db, bot_ids)
    bloat_by_bot = await _fetch_agent_bloat_data(db, bot_ids=bot_ids, after=after_dt)

    rows = _build_agent_smell_rows(
        events=events,
        baseline_events=baseline_events,
        tool_calls=tool_calls,
        error_events=error_events,
        bot_map=bot_map,
        bloat_by_bot=bloat_by_bot,
        limit=limit,
        window=window,
        baseline=baseline,
    )

    bloated_bots = [r for r in rows if any(reason.key == "context_bloat" for reason in r.reasons)]
    severity_rank = {"clean": 0, "watch": 1, "smelly": 2, "critical": 3}
    max_sev = "clean"
    for row in bloated_bots:
        if severity_rank.get(row.severity, 0) > severity_rank.get(max_sev, 0):
            max_sev = row.severity
    summary = AgentSmellSummary(
        bloated_bot_count=len(bloated_bots),
        total_unused_tools=sum(b.metrics.unused_tools_count for b in rows),
        total_pinned_unused_tools=sum(len(b.metrics.pinned_unused_tools) for b in rows),
        total_unused_skills=sum(b.metrics.unused_skills_count for b in rows),
        total_estimated_bloat_tokens=sum(b.metrics.estimated_bloat_tokens for b in rows),
        max_severity=max_sev,
    )

    return AgentSmellOut(
        window_start=after_dt.isoformat(),
        window_end=now.isoformat(),
        baseline_start=baseline_start.isoformat(),
        baseline_end=baseline_end.isoformat(),
        source_type=source_type,
        bots=rows,
        summary=summary,
    )
