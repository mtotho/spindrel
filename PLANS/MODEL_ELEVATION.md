---
status: draft
last_updated: 2026-03-22
owner: mtoth
summary: >
  Intelligent model elevation system: default to cheap/fast models, elevate to
  capable models only when pre-turn heuristics determine the turn is complex.
  Rule-based classifier → elevation logging → heartbeat analysis → local model tier.
---

# Model Elevation System

## Goal

Default every turn to the cheapest viable model (Haiku-class) and only elevate to a more capable model (Sonnet/Opus-class) when the turn actually needs it. The elevation decision happens **before** `_llm_call()` — no mid-turn model switching, ever. Savings come from not spinning up the expensive model in the first place.

### Design Principles

1. **Pre-turn only** — the classifier runs once per iteration, before the LLM call. A more expensive model never downgrades itself mid-turn.
2. **Deterministic first** — start with rule-based heuristics (Phase 1). ML/LLM-based classification is a future option, not a launch requirement.
3. **Observable** — every elevation decision is logged with enough context to evaluate correctness after the fact.
4. **Tunable** — weights and thresholds live in config (bot YAML + env vars), not hardcoded.
5. **Graceful** — if the classifier errors, fall through to the bot's configured default model (no silent failures, no blocked turns).

---

## 1. Architecture Overview

### 1.1 Where the Decision Lives

The elevation decision inserts into the agent tool loop at exactly one point: **inside `run_agent_tool_loop()` in `app/agent/loop.py`, before the `_llm_call()` on line 136**.

```
Current flow (loop.py:89–136):
  for iteration in range(AGENT_MAX_ITERATIONS):
      ...rate limit check...
      response = await _llm_call(model, messages, tools_param, tool_choice, ...)

New flow:
  for iteration in range(AGENT_MAX_ITERATIONS):
      ...rate limit check...
      elevation = classify_turn(messages, bot, iteration)  # NEW
      effective_model = elevation.model                     # NEW
      response = await _llm_call(effective_model, messages, tools_param, tool_choice, ...)
```

The `model` variable on line 56 (`model = model_override or bot.model`) becomes the **base model** (cheap tier). The classifier may elevate it. The `model_override` parameter still takes absolute precedence (compaction, forced-response retries, etc. can pin a specific model).

### 1.2 The Classifier Contract

```python
# app/agent/elevation.py

@dataclass
class ElevationResult:
    model: str              # the model to actually use for this turn
    tier: str               # "base" | "mid" | "top" (for logging)
    was_elevated: bool      # True if model != base model
    reason: str             # human-readable: which rules fired
    score: float            # numeric classifier score (0.0–1.0)
    confidence: float       # how confident the classifier is (0.0–1.0)
    rules_fired: list[str]  # machine-readable rule IDs

def classify_turn(
    messages: list[dict],
    bot: BotConfig,
    iteration: int,
    user_message: str | None = None,
) -> ElevationResult:
    """Synchronous, deterministic. Must be fast (<5ms). No I/O."""
```

### 1.3 How the Chosen Model Enters the LLM Call Path

No changes to `_llm_call()` signature needed. The effective model is simply passed as the first argument:

```python
response = await _llm_call(
    elevation.model,  # was: model
    messages, tools_param, tool_choice,
    provider_id=provider_id,
)
```

The existing `LLM_FALLBACK_MODEL` mechanism in `llm.py` still applies — if the elevated model fails after retries, it falls back as configured. This is orthogonal to elevation.

### 1.4 Configuration Surface

**Bot YAML** (per-bot overrides):
```yaml
model_elevation:
  enabled: true
  base_model: "claude-haiku"           # cheap default
  mid_model: "claude-sonnet"           # Phase 4 only; omit = same as top
  top_model: "claude-sonnet"           # elevated model
  threshold: 0.5                       # score >= this triggers elevation
  mid_threshold: 0.3                   # Phase 4: score >= this but < threshold = mid tier
  weights:                             # per-signal weight overrides
    message_length: 0.15
    code_content: 0.20
    keyword_elevate: 0.25
```

**Environment / Settings** (global defaults in `app/config.py`):
```python
MODEL_ELEVATION_ENABLED: bool = False
MODEL_ELEVATION_BASE_MODEL: str = ""         # empty = use bot.model (no elevation)
MODEL_ELEVATION_TOP_MODEL: str = ""          # empty = use bot.model (no elevation)
MODEL_ELEVATION_THRESHOLD: float = 0.5
MODEL_ELEVATION_LOG_ENABLED: bool = True     # Phase 2
```

