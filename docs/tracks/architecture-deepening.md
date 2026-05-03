---
title: Architecture Deepening
summary: Rolling track for architectural deepening passes. Holds the current candidate inventory from the improve-codebase-architecture skill, ordered by confidence; deepenings that ship are logged in deepening-log.md and removed from the inventory.
status: active
tags: [spindrel, architecture, refactor]
created: 2026-05-02
updated: 2026-05-03
---

# Architecture Deepening

## North Star

Spindrel's agent surfaces (loop, context assembly, tool dispatch) are the #1 bug source per AGENTS.md, and the rest of the codebase (UI, services, integrations) accretes its own quiet drift. This track captures **deepening candidates** — places where merging shallow modules into deeper ones would concentrate complexity, improve testability, and make the system more AI-navigable. It is a rolling inventory: the `improve-codebase-architecture` skill refreshes it; landed deepenings move to `docs/deepening-log.md`.

## How this track works

1. Run the `improve-codebase-architecture` skill periodically. It surfaces candidates and updates this inventory.
2. Pick a candidate — usually highest confidence with the most reported friction (cross-checked against `docs/inbox.md`).
3. Grill the design (skill drives this), land the deepening, append to `docs/deepening-log.md` in the same edit, remove or check off the row here.
4. The skill's next run will read the log and bias toward areas that haven't been deepened recently — preventing the agent loop from monopolising attention while UI/services drift.

## Status

| # | Candidate | Area | Confidence | State | Updated |
|---|---|---|---|---|---|
| 1 | Tool Execution Policy gateway | app/agent | high | not started | 2026-05-02 |
| 2 | Tool Result Envelope vs. invocation | app/agent | medium | not started | 2026-05-02 |
| 3 | Message Assembly module (consolidate transcript mutation) | app/agent | medium | not started | 2026-05-02 |
| 4 | Pruning policy vs. mechanics | app/agent | medium-low | not started | 2026-05-02 |
| 5 | LoopHarness facade | app/agent | low | needs grilling | 2026-05-02 |
| 6 | Tool Schema Resolver | app/agent + app/tools | low-medium | not started | 2026-05-02 |
| 7 | Widget envelope + response projection | api + services | high | not started | 2026-05-02 |
| 8 | Chat handler preflight + audio routing | api | high | not started | 2026-05-02 |
| 9 | Integration renderer drift / sdk lift | integrations | medium-high | not started | 2026-05-02 |
| 10 | Read Model Builder (channel/session/pin) | services | high | not started | 2026-05-02 |
| 11 | Large-screen UI state machines | ui | medium | not started | 2026-05-02 |

**Shipped:** Tool Surface composition (2026-05-03) — see `docs/deepening-log.md`.

