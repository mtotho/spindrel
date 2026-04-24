---
tags: [agent-server, track, integrations, docs, contract]
status: active
created: 2026-04-23
updated: 2026-04-23
---
# Track — Integration Contract + Canonical Guide

## North Star

Establish `docs/guides/integrations.md` as the north-star contract for integrations — the same "this page wins" authority `widget-system.md` has for widgets. Use the new contract to retire the dead `chat_hud` surface, standardize the `binding` picker, fix three hard-coded `integration_id == "x"` sites in `app/`, wire every session to a central canonical-guides index, and add a CI drift test so the surface map stays honest.

## Plan file

Planning: `~/.claude/plans/so-currently-our-wiggly-teapot.md` (approved 2026-04-23)

## Status

| Phase | Title | Status | Session | Commit |
|---|---|---|---|---|
| 1 | Canonical integration guide (`docs/guides/integrations.md`) | ✅ shipped | 2026-04-23 | (uncommitted) |
| 2 | Central canonical-guides index + pointer wiring | ✅ shipped | 2026-04-23 | (uncommitted) |
| 3 | Retire `chat_hud` / `chat_hud_presets` — teardown only | ✅ shipped | 2026-04-23 | (uncommitted) |
| 3.5 | Replacement native widgets for bb-status / bb-echo-diag / feed-status | not started | — | — |
| 4 | Standardize `binding.suggestions_endpoint` shape (schema + 3 endpoints + drift test) | ✅ shipped | 2026-04-23 | (uncommitted) |
| 4.5 | Promote binding picker in the new-channel wizard | not started | — | — |
| 5 | Fix 3 boundary violations via hook registry (task-engine one deferred) | not started | — | — |
| 6 | Drift enforcement — pytest gate + optional PostToolUse reminder | not started | — | — |

**Ordering:** P1 + P2 in parallel → P3, P4, P5 in parallel → P6 last.

## Phase detail (summary)

Full detail lives in the plan file. One-line-per-phase summary:

- **P1** — Create `docs/guides/integrations.md`. Claim authority. 9 sections. Section 3 is the `_KNOWN_KEYS` surface map that drives P6. Banner on `docs/integrations/index.md` defers authority.
- **P2** — Create `docs/guides/index.md` (Guides landing page). Add "Canonical Guides" section to `CLAUDE.md` + Roadmap. Create `reference_canonical_guides.md` memory + link from `MEMORY.md`. Update `AGENTS.md` startup step.
- **P3** — Deleted `chat_hud` surface across backend parser/passthrough, discover_* helpers, channel-detail payload (both public + admin), `/hud/*` router endpoints in `bluebubbles` + `ingestion`, YAML blocks, UI files (`useChatHud.ts`, `hud/*`, `HudPresetPicker.tsx`), render sites in `index.tsx`, UI store HUD state (`hudCollapsedChannels`, `hudExpandedOnMobile`, `toggleHud*`), TS types (`ChatHudWidget`, `ChatHudPreset`, `HudData`, `HudItem`, `HudOnClick`), and the `chat_hud` / `chat_hud_presets` sections of `docs/integrations/index.md`. Tombstone now lives in `docs/guides/integrations.md` under "Removed surface" with replacement pattern. Tests: 52 pass across `test_api_channels`, `test_channel_creation_wizard`, `test_channel_integration_lifecycle`. UI typecheck clean. mkdocs build warns drop from 25 → 24 (all pre-existing). Replacement widgets deferred to P3.5 — the current native widget registry is closed to core/* entries, so adding bluebubbles/ingestion widgets without a new integration-owned mechanism would itself be an `app/` boundary violation (the thing P5 exists to fix).
- **P3.5** — Build the integration-owned native widget registration path, then author bb-status / bb-echo-diag / feed-status against it. Likely lands alongside or after P5's `integration_validators.py` registry — same boundary-break fix, different target surface. Widgets themselves are small once the path exists.
- **P4** — Canonical Pydantic schema at `app/schemas/binding_suggestions.py` + `response_model=list[BindingSuggestion]` on all 3 endpoints (`slack`, `bluebubbles`, `wyoming`) + drift test at `tests/integration/test_binding_suggestions_shape.py` (6 passing). **Scope correction:** the plan file prescribed a renamed envelope shape (`id`/`label`/`hint`/`metadata` inside `BindingSuggestionsResponse` with `items`/`has_more`/`cursor`). That would have forced rewrites of all 3 endpoints plus the UI hook + picker. Reality on the wire was already `list[{client_id, display_name, description, config_values?}]` and the UI consumes that shape directly (`ui/src/api/hooks/useChannels.ts::BindingSuggestion`). We codified reality as the schema rather than forcing an orthogonal rename. Canonical guide § 4 rewritten to match.
- **P4.5** — Surface the binding picker prominently in the new-channel wizard. Today the picker exists (`BindingForm.tsx` + `SuggestionsPicker.tsx` in channel settings) but the new-channel flow doesn't pull it forward. Separate UI slice; the contract work in P4 is done.
- **P5** — `app/services/integration_validators.py` singleton hook registry. Migrate `ephemeral_dispatch.py:168-172` → `chat/_helpers.py:108` → `attachments.py:307`. Defer `tools/local/tasks.py:336` (Task Sub-Sessions active development).
- **P6** — `tests/unit/test_canonical_docs_drift.py` (asserts forward + reverse coverage between `_KNOWN_KEYS` and `docs/guides/integrations.md`). Optional `.claude/hooks/canonical-doc-reminder.sh`.

## Key invariants (emerge from this track)

- `docs/guides/integrations.md` wins against every other integration doc, UI copy, and track note (same model as `widget-system.md`).
- Every `_KNOWN_KEYS` entry must appear in the canonical guide's surface map — enforced by drift test.
- `binding.suggestions_endpoint` always returns `BindingSuggestionsResponse`; schema test gates drift.
- No integration-specific branches in `app/` — integrations register via `integration_validators.py` singleton registry.
- `chat_hud` / `chat_hud_presets` are dead surface. Do not reintroduce; use the widget/dashboard system.

## References

- Plan: `~/.claude/plans/so-currently-our-wiggly-teapot.md`
- `docs/guides/widget-system.md` — the voice/structure template for the new canonical guide
- `docs/integrations/index.md` — the existing authoring walkthrough (will defer authority to the new guide)
- `docs/integrations/design.md` — architectural rationale for the integration system
- [[Integration Depth Playbook]] — platform-growth recipe; cross-referenced from § 5 of the new guide
- [[Track - Integration Delivery]] — sibling track (outbox / bus / renderer abstraction)
- [[Track - Integration DX]] — completed sibling track (YAML migration, SDK expansion, config standardization)
