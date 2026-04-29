"""Usage forecast read model."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Bot, ChannelHeartbeat, HeartbeatRun, Task, TraceEvent
from app.services.usage_costs import (
    _compute_cost_for_events,
    _fetch_token_usage_events,
    _get_provider_type_map,
    _is_plan_billed,
    _load_pricing_map,
    _resolve_event_cost,
)
from app.schemas.usage import ForecastComponent, LimitForecast, UsageForecastOut

_RECURRENCE_RE = re.compile(r"^\+(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_MAINTENANCE_TASK_TYPES = ("memory_hygiene", "skill_review")


@dataclass(frozen=True)
class _ForecastWindow:
    now_utc: datetime
    today_start: datetime
    month_start: datetime
    seven_days_ago: datetime
    hours_elapsed: float
    days_elapsed: float


@dataclass
class _ForecastCostContext:
    pricing: dict
    ptype_map: dict[str | None, str]
    model_avg_cost: dict[str, float] | None = None

    async def model_average_costs(self, db: AsyncSession, *, after: datetime) -> dict[str, float]:
        if self.model_avg_cost is None:
            recent_events, _ = await _fetch_token_usage_events(db, after=after)
            self.model_avg_cost = _compute_model_average_costs(
                recent_events,
                self.pricing,
                self.ptype_map,
            )
        return self.model_avg_cost


def _recurrence_runs_per_day(recurrence: str) -> float:
    """Parse a recurrence string like '+30m' and return runs per day."""
    m = _RECURRENCE_RE.match(recurrence.strip())
    if not m:
        return 0.0
    n, unit = int(m.group(1)), m.group(2)
    interval_secs = n * _UNIT_SECONDS[unit]
    if interval_secs <= 0:
        return 0.0
    return 86400 / interval_secs


def _build_forecast_window(now_utc: datetime | None = None) -> _ForecastWindow:
    """Resolve forecast time windows in the configured local timezone."""
    now_utc = now_utc or datetime.now(timezone.utc)
    local_tz = ZoneInfo(settings.TIMEZONE)
    now_local = now_utc.astimezone(local_tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return _ForecastWindow(
        now_utc=now_utc,
        today_start=today_start,
        month_start=month_start,
        seven_days_ago=now_utc - timedelta(days=7),
        hours_elapsed=(now_utc - today_start).total_seconds() / 3600,
        days_elapsed=(now_utc - month_start).total_seconds() / 86400,
    )


async def _compute_actual_spend(
    db: AsyncSession,
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> tuple[float, float]:
    today_events, _ = await _fetch_token_usage_events(db, after=window.today_start)
    daily_spend = _compute_cost_for_events(today_events, cost_ctx.pricing, cost_ctx.ptype_map)

    month_events, _ = await _fetch_token_usage_events(db, after=window.month_start)
    monthly_spend = _compute_cost_for_events(month_events, cost_ctx.pricing, cost_ctx.ptype_map)
    return daily_spend, monthly_spend


def _compute_model_average_costs(
    events: list[TraceEvent],
    pricing: dict,
    ptype_map: dict[str | None, str],
) -> dict[str, float]:
    model_cost_sum: dict[str, float] = defaultdict(float)
    model_call_count: dict[str, int] = defaultdict(int)
    for ev in events:
        data = ev.data or {}
        model = data.get("model")
        if not model:
            continue
        cost = _resolve_event_cost(data, pricing, ptype_map)
        if cost is not None:
            model_cost_sum[model] += cost
            model_call_count[model] += 1
    return {
        model: model_cost_sum[model] / model_call_count[model]
        for model in model_cost_sum
        if model_call_count[model] > 0
    }


def _sum_costs_by_correlation(
    events: list[TraceEvent],
    cost_ctx: _ForecastCostContext,
) -> dict[str, float]:
    costs: dict[str, float] = defaultdict(float)
    for ev in events:
        correlation_id = str(ev.correlation_id) if ev.correlation_id else None
        if not correlation_id:
            continue
        cost = _resolve_event_cost(ev.data or {}, cost_ctx.pricing, cost_ctx.ptype_map)
        if cost is not None:
            costs[correlation_id] += cost
    return costs


async def _build_heartbeat_component(
    db: AsyncSession,
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> ForecastComponent | None:
    heartbeats = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.enabled == True)  # noqa: E712
    )).scalars().all()
    if not heartbeats:
        return None

    heartbeat_ids = [heartbeat.id for heartbeat in heartbeats]
    recent_runs = (await db.execute(
        select(HeartbeatRun).where(
            HeartbeatRun.heartbeat_id.in_(heartbeat_ids),
            HeartbeatRun.run_at >= window.seven_days_ago,
            HeartbeatRun.correlation_id.isnot(None),
        )
    )).scalars().all()
    correlation_ids = [run.correlation_id for run in recent_runs if run.correlation_id]

    cost_total = 0.0
    run_count = 0
    if correlation_ids:
        events = (await db.execute(
            select(TraceEvent).where(
                TraceEvent.event_type == "token_usage",
                TraceEvent.correlation_id.in_(correlation_ids),
            )
        )).scalars().all()
        cost_total = _compute_cost_for_events(events, cost_ctx.pricing, cost_ctx.ptype_map)
        run_count = len(correlation_ids)

    avg_cost_per_run = cost_total / run_count if run_count > 0 else 0.0
    daily_runs = _heartbeat_runs_per_day(heartbeats)
    daily_cost = daily_runs * avg_cost_per_run
    return ForecastComponent(
        source="heartbeats",
        label="Scheduled heartbeats",
        daily_cost=round(daily_cost, 4),
        monthly_cost=round(daily_cost * 30, 4),
        count=len(heartbeats),
        avg_cost_per_run=round(avg_cost_per_run, 6) if avg_cost_per_run > 0 else None,
    )


def _heartbeat_runs_per_day(heartbeats: list[ChannelHeartbeat]) -> float:
    from app.services.heartbeat import _resolve_quiet_range

    total_runs_per_day = 0.0
    for heartbeat in heartbeats:
        interval = heartbeat.interval_minutes or 60
        quiet = _resolve_quiet_range(heartbeat)
        if quiet:
            quiet_start, quiet_end = quiet
            quiet_mins = (
                quiet_end.hour * 60 + quiet_end.minute
            ) - (
                quiet_start.hour * 60 + quiet_start.minute
            )
            if quiet_mins < 0:
                quiet_mins += 24 * 60
        else:
            quiet_mins = 0
        active_mins = max(24 * 60 - quiet_mins, 0)
        total_runs_per_day += active_mins / interval if interval > 0 else 0
    return total_runs_per_day


async def _build_recurring_task_component(
    db: AsyncSession,
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> ForecastComponent | None:
    recurring_tasks = (await db.execute(
        select(Task).where(
            Task.status == "active",
            Task.recurrence.isnot(None),
        )
    )).scalars().all()
    if not recurring_tasks:
        return None

    template_run_costs = await _recent_recurring_task_costs(
        db,
        recurring_tasks,
        window,
        cost_ctx,
    )
    templates_with_data = set(template_run_costs.keys())

    from app.agent.bots import _registry as bot_registry

    daily_cost = 0.0
    for task in recurring_tasks:
        runs_per_day = _recurrence_runs_per_day(task.recurrence or "")
        if runs_per_day <= 0:
            continue

        task_id = str(task.id)
        if task_id in templates_with_data:
            costs = template_run_costs[task_id]
            avg_cost = sum(costs) / len(costs) if costs else 0.0
        else:
            bot = bot_registry.get(task.bot_id)
            model = bot.model if bot else None
            if model and _is_plan_billed(None, model):
                continue
            model_avg_cost = await cost_ctx.model_average_costs(db, after=window.seven_days_ago)
            avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

        daily_cost += runs_per_day * avg_cost

    return ForecastComponent(
        source="recurring_tasks",
        label="Recurring tasks",
        daily_cost=round(daily_cost, 4),
        monthly_cost=round(daily_cost * 30, 4),
        count=len(recurring_tasks),
    )


async def _recent_recurring_task_costs(
    db: AsyncSession,
    recurring_tasks: list[Task],
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> dict[str, list[float]]:
    template_ids = [task.id for task in recurring_tasks]
    recent_runs = (await db.execute(
        select(Task).where(
            Task.parent_task_id.in_(template_ids),
            Task.correlation_id.isnot(None),
            Task.completed_at >= window.seven_days_ago,
        )
    )).scalars().all()

    correlation_to_parent: dict[str, str] = {}
    correlation_ids = []
    for run in recent_runs:
        if run.correlation_id and run.parent_task_id:
            correlation_id = str(run.correlation_id)
            correlation_to_parent[correlation_id] = str(run.parent_task_id)
            correlation_ids.append(run.correlation_id)

    template_run_costs: dict[str, list[float]] = defaultdict(list)
    if not correlation_ids:
        return template_run_costs

    events = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.correlation_id.in_(correlation_ids),
        )
    )).scalars().all()

    for correlation_id, run_cost in _sum_costs_by_correlation(events, cost_ctx).items():
        parent_id = correlation_to_parent.get(correlation_id)
        if parent_id:
            template_run_costs[parent_id].append(run_cost)
    return template_run_costs


async def _build_maintenance_component(
    db: AsyncSession,
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> ForecastComponent | None:
    from app.services.memory_hygiene import resolve_config as resolve_hygiene_config

    maint_bots = (await db.execute(
        select(Bot).where(Bot.memory_scheme == "workspace-files")
    )).scalars().all()
    if not maint_bots:
        return None

    recent_maint = (await db.execute(
        select(Task).where(
            Task.task_type.in_(_MAINTENANCE_TASK_TYPES),
            Task.status.in_(("completed", "skipped")),
            Task.completed_at >= window.seven_days_ago,
        )
    )).scalars().all()
    type_run_costs = await _recent_maintenance_costs(db, recent_maint, cost_ctx)
    type_skip_rate = _maintenance_execution_rates(recent_maint)

    from app.agent.bots import _registry as bot_registry

    daily_cost = 0.0
    maint_count = 0
    for bot in maint_bots:
        for job_type in _MAINTENANCE_TASK_TYPES:
            cfg = resolve_hygiene_config(bot, job_type)
            if not cfg.enabled or cfg.interval_hours <= 0:
                continue

            maint_count += 1
            runs_per_day = 24.0 / cfg.interval_hours
            runs_per_day *= type_skip_rate.get(job_type, 0.5)

            costs = type_run_costs.get(job_type, [])
            if costs:
                avg_cost = sum(costs) / len(costs)
            else:
                model = cfg.model
                if not model:
                    registry_bot = bot_registry.get(bot.id)
                    model = registry_bot.model if registry_bot else None
                if model and _is_plan_billed(None, model):
                    continue
                model_avg_cost = await cost_ctx.model_average_costs(db, after=window.seven_days_ago)
                avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

            daily_cost += runs_per_day * avg_cost

    if maint_count <= 0:
        return None
    return ForecastComponent(
        source="maintenance_tasks",
        label="Maintenance tasks",
        daily_cost=round(daily_cost, 4),
        monthly_cost=round(daily_cost * 30, 4),
        count=maint_count,
    )


async def _recent_maintenance_costs(
    db: AsyncSession,
    recent_maint: list[Task],
    cost_ctx: _ForecastCostContext,
) -> dict[str, list[float]]:
    completed_corr_ids = [
        task.correlation_id
        for task in recent_maint
        if task.status == "completed" and task.correlation_id
    ]
    type_run_costs: dict[str, list[float]] = {task_type: [] for task_type in _MAINTENANCE_TASK_TYPES}
    if not completed_corr_ids:
        return type_run_costs

    events = (await db.execute(
        select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.correlation_id.in_(completed_corr_ids),
        )
    )).scalars().all()
    correlation_to_type = {
        str(task.correlation_id): task.task_type
        for task in recent_maint
        if task.status == "completed" and task.correlation_id
    }
    for correlation_id, run_cost in _sum_costs_by_correlation(events, cost_ctx).items():
        task_type = correlation_to_type.get(correlation_id)
        if task_type and task_type in type_run_costs:
            type_run_costs[task_type].append(run_cost)
    return type_run_costs


def _maintenance_execution_rates(recent_maint: list[Task]) -> dict[str, float]:
    type_skip_rate: dict[str, float] = {}
    for task_type in _MAINTENANCE_TASK_TYPES:
        completed = sum(
            1
            for task in recent_maint
            if task.task_type == task_type and task.status == "completed"
        )
        skipped = sum(
            1
            for task in recent_maint
            if task.task_type == task_type and task.status == "skipped"
        )
        total = completed + skipped
        type_skip_rate[task_type] = completed / total if total > 0 else 0.5
    return type_skip_rate


def _build_fixed_plan_component() -> ForecastComponent | None:
    from app.services.providers import _registry as provider_registry

    plan_daily = 0.0
    plan_count = 0
    for provider in provider_registry.values():
        if provider.billing_type == "plan" and provider.plan_cost:
            if provider.plan_period == "weekly":
                plan_daily += provider.plan_cost / 7
            else:
                plan_daily += provider.plan_cost / 30
            plan_count += 1
    if plan_count <= 0:
        return None
    return ForecastComponent(
        source="fixed_plans",
        label="Fixed plans",
        daily_cost=round(plan_daily, 4),
        monthly_cost=round(plan_daily * 30, 4),
        count=plan_count,
    )


def _build_trajectory_component(
    *,
    daily_spend: float,
    monthly_spend: float,
    window: _ForecastWindow,
) -> ForecastComponent | None:
    if window.hours_elapsed < 1.0:
        return None
    trajectory_daily = daily_spend / window.hours_elapsed * 24
    trajectory_monthly = (
        monthly_spend / window.days_elapsed * 30
        if window.days_elapsed >= 1.0
        else trajectory_daily * 30
    )
    return ForecastComponent(
        source="trajectory",
        label="Current pace",
        daily_cost=round(trajectory_daily, 4),
        monthly_cost=round(trajectory_monthly, 4),
    )


def _compute_projected_totals(components: list[ForecastComponent]) -> tuple[float, float]:
    fixed_plan_daily = next((c.daily_cost for c in components if c.source == "fixed_plans"), 0.0)
    fixed_plan_monthly = next((c.monthly_cost for c in components if c.source == "fixed_plans"), 0.0)
    variable_scheduled_daily = sum(
        c.daily_cost for c in components if c.source not in ("trajectory", "fixed_plans")
    )
    variable_scheduled_monthly = sum(
        c.monthly_cost for c in components if c.source not in ("trajectory", "fixed_plans")
    )
    trajectory_daily = next((c.daily_cost for c in components if c.source == "trajectory"), 0.0)
    trajectory_monthly = next((c.monthly_cost for c in components if c.source == "trajectory"), 0.0)
    return (
        max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily,
        max(trajectory_monthly, variable_scheduled_monthly) + fixed_plan_monthly,
    )


async def _build_limit_forecasts(
    db: AsyncSession,
    window: _ForecastWindow,
    cost_ctx: _ForecastCostContext,
) -> list[LimitForecast]:
    from app.services.usage_limits import _limits, _period_start

    limit_forecasts: list[LimitForecast] = []
    for limit in _limits:
        since = _period_start(limit.period)
        base_query = select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= since,
        )
        if limit.scope_type == "bot":
            base_query = base_query.where(TraceEvent.bot_id == limit.scope_value)
        elif limit.scope_type == "model":
            base_query = base_query.where(TraceEvent.data["model"].astext == limit.scope_value)

        events = (await db.execute(base_query)).scalars().all()
        current = _compute_cost_for_events(events, cost_ctx.pricing, cost_ctx.ptype_map)
        percentage = (current / limit.limit_usd * 100) if limit.limit_usd > 0 else 0

        if limit.period == "daily":
            projected = current / window.hours_elapsed * 24 if window.hours_elapsed >= 1.0 else current
        else:
            projected = current / window.days_elapsed * 30 if window.days_elapsed >= 1.0 else current

        projected_percentage = (projected / limit.limit_usd * 100) if limit.limit_usd > 0 else 0
        limit_forecasts.append(LimitForecast(
            scope_type=limit.scope_type,
            scope_value=limit.scope_value,
            period=limit.period,
            limit_usd=limit.limit_usd,
            current_spend=round(current, 4),
            percentage=round(percentage, 1),
            projected_spend=round(projected, 4),
            projected_percentage=round(projected_percentage, 1),
        ))
    return limit_forecasts


async def build_usage_forecast(db: AsyncSession = None):
    """Cost forecast: projected daily/monthly spend from scheduled and observed usage."""
    window = _build_forecast_window()
    pricing = await _load_pricing_map(db)
    cost_ctx = _ForecastCostContext(pricing=pricing, ptype_map=_get_provider_type_map())
    daily_spend, monthly_spend = await _compute_actual_spend(db, window, cost_ctx)

    components: list[ForecastComponent] = []
    for build_component in (
        _build_heartbeat_component,
        _build_recurring_task_component,
        _build_maintenance_component,
    ):
        component = await build_component(db, window, cost_ctx)
        if component is not None:
            components.append(component)

    for component in (
        _build_fixed_plan_component(),
        _build_trajectory_component(
            daily_spend=daily_spend,
            monthly_spend=monthly_spend,
            window=window,
        ),
    ):
        if component is not None:
            components.append(component)

    projected_daily, projected_monthly = _compute_projected_totals(components)
    limit_forecasts = await _build_limit_forecasts(db, window, cost_ctx)

    return UsageForecastOut(
        daily_spend=round(daily_spend, 4),
        monthly_spend=round(monthly_spend, 4),
        projected_daily=round(projected_daily, 4),
        projected_monthly=round(projected_monthly, 4),
        components=components,
        limits=limit_forecasts,
        computed_at=window.now_utc.isoformat(),
        hours_elapsed_today=round(window.hours_elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Provider Health — per-(provider, model) latency + cache-hit + last-call
# ---------------------------------------------------------------------------