Bot YAML values override env defaults. If `model_elevation.enabled` is false (or not set), the classifier is skipped entirely and the bot's `model` field is used as-is — zero overhead for bots that don't opt in.

---

## 2. Phase 1 — Rule-Based Classifier

### 2.1 Signal Inventory

Each signal is a pure function: `(messages, bot, iteration, user_message) → float` in range [0.0, 1.0]. The final score is a weighted sum, clamped to [0.0, 1.0].

| Signal ID | Weight | What it measures | Elevate when… | Rationale |
|-----------|--------|-----------------|---------------|-----------|
| `message_length` | 0.10 | Character count of the latest user message | > 500 chars = 0.5, > 1500 chars = 1.0 (linear interpolation) | Long messages usually contain complex requests, multi-part questions, or pasted content |
| `code_content` | 0.20 | Presence of code fences, indented blocks, or technical syntax (regex patterns for common languages) | Any code block = 0.7, multiple blocks = 1.0 | Code understanding/generation is where model capability matters most |
| `keyword_elevate` | 0.20 | Keywords in user message: "explain", "debug", "design", "plan", "analyze", "compare", "refactor", "why", "how does", "architecture" | Any match = 0.8, 2+ matches = 1.0 | These words signal reasoning-heavy tasks |
| `keyword_simple` | -0.20 | Keywords: "what time", "remind me", "turn on", "turn off", "set", "play", "stop", "thanks", "ok", "yes", "no" | Any match = 0.8, message < 50 chars + match = 1.0 | Short commands / acknowledgments don't need a big model |
| `tool_complexity` | 0.15 | Tools called in the current turn so far (look at assistant messages with `tool_calls`) | `delegate_to_harness`, `delegate_to_exec`, `delegate_to_agent` = 1.0; `web_search` + `browse_page` = 0.7; `get_time`, `toggle_tts` = 0.0 | Delegation and web research are multi-step reasoning tasks |
| `conversation_depth` | 0.10 | Number of tool calls already executed in context (count `role: tool` messages) | > 5 = 0.5, > 10 = 0.8, > 15 = 1.0 | Deep conversations with many tool calls indicate complex multi-step work |
| `iteration_depth` | 0.10 | Current iteration index within `run_agent_tool_loop` | iteration >= 3 = 0.5, >= 5 = 0.8, >= 8 = 1.0 | Later iterations in a tool loop mean the task was harder than expected |
| `prior_errors` | 0.15 | Count of error/failure indicators in recent tool results ("error", "failed", "exception", "traceback") | 1 error = 0.5, 2+ = 0.9 | Errors mid-loop suggest the base model is struggling; escalate |

### 2.2 Scoring Formula

```python
raw_score = sum(signal.weight * signal.evaluate(ctx) for signal in SIGNALS)
score = max(0.0, min(1.0, raw_score))

if score >= threshold:
    return ElevationResult(model=top_model, tier="top", was_elevated=True, ...)
else:
    return ElevationResult(model=base_model, tier="base", was_elevated=False, ...)
```

**Confidence** is derived from distance to the threshold: `confidence = abs(score - threshold) / max(threshold, 1 - threshold)`. Scores near the threshold have low confidence (useful for Phase 3 analysis).

### 2.3 Implementation Notes

- All signals are implemented as a list of `Signal` dataclasses with `id`, `weight`, `evaluate` callable.
- Default weights live in `ELEVATION_DEFAULT_WEIGHTS: dict[str, float]` in `elevation.py`.
- Bot YAML `weights` dict merges over defaults (missing keys keep default).
- The `iteration_depth` and `prior_errors` signals mean the classifier can elevate mid-loop (e.g., iteration 0 uses Haiku, iteration 4 escalates to Sonnet). This is intentional: each iteration is a fresh pre-turn decision.
- `keyword_simple` has negative weight — it actively suppresses elevation for trivial messages.

### 2.4 File Layout

```
app/agent/elevation.py          # ElevationResult, classify_turn(), Signal definitions
tests/unit/test_elevation.py    # Unit tests for each signal + scoring
```

No DB changes, no migrations, no new dependencies. Pure Python logic.

---

## 3. Phase 2 — Elevation Logging

### 3.1 What to Log

