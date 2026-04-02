# Usage Tracking & Cost Budgeting

Spindrel tracks every LLM call — tokens, latency, cost — and provides analytics, budget limits, and spend forecasting from the admin UI.

## How Cost Tracking Works

Every LLM call generates a `TraceEvent` with token counts, model name, provider, and duration. Cost is computed per-call using one of these sources (in priority order):

1. **Provider-reported cost** — some APIs return cost directly in the response
2. **DB pricing data** — per-model input/output rates from **Admin > Providers > Models**
3. **LiteLLM pricing cache** — auto-fetched from LiteLLM proxy `/model/info` at startup
4. **Cross-provider lookup** — matches model names across providers

If no pricing source matches, the call is tracked but cost shows as `--` with a "no pricing" badge.

!!! tip "LiteLLM bonus"
    When using a LiteLLM proxy, Spindrel automatically fetches pricing data for all available models at startup. This is the easiest path to full cost tracking without manual configuration.

### Prompt Caching Discounts

Cached input tokens are priced at a discount:

| Provider | Cache Discount |
|----------|---------------|
| Anthropic | 90% (cached tokens at 10% of input price) |
| OpenAI | 50% |
| Other | 50% (default) |

### Plan-Billed Providers

Providers with `billing_type: "plan"` (e.g., a flat monthly subscription) report $0 per-call cost. The fixed plan cost appears in the forecast breakdown instead.

## Usage Dashboard

Navigate to **Admin > Usage** to access five tabs:

### Overview

- **Forecast cards** — Today's spend and this month's spend with projected end-of-period totals
- **Limit warnings** — Orange/red banners when any budget limit is approaching or exceeded
- **Summary stats** — Total calls, tokens, cost, and average cost per call for the selected time window
- **Forecast breakdown** — Table showing projected daily/monthly cost by component (heartbeats, recurring tasks, trajectory, fixed plans)
- **Cost tables** — Breakdown by model, bot, and provider (click to drill into Logs)

### Logs

Two view modes:

- **By Trace** — Groups related LLM calls by correlation ID (one agent run = one trace). Shows iteration count, total tokens, cost, and latency. Expand to see individual calls.
- **Raw Calls** — Flat list of every LLM call with model, bot, channel, tokens, cost, and duration.

Click any trace to view the full trace detail page.

### Charts

- **Daily Forecast by Component** — Horizontal bar chart of projected daily cost (heartbeats, tasks, trajectory, fixed plans)
- **Cost by Model** — Horizontal bar chart of actual spend per model
- **Cost over Time** — Line chart of cost across time buckets
- **Calls over Time** — Line chart of call count

### Limits

