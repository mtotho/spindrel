---
tags: [agent-server, track, providers, llm, reasoning]
status: active
created: 2026-04-23
updated: 2026-04-24 (Phase 5 + Phase 6 shipped — capability metadata, extra_headers, Retry-After, catalog refresh, Provider Health panel)
---
# Track — Provider Refactor

## North Star

One canonical LLM provider subsystem: one reasoning knob, one slash-command registry, one place per capability. Reasoning/effort must be wired end-to-end without silent drops, and the prompt-dialect profile system must either earn its third option or drop it.

## Status

| Phase | Summary | Status |
|---|---|---|
| 1 | `/effort` slash command + reasoning plumbing fixes + unified slash registry + canonical providers guide | ✅ shipped 2026-04-23 |
| 2 | `ProviderModel.supports_reasoning` capability column + UI gating + `/effort` validator | ✅ shipped 2026-04-23 |
| 3 | Adapter dedup (`provider_translation.py`) + silent-failure cleanup + hardcoded model-list removal + real `test_connection` + provider-model admin/catalog cleanup | ◐ in progress |
| 4 | Prompt dialect `structured` decision (implement or drop) + tool-call ID truncation docs + message-folding dedup | 🔲 planned |
| 5 | Capability metadata + foot-guns: `context_window` / `max_output_tokens` split, `supports_prompt_caching` / `supports_structured_output` / `cached_input_cost_per_1m`, per-provider `extra_headers` JSON, per-model `extra_body` JSON, Retry-After honoring | ✅ shipped 2026-04-24 |
| 6 | Catalog auto-refresh + Provider Health panel: daily background `list_models_enriched()` refresh, `POST /providers/{id}/refresh-now`, `GET /usage/provider-health` aggregator (p50/p95 latency, cache-hit, cooldown), Usage → Providers tab | ✅ shipped 2026-04-24 |

## Phase 1 — Scope

**Ships:**

- `/effort <off|low|medium|high>` slash command with session ContextVar + channel persistence.
- Unified slash-command registry (backend is the source of truth; frontend bootstraps from it with a typed-literal fallback). `clear`/`scratch` become `local_only: True` entries so both registries agree.
- `translate_effort(model, effort)` per-family translator collapses the twin `reasoning_effort` select + `thinking_budget` slider into one UI knob. Old `thinking_budget` stays under an "Advanced" disclosure for power users.
- Fix: `reasoning_effort` silent-drop in the OpenAI Responses adapter (`app/services/openai_responses_adapter.py`) — Codex / gpt-5-* / o4-mini bots never actually received the knob before.
- Resolution order inside `run_stream` → ContextVar > `channel.config.effort_override` > `bot.model_params`.
- New canonical doc `agent-server/docs/guides/providers.md` in the mkdocs nav.
- Four unit tests: `test_slash_command_effort`, `test_effort_translation`, `test_openai_responses_reasoning_effort` (smoking-gun regression), `test_effort_resolution_order`.

**Explicitly out of scope for Phase 1:**

- No migration of existing `bot.model_params.thinking_budget` values; additive only.
- No change to `prompt_style` enum (Phase 4 owns the `structured` decision).
- No new `ProviderModel` column (Phase 2 owns `supports_reasoning`).

## Phase 2 — Scope (shipped)

**Shipped 2026-04-23:**

- Migration 242 adds `provider_models.supports_reasoning boolean not null default false` with a one-time UPDATE backfill for known reasoning families (Claude Opus/Sonnet/Haiku-4.5, gpt-5-*, o-series, codex-*, Gemini 2.5-*, DeepSeek Reasoner/R1, Grok 3).
- `_reasoning_capable_models: set[str]` cache populated in `load_providers()` plus public accessors `supports_reasoning(model)` and `supports_reasoning_set()`.
- `filter_model_params` consults the DB flag as a second gate — reasoning params get stripped for models the admin hasn't marked reasoning-capable, even within a reasoning-family.
- `/effort <high|medium|low>` rejects with 400 on channels whose primary bot runs a non-reasoning model (explicit error toast instead of silent drop). `/effort off` always succeeds.
- `BotEditorDataOut.reasoning_capable_models` whitelist exposed to frontend; `ModelParamsSection.tsx` greys out the Reasoning effort / reasoning_effort / thinking_budget controls with a tooltip when the current model is not reasoning-capable.
- Admin → Providers → Models: new **Reasoning** checkbox on add + edit + badge on the model row.
- Bot editor model dropdown (`LlmModelDropdownContent`) shows a `reasoning` chip next to each reasoning-capable model — so users picking a model see which ones support `/effort` before selection. `/admin/models` endpoint now returns `supports_reasoning` per model, sourced from the `_reasoning_capable_models` cache.
- `docs/guides/providers.md` extended with a ProviderModel capability columns table and a "marking a new model as reasoning-capable" workflow.
- Tests (all real-DB, no mocks): `test_supports_reasoning_cache.py`, `test_filter_model_params_reasoning_gate.py`, `test_slash_command_effort_capability_gate.py`, `test_editor_data_reasoning_capable.py` — 15 new tests green.

