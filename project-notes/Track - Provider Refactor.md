---
tags: [agent-server, track, providers, llm, reasoning]
status: active
created: 2026-04-23
updated: 2026-04-23 (phase 1 in-flight)
---
# Track — Provider Refactor

## North Star

One canonical LLM provider subsystem: one reasoning knob, one slash-command registry, one place per capability. Reasoning/effort must be wired end-to-end without silent drops, and the prompt-dialect profile system must either earn its third option or drop it.

## Status

| Phase | Summary | Status |
|---|---|---|
| 1 | `/effort` slash command + reasoning plumbing fixes + unified slash registry + canonical providers guide | 🟡 in-flight |
| 2 | `ProviderModel.supports_reasoning` capability column + UI gating | 🔲 planned |
| 3 | Adapter dedup (`provider_translation.py`) + silent-failure cleanup + hardcoded model-list removal + real `test_connection` | 🔲 planned |
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