Create and manage budget caps. See [Budget Limits](#budget-limits) below.

### Alerts

Configure spike detection to get notified when spend rate jumps unexpectedly. See [Spike Alerts](#spike-alerts) below.

### Filters

All tabs share a filter bar:

- **Time presets** — 1h, 12h, 24h, 48h, 7d, 30d
- **Bot** — Filter by bot
- **Model** — Filter by model (populated from data in the selected time range)
- **Provider** — Filter by provider

## Budget Limits

Budget limits cap spending by scope and period. When a limit is exceeded, further LLM calls for that scope are blocked until the period resets.

### Creating a Limit

In **Admin > Usage > Limits**, click **Add Limit**:

| Field | Options | Description |
|-------|---------|-------------|
| Type | `model`, `bot` | What to cap |
| Value | Model name or bot ID | The specific model or bot |
| Period | `daily`, `monthly` | Reset cycle |
| Limit ($) | Any positive number | Dollar cap |

### How Enforcement Works

Before every agent run, Spindrel checks all enabled limits:

1. Computes spend since the current period start (midnight or 1st of month, in server timezone)
2. If spend >= limit, the run is blocked with a `UsageLimitExceeded` error
3. The client receives a message explaining which limit was hit

Limits are cached in memory and refreshed every 60 seconds.

!!! note "Timezone"
    Period boundaries (midnight, 1st of month) use the `TIMEZONE` setting from `.env` (default: `America/New_York`).

### Projected Spend

Each limit card shows:

- **Current spend** — Actual spend so far in the period (solid progress bar)
- **Projected spend** — Extrapolated to end of period based on current pace (translucent extension)
- **Warning colors** — Green (<70%), orange (70-90%), red (>90%)

## Spend Forecasting

The forecast system projects future spend by analyzing four components:

### Heartbeats

- Looks at enabled heartbeats with recent execution history (7 days)
- Computes average cost per heartbeat run
- Factors in quiet hours to reduce daily run count
- Formula: `runs_per_day * avg_cost_per_run`

### Recurring Tasks

- Queries active tasks with recurrence schedules (`+30m`, `+1h`, `+1d`, etc.)
- Estimates cost from recent execution history, falling back to the bot's model average
- Formula: `runs_per_day * avg_cost_per_run`

### Fixed Plans

- Sums daily cost of all plan-billed providers
- Weekly plans: `plan_cost / 7` per day
- Monthly plans: `plan_cost / 30` per day

### Trajectory (Current Pace)

- Extrapolates from actual spend so far today/this month
- Only computed when at least 1 hour has elapsed today
- Daily: `spend_today / hours_elapsed * 24`
- Monthly: `spend_this_month / days_elapsed * 30`

### Projection Formula

The final projection takes the **higher** of trajectory vs. scheduled costs (heartbeats + recurring tasks), then **adds** fixed plan costs:

```
projected = max(trajectory, scheduled_variable) + fixed_plans
```

This ensures the forecast isn't underestimated when scheduled events haven't fired yet today.

## Spike Alerts

Spike alerts monitor your spend *rate* and push notifications when it exceeds a baseline — catching runaway loops and unexpected traffic before a hard budget limit is hit.

### How It Works

A background worker checks every 60 seconds:

1. Computes the **window rate** — cost per hour over the last N minutes (default: 30)
2. Computes the **baseline rate** — cost per hour over the last N hours (default: 24), excluding the window
3. Fires an alert if either threshold is exceeded:
    - **Relative threshold** — window rate ÷ baseline rate ≥ multiplier (default: 2.0x)
    - **Absolute threshold** — window rate ≥ fixed $/hr (default: disabled)

After firing, a **cooldown** period (default: 60 minutes) prevents repeat alerts.

### Configuring Alerts

In **Admin > Usage > Alerts**:

| Field | Default | Description |
|-------|---------|-------------|
| Enabled | Off | Master toggle |
| Window (min) | 30 | How far back to measure current rate |
| Baseline (hrs) | 24 | How far back for the comparison average |
| Relative threshold | 2.0x | Fire when current rate is this many times the baseline |
| Absolute threshold | $0/hr | Fire when current rate exceeds this (0 = disabled) |
| Cooldown (min) | 60 | Minimum gap between alerts |

### Notification Targets

Alerts are delivered via the same dispatcher system used for bot messages. You can add multiple targets:

- **Channel** — Any channel with a configured integration (Slack, Discord, BlueBubbles, etc.)
- **Integration binding** — A specific integration client ID (e.g., a particular Slack channel or iMessage contact)

Each target is dispatched independently — one failure doesn't block others.

### Alert Content

Notifications include:

- Current rate vs. baseline rate ($/hr)
- Spike ratio (e.g., 3.2x)
- Top models by cost (with call counts)
- Top bots by cost
- Most expensive recent traces

### Test Alerts

Click **Send Test Alert** to fire a notification that bypasses thresholds and cooldown. Useful for verifying targets are configured correctly.

### HUD Indicator

When spike alerts are enabled, the sidebar usage badge shows a status indicator:

- **Green dot** — Normal (with current ratio if available)
- **Red pulsing dot** — Spike active
- **Gray dot** — Alerts disabled

### Alert History

The Alerts tab shows a paginated log of all fired alerts with trigger details, delivery results, and context snapshots.

## Provider Configuration

Providers are configured in two ways:

### Default Provider (`.env`)

```bash
LITELLM_BASE_URL=http://litellm:4000/v1  # Any OpenAI-compatible endpoint
LITELLM_API_KEY=your-key
```

| Provider | `LITELLM_BASE_URL` | Notes |
|----------|-------------------|-------|
| LiteLLM proxy | `http://litellm:4000/v1` | Self-hosted, 100+ models, auto pricing |
| OpenAI | `https://api.openai.com/v1` | Direct API |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible |
| OpenRouter | `https://openrouter.ai/api/v1` | Multi-provider |
| Ollama | `http://localhost:11434/v1` | Local models |

### Additional Providers (Admin UI)

Add providers via **Admin > Providers** with:

| Field | Description |
|-------|-------------|
| Provider type | `openai`, `openai-compatible`, `anthropic`, `anthropic-compatible`, `litellm` |
| API key | Encrypted at rest |
| Base URL | Custom endpoint (optional for direct API providers) |
| TPM / RPM limits | Rate limiting (tokens/requests per minute) |
| Billing type | `usage` (per-token) or `plan` (flat rate) |
| Plan cost / period | For plan-billed providers |

### Assigning Providers to Bots

In bot YAML:

```yaml
id: my_bot
model: claude-sonnet-4-20250514
model_provider_id: my_anthropic_provider  # References provider ID
```

Bots without `model_provider_id` use the `.env` default provider.

### Model Pricing

For accurate cost tracking, configure per-model pricing in **Admin > Providers > [Provider] > Models**:

- **Sync from provider** — Auto-fetch model list and pricing (works with LiteLLM and Ollama)
- **Manual entry** — Set input/output cost per 1M tokens

## API Reference

All endpoints require admin authentication and are prefixed with `/api/v1/admin`.

### Usage Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/usage/summary` | Aggregate stats (calls, tokens, cost) |
| GET | `/usage/logs` | Paginated event log |
| GET | `/usage/breakdown` | Grouped by model/bot/channel/provider |
| GET | `/usage/timeseries` | Cost over time (bucketed) |
| GET | `/usage/forecast` | Projected spend + limit forecasts |

**Common query parameters**: `after`, `before`, `bot_id`, `model`, `provider_id`, `channel_id`

### Budget Limits

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/limits/` | List all limits |
| POST | `/limits/` | Create limit |
| PUT | `/limits/{id}` | Update limit (amount, enabled) |
| DELETE | `/limits/{id}` | Delete limit |
| GET | `/limits/status` | Current spend vs. limit for all |

### Spike Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/spike-alerts/config` | Get config (auto-creates default if missing) |
| PUT | `/spike-alerts/config` | Update thresholds, targets, enabled |
| POST | `/spike-alerts/test` | Fire test alert (bypasses cooldown) |
| GET | `/spike-alerts/history` | Paginated alert history |
| GET | `/spike-alerts/status` | Current rate, baseline, spike ratio |
| GET | `/spike-alerts/targets/available` | List available notification targets |

### Providers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/providers` | List all providers |
| POST | `/providers` | Create provider |
| PUT | `/providers/{id}` | Update provider |
| DELETE | `/providers/{id}` | Delete provider |
| POST | `/providers/{id}/test` | Test connection |
| GET | `/providers/{id}/models` | List model pricing |
| POST | `/providers/{id}/models` | Add model pricing |
| POST | `/providers/{id}/sync-models` | Sync from provider API |

## Sidebar HUD

Toggle the usage badge in the sidebar via the eye icon on the Usage page. The badge shows a compact spend summary with a popover for forecast details — useful for at-a-glance cost monitoring without leaving your current page. When spike alerts are enabled, the popover also shows a spike status indicator.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_BASE_URL` | — | Default LLM endpoint |
| `LITELLM_API_KEY` | — | Default LLM API key |
| `TIMEZONE` | `America/New_York` | Period boundaries for limits and forecasts |
| `LLM_TIMEOUT` | `120` | HTTP timeout (seconds) |
| `LLM_MAX_RETRIES` | `3` | Transient error retries |
| `LLM_RATE_LIMIT_RETRIES` | `3` | Rate limit retries |
| `LLM_RATE_LIMIT_INITIAL_WAIT` | `90` | Rate limit backoff (seconds) |
