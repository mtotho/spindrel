---
tags: [agent-server, roadmap, master]
status: active
updated: 2026-04-19 (session 18 — user management Phases 0-2 shipped)
---
# Agent Server — Roadmap

The canonical view of where the project stands. For *why* → [[Architecture Decisions]]. For *how* → [[Architecture]] and [[How Discovery Works]]. For bugs → [[Loose Ends]].

## Product Identity
**"Best self-hosted personal AI agent."** Target: runs Ollama/local models, wants more than chat, values self-hosting. Auto-discovery is the killer feature — bots need only `model` + `system_prompt`.

## Current Phase: Freeze + Polish (April 7 → present)
**No new features/mechanisms/tables.** Structural cleanup, refactoring, splitting god functions, removing dead code, fixing bugs. See [[Loose Ends]] for open bugs.

## Completed (monitor only)
Full detail in [[Completed Tracks]].

| Area | One-line |
|---|---|
| Security hardening | Tool policy, scoped API keys, injection fixes, capability approval, endpoint catalog |
| Auto-discovery | Skill auto-enrollment, hybrid tool RAG, capability RAG, approval gate |
| Workflows | **DEPRECATED** — superseded by task pipelines. UI hidden, backend dormant. See [[Track - Automations]] |
| Memory hygiene | Two job types (Maintenance + Skill Review), cross-channel curation, 80+ tests |
| Mission Control | DB-backed, write-through markdown. Frozen, do not extend |
| Multi-bot channels | Unified `prepare_bot_context()` pipeline, identity/routing fixes |
| Skill simplification | All 7 phases done. Per-bot working set, auto-inject, enrolled ranking. See [[Track - Skill Simplification]] |
| Sub-agent system | 5 presets, parallel exec, depth/rate limit, 25 unit + 10 E2E tests |
| Declarative integrations | YAML-only, bundled MCP, visual/YAML editor, per-channel scoping |
| Web-native Phase 2 | Metro→Vite, expo-router→react-router v7, all RN→HTML. Zero TS errors |
| Integration delivery | Bus + outbox + renderer abstraction. POST /chat → 202. See [[Track - Integration Delivery]] |
| Workspace container collapse | Subprocess-based `exec_tool`, container lifecycle deleted (2026-04-14) |
| Workspace singleton | Single workspace, bootstrap-owned membership (2026-04-10) |

## Active

### User Management — Phases 0-2 shipped 2026-04-19
Half-built user-management surface being tightened into a coherent admin-vs-user experience. **Shipped**: Phase 0 (track opened), Phase 1 (120+ mutation endpoints audited, no leaks, [[Scope Matrix]] reference doc), Phase 1.5 (`require_scopes` fails closed for JWT users with no resolved scopes — admin bypass preserved via is_admin), Phase 2 (`/auth/me` returns effective scopes; `useScope()` / `useScopes()` / `useAnyScope()` / `useIsAdmin()` hooks mirror backend `has_scope()` semantics). **Remaining**: Phase 3 UI route guards + nav filtering + control hiding, Phase 4 channel ownership enforcement, Phase 5 `bot_grants` table + view/manage roles + GrantsTab, Phase 6 integration-binding lockdown, Phase 7 non-admin self-service. Non-goals: multi-user shared channels, SSO, audit log, invitation emails. Plan: `~/.claude/plans/fizzy-humming-aurora.md`. See [[Track - User Management]].