**Out of scope for Phase 2:**

- `/effort` validation against dispatch side-bots (only `Channel.bot_id` is checked).
- Auto-setting `supports_reasoning=True` at model create based on model-id heuristics (admin toggles the checkbox at create time).
- Per-family runtime fallback heuristic — DB flag is the sole runtime authority.

## Phase 3 — Provider-model admin/catalog follow-up (partial, 2026-04-23)

**Shipped in this follow-up:**

- Added `PUT /api/v1/admin/providers/{provider_id}/models/{model_pk}` so existing provider-model rows can be edited in place instead of delete/recreate.
- Provider-model create, update, and delete now always call `load_providers()` after commit so prompt-style / no-system / tools / vision / reasoning caches refresh even when only a "default-looking" field changes.
- `list_models_for_provider()` now merges DB-backed `provider_models` rows with live driver catalogs instead of treating DB rows as a pure fallback.
- Result: a manually added ChatGPT subscription row like `gpt-5.5` now shows up in `/api/v1/admin/models` and downstream model dropdowns even if the driver still reports `gpt-5.4` / `gpt-5.4-mini`.
- Admin → Providers → Models now shows prompt style on existing rows consistently, adds inline edit/save/cancel controls, and exposes the current row flags (`no_system_messages`, tools, vision, reasoning, prompt_style`) during edit.
- Added integration coverage for provider-model update semantics and for the DB/live catalog union behavior.
- 2026-04-24 follow-up: Bot editor existing-bot saves now send a minimal changed-field payload instead of round-tripping the whole `editorData.bot` object. This prevents unrelated legacy `api_permissions` validation from returning 422 when the user only changes model/provider, and the save banner now exposes FastAPI `detail` for future validation failures.
- 2026-04-24 doc sync: `docs/guides/providers.md` picked up a **Managing models on a provider** subsection (driver-catalog ∪ DB rows, inline edit/save/cancel over the PUT endpoint, per-row flag table) and the Known-limits fallback-list note now mentions the DB/live union as today's mitigation. Confirmed: gpt-subscription `reasoning.effort` flows end-to-end in production (Phase 1 silent-drop fix verified).
- 2026-04-24 prompt-style fix: dialect lookup is now provider+model aware, and effective model/provider overrides are passed into system-prompt rendering, context assembly, and previews so duplicate model IDs can resolve different prompt styles per provider.

**Still belongs to Phase 3:**

- Adapter dedup (`provider_translation.py`), silent `try/except: return []` cleanup, and real `test_connection()` work remain open.
- This follow-up intentionally did **not** expand the hardcoded ChatGPT OAuth allowlist just to surface manual rows; the DB/live union is the durable fix.

## Audit Findings — All Severities

Authoritative severity list with file:line cites and phase ownership lives in the approved plan at `~/.claude/plans/id-like-a-strong-polymorphic-hippo.md`. Summary:

**Critical (silent bugs):**

1. Codex `reasoning_effort` dropped at adapter — **Phase 1**.
2. `anthropic-subscription` provider type points at plain `AnthropicDriver` — **Phase 3**.
3. `resolveSlashCommand` rejects arg-bearing input — **Phase 1**.

**High (design smells):**

4. Two slash-command registries diverged — **Phase 1**.
5. `thinking_budget` → `reasoning_effort` bucketed heuristic; two UI knobs for one capability — **Phase 1**.
6. No `ProviderModel.supports_reasoning` flag — **Phase 2**.
7. Tool-translation duplicated across `anthropic_adapter` and `openai_responses_adapter` — **Phase 3**.
8. `structured` prompt_style is dead code aliased to markdown — **Phase 4**.

**Medium (hygiene):**

9. Hardcoded model lists decay (`anthropic_driver`, `openai_subscription_driver`) — **Phase 3**.
10. `test_connection()` no-ops on Anthropic + OpenAI-subscription — **Phase 3**.
11. `try/except: return []` swallow pattern on list_models — **Phase 3**.
12. Codex tool-call ID silent truncation — **Phase 4** (docs only).

**Low (note-only):**

13. Codex OAuth client_id is a well-known public constant — docs.
14. `_fold_system_messages` duplicates Anthropic adapter's `_merge_consecutive_roles` — Phase 4.
15. Driver singletons require implicit thread safety.
16. Decrypted API keys live in `_registry` for uptime — acceptable for self-hosted.

## Key Invariants (locked)

- The slash-command argument contract is one positional token enum today; no multi-token grammar until a real need shows up.
- `/effort` is per-channel, not per-bot — bot-level default lives on `bot.model_params`.
- `translate_effort` is the **only** place a family→request-shape translation for reasoning happens. Phase 1's `_prepare_call_params` must not re-branch.
- Channel config writes go through `api_v1_channels.py` helpers, never raw ORM mutation.
- Additive rollout: the `effort` enum lives alongside `thinking_budget`; one commit doesn't need a flag-off compat shim (per `feedback_one_commit_no_legacy`).

## Phase 5 — Capability metadata + foot-guns (shipped 2026-04-24)

**Shipped:**

- Migration 245 adds six new `provider_models` columns + backfills known families:
    - `context_window` (int, input cap) + `max_output_tokens` (int, output cap) — unambiguous context-budget math. `max_output_tokens` backfilled from the legacy `max_tokens` column.
    - `supports_prompt_caching` (bool, backfilled true for Claude families / GPT-4o/5/Codex / Gemini 2.x) — replaces fragile `"claude" in model.lower()` sniff in `app/agent/prompt_cache.py`.
    - `supports_structured_output` (bool, backfilled true for OpenAI + Gemini families) — forward-looking gate for `response_format={"type":"json_schema"}`.
    - `cached_input_cost_per_1m` (text, backfilled `$0.30`/`$1.50`/`$0.08` for Claude Sonnet/Opus/Haiku) — admin-set per-model cached-read rate. Stops `/admin/usage` overstating Anthropic cost ~10× while cache_control is active.
    - `extra_body` (jsonb) — per-model arbitrary JSON merged into the SDK `extra_body`. Primary use: Ollama's `options.num_ctx` foot-gun (default 2048 truncation regardless of Modelfile context).
- Per-provider `extra_headers` JSON sub-key on `ProviderConfig.config` (no migration) + KV editor on the provider edit page. Flows through `AsyncOpenAI(default_headers=...)`, `AnthropicOpenAIAdapter.default_headers`, and `OpenAIResponsesAdapter._extra_headers`. Unblocks OpenRouter analytics headers, OpenAI `OpenAI-Organization` / `OpenAI-Project`, and `anthropic-beta` opt-ins.
- `_classify_error` in `app/agent/llm.py` now parses upstream `Retry-After` (seconds-int or HTTP-date), clamps to `[1s, 120s]`, uses it as `base_wait`. Falls back to the existing exp-jitter when the header is absent or unparseable. `RateLimitError` classification propagates the parsed value via a new `_ErrorClassification.retry_after_seconds` field.
- `_deep_merge_dicts` helper + extra_body composition in `_prepare_call_params`: `ProviderModel.extra_body` (baseline) < caller-supplied `model_params.extra_body` < `translate_effort`'s `extra_body` (e.g. Gemini `thinking_config`). Caller value is pulled from the raw `model_params` dict since `filter_model_params` strips `extra_body` (it's not in any family's supported-param set).
- `app/agent/prompt_cache.py::should_apply_cache_control` now consults `providers.supports_prompt_caching(...)` (DB cache) instead of string-sniffing the model ID. Provider-type fallback retained for legacy bots without a `provider_models` row.
- `/admin/usage` cost math updated: `_lookup_pricing` now returns `(input, output, cached_input)` triples, `_compute_cost` uses the explicit `cached_input_rate_str` when present and falls back to the discount heuristic otherwise. Pricing map + cache TraceEvent reads unchanged.
- Admin router + UI: `POST/PUT /providers/{id}/models` accept all new columns; `POST/PUT /providers/{id}` accepts `extra_headers` (validates dict-of-strings, rejects control chars). Provider edit page gains a Custom Headers KV editor (`ProviderExtraHeadersSection.tsx`, Tailwind). Per-model edit form gains rows for `context_window`, `max_output_tokens`, `cached_input_cost_per_1m`, `supports_prompt_caching`, `supports_structured_output`, `extra_body` (JSON textarea with parse-error UX).
- 2026-04-24 follow-up: `ProviderExtraHeadersSection.tsx` no longer mirrors identical header maps back into parent state on mount. The section now compares content before syncing local rows or emitting `onChange`, and the provider detail screen moved its one-time provider hydration out of render and into a `useEffect`. Regression pinned by `providerExtraHeadersState.test.ts`.

Tests (31 new, all passing in Dockerfile.test on Python 3.12):

- `tests/unit/test_provider_capability_completeness.py` — cache population from DB, prompt-cache module no longer sniffs string, extra_body / extra_headers / cached-cost accessors + deep-copy contract.
- `tests/unit/test_extra_body_merge.py` — deep-merge helper + three-layer merge in `_prepare_call_params` (provider baseline < caller < effort).
- `tests/unit/test_retry_after_honored.py` — `_parse_retry_after` handles seconds, float, HTTP-date (past/future/malformed/missing); `_classify_error` propagation.
- `tests/unit/test_cached_pricing_math.py` — explicit cached-rate split, fallback to discount, explicit rate wins, uncached-floor clamp.

## Phase 6 — Catalog auto-refresh + Provider Health panel (shipped 2026-04-24)

**Shipped:**

- `app/services/provider_catalog_refresh.py` — `refresh_one_provider(provider_id)` calls `driver.list_models_enriched()`, upserts `provider_models`, records `last_refresh_ts` / `last_refresh_error` on `ProviderConfig.config`. `refresh_all_providers()` sequences enabled providers. `start_refresh_task()` runs a daily `asyncio.create_task` loop, wired into `app/main.py` startup. Error clears on subsequent success.
- `POST /api/v1/admin/providers/{id}/refresh-now` endpoint for manual force-refresh. Successful `Test Connection` also triggers a background refresh via `asyncio.create_task(refresh_one_provider(id))` so one click picks up freshly-shipped models without a second.
- Usage → Providers tab (`GET /api/v1/admin/usage/provider-health?hours=N`) aggregates `token_usage` events over a window (1–168h), returns per-(provider, model): sample count, p50/p95 latency, cache-hit rate, last-call ts, and circuit-breaker cooldown expiry (joined from `app.agent.llm.get_active_cooldowns()`). `_percentile` helper does linear-interp; no numpy dep. New `ProviderHealthTab.tsx` Tailwind surface renders the table with cooldown = red / ok = green status column.
- Provider edit page surfaces `last_refresh_ts` ("Last auto-refresh: Xm ago") and `last_refresh_error` on the existing Sync Models section via `SyncModelsSection` props.

Tests (10 new, all passing in Dockerfile.test):

- `tests/unit/test_provider_catalog_refresh.py` — happy-path upsert, `last_refresh_ts` write, error recording + clearing, disabled-provider skip.
- `tests/unit/test_provider_health_endpoint.py` — `_percentile` math pins (empty/single/sorted/unsorted/p50/p95-interp).

**Not dropped:** the hardcoded Anthropic + OpenAI-subscription fallback model lists. Anthropic has no public `/models` endpoint so the list is THE source; OpenAI-subscription's live `/models` can fail before the user completes OAuth, so the fallback keeps the add-provider dropdown non-empty. Phase 3's "hardcoded list removal" reframed as "prefer live, keep fallback for zero-config case."

## Parking lot / future investigations

- **Response-side safety (moderation / PII redaction / jailbreak detection)** — user explicitly parked 2026-04-24: "Add a note to the track to investigate this later." Options when revisited: OpenAI `/moderations` pre- or post-call (adds latency + external dep), PII redaction via a per-tenant detector, jailbreak detection (heuristic, noisy). Single-user self-hosted philosophy currently says no; revisit if Spindrel ever serves public-facing bots.
- **Native Azure / Bedrock / Gemini drivers** — not in user's daily stack. The openai-compatible escape hatch covers them today (with degraded UX: no live pricing, no native headers). Build only if the user adopts them.
- **Per-user quotas / audit log / OIDC** — explicitly out of scope ("personal-first polish, not platform-grade"). Aligned with the Roadmap "Frozen / multi-tenancy" item.
- **Model aliases / `modelSpecs`-style presets** — overlaps with `Bot` (each bot is already a (provider, model, params, prompt) bundle). Not a real gap.
- **`supports_parallel_tool_calls`, `training_cutoff`, `supports_audio` columns** — low ROI; revisit if a downstream consumer surfaces.

## References

- Canonical guide: `agent-server/docs/guides/providers.md` — extended in Phase 5 (capability columns, extra_headers, extra_body / Ollama `num_ctx`) and Phase 6 (daily refresh, Provider Health panel).
- Plan file (Phase 1–2, approved): `~/.claude/plans/id-like-a-strong-polymorphic-hippo.md`.
- Plan file (Phase 5–6, approved): `~/.claude/plans/do-we-have-ticklish-phoenix.md`.
- Related: [[Track - Code Quality]] (god-function split of `_prepare_call_params` is sibling work).
- Related: [[Track - Experiments]] (pipeline-layer optimization harness — `/effort` becomes an interesting knob for autoresearch once Phase 2 gates it).