Every call to `classify_turn()` produces a log record, regardless of whether elevation occurred.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `turn_id` | UUID | Correlation ID from the agent loop (maps to `correlation_id`) |
| `timestamp` | datetime | When the decision was made |
| `channel_id` | UUID (nullable) | Channel context |
| `bot_id` | str | Which bot |
| `session_id` | UUID (nullable) | Session context |
| `iteration` | int | Loop iteration index |
| `model_chosen` | str | The model actually used |
| `base_model` | str | What would have been used without elevation |
| `was_elevated` | bool | Whether elevation occurred |
| `tier` | str | "base" / "mid" / "top" |
| `classifier_score` | float | Raw score |
| `confidence` | float | Distance-from-threshold confidence |
| `elevation_reason` | str | Human-readable rule summary |
| `rules_fired` | JSONB | `["code_content", "keyword_elevate"]` |
| `signal_scores` | JSONB | `{"code_content": 0.7, "keyword_elevate": 0.8, ...}` — full breakdown |
| `turn_outcome` | str (nullable) | Backfilled after the turn: "success" / "error" / "max_iterations" |
| `tool_calls_made` | int (nullable) | Backfilled: how many tool calls this iteration produced |
| `tokens_used` | int (nullable) | Backfilled: total tokens from `response.usage` |
| `latency_ms` | int (nullable) | Backfilled: wall-clock time of the `_llm_call()` |

### 3.2 Storage

**Primary: DB table `model_elevation_log`** — new Alembic migration.

```sql
CREATE TABLE model_elevation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel_id UUID REFERENCES channels(id) ON DELETE SET NULL,
    bot_id VARCHAR NOT NULL,
    session_id UUID,
    iteration INTEGER NOT NULL DEFAULT 0,
    model_chosen VARCHAR NOT NULL,
    base_model VARCHAR NOT NULL,
    was_elevated BOOLEAN NOT NULL DEFAULT FALSE,
    tier VARCHAR NOT NULL DEFAULT 'base',
    classifier_score FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    elevation_reason TEXT,
    rules_fired JSONB DEFAULT '[]',
    signal_scores JSONB DEFAULT '{}',
    turn_outcome VARCHAR,
    tool_calls_made INTEGER,
    tokens_used INTEGER,
    latency_ms INTEGER
);

CREATE INDEX ix_elevation_log_bot_ts ON model_elevation_log (bot_id, timestamp DESC);
CREATE INDEX ix_elevation_log_turn ON model_elevation_log (turn_id);
CREATE INDEX ix_elevation_log_elevated ON model_elevation_log (was_elevated, timestamp DESC);
```

**Secondary (optional): JSONL file at `data/elevation_log.jsonl`** — append-only, one JSON object per line. Useful for quick local analysis without DB queries. Enabled via `MODEL_ELEVATION_LOG_JSONL: bool = False`. Written async (fire-and-forget `asyncio.create_task`), same pattern as `_record_trace_event`.

### 3.3 Backfill Pattern

The elevation decision is logged *before* `_llm_call()`. Outcome fields (`turn_outcome`, `tool_calls_made`, `tokens_used`, `latency_ms`) are backfilled *after* `_llm_call()` returns. This keeps the hot path simple:

```python
# In run_agent_tool_loop, per iteration:
elevation = classify_turn(messages, bot, iteration, user_message)
log_id = await log_elevation(elevation, ...)   # writes pre-turn fields

t0 = time.monotonic()
response = await _llm_call(elevation.model, ...)
latency_ms = int((time.monotonic() - t0) * 1000)

# Backfill outcome
await backfill_elevation_log(log_id, response, latency_ms)
```

Both `log_elevation` and `backfill_elevation_log` use `asyncio.create_task` — non-blocking, fire-and-forget. Failures are logged but never block the agent loop.

### 3.4 File Layout

```
app/agent/elevation.py           # add log_elevation(), backfill_elevation_log()
app/db/models.py                 # add ModelElevationLog ORM model
migrations/versions/XXX_model_elevation_log.py  # Alembic migration
```

---

## 4. Phase 3 — Heartbeat Analysis

### 4.1 Integration Point

The heartbeat worker (`app/services/heartbeat.py`) already runs on a schedule. Add an `elevation_analysis` task that runs on a longer cadence (e.g., every 6 hours or daily). This can be a new async function called from `heartbeat_worker` or a separate cron-style task.