### ChatGPT Subscription OAuth Provider — shipped 2026-04-19
New `openai-subscription` provider type authenticates against OpenAI's Codex Responses API with a ChatGPT OAuth Bearer token (no API key). Device-code flow at `/api/v1/admin/providers/openai-oauth/{start,poll,status,disconnect}` drives an inline Connect-ChatGPT panel on the provider edit page; tokens persist encrypted in `ProviderConfig.config.oauth` with 10-min leeway auto-refresh. `OpenAIResponsesAdapter` translates `chat.completions` ↔ `/responses` so `llm.py` sees a uniform interface; `AnthropicOpenAIAdapter` was the prior-art for the pattern. Model allowlist (`gpt-5-codex`, `gpt-5`, `gpt-5-mini`, `o4-mini`) auto-seeds into `provider_models` on boot. Admin UI pre-fills `billing_type=plan` / `plan_cost=20` / `plan_period=monthly` so the existing plan-billing path handles $0-per-call cost reporting. Amber ToS disclaimer surfaces in the Connect panel. 45 new tests (25 adapter, 13 OAuth service, 7 admin integration). Load-bearing: Codex CLI client_id `app_EMoamEEZ73f0CkXaXp7hrann` reused (no public OAuth-app program for third parties); Responses API only (tokens don't work against `/v1/chat/completions`). See [[Architecture Decisions#ChatGPT Subscription OAuth — Codex Device-Code Flow, Responses-API-Only]].

### ~~Chat State Rehydration~~ — shipped 2026-04-18
All 3 phases shipped same day. Phase 1: channel-scoped `/approvals` + inline orphan section. Phase 2: migration 207 (`tool_calls.status`/`completed_at` + `tool_approvals.tool_call_id`/`approval_metadata`), at-start upsert + UPDATE on completion, decide endpoint flips linked ToolCall, capability metadata persisted. Phase 3: `GET /api/v1/channels/{id}/state` snapshot endpoint returns `{active_turns, pending_approvals}` with 10-min active-turn window + terminal-Message exclusion + skill-name rehydrate; `useChannelState` hook + `rehydrateTurn` store action seed the chat store on mount, with live-SSE-wins idempotency; `replay_lapsed` invalidates the snapshot to cover reconnect. Kills Loose Ends D2 (streaming refresh / mobile tab-wake) and the "non-inline approval prompt" scratch-pad item. Track closed — see [[Track - Chat State Rehydration]], [[Completed Tracks]].

### Task Sub-Sessions — pipeline-as-chat refactor (2026-04-18)
**Phase 3 planned (2026-04-19):** extensible ephemeral-session primitive — reusable `<EphemeralSession>` with modal + bottom-right dock shapes, per-session bot picker, optional `context` prop. First consumer: widget dashboard ad-hoc chat. Pipeline wizard migrates onto the shared modal shell. Hard invariant: reuses existing `MessageInput`/`SessionChatView`/`ChatMessageArea` render pipeline — no parallel streaming/renderer. Plan: `~/.claude/plans/snappy-honking-candle.md`. See [[Track - Task Sub-Sessions]] Phase 3.

Pipeline runs now render as a chat-native sub-session. Clicking a pipeline tile opens a modal with description + params (pre-run), streams every step's rich LLM thinking / tool widgets / Markdown / JSON as real Messages on a dedicated Session (live), and settles into a browsable transcript (complete). Parent channel shows a compact anchor card (icon · title · status · N steps · Open →) with a summary excerpt on completion. **Phase 0 (backend) + Phase 1 (UI + bus bridge) shipped 2026-04-18.** Bus bridge: `sub_session_bus.resolve_bus_channel_id` walks `parent_session_id`; `persist_turn` + `emit_step_output_message` + `tasks.py` turn lifecycle events route sub-session pipeline children's events onto the parent channel's bus tagged with session_id so the run-view modal (subscribed via the parent channel's SSE stream) receives them while the parent chat filters them out. Frontend: `useChannelEvents` gained `sessionFilter` + `dispatchChannelId`; new `useSessionEvents`, `SessionChatView`, `PipelineRunModal` + `PipelineRunPreRun` + `PipelineRunLive`, `SubSessionAnchor` render branch in `TaskRunEnvelope`. Tile click routes to `/channels/:id/pipelines/:pipelineId` → pre-run modal; Start transitions URL to `/channels/:id/runs/:taskId` → live transcript. Backend 195+ tests green; UI tsc clean. **Phase 3 (interactive push-back — enable composer + backend step pause/resume) remains a separate plan.** Tracked in [[Track - Task Sub-Sessions]]. Plans: `~/.claude/plans/snazzy-gliding-rain.md` (Phase 0), `~/.claude/plans/reactive-chasing-penguin.md` (Phase 1).

### Bot Audit Pipelines (2026-04-18)
Five orchestrator audit pipelines now cover the tunable surface of a bot: `analyze_discovery` (tool RAG threshold + pinning), `analyze_skill_quality` (skill descriptions/triggers + enrollment prune), `analyze_memory_quality` (compaction cadence + memory hygiene interval), `analyze_tool_usage` (pinned_tools promote, local_tools prune from ToolCall stats), `analyze_costs` (compaction tuning + fallback reorder from token_usage traces). Each prompt now names a strict whitelist of fields it may PATCH — fixes the crumb bug where the LLM narrated the right fix (`tool_similarity_threshold` drop) but couldn't emit it because the old prompt limited proposals to skills/tools only. `full_scan` and `deep_dive_bot` whitelists also tightened to drift-safe fields only. `get_trace` list mode gained `include_user_message: bool` so audit pipelines can see what the user actually said on each traced turn. New `list_pipelines` + `run_pipeline(pipeline_id, params, channel_id)` tools let the orchestrator invoke audits conversationally ("audit crumb's skill hygiene") without routing through the UI launchpad. New `audits` skill teaches the decision table. 35 tests green.

### Automations (Task Pipelines) — All phases shipped (2026-04-17)
Phases 1–5 SHIPPED. **Phase 5** added per-channel pipeline subscriptions (new `channel_pipeline_subscriptions` table), per-channel cron scheduling, tool-error + `fail_if` step-failure signaling, `pipeline_mode` channel override, channel-settings `PipelinesTab` (replaces deleted `WorkflowsTab`), and admin/tasks "Used by" column + "Subscribed channels" panel. Track ready to close — see follow-ups in [[Track - Automations]] §Phase 5 (deferred).

### Test Quality (2026-04-19)
Phases 0–4 + A + B.1-B.10 + C + D + E.1-E.10 + F.1-F.7 + G.1-G.6 + H.1-H.3 + I + J + K + L ALL SHIPPED. Total: 640+ tests. **Phase M shipped 2026-04-19**: 15 new tests in `test_widget_packages_seeder.py` covering seeder idempotency, orphan sweep, and sample-payload sync. `openai_responses_adapter.py` already had 25 tests from a parallel session. One SQLite drift pinned (active-transfer constraint ordering). Total 655+ tests. See [[Track - Test Quality]].

### Experiments / Autoresearch (2026-04-18)
Pipeline-layer optimization harness — knob → apply → evaluate → score → record → propose → loop. **Phase 1a** (c1a273ff) shipped the `evaluate` step, metric library, and `exec` evaluator. **Phase 1b** (Session 8) replaced the `bot_invoke` stub with a real evaluator: task-scoped `current_system_prompt_override` ContextVar, child Tasks (`task_type="eval"`, pipeline_task_id UI suppression, channel_id=None), capture `{response_text, tool_calls, token_count, latency_ms}` via Task + ToolCall + TraceEvent queries by correlation_id. 23 unit tests. Next: Phase 2 (`experiment.iterate.yaml` + hand-written spec for a first hill-climb). See [[Track - Experiments]].

### Temporal Context Awareness (2026-04-17)
`app/services/temporal_context.py` replaces the one-line "Current time" system message at `app/agent/context_assembly.py:1770` with a plain-English block: weekday + day-part, gap since last human message, conditional non-user-activity line, plus Layer-2 resolved references for relative-time phrases (`overnight`, `tonight`, `today`, `tomorrow`, `yesterday`, `this morning/afternoon/evening`) when the gap is ≥4h or crosses a day. Pre-persisted current-turn user message excluded via 5s cutoff. Stays at existing late-injection position — cache-safe. 35 unit tests.

### Web-Native Conversion — Phase 3 (Tailwind + cleanup)
Sidebar redesigned. Unified `PageHeader`. 210 Tailwind classNames fixed. Global `flex-direction: column` hack removed (2026-04-15) — 127 containers made explicit across 55 files.

### Integration Delivery — remaining work
Phases A–G + UI + bus restructure shipped. **Remaining**: Phase H acceptance test gaps, manual smoke coverage, ~10 polish items. See [[Track - Integration Delivery]].

**Integration Event System (2026-04-15)**: Standard `events:` declarations across 7 integrations. `emit_integration_event()` with category-based cooldowns. Trigger-events API, grouped source dropdown, auto-injected event_filter.

**Integration DX (updated 2026-04-15)**: `sdk.py` single-import, YAML as single source of truth, `setup.py` removed, auto-install deps on startup, system dep management via admin UI.

### Streaming Architecture
Phase 1 done (bus carries data + seq numbers + replay). Phase 2 folded into Integration Delivery (shipped). Phases 3-5 planned: split UI cache, separate domain from transport, backpressure + outbox. See [[Track - Streaming Architecture]].

### Code Quality & Refactoring
6 bugs from 156-file audit landed. `assemble_context` extracted (~1400→~990 lines). Remaining: loop, file_sync, tasks, tool_dispatch, compaction god-function splits. See [[Track - Code Quality]].

### Learning Center Enhancements (2026-04-15)
Time-windowed metrics, skill activity chart, activity heatmap, skill ring. Dreaming job split (Maintenance + Skill Review) with per-bot config.

### Wyoming Voice Integration
Phase 1 scaffold + Phase 3 ESPHome + Phase 4 satellite shipped. **Remaining**: wake word routing, streaming TTS, ESPHome wake word support.

### Interactive Tool Result Widgets (2026-04-16)
DX + robustness track: [[Track - Widgets]] (P0-3 docs live, P0-1 schema + P1-1 fragments in flight). Authoring reference: [[Widget Authoring]]. **Flagship HTML widget catalog + Phase 0 theme DX layer shipped 2026-04-19** (track §Flagship Catalog) — `sd-*` CSS vocabulary + design-token vars + dark-mode propagation injected into every iframe, first flagship (`frigate_get_events` timeline) landed, Frigate snapshot dup + widget-auth UX fixed. Phase 1 remaining: HA room dashboard + `get_trace` waterfall, both blocked on engine design calls (documented on track). **Phase 2 top four shipped 2026-04-19** (same session): `generate_image` (gallery + regen-prompt buttons), `get_weather` (SVG hourly chart + daily tiles — replaces component widget), `web_search` (favicon cards + star-to-save via `widget_config.starred[]` + Summarize→`fetch_url`), `frigate_list_cameras` (2×N wall + per-tile 10s snapshot refresh). Engine sidecar: `widget_config` now rides into `window.spindrel.toolResult.config` (was previously dropped); `InteractiveHtmlRenderer` exposes `window.spindrel.dashboardPinId` so widgets can target `widget_config` dispatches at the right pin; new thin `/api/v1/favicon?domain=` proxy for CSP-bound cross-origin icon fetches. Plan: `~/.claude/plans/memoized-gathering-abelson.md`.


Tool results become live, interactive control surfaces. Phases 0-4 shipped. **Phase 5 (Visual consistency + sync fix) shipped 2026-04-16**: Unified card design across ToolBadges, WidgetCard, and integration event envelopes (surfaceRaised bg, rounded-lg, uppercase tracking-wider headers). Shared `broadcastEnvelope` store syncs inline ↔ pinned widgets in real-time. `display_label` template field replaces fragile body-parsing for entity names. Widget card max-height + auto-collapse for stacked widgets. Width constraint removed (cards fill available space). **State poll (2026-04-16)**: `state_poll` field in widget template YAML — declares a read-only tool to call on page load for fresh state. Code transform + separate template reshape poll results. 30s server-side cache deduplicates concurrent polls. HA integration uses GetLiveContext with entity_state transform. **Per-pin config + tiles + hover-reveal (2026-04-17)**: `default_config:` + `{{config.*}}` substitution in templates AND `state_poll.args`; `dispatch:"widget_config"` action type shallow-merges patches via new `PATCH /widget-pins/{id}/config`; poll cache re-keyed by `(tool, args_json)` so per-config variants don't collide; `tiles` component (responsive auto-fill grid); Button `subtle` prop (opacity-25 → 100 on `group-hover`); `not` transform for inverse when-gates; PinnedToolWidget gets `group` class + "Updated Xm ago" hover-reveal chip; `_substitute_string` multi-var bug fix. OpenWeather uses all of it: subtle Show/Hide Forecast buttons, daily forecast as tiles, `include_daily` from config. 77 tests. **Pinned-widget context injection (2026-04-17)**: `app/services/widget_context.py` renders a plain-text system message from `channel.config["pinned_widgets"]` (uses each envelope's `display_label` + `plain_body`, annotates foreign-bot pins and "updated ~Xm ago"). Injected in `context_assembly.py` right after the temporal block — same cache-safety band, no new DB query (reuses `_ch_row`). Stale-but-OK: no synchronous `state_poll`, relies on the stored envelope. Flows into the `sys:pinned_widgets` line of the context-estimate UI and the `_inject_chars` trace. Caps: 12 pins, 250 char/pin, 2000 char global. 21 tests. **Next**: widget templates for core tools (web_search, exec_command, file ops). **Later**: Phase 6 (widget type registry), entity capability detection, envelope write-back on state_poll refresh so injected context stays fresh.

