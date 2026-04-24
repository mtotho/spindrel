---
tags: [agent-server, roadmap, master]
status: active
updated: 2026-04-24 (added Standing Orders + Widget Primitives tracks)
---
# Agent Server — Roadmap

The canonical view of where the project stands. For *why* → [[Architecture Decisions]]. For *how* → [[Architecture]], `agent-server/docs/guides/context-management.md`, and `agent-server/docs/guides/discovery-and-enrollment.md`. For bugs → [[Loose Ends]].

## Product Identity
**"Best self-hosted personal AI agent."** Target: runs Ollama/local models, wants more than chat, values self-hosting. Auto-discovery is the killer feature — bots need only `model` + `system_prompt`.

## Current Phase: Freeze + Polish (April 7 → present)
**No new features/mechanisms/tables.** Structural cleanup, refactoring, splitting god functions, removing dead code, fixing bugs. See [[Loose Ends]] for open bugs.

## Completed (monitor only)
Full detail in [[Completed Tracks]]. `run_script` follow-up on 2026-04-21: bot-authored skills can now carry named stored scripts, so reusable tool workflows can be saved with `manage_bot_skill` and executed later by reference.

| Area | One-line |
|---|---|
| Security hardening | Tool policy, scoped API keys, injection fixes, capability approval, endpoint catalog |
| Auto-discovery | Skill auto-enrollment, hybrid tool RAG, capability RAG, approval gate |
| Workflows | **DEPRECATED** — superseded by task pipelines. UI hidden, backend dormant. See [[Track - Automations]] |
| Memory hygiene | Two job types (Maintenance + Skill Review), cross-channel curation, 80+ tests |
| Multi-bot channels | Unified `prepare_bot_context()` pipeline, identity/routing fixes |
| Skill simplification | All 7 phases done. Per-bot working set, auto-inject, enrolled ranking. See [[Track - Skill Simplification]] |
| Sub-agent system | Experimental readonly sidecars only; prompt nudges removed, policy enforced, traceable child runs |
| Declarative integrations | YAML-only, bundled MCP, visual/YAML editor, per-channel scoping |
| Web-native Phase 2 | Metro→Vite, expo-router→react-router v7, all RN→HTML. Zero TS errors |
| Integration delivery | Bus + outbox + renderer abstraction. POST /chat → 202. See [[Track - Integration Delivery]] |
| Workspace container collapse | Subprocess-based `exec_tool`, container lifecycle deleted (2026-04-14) |
| Workspace singleton | Single workspace, bootstrap-owned membership (2026-04-10) |
| User Management | Admin-vs-user experience locked down across 8 phases. See [[Completed Tracks#User Management]] and [[Track - User Management]] |

## Active

### Integration Contract + Canonical Guide (2026-04-23)
New north-star guide at `docs/guides/integrations.md` (mirroring `widget-system.md`'s authority model), a central canonical-guides index at `docs/guides/index.md`, retirement of the legacy `chat_hud` / `chat_hud_presets` surface in favor of dashboard widgets, `binding.suggestions_endpoint` shape standardization, three `integration_id == "x"` boundary fixes in `app/` via a new hook registry, and a pytest drift gate. See [[Track - Integration Contract]]. Plan: `~/.claude/plans/so-currently-our-wiggly-teapot.md`.

### `browser_live` integration — v0.1 shipped 2026-04-19
MV3 Chrome-extension bridge drives the user's real logged-in session. Five tools: `browser_goto/act/eval/screenshot/status`. Pairing via a single `BROWSER_LIVE_PAIRING_TOKEN` admin setting. See `integrations/browser_live/README.md`.

### Local machine control — provider profiles shipped 2026-04-24
Machine control is now a core subsystem with pluggable providers, probe-based readiness, and provider-scoped profiles. Targets are addressed as `(provider_id, target_id)`; session leases enforce one-session-one-target. `local_companion` and `ssh` are both shipped, and SSH now binds each target to an explicit named profile instead of ambient provider-global credentials. Shared broker, `browser_live` lease convergence, and richer capabilities remain. See [[Track - Local Machine Control]].

### Provider Refactor — Phase 2 shipped 2026-04-23
Phase 1 shipped: unified reasoning/effort knob + `/effort <off|low|medium|high>`, single slash-command registry source of truth, canonical `docs/guides/providers.md`, silent Codex `reasoning_effort` drop fixed. Phase 2 shipped: `ProviderModel.supports_reasoning` column (migration 242 + known-family backfill), bot editor UI gates the reasoning control per model, `/effort` rejects with a helpful toast on non-reasoning bots, admin models form exposes the flag. Phases 3–4 (adapter dedup, prompt-dialect polish) queued. See [[Track - Provider Refactor]].

### Provider-dialect prompt templating — v1 shipped 2026-04-19
`prompt_style` capability flag on `ProviderModel` (markdown/xml/structured). Framework prompts use `{% section %}` markers rewritten per model. **Open question**: does XML wrapping on Anthropic move any metric? No eval data yet — hook into [[Track - Experiments]]. Plan: `~/.claude/plans/swirling-plotting-biscuit.md`.

### Programmatic Tool Calling — run_script + returns-schema lint-pin (2026-04-19)
`run_script` collapses 10–50 LLM-driven dispatches into one Python script; output-schema discoverability via `register(returns=...)` + `list_tool_signatures`. Tiers 1–4 backfilled (45+ tools); 5 complex local tools remain in `_PENDING_BACKFILL`. Lint pin in `tests/unit/test_tool_returns_schema_coverage.py`.

### Knowledge Base convention — shipped 2026-04-19 (session 22)
Every channel and bot gets an auto-created `knowledge-base/` folder, auto-indexed + auto-retrieved. Two narrow search tools: `search_channel_knowledge(query)` and `search_bot_knowledge(query)`. Replaces the 4-knob segment mudball. See [[Track - Indexing & Search]] Phase 4 + [[Architecture Decisions#Knowledge-base convention replaces manual segment UI as the default]].

### Docs Refresh — Phase B + D + E text work shipped 2026-04-19 (session 19)
Seven new guides landed + `docs/index.md` table + `mkdocs.yml` nav rebuilt. Phase A (screenshots — needs e2e staging) and Phase F (grep-sweep cleanup) remain. See [[Track - Docs Refresh]].

### ChatGPT Subscription OAuth Provider — shipped 2026-04-19
New `openai-subscription` provider type authenticates against OpenAI's Codex Responses API with a ChatGPT OAuth Bearer token (no API key). Device-code flow + `OpenAIResponsesAdapter` + allowlisted model autoseed. See [[Architecture Decisions#ChatGPT Subscription OAuth — Codex Device-Code Flow, Responses-API-Only]].

### ~~Chat State Rehydration~~ — shipped 2026-04-18
All 3 phases shipped same day (channel-scoped `/approvals`, at-start ToolCall upsert, `GET /channels/{id}/state` snapshot + `useChannelState` hook). See [[Track - Chat State Rehydration]], [[Completed Tracks]].

### Context Estimation Consolidation — shipped 2026-04-21
One tokenizer (`app/agent/tokenization.py`): Anthropic hits native `messages.count_tokens`, others go through `tiktoken`, unknowns fall back to chars/3.5. Header shows real API `prompt_tokens` (`source: "api"`) with pre-call estimate fallback; `compute_context_breakdown` gained `mode: "last_turn" | "next_turn"`. Plan: `~/.claude/plans/sleepy-puzzling-island.md`.

### Sub-session polish — Phase 8 + Phase 9 shipped 2026-04-21
Phase 8 closed visibility/mobile/cross-device scratch gaps; Phase 9 made scratch sessions first-class (titles, summaries, rename/promote endpoints, bootstrap summary, per-session history reads). See [[Track - Task Sub-Sessions#Phase 8]] and [[Track - Task Sub-Sessions#Phase 9]].

### Slack thread_ts mirroring + thread UX polish — shipped 2026-04-20 (Track Phase 7)
Threads are one bidirectional conversation across web and Slack via integration-generic `IntegrationMeta` thread-ref hooks + migration 230's `sessions.integration_thread_refs`. `ThreadParentAnchor` + lazy-spawn on first send. See [[Track - Task Sub-Sessions#Phase 7]].

### Threads + in-channel scratch chat — shipped 2026-04-20 (Track Phase 6)
Reply-in-thread forks a sub-session anchored at a Message; Scratch chat FAB mounts an ephemeral dock with zero main-feed footprint. Both ride the existing `ChatSession` primitive. See [[Track - Task Sub-Sessions#Phase 6]].

### Task Sub-Sessions — pipeline-as-chat refactor (2026-04-18)
Pipeline runs render as a chat-native sub-session (pre-run modal → live transcript → compact anchor card). Phase 0 backend + Phase 1 UI + bus bridge shipped. **Phase 3 (interactive push-back: composer + backend pause/resume) + extensible `<EphemeralSession>` primitive** remain separate plans. See [[Track - Task Sub-Sessions]].

### Bot Audit Pipelines (2026-04-18, demoted 2026-04-20)
Five orchestrator audit pipelines exist; only `analyze_discovery` stays featured. The broader "one pipeline per knob" surface produced noise; configurator skill + `propose_config_change` replaces ambient config-fix. See [[Track - Automations]].

### Configurator skill + `propose_config_change` (2026-04-20)
Organic ambient-chat path for fixing bot / channel / integration config. Folder-layout skill `skills/configurator/{index,bot,channel,integration}.md` + a `safety_tier="mutating"` tool with per-scope field allowlists. Skills loader now handles `skills/<name>/index.md` folder layout. Plan: `~/.claude/plans/scalable-prancing-music.md`.

### Automations (Task Pipelines) — Phases 1–5 shipped (2026-04-17)
Per-channel pipeline subscriptions, cron scheduling, `fail_if` step-failure signaling, `pipeline_mode` channel override, channel-settings `PipelinesTab`, admin "Used by" + "Subscribed channels" views. See [[Track - Automations]].

### Test Quality (2026-04-24)
Phases 0–Q-SEC-3 all shipped (~1195+ tests) — **full Q-SEC sweep closed 2026-04-24** (Q-SEC-1 widget-auth, Q-SEC-2 SSRF, Q-SEC-3 webhook replay all shipped same day). 13 real bugs fixed in code, **0 open drift-pinned bugs** (Q-SEC-2 surfaced 3 SSRF horizontal gaps + Q-SEC-3 surfaced 5 webhook replay-contract gaps, all documented in [[Loose Ends]] with flip-on-fix pins). **Phase Q-SEC-3 (2026-04-24)** added 14 webhook-replay drift pins across five surfaces: GitHub HMAC body-only replayability (same-payload-twice + no delivery-id binding), BlueBubbles static-token auth with self-reported `dateCreated` staleness (token-only auth + GUID-dedup-attacker-controlled), Slack Socket-Mode absence-pin (zero POST routes; future Events API migration forces fresh drift file), local_companion WS `secrets.compare_digest` on static token with no challenge/nonce in hello handshake, and outbound Spindrel webhook signatures (deterministic sign_payload, captured-sig-valid-forever, `X-Spindrel-Signature` set without `X-Spindrel-Timestamp`). **Phase Q-SEC-2 (2026-04-24)** added 9 SSRF horizontal drift pins — proving `assert_public_url` is actually invoked at `standing_orders` fetch + loopback-rejected end-to-end, AST-inspection pins on 2 ungated sinks (`attachment_summarizer.py`, `mcp_servers._test_mcp_connection`), and string-only bypass pins for `validate_webhook_url` (DNS-rebinding hostname, decimal-encoded IP, IPv6-mapped-IPv4 loopback). **Phase Q-SEC-1 (2026-04-24)** added 13 widget-auth drift pins covering token-claim shape, `pin_id` passthrough, scope verbatim, non-admin ApiKeyAuth gate, dangling FK 400; flipped 1 broken concurrent-mint test so the `jti` nonce contract is now positively pinned. **Phase Q-MACH (2026-04-24)** closed the three boundaries Phase O explicitly stopped at: 36 new drift tests across admin `/machines` routes (exception-to-HTTP mapping, read/write scope gates, body passthrough + path-wins-over-body, disconnected-target 200 envelope shape) + `local_companion` WS handshake (4404 unknown target, 4401 wrong token, empty-registered-token short-circuit, 4400 malformed hello across three variants, successful register target+bridge pair, empty-capabilities → `["shell"]` default on both sides, clean-disconnect finally unregister, multi-connect last-writer-wins) + provider-impl extensions (register_connected_target no-op on unknown, probe_target ValueError vs offline envelope). No new production bugs — all invariants hold. Revived 1 pre-existing broken test (`test_machine_status_returns_refreshable_semantic_envelope` fixture was missing `"ready": True`). Phase P2 (2026-04-24) closed both pre-existing broken-test entries from [[Loose Ends]] with 12 staleness flips across `test_model_params_llm` + `test_dashboard_pins_service`. Phase P (2026-04-23) closed the 4 drift-pinned Loose Ends carried out of Phase N (L.1 heartbeat `reset_stale_running_runs`, J.5 widget-auth JWT `jti`, I.5 generic-regex attribution idempotency, N.3 channel-delete cache invalidation). Phase O (2026-04-23) landed the 19-test `machine_control.py` service-layer drift sweep. Phase N (N.1–N.8, 2026-04-23) shipped 79 tests across widget presets + native envelope repair + channel-skill enrollment + session_plan_mode + rerank header-prefix + approval lifecycle + context-assembly bot cache + outbox drainer fire-and-forget, including N.6's two production-breaking NameError fixes in `_create_approval_state`. Backlog: Q-CONC (loop_dispatch gather isolation + tokenization cascade + SSE back-pressure + rerank pathological + bus publisher isolation), Q-CHURN (loop_dispatch/loop_helpers/rag_formatting + integration config routers + binding_suggestions + device_status cache). See [[Track - Test Quality]].

### Experiments / Autoresearch (2026-04-18)
Pipeline-layer optimization harness — knob → apply → evaluate → score → record → propose → loop. Phase 1a + 1b shipped (real `bot_invoke` evaluator via task-scoped `current_system_prompt_override` ContextVar, eval child Tasks, outcome capture via correlation_id). Phase 2 next: `experiment.iterate.yaml` + first hill-climb spec. See [[Track - Experiments]].

### Temporal Context Awareness (2026-04-17)
`app/services/temporal_context.py` replaces the one-line "Current time" injection with a plain-English block (weekday + day-part, gap since last human message, Layer-2 resolved references for relative-time phrases). Cache-safe; 35 unit tests.

### Web-Native Conversion — Phase 3 (Tailwind + cleanup)
Sidebar redesigned. Unified `PageHeader`. 210 Tailwind classNames fixed. Global `flex-direction: column` hack removed (2026-04-15) — 127 containers made explicit across 55 files.

### Integration Delivery — remaining work
Phases A–G + UI + bus restructure shipped. **Remaining**: Phase H acceptance test gaps, manual smoke coverage, ~10 polish items. See [[Track - Integration Delivery]].

**Integration Event System (2026-04-15)**: Standard `events:` declarations across 7 integrations. `emit_integration_event()` with category-based cooldowns. Trigger-events API, grouped source dropdown, auto-injected event_filter.

**Integration DX (updated 2026-04-15)**: `sdk.py` single-import, YAML as single source of truth, `setup.py` removed, auto-install deps on startup, system dep management via admin UI.

### Streaming Architecture
Phase 1 done (bus carries data + seq numbers + replay). Phase 2 folded into Integration Delivery (shipped). Phases 3-5 planned: split UI cache, separate domain from transport, backpressure + outbox. See [[Track - Streaming Architecture]].

### Code Quality & Refactoring
Ousterhout depth audit clusters 1–5 shipped 2026-04-23 → 2026-04-24 (indexing boundary, dashboard router split + preset drift, HTTPException boundary-bypass, cross-surface drift guards across event bus / widget boundary / theme tokens / inline-hex ratchet, tool_dispatch deepening 686→310 LOC via 7 cohesive helpers). 6 bugs from 156-file audit landed. `assemble_context` extracted (~1400→~990 lines). Remaining: `assemble_context` (1500) + `run_agent_tool_loop` (883) as Cluster 6+; widget envelope triple-rebuild reconciliation as its own cluster; loop, file_sync, tasks, compaction god-function splits queued behind. See [[Track - Code Quality]].

### Learning Center Enhancements (2026-04-15)
Time-windowed metrics, skill activity chart, activity heatmap, skill ring. Dreaming job split (Maintenance + Skill Review) with per-bot config.

### Wyoming Voice Integration
Phase 1 scaffold + Phase 3 ESPHome + Phase 4 satellite shipped. **Remaining**: wake word routing, streaming TTS, ESPHome wake word support.

### Widget SDK (2026-04-21)
Phase A (iframe SDK) + B.0–B.6 backend shipped. Bot↔widget handler bridge (2026-04-20) turns any `@on_action` into a bot-callable tool via declarative `handlers:` block; Todo widget is the reference. `@on_event` channel subscriptions + shared-DB suites (`widget_suite.py`) are the primitive layer. See [[Track - Widget SDK]].

### Standing Orders — shipped 2026-04-24
First-party native widget (`core/standing_order_native`) plus a new native-widget cron seam so a bot can plant a dashboard tile that keeps ticking after the turn ends, then pings back in chat when a completion condition fires. Spec + action dispatcher in `app/services/native_app_widgets.py`; tick engine + strategies (`poll_url`, `timer`) + scheduler loop in `app/services/standing_orders.py`; `spawn_standing_order` tool in `app/tools/local/standing_order_tools.py` (skill-gated under `skills/standing_orders.md`, per-bot cap 5). React tile at `ui/src/components/chat/renderers/nativeApps/StandingOrderWidget.tsx`. `create_pin(override_widget_instance=...)` enables multi-instance-per-channel. 25 tests across unit + integration. **Follow-ups**: `event_wait` strategy + `event_seen` completion kind (plan spec'd 3 strategies, v1 shipped 2), e2e verification on the live server. See session log `Sessions/agent-server/2026-04-24-08-standing-orders-native-widget.md`.

### Widget Primitives — Phase 1 shipped 2026-04-24
Expand the YAML component-tree primitive set so integration-owned widgets default to declarative YAML instead of hand-rolled HTML. **Phase 1 shipped same day** — `image` v2 with `aspect_ratio`, `auth: bearer`, `lightbox`, and normalized-coord `overlays` (schema + renderer + 11 tests + docs). Next: `tiles` v2, `timeline` primitive, ISO-8601 canonicalization, frigate port, broader HTML-widget audit. Bot-authored widgets stay HTML+SDK (AI-first library contract, unchanged). Design principle: every new field passes the "LLM emitting this YAML has one obvious choice" entropy test. See [[Track - Widget Primitives]].

### HTML Widget Catalog + Frontmatter — shipped 2026-04-19 (Widgets P3-1)
`app/services/html_widget_scanner.py` walks `**/widgets/**/*.html` ∪ spindrel-using workspace HTML, parses YAML frontmatter, memoizes by (path, mtime). Pins via `emit_html_widget` path-mode envelope — reuses the existing renderer. See [[Architecture Decisions#Tool Renderers vs HTML Widgets: Two Kinds, Not One]].

### Interactive Tool Result Widgets (2026-04-16)
DX + robustness track. Phases 0–5 shipped. `sd-*` CSS vocabulary + design-token vars + dark-mode propagation in every iframe; state_poll + per-pin config + tiles + hover-reveal (77 tests). Pinned-widget context injection renders pin envelopes as a system message. Flagship HTML catalog + Phase 2 HTML result renderers (`generate_image`, `get_weather`, `frigate_list_cameras`, `web_search` via `core.search_results`) shipped and tightened 2026-04-23. See [[Track - Widgets]] and [[Widget Authoring]].

### Channel Dashboards + OmniPanel TLC (2026-04-18, redesign 2026-04-19)
Every channel has an implicit widget dashboard at slug `channel:<uuid>`, lazy-created and cascade-deleted. OmniPanel is a scaled mini-view of the dashboard's left half; layout fidelity round-trips. Migrations 213 + 215 moved the old `config.pinned_widgets[]` shape into `widget_dashboard_pins`. See [[Track - Widget Dashboard]].

### Mobile polish + channel layout_mode — shipped 2026-04-20
Mobile hamburger on channel routes now opens a tabbed `MobileChannelDrawer` (Widgets / Files / Jump). New `channel.config["layout_mode"]` (full / rail-header-chat / rail-chat / dashboard-only) gates chat zones. Mobile editor gate on `<768px`. See [[Architecture Decisions#Mobile hamburger on channel routes opens a tabbed drawer]] and [[Architecture Decisions#Chat-screen zones are gated by `channel.config["layout_mode"]`]].

### Chat-screen zones via positional dashboard placement — P12 shipped 2026-04-20
Channel dashboard is now the chat-screen layout editor. Three positional zones recomputed every read via `channel_chat_zones.classify_pin`: leftmost cols → `rail`, rightmost cols → `dock_right`, top row → `header_chip`. No migration; no `chat_zone` key. See [[Track - Widget Dashboard]].

### Kiosk / Fullscreen + Panel-mode HTML widget — P9 + P10 shipped 2026-04-19
`?kiosk=1` URL param hides chrome; `useKioskMode` wires Fullscreen API + Wake Lock + idle-cursor-hide. Panel mode (migration 224 `is_main_panel` + partial unique index) promotes one HTML widget to a side panel. P11-a (size presets, Full-width, Reset-layout) shipped same day. Remaining: P11-b undo, P11-c HA-style sections. See [[Track - Widget Dashboard]].

### Sandbox bot/channel context + tool grouping (2026-04-19)
`/widgets/dev#tools` now passes user-selected bot/channel into `admin_execute_tool` so ContextVar-consuming tools return real data. `requires_bot_context` / `requires_channel_context` flags on `@register(...)`; sidebar grouped by `source_integration`. See [[Track - Widget Dashboard]] P7.

### Widget Dashboard + Developer Panel (2026-04-18)
P5 code shipped but not user-tested. HA/Grafana-style grid (`react-grid-layout/legacy`, 12-col, migration 211 `grid_layout` JSONB), `EditPinDrawer`, `RecentTab`, sample_payload seeds. HTML widget output v1 + bot-scoped iframe auth (short-lived JWT minted against emitting bot's scopes) shipped same track. See [[Track - Widget Dashboard]] and [[Architecture Decisions#Interactive HTML Widgets Authenticate as the Emitting Bot]].

### Home Assistant Integration (2026-04-16)
New `integrations/homeassistant/` — skill + carapace moved from mission_control. `tool_widgets` templates: HassTurnOn/Off use status + toggle + entity properties; HassLightSet adds power toggle + brightness slider. Args use `where: type=entity | pluck: name | first` to target entities (not areas).

### Excalidraw Diagram Integration
Tools-only integration for hand-drawn diagrams. Shipped 2026-04-12. **Remaining**: verify on test server (needs Chrome), unit tests.

### E2E Testing
308+ tests, 23 files, cron every 6h. OpenAI native provider smoke landed. See [[E2E Testing Roadmap]].

### Google Workspace
Token refresh + Drive folder done. Pending: hard folder enforcement, retry/backoff. Direction shift to community MCP server. See [[Track - Google Workspace]].

### UI Design — canonical spec shipped 2026-04-23
`agent-server/docs/guides/ui-design.md` is the target spec for all UI work. Two surface archetypes (command / content), one token system, canonical active-row pill, documented anti-patterns, known-debt appendix. Adoption + debt migration tracked in [[Track - UI Vision]]. Cross-referenced from `feedback_no_gratuitous_borders`, `feedback_no_left_colored_borders`, `feedback_tailwind_not_inline`, `feedback_widgets_use_app_theme`.

### UI Polish
Pass 1 done. **Per-channel terminal chat mode shipped 2026-04-21** — channel setting flips the main feed/composer into a command-first Codex/Claude-style presentation without changing approvals/widgets/tool plumbing. Rich tool-result rendering and broader polish history live in [[Track - UI Polish]]. Target spec lives in `agent-server/docs/guides/ui-design.md` ([[Track - UI Vision]]).

### PWA & Push Notifications (2026-04-19)
Icons, favicon, service worker, Web Push end-to-end. Bot-callable `send_push_notification` tool (HomeAssistant-notify style, not auto-push on every message) + `POST /api/v1/push/send` scoped endpoint. See [[Track - PWA & Push]].

### Integration Depth — Slack pilot shipped (2026-04-17)
Slack grew from "mature chat renderer" to "first-class Slack app" across 5 phases: @-mentions + thread read-up + reactions-as-intents, scheduled/pin/bookmark + App Home + shortcuts, `Capability.EPHEMERAL` + `chat.postEphemeral`, `Capability.MODALS` + `views.open`, plus reusable recipe in [[Integration Depth Playbook]]. See [[Track - Slack Depth]].

## Technical Debt
_None load-bearing right now._

## Frozen (do not build)
Template onboarding, workflow visual builder, new retrieval mechanisms, multi-tenancy.

## Next Phase: Integration Depth — remaining integrations
Discord audit next (following the playbook), then BlueBubbles, then GitHub's distinct surface (issues / PRs / check runs). Onboarding polish (`docker compose up` → working agent), progressive disclosure in admin UI, docs refresh, Flynn Thoughts test case remain queued.

## Principles
- If the user has to choose, we failed
- Explain by showing, not by labeling
- Composition over configuration
- Trust the pipeline — fix mechanisms, don't add config knobs

## Canonical Guides
Index: `agent-server/docs/guides/index.md`. These win against other docs when they disagree.
- `agent-server/docs/guides/context-management.md` — context admission + history profiles
- `agent-server/docs/guides/discovery-and-enrollment.md` — tool / skill / MCP residency + enrollment
- `agent-server/docs/guides/widget-system.md` — widget contracts, origins, presentation, host policy
- `agent-server/docs/guides/ui-design.md` — UI archetypes, design tokens, anti-patterns
- `agent-server/docs/guides/integrations.md` — integration contract + responsibility boundary

## Related
- [[Architecture]] — subsystem map and request flow
- [[Architecture Decisions]] — load-bearing decisions
- [[Loose Ends]] — bugs, gotchas, things to verify
- [[Open Issues]] — untriaged review findings (accumulative)
- [[Ideas & Investigations]] — parking lot
