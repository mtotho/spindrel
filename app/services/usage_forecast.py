"""Usage forecast read model."""
from __future__ import annotations

import re
from collections import defaultdict
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


async def build_usage_forecast(db: AsyncSession = None):
    """Cost forecast: projected daily/monthly spend from heartbeats, recurring tasks, and current trajectory."""
    now_utc = datetime.now(timezone.utc)
    # Compute "today" and "this month" boundaries in the user's configured timezone
    local_tz = ZoneInfo(settings.TIMEZONE)
    now_local = now_utc.astimezone(local_tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    seven_days_ago = now_utc - timedelta(days=7)
    hours_elapsed = (now_utc - today_start).total_seconds() / 3600
    days_elapsed = (now_utc - month_start).total_seconds() / 86400

    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

    # --- Actual spend today & this month ---
    today_events, _ = await _fetch_token_usage_events(db, after=today_start)
    daily_spend = _compute_cost_for_events(today_events, pricing, ptype_map)

    month_events, _ = await _fetch_token_usage_events(db, after=month_start)
    monthly_spend = _compute_cost_for_events(month_events, pricing, ptype_map)

    components: list[ForecastComponent] = []

    # --- Heartbeat forecast ---
    heartbeats = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.enabled == True)  # noqa: E712
    )).scalars().all()

    if heartbeats:
        hb_ids = [hb.id for hb in heartbeats]
        # Fetch recent runs with correlation_ids for cost lookup
        recent_runs = (await db.execute(
            select(HeartbeatRun).where(
                HeartbeatRun.heartbeat_id.in_(hb_ids),
                HeartbeatRun.run_at >= seven_days_ago,
                HeartbeatRun.correlation_id.isnot(None),
            )
        )).scalars().all()

        correlation_ids = [r.correlation_id for r in recent_runs if r.correlation_id]

        hb_cost_total = 0.0
        hb_run_count = 0
        if correlation_ids:
            # Batch fetch trace events for heartbeat runs
            hb_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(correlation_ids),
                )
            )).scalars().all()
            hb_cost_total = _compute_cost_for_events(hb_events, pricing)
            hb_run_count = len(correlation_ids)

        avg_cost_per_hb = hb_cost_total / hb_run_count if hb_run_count > 0 else 0.0

        # Compute total runs per day across all enabled heartbeats
        from app.services.heartbeat import _resolve_quiet_range
        total_runs_per_day = 0.0
        for hb in heartbeats:
            interval = hb.interval_minutes or 60
            quiet = _resolve_quiet_range(hb)
            if quiet:
                qs, qe = quiet
                quiet_mins = (qe.hour * 60 + qe.minute) - (qs.hour * 60 + qs.minute)
                if quiet_mins < 0:
                    quiet_mins += 24 * 60  # wraps midnight
            else:
                quiet_mins = 0
            active_mins = max(24 * 60 - quiet_mins, 0)
            total_runs_per_day += active_mins / interval if interval > 0 else 0

        hb_daily = total_runs_per_day * avg_cost_per_hb
        components.append(ForecastComponent(
            source="heartbeats",
            label="Scheduled heartbeats",
            daily_cost=round(hb_daily, 4),
            monthly_cost=round(hb_daily * 30, 4),
            count=len(heartbeats),
            avg_cost_per_run=round(avg_cost_per_hb, 6) if avg_cost_per_hb > 0 else None,
        ))

    # Shared lazy-loaded model average cost map (used by recurring tasks + maintenance)
    model_avg_cost: dict[str, float] | None = None

    # --- Recurring task forecast ---
    recurring_tasks = (await db.execute(
        select(Task).where(
            Task.status == "active",
            Task.recurrence.isnot(None),
        )
    )).scalars().all()

    if recurring_tasks:
        # Estimate cost per recurring task using correlation_id-based cost
        # attribution from recent spawned runs. Falls back to model-based
        # estimate for tasks without correlation data (pre-migration runs).
        from app.agent.bots import _registry as _bot_registry
        from collections import defaultdict

        template_ids = [t.id for t in recurring_tasks]

        # --- Phase 1: correlation_id-based cost (precise) ---
        recent_runs = (await db.execute(
            select(Task).where(
                Task.parent_task_id.in_(template_ids),
                Task.correlation_id.isnot(None),
                Task.completed_at >= seven_days_ago,
            )
        )).scalars().all()

        # Map correlation_id → parent_task_id
        corr_parent: dict[str, str] = {}
        task_corr_ids = []
        for run in recent_runs:
            if run.correlation_id and run.parent_task_id:
                cid = str(run.correlation_id)
                corr_parent[cid] = str(run.parent_task_id)
                task_corr_ids.append(run.correlation_id)

        # Batch fetch trace events by correlation_id
        template_run_costs: dict[str, list[float]] = defaultdict(list)
        if task_corr_ids:
            task_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(task_corr_ids),
                )
            )).scalars().all()

            corr_costs: dict[str, float] = defaultdict(float)
            for ev in task_events:
                cid = str(ev.correlation_id) if ev.correlation_id else None
                if not cid:
                    continue
                d = ev.data or {}
                cost = _resolve_event_cost(d, pricing, ptype_map)
                if cost is not None:
                    corr_costs[cid] += cost

            for cid, run_cost in corr_costs.items():
                parent_id = corr_parent.get(cid)
                if parent_id:
                    template_run_costs[parent_id].append(run_cost)

        # --- Phase 2: model-based fallback for tasks without correlation data ---
        # Build avg cost-per-call by model from recent 7-day usage (lazy, only if needed)
        templates_with_data = set(template_run_costs.keys())

        task_daily = 0.0
        for task in recurring_tasks:
            runs_per_day = _recurrence_runs_per_day(task.recurrence or "")
            if runs_per_day <= 0:
                continue

            tid = str(task.id)
            if tid in templates_with_data:
                # Use actual correlation-based cost average
                costs = template_run_costs[tid]
                avg_cost = sum(costs) / len(costs) if costs else 0.0
            else:
                # Fallback: estimate from model's avg cost per call
                bot = _bot_registry.get(task.bot_id)
                model = bot.model if bot else None

                if model and _is_plan_billed(None, model):
                    continue

                # Lazy-load model averages on first fallback
                if model_avg_cost is None:
                    recent_events, _ = await _fetch_token_usage_events(db, after=seven_days_ago)
                    _mcs: dict[str, float] = defaultdict(float)
                    _mcc: dict[str, int] = defaultdict(int)
                    for ev in recent_events:
                        d = ev.data or {}
                        ev_model = d.get("model")
                        if not ev_model:
                            continue
                        c = _resolve_event_cost(d, pricing, ptype_map)
                        if c is not None:
                            _mcs[ev_model] += c
                            _mcc[ev_model] += 1
                    model_avg_cost = {
                        m: _mcs[m] / _mcc[m] for m in _mcs if _mcc[m] > 0
                    }

                avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

            task_daily += runs_per_day * avg_cost

        components.append(ForecastComponent(
            source="recurring_tasks",
            label="Recurring tasks",
            daily_cost=round(task_daily, 4),
            monthly_cost=round(task_daily * 30, 4),
            count=len(recurring_tasks),
        ))

    # --- Maintenance tasks forecast (memory_hygiene + skill_review) ---
    from app.services.memory_hygiene import resolve_config as resolve_hygiene_config

    maint_bots = (await db.execute(
        select(Bot).where(Bot.memory_scheme == "workspace-files")
    )).scalars().all()

    maint_daily = 0.0
    maint_count = 0

    if maint_bots:
        # Fetch recent completed + skipped maintenance tasks for cost & skip-rate
        maint_types = ("memory_hygiene", "skill_review")
        recent_maint = (await db.execute(
            select(Task).where(
                Task.task_type.in_(maint_types),
                Task.status.in_(("completed", "skipped")),
                Task.completed_at >= seven_days_ago,
            )
        )).scalars().all()

        # Cost per run via correlation_id (completed tasks only)
        completed_corr_ids = [
            t.correlation_id for t in recent_maint
            if t.status == "completed" and t.correlation_id
        ]
        type_run_costs: dict[str, list[float]] = {"memory_hygiene": [], "skill_review": []}
        if completed_corr_ids:
            maint_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(completed_corr_ids),
                )
            )).scalars().all()

            # Sum cost per correlation_id
            from collections import defaultdict as _defaultdict
            corr_cost: dict[str, float] = _defaultdict(float)
            for ev in maint_events:
                cid = str(ev.correlation_id) if ev.correlation_id else None
                if not cid:
                    continue
                d = ev.data or {}
                cost = _resolve_event_cost(d, pricing, ptype_map)
                if cost is not None:
                    corr_cost[cid] += cost

            # Map correlation_id back to task_type
            corr_to_type = {
                str(t.correlation_id): t.task_type
                for t in recent_maint
                if t.status == "completed" and t.correlation_id
            }
            for cid, run_cost in corr_cost.items():
                tt = corr_to_type.get(cid)
                if tt and tt in type_run_costs:
                    type_run_costs[tt].append(run_cost)

        # Skip rate per job type: fraction of runs that actually executed
        type_skip_rate: dict[str, float] = {}
        for tt in maint_types:
            completed = sum(1 for t in recent_maint if t.task_type == tt and t.status == "completed")
            skipped = sum(1 for t in recent_maint if t.task_type == tt and t.status == "skipped")
            total = completed + skipped
            type_skip_rate[tt] = completed / total if total > 0 else 0.5  # default 50% if no data

        for bot in maint_bots:
            for job_type in maint_types:
                cfg = resolve_hygiene_config(bot, job_type)
                if not cfg.enabled or cfg.interval_hours <= 0:
                    continue

                maint_count += 1
                runs_per_day = 24.0 / cfg.interval_hours
                # Apply empirical execution rate (accounts for only_if_active skips)
                runs_per_day *= type_skip_rate.get(job_type, 0.5)

                costs = type_run_costs.get(job_type, [])
                if costs:
                    avg_cost = sum(costs) / len(costs)
                else:
                    # Fallback: use model-based average (same lazy-load as recurring tasks)
                    model = cfg.model
                    if not model:
                        from app.agent.bots import _registry as _bot_reg
                        b = _bot_reg.get(bot.id)
                        model = b.model if b else None
                    if model and _is_plan_billed(None, model):
                        continue
                    if model_avg_cost is None:
                        recent_events, _ = await _fetch_token_usage_events(db, after=seven_days_ago)
                        _mcs2: dict[str, float] = {}
                        _mcc2: dict[str, int] = {}
                        for ev in recent_events:
                            d = ev.data or {}
                            ev_model = d.get("model")
                            if not ev_model:
                                continue
                            c = _resolve_event_cost(d, pricing, ptype_map)
                            if c is not None:
                                _mcs2[ev_model] = _mcs2.get(ev_model, 0.0) + c
                                _mcc2[ev_model] = _mcc2.get(ev_model, 0) + 1
                        model_avg_cost = {
                            m: _mcs2[m] / _mcc2[m] for m in _mcs2 if _mcc2[m] > 0
                        }
                    avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

                maint_daily += runs_per_day * avg_cost

    if maint_count > 0:
        components.append(ForecastComponent(
            source="maintenance_tasks",
            label="Maintenance tasks",
            daily_cost=round(maint_daily, 4),
            monthly_cost=round(maint_daily * 30, 4),
            count=maint_count,
        ))

    # --- Fixed plan costs ---
    from app.services.providers import _registry as _provider_registry
    plan_daily = 0.0
    plan_count = 0
    for prow in _provider_registry.values():
        if prow.billing_type == "plan" and prow.plan_cost:
            if prow.plan_period == "weekly":
                plan_daily += prow.plan_cost / 7
            else:  # monthly
                plan_daily += prow.plan_cost / 30
            plan_count += 1
    if plan_count > 0:
        components.append(ForecastComponent(
            source="fixed_plans",
            label="Fixed plans",
            daily_cost=round(plan_daily, 4),
            monthly_cost=round(plan_daily * 30, 4),
            count=plan_count,
        ))

    # --- Trajectory (extrapolation from current pace) ---
    if hours_elapsed >= 1.0:
        traj_daily = daily_spend / hours_elapsed * 24
        traj_monthly = monthly_spend / days_elapsed * 30 if days_elapsed >= 1.0 else traj_daily * 30
        components.append(ForecastComponent(
            source="trajectory",
            label="Current pace",
            daily_cost=round(traj_daily, 4),
            monthly_cost=round(traj_monthly, 4),
        ))

    # Projected = max(trajectory, scheduled_variable) + fixed_plans
    # Trajectory already includes variable scheduled costs (heartbeats + tasks) that
    # ran today, so we take the higher of trajectory vs scheduled variable costs.
    # Fixed plan costs are always added on top since they're unavoidable flat fees.
    fixed_plan_daily = next((c.daily_cost for c in components if c.source == "fixed_plans"), 0.0)
    fixed_plan_monthly = next((c.monthly_cost for c in components if c.source == "fixed_plans"), 0.0)
    variable_scheduled_daily = sum(c.daily_cost for c in components if c.source not in ("trajectory", "fixed_plans"))
    variable_scheduled_monthly = sum(c.monthly_cost for c in components if c.source not in ("trajectory", "fixed_plans"))
    trajectory_daily = next((c.daily_cost for c in components if c.source == "trajectory"), 0.0)
    trajectory_monthly = next((c.monthly_cost for c in components if c.source == "trajectory"), 0.0)
    projected_daily = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily
    projected_monthly = max(trajectory_monthly, variable_scheduled_monthly) + fixed_plan_monthly

    # --- Limit forecasts ---
    from app.services.usage_limits import _limits, _period_start
    limit_forecasts: list[LimitForecast] = []
    for limit in _limits:
        since = _period_start(limit.period)
        # Compute current spend for this limit's scope
        base_q = select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= since,
        )
        if limit.scope_type == "bot":
            base_q = base_q.where(TraceEvent.bot_id == limit.scope_value)
        elif limit.scope_type == "model":
            base_q = base_q.where(TraceEvent.data["model"].astext == limit.scope_value)

        limit_events = (await db.execute(base_q)).scalars().all()
        current = _compute_cost_for_events(limit_events, pricing)
        pct = (current / limit.limit_usd * 100) if limit.limit_usd > 0 else 0

        # Project spend to end of period by extrapolating this scope's own pace
        if limit.period == "daily":
            projected = current / hours_elapsed * 24 if hours_elapsed >= 1.0 else current
        else:  # monthly
            projected = current / days_elapsed * 30 if days_elapsed >= 1.0 else current

        proj_pct = (projected / limit.limit_usd * 100) if limit.limit_usd > 0 else 0

        limit_forecasts.append(LimitForecast(
            scope_type=limit.scope_type,
            scope_value=limit.scope_value,
            period=limit.period,
            limit_usd=limit.limit_usd,
            current_spend=round(current, 4),
            percentage=round(pct, 1),
            projected_spend=round(projected, 4),
            projected_percentage=round(proj_pct, 1),
        ))

    return UsageForecastOut(
        daily_spend=round(daily_spend, 4),
        monthly_spend=round(monthly_spend, 4),
        projected_daily=round(projected_daily, 4),
        projected_monthly=round(projected_monthly, 4),
        components=components,
        limits=limit_forecasts,
        computed_at=now_utc.isoformat(),
        hours_elapsed_today=round(hours_elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Provider Health — per-(provider, model) latency + cache-hit + last-call
# ---------------------------------------------------------------------------