### Channel Dashboards + OmniPanel TLC (2026-04-18, redesign 2026-04-19)
Each channel now has an **implicit widget dashboard** at slug `channel:<uuid>`, lazy-created and cascade-deleted with its channel. The left `OmniPanel` is a **scaled mini-view of the dashboard's left half** — any pin whose left edge sits in the leftmost `railZoneCols` (6/12 in standard, 12/24 in fine) surfaces in the panel; the panel renders them in a CSS-Grid templated to the same column count, scaled to its current width via `1fr`. Layout fidelity round-trips: position and size on the dashboard transmit to the OmniPanel mini-grid (and the user's resize of the panel divider reflows pins live, no recalc). Full dashboard reachable via the palette ("Channel dashboard" under THIS CHANNEL), a new `LayoutDashboard` icon in the channel header, and an "Edit channel dashboard" link inside the OmniPanel widgets header. Edit mode shows subtle full-grid guides (4% opacity cell lines) plus a single 1px rail divider with a tiny "← Sidebar" label that brightens to accent during a drag-into-zone — no loud overlay. Mobile bottom sheet rewritten native-feeling: tall default (≈88vh), two snaps only (tall + dismissed), segmented pill tabs with localStorage-persisted last selection (default Widgets), body scroll-lock, safe-area padding. Server-side: `/api/v1/channels/{id}/widget-pins/*` endpoints deleted (all CRUD runs through `/api/v1/widgets/dashboard?slug=channel:<uuid>`); Alembic migration 213 one-shot-moves every `channel.config.pinned_widgets[]` entry into `widget_dashboard_pins`; migration 215 backfills layout coordinates so migrated pins land in the rail zone; `context_assembly` + context-estimate read channel pins via new `fetch_channel_pin_dicts`. Plans: `~/.claude/plans/quirky-crafting-glade.md` (initial), `~/.claude/plans/structured-spinning-wigderson.md` (rail-zone redesign). 54 adjacent tests green; UI tsc clean. **Remaining**: manual smoke on the test server (drag in/out of zone, OmniPanel resize, mobile sheet).