### 4.2 Metrics to Compute

Query `model_elevation_log` for the analysis window (default: last 24 hours).

| Metric | Query | Purpose |
|--------|-------|---------|
| **Elevation rate** | `COUNT(was_elevated=true) / COUNT(*)` per bot | Are we elevating too much (>40%) or too little (<5%)? |
| **Rule frequency** | Unnest `rules_fired`, count by rule ID | Which signals drive most elevations? |
| **Outcome correlation** | Compare `was_elevated` vs `turn_outcome` | Do elevated turns actually succeed more often? |
| **Complexity proxy** | Avg `tool_calls_made` for elevated vs. non-elevated | Are elevated turns genuinely more complex? |
| **Token savings** | Sum `tokens_used` where `was_elevated=false`, estimate cost delta | What's the actual savings? |
| **Low-confidence decisions** | Count where `confidence < 0.2` | How many decisions are borderline? |
| **Latency impact** | Avg `latency_ms` by tier | Is the base model actually faster? |

### 4.3 Analysis Output

The heartbeat analysis writes a summary to:
1. **A knowledge chunk** (if the bot has `knowledge.enabled`) — so the bot itself can reference its elevation stats when asked.
2. **Logs** (INFO level) — for operator visibility.
3. **Optionally: a Slack/channel message** — if a heartbeat channel is configured and elevation rate is abnormal.

### 4.4 Adaptive Tuning (Stretch)

The analysis can output **suggested weight adjustments** based on patterns:
- If a rule fires frequently but elevated turns don't show higher complexity → suggest reducing its weight.
- If non-elevated turns frequently error → suggest lowering the threshold.
- These suggestions are logged, NOT auto-applied. Operator reviews and updates bot YAML.

Future: auto-apply suggestions with a confidence gate and a "dry run" mode that logs what *would* change.

---

## 5. Phase 4 — Local Model Tier

### 5.1 Three-Tier Architecture

| Tier | Model | Use case | Cost |
|------|-------|----------|------|
| **base** | Ollama on Mac mini (e.g., `ollama/llama-3.1-8b`) | Simple queries, acknowledgments, smart-home commands | Free (local compute) |
| **mid** | Claude Haiku via LiteLLM | Moderate complexity: tool use, short code, summaries | Low |
| **top** | Claude Sonnet/Opus via LiteLLM | Complex reasoning, debugging, planning, code generation | High |

### 5.2 Classifier Changes

The scoring formula gains a second threshold:

```python
if score >= top_threshold:      # default 0.6
    tier = "top"
elif score >= mid_threshold:    # default 0.3
    tier = "mid"
else:
    tier = "base"
```

Bot YAML adds `mid_model` and `mid_threshold` fields (already shown in §1.4).

### 5.3 Availability / Latency Awareness

Local models can be slow or unavailable. The classifier needs a fast health check:

```python
# app/agent/elevation.py

async def check_local_model_health(base_url: str, timeout: float = 1.0) -> bool:
    """Ping the local Ollama/LiteLLM endpoint. Returns False if unreachable or slow."""
    ...
```

**Fallback behavior**: If the local model is down, promote base → mid automatically. If mid is also down, use top. This is separate from `LLM_FALLBACK_MODEL` (which handles failures *during* a call); this is a pre-turn availability check.

**Caching**: Health check result is cached for 60 seconds (stale-while-revalidate pattern). The check is async but fast (1s timeout on a simple GET/HEAD).

### 5.4 Config Additions

```python
# app/config.py
MODEL_ELEVATION_LOCAL_BASE_URL: str = ""       # e.g., "http://mac-mini:11434/v1"
MODEL_ELEVATION_LOCAL_HEALTH_CACHE_TTL: int = 60
MODEL_ELEVATION_MID_MODEL: str = ""
MODEL_ELEVATION_MID_THRESHOLD: float = 0.3
```

### 5.5 LiteLLM Integration

Ollama models are already supported by LiteLLM with the `ollama/` prefix. No new client code needed — just configure the model name in bot YAML. The only new piece is the health check, since LiteLLM's retry logic handles call-time failures but doesn't help with pre-turn routing.

---

## 6. Implementation Order

### Phase 1 — Rule-Based Classifier
**Effort: ~1 day. No infra changes.**

