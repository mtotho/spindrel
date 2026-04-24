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
| 4.5 | Promote binding picker in the new-channel wizard | ✅ shipped | 2026-04-23 | (uncommitted) |
| 5 | Fix 3 boundary violations via hook registry (task-engine one deferred) | ✅ shipped | 2026-04-23 | (uncommitted) |
| 6 | Drift enforcement — pytest gate + optional PostToolUse reminder | ✅ shipped | 2026-04-23 | (uncommitted) |

**Ordering:** P1 + P2 in parallel → P3, P4, P5 in parallel → P6 last.

## Phase detail (summary)

Full detail lives in the plan file. One-line-per-phase summary:

- **P1** — Create `docs/guides/integrations.md`. Claim authority. 9 sections. Section 3 is the `_KNOWN_KEYS` surface map that drives P6. Banner on `docs/integrations/index.md` defers authority.
- **P2** — Create `docs/guides/index.md` (Guides landing page). Add "Canonical Guides" section to `CLAUDE.md` + Roadmap. Create `reference_canonical_guides.md` memory + link from `MEMORY.md`. Update `AGENTS.md` startup step.
- **P3** — Deleted `chat_hud` surface across backend parser/passthrough, discover_* helpers, channel-detail payload (both public + admin), `/hud/*` router endpoints in `bluebubbles` + `ingestion`, YAML blocks, UI files (`useChatHud.ts`, `hud/*`, `HudPresetPicker.tsx`), render sites in `index.tsx`, UI store HUD state (`hudCollapsedChannels`, `hudExpandedOnMobile`, `toggleHud*`), TS types (`ChatHudWidget`, `ChatHudPreset`, `HudData`, `HudItem`, `HudOnClick`), and the `chat_hud` / `chat_hud_presets` sections of `docs/integrations/index.md`. Tombstone now lives in `docs/guides/integrations.md` under "Removed surface" with replacement pattern. Tests: 52 pass across `test_api_channels`, `test_channel_creation_wizard`, `test_channel_integration_lifecycle`. UI typecheck clean. mkdocs build warns drop from 25 → 24 (all pre-existing). Replacement widgets deferred to P3.5 — the current native widget registry is closed to core/* entries, so adding bluebubbles/ingestion widgets without a new integration-owned mechanism would itself be an `app/` boundary violation (the thing P5 exists to fix).
- **P3.5** — Build the integration-owned native widget registration path, then author bb-status / bb-echo-diag / feed-status against it. Likely lands alongside or after P5's `integration_validators.py` registry — same boundary-break fix, different target surface. Widgets themselves are small once the path exists.
- **P4** — Canonical Pydantic schema at `app/schemas/binding_suggestions.py` + `response_model=list[BindingSuggestion]` on all 3 endpoints (`slack`, `bluebubbles`, `wyoming`) + drift test at `tests/integration/test_binding_suggestions_shape.py` (6 passing). **Scope correction:** the plan file prescribed a renamed envelope shape (`id`/`label`/`hint`/`metadata` inside `BindingSuggestionsResponse` with `items`/`has_more`/`cursor`). That would have forced rewrites of all 3 endpoints plus the UI hook + picker. Reality on the wire was already `list[{client_id, display_name, description, config_values?}]` and the UI consumes that shape directly (`ui/src/api/hooks/useChannels.ts::BindingSuggestion`). We codified reality as the schema rather than forcing an orthogonal rename. Canonical guide § 4 rewritten to match.
- **P4.5** — New `ui/src/components/channels/BindableIntegrationsList.tsx` reuses the existing `BindingForm` (with `lockType`) + `SuggestionsPicker`. Wizard step 2 now renders two stacked subsections: "Connect External Service" (picker tiles, one per integration with a `binding:` block) and "Activate Integrations" (existing tool/skill toggles). Step indicator + footer now gate on `hasIntegrationStep = hasActivatable || hasBindable`, so any bindable integration promotes step 2 even when there's nothing activatable. Binding tiles expand the shared `BindingForm` inline; user's selection is captured into `pendingBindings` wizard state (client_id, display_name, dispatch_config) and applied after channel creation via sequential `POST /channels/:id/integrations`. Per-binding failures log + continue (the channel is already created, so stranding the user on the wizard over a binding error would be worse than silent recovery in channel settings). UI typecheck clean.
- **P5** — Three integration-specific branches in `app/` were migrated to a registry lookup in `app/agent/hooks.py`. **Scope correction:** the plan prescribed a new singleton at `app/services/integration_validators.py` with a parallel `register()/lookup()` API. Reality: `app/agent/hooks.py::_meta_registry` already *is* the per-integration callable registry (`client_id_prefix`, `user_attribution`, `resolve_display_names`, `resolve_dispatch_config`, `apply_thread_ref`, …). Adding a second registry next to it would have duplicated the infra the plan was asking us to build. Extended `IntegrationMeta` with two optional fields — `claims_user_id` and `attachment_file_id_key` — and added three lookup helpers (`claims_user_id`, `integration_id_from_sender_id`, `integration_id_from_attachment_meta`) next to the existing `get_all_client_id_prefixes`. Each integration registers the new fields inside its own `hooks.py`. Migration sites: `ephemeral_dispatch.py` (deleted the three `integration_id == "…"` branches + the `_claims_user_id` helper); `chat/_helpers.py:108` (replaced `sender_id.startswith("slack:")` with the generic `integration_id_from_sender_id` lookup; the `extra_kwargs` + `resolve_integration_user` path now works for any registered integration); `attachments.py:307` (`_infer_integration_from_metadata` now walks the registry instead of hard-coding `slack_file_id`). Deferred `tools/local/tasks.py:336` per plan (Task Sub-Sessions still in active development). Tests: `test_ephemeral_dispatch.py` fixture now registers minimal `IntegrationMeta`s for slack/discord/bluebubbles; `TestClaimsUserId` rewrote to call the central `claims_user_id()` helper; added `test_unregistered_integration_safe_default` to lock the "unregistered → False, no exception" contract from the plan's verification list. 35/35 tests green across `test_ephemeral_dispatch`, `test_ephemeral_message_kind`, `test_attachments`, `test_binding_suggestions_shape`; adjacent `test_dispatch_resolution*` + `test_dispatch_recording_seam` + `test_chat` + `test_channel_ownership` all green too.
- **P6** — `tests/unit/test_canonical_docs_drift.py` asserts forward + reverse parity between `_KNOWN_KEYS` (in `app/services/integration_manifests.py`) and the surface-map table in `docs/guides/integrations.md`. Two tests, 29/29 key parity, both green in Docker; injected-drift simulation confirmed both directions (forward: fake `_KNOWN_KEYS` entry → test red; reverse: extra table row → test red). Needed one companion change: `Dockerfile.test` now `COPY docs/ docs/` so the docs directory is inside the test image (previously only host-local tooling could see it — CI would have silently skipped the gate). The optional `.claude/hooks/canonical-doc-reminder.sh` PostToolUse hook was scoped out per plan guidance ("pytest is the real gate; hook is belt-and-suspenders — skip if it adds noise"); revisit only if drift slips past the pytest.

## Key invariants (emerge from this track)

- `docs/guides/integrations.md` wins against every other integration doc, UI copy, and track note (same model as `widget-system.md`).
- Every `_KNOWN_KEYS` entry must appear in the canonical guide's surface map — enforced by drift test.
- `binding.suggestions_endpoint` always returns `BindingSuggestionsResponse`; schema test gates drift.
- No integration-specific branches in `app/` — integrations register per-integration callables on `IntegrationMeta` in their own `hooks.py`, and `app/` calls through the lookup helpers in `app/agent/hooks.py` (`claims_user_id`, `integration_id_from_sender_id`, `integration_id_from_attachment_meta`, `get_all_client_id_prefixes`).
- `chat_hud` / `chat_hud_presets` are dead surface. Do not reintroduce; use the widget/dashboard system.

## References

- Plan: `~/.claude/plans/so-currently-our-wiggly-teapot.md`
- `docs/guides/widget-system.md` — the voice/structure template for the new canonical guide
- `docs/integrations/index.md` — the existing authoring walkthrough (will defer authority to the new guide)
- `docs/integrations/design.md` — architectural rationale for the integration system
- [[Integration Depth Playbook]] — platform-growth recipe; cross-referenced from § 5 of the new guide
- [[Track - Integration Delivery]] — sibling track (outbox / bus / renderer abstraction)
- [[Track - Integration DX]] — completed sibling track (YAML migration, SDK expansion, config standardization)