### Sandbox bot/channel context + tool grouping (2026-04-19)
**P7 of [[Track - Widget Dashboard]]**, shipped today. Closes the dev-panel false-oracle: `/widgets/dev#tools` now passes user-selected bot/channel into `admin_execute_tool` (which sets `current_bot_id` / `current_channel_id` ContextVars), so any tool that calls `current_bot_id.get()` (35 local + 10 integration tools, audited via grep) returns real data instead of `"No bot context available."` Always-visible BotPicker + ChannelPicker in the sandbox (sticky via `localStorage`); tools declare needs via new `requires_bot_context` / `requires_channel_context` flags on `@register(...)`; sidebar grouped collapsibly by `source_integration` (Built-in first); per-tool Bot/Hash icons preview the requirement; Pin button gated until selection complete. `_do_state_poll` propagates pin's `source_bot_id` / `source_channel_id` so dashboard refresh respects identity. 73 backend tests + UI tsc green. Plan: `~/.claude/plans/linear-marinating-hammock.md`.

### Widget Dashboard + Developer Panel (2026-04-18)
**P5 code shipped but NOT user-tested yet.** Automated tests (112) + tsc + vite build are green; manual QA and fix-up sessions still ahead. **Do not close this track until the testing checklist in [[Track - Widget Dashboard]] is signed off.** P5 landed: HA/Grafana-style grid (`react-grid-layout/legacy`, 12-col responsive, per-pin `{x, y, w, h}`, drag + resize, migration 211 `grid_layout` JSONB, `POST /pins/layout` + `PATCH /pins/{id}`), `EditPinDrawer` (display_label + widget_config JSON), `RecentTab` (filter bar + Import-into-Templates handoff + Pin-generic-view), sample_payload seeds in all three core `.widgets.yaml` files. Plan: `~/.claude/plans/ancient-churning-bubble.md`. Still open: P5-qa (manual testing + regression fixes), plus track [[Track - Widget Dashboard#Ideas / Future phases]] items — bot-authored ephemeral widgets / LLM-driven builder, `result_mime_type` / `output_schema`, multi-dashboard, authoring-UX debt in [[Loose Ends#Widget Dev Panel UX debt]]. See track for the full list. **HTML widget output v1 shipped 2026-04-18** (parallel session): new `emit_html_widget` tool + `application/vnd.spindrel.html+interactive` content type + permissive-sandbox `InteractiveHtmlRenderer`, with inline-html and workspace-path modes (path-backed auto-updates via 3s poll). Plan: `~/.claude/plans/fluttering-roaming-neumann.md`. **Bot-scoped iframe auth shipped 2026-04-19**: widgets authenticate as the emitting bot (not the viewing user) via short-lived JWT minted against the bot's API-key scopes; envelope carries `source_bot_id`, renderer re-mints every 12 min and pushes fresh tokens through `window.spindrel.__setToken` without reloading the srcDoc; subtle `@botname` chip signals the security model. Fixes the 422-on-every-API-call bug for pinned HTML widgets and closes the "admin lends credentials to bot JS" hole. See [[Architecture Decisions#Interactive HTML Widgets Authenticate as the Emitting Bot]].

### Home Assistant Integration (2026-04-16)
New `integrations/homeassistant/` — skill + carapace moved from mission_control. `tool_widgets` templates: HassTurnOn/Off use status + toggle + entity properties; HassLightSet adds power toggle + brightness slider. Args use `where: type=entity | pluck: name | first` to target entities (not areas).

### Excalidraw Diagram Integration
Tools-only integration for hand-drawn diagrams. Shipped 2026-04-12. **Remaining**: verify on test server (needs Chrome), unit tests.

### E2E Testing
308+ tests, 23 files, cron every 6h. OpenAI native provider smoke landed. See [[E2E Testing Roadmap]].

### Google Workspace
Token refresh + Drive folder done. Pending: hard folder enforcement, retry/backoff. Direction shift to community MCP server. See [[Track - Google Workspace]].

### UI Polish
Pass 1 done. Rich tool-result rendering designed but blocked on Integration Delivery. Component vocabulary shipped (10 primitives). See [[Track - UI Polish]].

### PWA & Push Notifications (2026-04-19)
Icons, favicon, service worker, Web Push end-to-end. Bot-callable `send_push_notification` tool (HomeAssistant-notify style, not auto-push on every message) + `POST /api/v1/push/send` scoped endpoint. See [[Track - PWA & Push]].

## Technical Debt
- **Two parallel "plans" systems** — generic agent plans vs MC plans, both deprecated under workspace-files

## Frozen (do not build)
MC dashboard, template onboarding, workflow visual builder, new retrieval mechanisms, multi-tenancy.

### Integration Depth — Slack pilot shipped (2026-04-17)
Slack grew from "mature chat renderer" to "first-class Slack app" across 5 phases: bot @-mentions humans + thread read-up + reactions-as-intents (Phase 1), scheduled/pin/bookmark tools + App Home + shortcuts (Phase 2), new `Capability.EPHEMERAL` + `EPHEMERAL_MESSAGE` event with `chat.postEphemeral` consumer (Phase 3), new `Capability.MODALS` + `OpenModal` action + `MODAL_SUBMITTED` event with `views.open` + view_submission bridge (Phase 4), plus reusable recipe in [[Integration Depth Playbook]] (Phase 5). See [[Track - Slack Depth]]. Manifest additions documented in the track.

## Next Phase: Integration Depth — remaining integrations
Discord audit next (following the playbook), then BlueBubbles, then GitHub's distinct surface (issues / PRs / check runs). Onboarding polish (`docker compose up` → working agent), progressive disclosure in admin UI, docs refresh, Flynn Thoughts test case remain queued.

## Principles
- If the user has to choose, we failed
- Explain by showing, not by labeling
- Composition over configuration
- Trust the pipeline — fix mechanisms, don't add config knobs

## See Also
- [[Architecture]] — subsystem map and request flow
- [[Architecture Decisions]] — load-bearing decisions
- [[How Discovery Works]] — runtime discovery pipeline
- [[Loose Ends]] — bugs, gotchas, things to verify
- [[Ideas & Investigations]] — parking lot