**Coverage gap closed on 2026-05-02 follow-up sweep.** Initial pass produced 7 candidates all inside `app/agent/`; follow-up swept `ui/`, `app/services/`, `app/db/`, `app/api/`, `integrations/`, and `app/tools/local/` outside the existing inventory. Five additional non-`app/agent` candidates surfaced (now numbered #7–#11). Areas confirmed clean enough to deprioritize next sweep: `ui/src/hooks/` (focused single-concern hooks), `app/db/` (no ORM leakage), `integrations/sdk.py` proper (clean import boundary), the bulk of `app/services/` and `app/tools/local/`. The next sweep should bias toward `app/agent/` drift detection on landed deepenings rather than fresh discovery.

## Candidate Inventory

### 1. Tool Execution Policy gateway — confidence: **high**

- **Files**: `app/agent/loop_dispatch.py` (664 lines), `app/agent/tool_dispatch.py` (2096 lines), guards `_authorization_guard`, `_execution_policy_guard`, `_policy_and_approval_guard`, `_plan_mode_guard`.
- **Problem**: Authorization / execution / approval / plan-mode rules are entangled with envelope building and trace emission, split across two modules. Approval-race bugs require cross-module tracing. Adding a new policy layer threads through 4 guards.
- **Solution sketch**: A single Tool Execution Policy module owns the gate chain. `dispatch_tool_call` becomes a client of it, not the host of it.
- **Benefits**: Locality for security-critical rules. New policies (rate limits, cost caps, delegation rules) plug in as new gates, not new branches inside dispatch.
- **Test seam**: `tests/unit/test_loop_approval_race.py` already exercises this surface.

### 2. Tool Result Envelope vs. tool invocation — confidence: **medium**

- **Files**: `app/agent/tool_dispatch.py` — `_build_default_envelope`, `_build_envelope_from_optin`, `_detect_content_type`, `_select_result_envelope`, `_build_tool_event`.
- **Problem**: ~1080 lines of envelope-building (truncation, plaintext fallback, widget binding, size caps) live alongside execution. Envelope-only tests need full execution context with mocks.
- **Solution sketch**: Separate envelope construction into its own module — pure-ish function over tool result + metadata + caps. `dispatch_tool_call` calls it after execution.
- **Benefits**: Presentation concerns decouple from execution. Truncation/widget tests become micro-unit tests with no async, no DB.
- **Risk**: `_select_result_envelope` reads plan-mode state — needs threading as an explicit parameter.

### 3. Message Assembly module — confidence: **medium**

- **Files**: `app/agent/loop_helpers.py` (1080 lines), `app/agent/message_utils.py`, `loop_pre_llm.py`, `loop_tool_iteration.py`, sanitization paths in `context_assembly.py`.
- **Problem**: `_sanitize_messages`, `_sanitize_llm_text`, `_extract_last_user_text`, `_append_transcript_text_entry`, `_collapse_final_assistant_tool_turn`, `_merge_tool_schemas` live in five different files but all mutate the messages array. The contract between them is implicit (e.g., sanitization runs once, callers must not re-sanitize).
- **Solution sketch**: A Message Assembly module owns the mutation contract. Composable operations (append transcript, merge tool results, truncate history) called by the 5 current sites.
- **Benefits**: A new mutation (reasoning-trace injection, compaction-summary formatting) changes one file instead of five. Pure-function tests replace event-loop tests.
- **Risk**: Some operations read context vars (`current_skills_in_context`); those would need to become explicit parameters.

### 4. Pruning policy vs. pruning mechanics — confidence: **medium-low**

- **Files**: `app/agent/context_pruning.py` (478 lines), `_run_context_pruning` in `context_assembly.py`.
- **Problem**: Two pruning phases — assembly-time (watermark-based) and in-loop (ratio-based) — duplicate the logic with different conditions. New strategies (cost-based, relevance-based) require touching both.
- **Solution sketch**: Pruning Policy as a parameter to a single mechanics module. Both phases call the same machinery with different policies injected.
- **Benefits**: Strategy experimentation without forking mechanics.
- **Risk**: In-loop pruning runs every iteration — allocation overhead matters. Payoff depends on whether new policies actually emerge.

### 5. LoopHarness facade — confidence: **low (needs grilling)**

- **Files**: 11 `loop*.py` modules under `app/agent/`, 15+ inter-agent imports.
- **Problem**: The loop is callable but has no interface. Tests mock the whole DAG. Adding a new caller (subagent, batch task) means following the streaming generator through every submodule.
- **Solution sketch**: A LoopHarness facade — single entry point for callers — without disturbing the internal submodule structure.
- **Benefits**: Callers mock the harness, not the cluster.
- **Open question for grilling**: are loop variants on the roadmap (parallel tool execution? reasoning mode?), or is the current streaming generator the canonical form? If no variants, this is indirection.

### 6. Tool Schema Resolver — confidence: **low-medium**

- **Files**: `app/agent/tools.py` (678 lines, `retrieve_tools()`), `app/tools/registry.py` (392 lines), schema composition in `context_assembly.py`.
- **Problem**: Pinned/tagged/enrolled lookup, in-memory registry, and semantic RAG retrieval are three modules with overlapping responsibility. Heartbeat vs. normal vs. fallback retrieval branches in `_run_tool_retrieval`.
- **Solution sketch**: One Tool Schema Resolver — composite that checks pinned → enrolled → retrieval (if policy allows) → fallback. Single call from `context_assembly`.
- **Benefits**: New discovery modes (MCP tool retrieval, plan-mode-restricted surfaces) add a resolver implementation, not branches in three modules.
- **Caveat**: The taxonomy (Local/MCP/Client/Workspace) is settled in `architecture.md`. This is hygiene more than a load-bearing seam unless new discovery modes are coming.

### 7. Widget envelope + response projection — confidence: **high**

- **Files**: `app/services/widget_templates.py` (1297 lines, 26 functions), inline `model_validate()` chains in `app/routers/api_v1_channels.py` (~900+), `api_v1_sessions.py:491–912`, `api_v1_projects.py` (~900+).
- **Problem**: Widget contract serialization (envelope transform, rendering-support matrix, rich-result adapter) lives in one dense service module. Channel/session/widget detail routes inline-construct `ChannelOut`, `SessionOut`, `WidgetEnvelopeOut` rather than going through a shared seam. `test_widget_catalog_api.py` (645 lines) mocks 12 collaborators because there's no isolated serializer to test.
- **Solution sketch**: A Widget Envelope Serializer module that owns `serialize_widget_envelope(widget, binding_context, policy)` — every route that emits widget payloads calls it. A separate Response Projector module centralizes `build_<shape>_out(row, db)` for the shapes currently scattered across `channel_read_models.py`, `channel_sessions.py`, and three route helpers.
- **Benefits**: V1 widget shape changes touch one file, not 15. Session detail evolves through one builder, not four. Tests become micro-units instead of integration mocks.
- **Domain language**: Widget Envelope, Widget Binding Context (existing), Response Projector.

### 8. Chat handler preflight + audio routing — confidence: **high**

- **Files**: `app/routers/chat/_routes.py` (876 lines, 9 `@router.post` handlers), `app/routers/chat/_helpers.py` (323 lines), overlap with `app/services/audio_input.py`.
- **Problem**: Validation, auth pre-checks, audio transcription (`_transcribe_audio_data`), attachment marshalling, session resolution, turn enqueueing all live inline in handlers. Handlers operate on `Any` for channel/session/bot — no typed pre-flight contract. Audio transcription mode-negotiation (`_resolve_audio_native` vs. `_transcribe_audio_data`) is split between route handler and service layer; same logic in two places.
- **Solution sketch**: A Chat Preflight Validator service — `validate_chat_request(body, auth) → PreparedChatInput` returns a typed, validated request with channel/session/bot resolved + attachments parsed. An Audio Transcription Router owns the single decision point of `native | transcribe | fail`. Handlers shrink to ~15 lines: parse → validate → enqueue → 202.
- **Benefits**: Audio mode-negotiation bugs fix in one place. New chat-request fields (RAG hints, embedding overrides) plug into the validator instead of being threaded through handler bodies. Worker tests mock `PreparedChatInput`, not the full handler stack.
- **Domain language**: Chat Preflight Validator, Prepared Chat Input, Audio Transcription Router.

### 9. Integration renderer drift / `sdk.py` lift — confidence: **medium-high**

- **Files**: `integrations/discord/renderer.py` (727 lines, 18 handlers), `integrations/slack/renderer.py` (207 lines), `integrations/arr/tools/_helpers.py` (64 lines), similar patterns in `bluebubbles/`, `github/`. `integrations/sdk.py` (586 lines).
- **Problem**: Discord is 3.5× Slack despite overlapping delivery concerns — both reimplement streaming-message coalesce, rate-limiting windows, message-ID tracking. ARR + GitHub duplicate entity parsing / state extraction helpers. AGENTS.md and `integrations.md` § Anti-patterns #7 already say "same private helper in 2+ integrations is a smell, lift to `sdk.py`" — that contract has drifted.
- **Solution sketch**: A Streaming Delivery Helper in `sdk.py` owns chunk coalescing, rate-limit windows, message-ID tracking. Renderers retain only platform-API adapter logic. ARR + GitHub parsing helpers lift as `parse_*` composables in `sdk.py`. New integrations (Telegram, Matrix, etc.) reuse rather than rebuild.
- **Benefits**: Discord renderer shrinks ~400 lines. New integration onboarding cost drops. Test doubles for streaming delivery exist once.
- **Domain language**: Streaming Delivery Helper, Platform API Adapter.
- **Cross-ref**: `tests/unit/test_integration_no_duplicate_helpers.py` already gates this contract — drift suggests the gate is missing some helpers.

### 10. Read Model Builder (channel / session / pin) — confidence: **high**

- **Files**: `app/services/channel_read_models.py` (312 lines), `app/services/channel_sessions.py` (450+ lines), `app/services/dashboard_pins.py` (1334 lines).
- **Problem**: Three modules own overlapping projections from DB rows to response shapes. `dashboard_pins.py` bundles three concepts: pin rendering, widget contract projection, theme resolution. Routes (`api_v1_channels.py`, `api_v1_sessions.py`, `api_v1_projects.py`) import 2–3 of these and combine inline — new fields leak into both query and three builders.
- **Solution sketch**: A Read Model Builder facade — `builder.channel(row, db)`, `builder.session_detail(row, db)`, `builder.pin_with_widget_envelope(pin, db)`. Dashboard-pin widget logic becomes a sub-concern of the builder rather than its own 1334-line module. All routes call the builder; no inline `model_validate` chains.
- **Benefits**: New `Channel` / `Session` / `Pin` field = one builder, one query, one test. Heartbeat projection (currently inline) plugs in for free. Cross-overlap with #7 — the builder and the envelope serializer want to share a base; landing #7 first would inform the builder shape.
- **Domain language**: Read Model Builder, Projection Seam.

### 11. Large-screen UI state machines — confidence: **medium**

- **Files**: `ui/src/components/spatial-canvas/SpatialCanvas.tsx` (1008 lines, 20 hooks), `ui/src/components/attention/AttentionCommandDeck.tsx` (1957 lines, 16 hooks), `ui/app/(app)/channels/[channelId]/index.tsx` (2017 lines, 22 hooks), `ui/src/components/spatial-canvas/useSpatialNavigation.tsx` (753 lines, 15+ props).
- **Problem**: Modal state, tab selection, sidebar visibility, detail-panel expansion, selection mode all live in scattered `useState` calls with transitions inlined into `useCallback` branches. Expanding the spatial canvas map calls 4 separate setState functions. State invariants (e.g., "detail closed when selection empty") aren't enforced anywhere. Zero unit tests on the canvas state logic. `useSpatialNavigation` takes 15+ props because there's no context seam.
- **Solution sketch**: A `useSpatialCanvasState()` reducer hook returning `{ state, dispatch }`. Same for the attention deck and channel-screen tab/detail logic. Add a shallow `<SpatialCanvasStateContext>` to break the prop-drilling chain. Not a rewrite — funnel scattered `useState` calls into a reducer so transitions become unit-testable.
- **Benefits**: Tab/sidebar/detail transitions become one dispatch instead of four setState calls. State invariants enforced in the reducer. Tests assert on reducer transitions without rendering. Prop drilling drops ~60% on the spatial-navigation tree.
- **Domain language**: Canvas State Machine, Spatial Navigation Context.
- **Cross-cutting risk**: This brushes against `spindrel-ui` skill territory (UI archetypes, component catalog). Any deepening here must respect the command/app-shell/control archetype split and use canonical components from `docs/guides/ui-components.md` rather than introducing parallel patterns.

## Key Invariants

- No integration-specific code in `app/` (per `architecture-decisions.md`). Any deepening that touches integration plumbing must keep the dispatcher protocol as the only seam.
- `memory_scheme: "workspace-files"` and `history_mode: "file"` are the only active options — don't surface deepening candidates that re-introduce the alternative paths.
- `flex-direction: column-reverse` chat scroll is non-negotiable (per `AGENTS.md`). Any UI deepening near `ChatMessageArea.tsx` preserves it.
- Test-first bug fixing remains the contract — every deepening lands with new tests at the deepened module's interface, and old shallow-module tests are deleted (per `DEEPENING.md` "replace, don't layer").

## References

- Skill: `.agents/skills/improve-codebase-architecture/SKILL.md` (+ `LANGUAGE.md`, `DEEPENING.md`, `INTERFACE-DESIGN.md`) — has `Unattended mode` for overnight Project coding runs
- Log of landed deepenings: `docs/deepening-log.md`
- Architecture: `docs/architecture.md`, `docs/architecture-decisions.md`
- Domain glossary: `docs/guides/ubiquitous-language.md`
