---
tags: [agent-server, track, providers, llm, reasoning]
status: active
created: 2026-04-23
updated: 2026-04-24 (bot editor model-save 422 fix)
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

## References

- Canonical guide: `agent-server/docs/guides/providers.md` (Phase 1 ships this).
- Plan file (approved): `~/.claude/plans/id-like-a-strong-polymorphic-hippo.md`.
- Related: [[Track - Code Quality]] (god-function split of `_prepare_call_params` is sibling work).
- Related: [[Track - Experiments]] (pipeline-layer optimization harness — `/effort` becomes an interesting knob for autoresearch once Phase 2 gates it).
