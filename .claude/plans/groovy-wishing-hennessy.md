# Fixed-Cost Plan Billing for Providers

## Context
Providers like MiniMax charge a flat monthly/weekly rate (e.g. $40/mo) regardless of token usage. The current system only supports per-token pricing via `ProviderModel.input_cost_per_1m`/`output_cost_per_1m`. When no per-token rates exist, calls show "no pricing" in the usage UI and are invisible to the forecast/HUD badge. The fix: let providers declare a fixed plan cost so it surfaces correctly in usage tracking.

## Files to Modify

### 1. DB Model — `app/db/models.py`
Add 3 nullable columns to `ProviderConfig` (after `config` field, ~line 716):
- `billing_type: Mapped[str]` — `"usage"` (default) or `"plan"`, server_default `"usage"`
- `plan_cost: Mapped[float | None]` — fixed cost amount (e.g. 40.0)
- `plan_period: Mapped[str | None]` — `"weekly"` or `"monthly"`

### 2. Migration — `migrations/versions/143_provider_plan_billing.py`
Simple additive migration (pattern from `138_provider_model_supports_tools.py`):
- `op.add_column("provider_configs", sa.Column("billing_type", sa.Text(), nullable=False, server_default=sa.text("'usage'")))`
- `op.add_column("provider_configs", sa.Column("plan_cost", sa.Float(), nullable=True))`
- `op.add_column("provider_configs", sa.Column("plan_period", sa.Text(), nullable=True))`
- Downgrade drops all 3

### 3. Provider API — `app/routers/api_v1_admin/providers.py`
- **`ProviderOut`**: Add `billing_type: str`, `plan_cost: float | None`, `plan_period: str | None`
- **`ProviderCreateIn`**: Add same 3 fields (billing_type defaults to `"usage"`, others optional)
- **`ProviderUpdateIn`**: Add same 3 fields as optional + `clear_plan_cost: bool = False`
- **`_provider_to_out()`**: Pass through new fields
- **Create/Update handlers**: Save new fields to DB

### 4. Provider Service — `app/services/providers.py`
- **`ProviderConfigRow`** namedtuple/dataclass: Add `billing_type`, `plan_cost`, `plan_period` fields
- **`load_providers()`**: Load new fields into registry so they're available in-memory

### 5. Usage Cost Resolution — `app/routers/api_v1_admin/usage.py`

#### 5a. `_resolve_event_cost()` (~line 107)
When cost is None (no per-token pricing), check if the event's `provider_id` belongs to a plan provider. If so, return `0.0` instead of `None` — the cost is real but marginal cost per call is zero. This prevents "no pricing" warnings.

Need a helper to check plan status:
```python
def _is_plan_provider(provider_id: str | None) -> bool:
    from app.services.providers import _registry
    if not provider_id or provider_id not in _registry:
        return False
    return _registry[provider_id].billing_type == "plan"
```

#### 5b. Forecast endpoint (`usage_forecast`, ~line 868)
Add a new "Fixed plans" component after the trajectory block (~line 1024):
```python
# --- Fixed plan costs ---
plan_daily = 0.0
plan_count = 0
for pid, prow in _registry.items():
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
```

Also add `plan_daily` to `scheduled_daily`/`scheduled_monthly` so projected totals include it.

### 6. UI API Hooks — `ui/src/api/hooks/useProviders.ts`
- **`ProviderItem`**: Add `billing_type: string`, `plan_cost?: number | null`, `plan_period?: string | null`
- **`ProviderCreatePayload`**: Add same fields
- **`ProviderUpdatePayload`**: Add same fields + `clear_plan_cost?: boolean`

### 7. UI Provider Detail Form — `ui/app/(app)/admin/providers/[providerId]/index.tsx`
Add a **"Billing"** section (between "Rate Limits" and "Models"):
- **Billing Type** toggle/select: "Per-token usage" vs "Fixed plan"
- When "Fixed plan" selected, show:
  - **Plan Cost** number input (e.g. 40)
  - **Plan Period** select: "Monthly" / "Weekly"
- State: `billingType`, `planCost`, `planPeriod`
- Initialize from provider data on load
- Include in save payload

### 8. UI Forecast Type — `ui/src/api/hooks/useUsageForecast.ts`
The `ForecastComponent.source` is already typed as `string`, and the badge renders all components generically — no change needed. The new `"fixed_plans"` source will just show up in the popover breakdown automatically.

## Verification
1. **Migration**: Run `alembic upgrade head` — verify 3 new columns on `provider_configs`
2. **API**: Create/update a provider with `billing_type: "plan"`, `plan_cost: 40`, `plan_period: "monthly"` — verify it round-trips
3. **Usage summary**: Make calls through a plan provider → verify they show `cost: 0.0` and `has_cost_data: true` (no "no pricing" warning)
4. **Forecast**: Verify the HUD badge includes "Fixed plans: $1.33/day" component
5. **UI form**: Open provider detail → verify Billing section shows and saves correctly
6. **Typecheck**: `cd ui && npx tsc --noEmit` — no new errors
7. **Tests**: Add unit test for `_is_plan_provider` and the fixed plan forecast component