| Step | Task | Details |
|------|------|---------|
| 1a | Create `app/agent/elevation.py` | `Signal` dataclass, 8 signal implementations, `classify_turn()`, `ElevationResult` |
| 1b | Add config fields | `MODEL_ELEVATION_*` in `app/config.py`, `model_elevation` block in `BotConfig` |
| 1c | Wire into loop | ~10 lines in `run_agent_tool_loop()`: call classifier, use returned model |
| 1d | Unit tests | `tests/unit/test_elevation.py` — test each signal in isolation, test scoring, test threshold logic |
| 1e | Bot YAML opt-in | Add `model_elevation` section to one bot's YAML for testing |

### Phase 2 — Elevation Logging
**Effort: ~0.5 day. Requires Alembic migration.**

| Step | Task | Details |
|------|------|---------|
| 2a | ORM model | `ModelElevationLog` in `app/db/models.py` |
| 2b | Migration | Alembic auto-generate for `model_elevation_log` table + indexes |
| 2c | Log + backfill functions | `log_elevation()`, `backfill_elevation_log()` in `elevation.py` |
| 2d | Wire into loop | Add log call before `_llm_call()`, backfill call after |
| 2e | Optional JSONL writer | Append to `data/elevation_log.jsonl` if `MODEL_ELEVATION_LOG_JSONL=true` |

### Phase 3 — Heartbeat Analysis
**Effort: ~0.5 day. No infra changes.**

| Step | Task | Details |
|------|------|---------|
| 3a | Analysis function | `analyze_elevation_logs()` in `app/services/elevation_analysis.py` |
| 3b | Heartbeat integration | Call from heartbeat worker on configurable cadence |
| 3c | Admin dashboard | Add elevation stats panel to `/admin` (elevation rate chart, rule frequency, savings estimate) |

### Phase 4 — Local Model Tier
**Effort: ~1 day. Requires local Ollama setup.**

| Step | Task | Details |
|------|------|---------|
| 4a | Health check | `check_local_model_health()` with TTL cache |
| 4b | Three-tier scoring | Add `mid_threshold` logic to `classify_turn()` |
| 4c | Config + bot YAML | `mid_model`, `mid_threshold`, local model URL settings |
| 4d | Integration test | Test with actual Ollama instance on local network |

**Total estimated effort: ~3 days across all phases.**

---

## 7. Open Questions

1. **Correctness evaluation**: How do we know if an elevation decision was right? Proxy metrics (errors, tool call count, token usage) are imperfect. Consider: periodically re-run a sample of non-elevated turns through the top model and compare outputs (expensive but ground-truth).

2. **Per-iteration vs. per-turn**: The current design re-evaluates every iteration. Should we lock the model for the entire turn (all iterations) after the first decision? Pro: simpler mental model. Con: loses the ability to escalate mid-loop when errors accumulate.

3. **Compaction turns**: Compaction already uses `COMPACTION_MODEL` (typically a cheap model). Should elevation apply to compaction? Probably not — compaction is summarization, not reasoning. Explicitly skip elevation when `compaction=True`.

4. **Fallback model interaction**: If the elevated model fails and falls back to `LLM_FALLBACK_MODEL`, should the elevation log record the fallback? Yes — add a `fallback_used` boolean field to the log.

5. **Multi-modal turns**: Native audio turns (`audio_input: native`) may need different signal weights. Consider an `audio_content` signal in future.

6. **Cost tracking**: Elevation logging captures `tokens_used` but not dollar cost. Cost depends on provider pricing which we don't track. Consider adding a `cost_estimate` field that uses a configurable per-model rate.

---

## 8. Integration Points Summary

| File | Change | Phase |
|------|--------|-------|
| `app/agent/elevation.py` | **New file** — classifier, signals, logging | 1, 2 |
| `app/agent/loop.py` | Call `classify_turn()` before `_llm_call()`, log + backfill | 1, 2 |
| `app/config.py` | `MODEL_ELEVATION_*` settings | 1 |
| `app/agent/bots.py` | `ModelElevationConfig` dataclass, parse from YAML | 1 |
| `app/db/models.py` | `ModelElevationLog` ORM model | 2 |
| `migrations/versions/` | New migration for `model_elevation_log` | 2 |
| `app/services/elevation_analysis.py` | **New file** — heartbeat analysis queries | 3 |
| `app/services/heartbeat.py` | Call elevation analysis on cadence | 3 |
| `tests/unit/test_elevation.py` | **New file** — signal + classifier tests | 1 |
