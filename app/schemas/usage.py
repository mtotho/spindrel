"""Usage analytics response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CostByDimension(BaseModel):
    label: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None
    has_cost_data: bool = True

class UsageSummaryOut(BaseModel):
    total_calls: int = 0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float | None = None
    cost_by_model: list[CostByDimension] = []
    cost_by_bot: list[CostByDimension] = []
    cost_by_provider: list[CostByDimension] = []
    models_without_cost_data: list[str] = []
    calls_without_cost_data: int = 0

class UsageLogEntry(BaseModel):
    id: str
    created_at: str
    correlation_id: str | None = None
    model: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    bot_id: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None
    has_cost_data: bool = False
    duration_ms: int | None = None

class UsageLogsOut(BaseModel):
    entries: list[UsageLogEntry] = []
    total: int = 0
    page: int = 1
    page_size: int = 50
    bot_ids: list[str] = []
    model_names: list[str] = []
    provider_ids: list[str] = []

class BreakdownGroup(BaseModel):
    label: str
    key: str = ""
    calls: int = 0
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None

class UsageBreakdownOut(BaseModel):
    group_by: str
    groups: list[BreakdownGroup] = []

class TimeseriesPoint(BaseModel):
    bucket: str
    cost: float | None = None
    tokens: int = 0
    calls: int = 0

class UsageTimeseriesOut(BaseModel):
    bucket_size: str
    points: list[TimeseriesPoint] = []

class UsageAnomalyMetric(BaseModel):
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost: float | None = None
    has_cost_data: bool = True

class UsageAnomalySource(BaseModel):
    source_type: str = "unknown"
    title: str | None = None
    task_id: str | None = None
    task_type: str | None = None
    bot_id: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    model: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None

class UsageAnomalySignal(BaseModel):
    id: str
    kind: str
    label: str
    severity: str = "info"
    reason: str
    created_at: str | None = None
    bucket: str | None = None
    correlation_id: str | None = None
    dimension: str | None = None
    dimension_value: str | None = None
    metric: UsageAnomalyMetric
    baseline: UsageAnomalyMetric | None = None
    ratio: float | None = None
    cost_confidence: str = "unknown"
    source: UsageAnomalySource = Field(default_factory=UsageAnomalySource)

class UsageAnomaliesOut(BaseModel):
    window_start: str
    window_end: str
    baseline_start: str
    baseline_end: str
    bucket_size: str
    time_spikes: list[UsageAnomalySignal] = Field(default_factory=list)
    trace_bursts: list[UsageAnomalySignal] = Field(default_factory=list)
    contributors: list[UsageAnomalySignal] = Field(default_factory=list)

class AgentSmellReason(BaseModel):
    key: str
    label: str
    detail: str
    severity: str = "watch"
    points: int = 0

class AgentSmellMetrics(BaseModel):
    traces: int = 0
    calls: int = 0
    total_tokens: int = 0
    baseline_tokens: int = 0
    token_ratio: float | None = None
    max_trace_tokens: int = 0
    tool_calls: int = 0
    repeated_tool_calls: int = 0
    max_repeated_tool_signature: int = 0
    max_tool_calls_per_trace: int = 0
    max_iterations: int = 0
    tool_error_count: int = 0
    tool_denied_count: int = 0
    tool_expired_count: int = 0
    error_events: int = 0
    slow_trace_count: int = 0
    max_trace_duration_ms: int = 0
    # Context bloat — working-set hygiene
    enrolled_tools_count: int = 0
    unused_tools_count: int = 0
    pinned_unused_tools: list[str] = Field(default_factory=list)
    enrolled_skills_count: int = 0
    unused_skills_count: int = 0
    pinned_unused_skills: list[str] = Field(default_factory=list)
    tool_schema_tokens_estimate: int = 0
    estimated_bloat_tokens: int = 0

class AgentSmellTraceEvidence(BaseModel):
    correlation_id: str | None = None
    created_at: str | None = None
    reason: str
    tokens: int = 0
    tool_calls: int = 0
    repeated_tool_calls: int = 0
    errors: int = 0
    duration_ms: int = 0

class AgentSmellBot(BaseModel):
    rank: int = 0
    bot_id: str
    name: str
    display_name: str | None = None
    model: str | None = None
    avatar_url: str | None = None
    avatar_emoji: str | None = None
    score: int = 0
    severity: str = "clean"
    reasons: list[AgentSmellReason] = Field(default_factory=list)
    metrics: AgentSmellMetrics = Field(default_factory=AgentSmellMetrics)
    traces: list[AgentSmellTraceEvidence] = Field(default_factory=list)

class AgentSmellSummary(BaseModel):
    """Top-level workspace-wide bloat signal for satellites/badges."""
    bloated_bot_count: int = 0
    total_unused_tools: int = 0
    total_pinned_unused_tools: int = 0
    total_unused_skills: int = 0
    total_estimated_bloat_tokens: int = 0
    max_severity: str = "clean"

class AgentSmellOut(BaseModel):
    window_start: str
    window_end: str
    baseline_start: str
    baseline_end: str
    source_type: str | None = None
    bots: list[AgentSmellBot] = Field(default_factory=list)
    summary: AgentSmellSummary = Field(default_factory=AgentSmellSummary)

class ForecastComponent(BaseModel):
    source: str          # "heartbeats" | "recurring_tasks" | "trajectory"
    label: str
    daily_cost: float
    monthly_cost: float
    count: int | None = None
    avg_cost_per_run: float | None = None

class LimitForecast(BaseModel):
    scope_type: str
    scope_value: str
    period: str
    limit_usd: float
    current_spend: float
    percentage: float
    projected_spend: float
    projected_percentage: float

class UsageForecastOut(BaseModel):
    daily_spend: float
    monthly_spend: float
    projected_daily: float
    projected_monthly: float
    components: list[ForecastComponent] = []
    limits: list[LimitForecast] = []
    computed_at: str
    hours_elapsed_today: float

class ProviderHealthRow(BaseModel):
    provider_id: str | None = None
    provider_name: str | None = None
    model: str
    sample_count: int
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    cache_hit_rate: float | None = None
    last_call_ts: str | None = None
    cooldown_until_ts: str | None = None

class ProviderHealthOut(BaseModel):
    window_hours: int
    rows: list[ProviderHealthRow]
