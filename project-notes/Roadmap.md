---
tags: [agent-server, roadmap, master]
status: active
updated: 2026-04-30
---
# Agent Server — Roadmap

Where the project stands. **Read [[INDEX]] first** for navigation. For *why* → [[Architecture Decisions]]. For *how* → [[Architecture]] + `agent-server/docs/guides/`. For bugs → [[Loose Ends]].

## Product Identity
**"Best self-hosted personal AI agent."** Target: runs Ollama/local models, wants more than chat, values self-hosting. Auto-discovery is the killer feature — bots need only `model` + `system_prompt`.

## Current Phase: Active Product Buildout
Feature work, structural cleanup, and bug fixing all in scope. Keep new mechanisms deep and documented; update the owning track when shipping cross-cutting work.

## Completed (monitor only)
Full detail in [[Completed Tracks]].

| Area | One-line |
|---|---|
| Security hardening foundation | Tool policy, scoped API keys, injection fixes, capability approval, endpoint catalog |
| Auto-discovery | Skill auto-enrollment, hybrid tool RAG, capability RAG, approval gate |
| Workflows | **DEPRECATED** — superseded by task pipelines. UI hidden, backend dormant. See [[Track - Automations]] |
| Memory hygiene | Two job types (Maintenance + Skill Review), cross-channel curation, 80+ tests |
| Multi-bot channels | Unified `prepare_bot_context()` pipeline, identity/routing fixes |
| Skill simplification | All 7 phases done. See [[Track - Skill Simplification]] |
| Sub-agent system | Experimental readonly sidecars only |
| Declarative integrations | YAML-only, bundled MCP, visual/YAML editor |
| Web-native Phase 2 | Metro→Vite, expo-router→react-router v7, all RN→HTML |
| Integration delivery | Bus + outbox + renderer abstraction. See [[Track - Integration Delivery]] |
| Workspace container collapse | Subprocess-based `exec_tool`, container lifecycle deleted (2026-04-14) |
| Workspace singleton | Single workspace, bootstrap-owned membership (2026-04-10) |
| User Management | Admin-vs-user experience locked down (8 phases). See [[Track - User Management]] |
| Web-Native Phase 3 | Tailwind cleanup, sidebar redesigned, `PageHeader` unified, column-reverse hack removed |
| Chat State Rehydration | Channel-scoped `/approvals`, ToolCall upsert, `GET /channels/{id}/state` snapshot. See [[Track - Chat State Rehydration]] |
| Knowledge Base convention | Auto `knowledge-base/` per channel & bot; two narrow search tools. See [[Track - Indexing & Search]] |
| Context Estimation | Single tokenizer (`app/agent/tokenization.py`); real API `prompt_tokens` in header |
| Temporal Context | `app/services/temporal_context.py` plain-English block; 35 tests |

## Active

| Area | Latest | One-line | Track |
|---|---|---|---|
| Security Architecture | agentic audit started 2026-04-30 | Dedicated security track is active again after Projects/harness/widgets/integrations expanded the attack surface; security audit now reports cross-workspace bots, high-risk bot API scopes, and widget-action API allowlist breadth. | [[Track - Security]] |
| System Health Visibility | shipped 2026-04-26 | Rotating JSONL log handler + `read_container_logs` / `get_recent_server_errors` tools + deterministic daily summary + `DailyHealthLandmark` canvas marker | (in [[Architecture Decisions]]) |
| Agent-first capability surface | work snapshot 2026-04-30 | Machine-readable `/api/v1/agent-capabilities` plus `list_agent_capabilities` / `run_agent_doctor`; UI readiness covers API/tools/skills/Project/harness/widgets/integrations, repo-local `.agents/skills` guide outside/dev agents, `llms.txt`/`/llms.txt` gives external agents a stable discovery entrypoint, and runtime agents now get compact context-budget plus assigned-work snapshots. | [[Track - Mission Control Vision]] / `docs/guides/discovery-and-enrollment.md` |
| Mission Control Vision | 2026-04-30 | Operator Map north star plus active review deck: rough conversational issue notes and autonomous bot blockers now converge into Attention-backed Issue Work Packs before Project coding runs launch. | [[Track - Mission Control Vision]] |
| Projects | 2026-04-30 | First-class shared roots inside the singleton Workspace. Fresh instances, setup commands, coding-run receipts, review sessions, task-scoped execution grants, and Issue Work Pack launch provenance are now the v0 path toward reviewable agent implementation runs. | [[Track - Projects]] |
| Harness SDK | 2026-04-27 | External agent harnesses as a real runtime lane. Phases 3–6 v1 shipped; scheduled harness heartbeats/tasks now run real harness turns with per-run model/effort | [[Track - Harness SDK]] |
| Notifications | 2026-04-27 | Reusable targets plus durable per-user/session unread read-state, cross-session UI badges/toasts, and unread reminder plumbing | [[Track - Notifications]] |
| Spatial Canvas | 2026-04-26 | Workspace-scope infinite plane replacing `HomeGrid`. Channels as draggable tiles, bots as actors, Attention Beacons, zoom-dive to dashboards. `Ctrl+Shift+Space` toggles overlay | [[Track - Spatial Canvas]] |
| Integration Contract | 2026-04-23 | Canonical guide at `docs/guides/integrations.md`; `chat_hud` retired in favor of dashboard widgets; `integration_id == "x"` boundary fixes via hook registry; pytest drift gate | [[Track - Integration Contract]] |
| Integration Rich Results | 2026-04-24 | Slack-led v1: `rich_tool_results` capability, `tool_result_rendering` matrix, SDK portable-card boundary, Slack Block Kit + approval split + depth contract tests | [[Track - Integration Rich Results]] |
| `browser_live` integration | shipped 2026-04-19 | MV3 Chrome-extension bridge, 5 tools, `BROWSER_LIVE_PAIRING_TOKEN` pairing | `integrations/browser_live/README.md` |
| Local machine control | 2026-04-25 | Pluggable providers, probe readiness, session leases. `local_companion` recoverable launcher + reconnecting Linux service. Shared broker / packaging remain | [[Track - Local Machine Control]] |
| Image Generation | shipped 2026-04-24 | `generate_image` first-class for any bot. Migration 246 + capability flag + family routing + Gemini multimodal edit + Responses API path | [[Track - Provider Refactor]] |
| Provider Refactor | Phases 5+6 shipped 2026-04-24 | Capability metadata (`extra_headers`/`extra_body`/cache flag), catalog auto-refresh, `/admin/usage` Providers tab. Phases 3–4 queued | [[Track - Provider Refactor]] |
| Provider-dialect templating | v1 2026-04-19 | `prompt_style` capability flag; `{% section %}` markers rewritten per model. XML-on-Anthropic eval pending | [[Track - Experiments]] |
| Programmatic Tool Calling | 2026-04-19 | `run_script` collapses 10–50 dispatches; `register(returns=...)` + `list_tool_signatures`; lint pin |  |
| Docs Refresh | 2026-04-26 | README/docs index audit. Harness positioning corrected. Screenshot heroes / workflow deprecation / MkDocs verify remain | [[Track - Docs Refresh]] |
| ChatGPT OAuth Provider | shipped 2026-04-19 | `openai-subscription` provider type, device-code flow, `OpenAIResponsesAdapter` |  |
| Task Sub-Sessions | Phases 6–9 shipped 2026-04-21 | Threads + scratch chat; thread_ts mirroring; first-class scratch sessions (titles/promote/per-session history); pipeline-as-chat refactor. Phase 3 interactive push-back queued | [[Track - Task Sub-Sessions]] |
| Bot Audit Pipelines | demoted 2026-04-20 | Only `analyze_discovery` featured; configurator skill + `propose_config_change` replaces ambient config-fix | [[Track - Automations]] |
| Configurator skill | 2026-04-20 | Folder-layout `skills/configurator/{index,bot,channel,integration}.md` + safety-tier `propose_config_change` |  |
| Automations | Phases 1–5 shipped 2026-04-17 | Per-channel pipeline subs, cron, `fail_if`, `pipeline_mode`, channel `PipelinesTab` | [[Track - Automations]] |
| Test Quality | Q-SEC sweep closed 2026-04-24 | ~1195+ tests, 13 real bugs fixed, 0 open drift-pinned bugs. Q-CONC + Q-CHURN backlog | [[Track - Test Quality]] |
| Experiments / Autoresearch | 2026-04-18 | Knob → apply → evaluate → score → record → propose → loop. Phase 1a/1b shipped; Phase 2 (`experiment.iterate.yaml`) next | [[Track - Experiments]] |
| Integration Delivery | shipped + remaining | Phases A–G + UI + bus restructure shipped. H acceptance gaps + manual smoke + ~10 polish remain | [[Track - Integration Delivery]] |
| Streaming Architecture | Phase 1 shipped | Bus carries data + seq + replay. Phases 3–5 (split UI cache, transport split, backpressure) planned | [[Track - Streaming Architecture]] |
| Code Quality | ambient track refreshed 2026-04-29 | Ousterhout/deep-module cleanup continues by fresh verify-first scan, not stale cluster numbers. Major shipped waves include indexing, tool dispatch, loop/context/task/turn/heartbeat, startup/runtime, usage, integrations, widgets, chat UI, and context diagnostics. | [[Track - Code Quality]] |
| Memory & Knowledge admin | 2026-04-24 | `/admin/learning` reframed; read-first unified search across bot memory + KBs + history + dreaming | (in admin UI) |
| Wyoming Voice | Phase 1 + 3 + 4 shipped | Scaffold + ESPHome + satellite. Wake-word routing / streaming TTS / ESPHome wake remain |  |
| Widget SDK | A + B.0–B.6 shipped | iframe SDK + handler bridge (Todo widget); `@on_event` channel subs + `widget_suite.py` shared-DB suites | [[Track - Widget SDK]] |
| Standing Orders | shipped 2026-04-24 | Native widget + cron seam; `spawn_standing_order` tool; `core/standing_order_native`; tick engine + strategies | (in [[Track - Widget SDK]]) |
| Widget Primitives | Phase 1 shipped 2026-04-24 | `image` v2 (aspect, auth, lightbox, overlays). `tiles` v2 / `timeline` / ISO-8601 / frigate port queued | [[Track - Widget Primitives]] |
| HTML Widget Catalog | shipped 2026-04-19 | `app/services/html_widget_scanner.py` walks `**/widgets/**`, parses frontmatter, `(path, mtime)` memo. Path-mode envelope reuses renderer | (in [[Track - Widgets]]) |
| Interactive Tool Result Widgets | Phases 0–5 shipped | `sd-*` CSS, design-token vars, dark-mode propagation; `state_poll` + per-pin config + tiles + hover-reveal (77 tests) | [[Track - Widgets]] |
| Channel Dashboards + OmniPanel | 2026-04-19 | Implicit dashboard at `channel:<uuid>`, lazy-create + cascade-delete; OmniPanel mini-view; migrations 213+215 | [[Track - Widget Dashboard]] |
| Mobile + layout_mode | 2026-04-20 | Tabbed `MobileChannelDrawer`; `channel.config["layout_mode"]` (full / rail-header-chat / rail-chat / dashboard-only); `<768px` editor gate |  |
| Chat zones via dashboard | P12 shipped 2026-04-20 | `channel_chat_zones.classify_pin` recomputes `rail`/`dock_right`/`header_chip` per read |  |
| Kiosk + panel-mode | P9–P11a shipped 2026-04-19 | `?kiosk=1`, `useKioskMode`, Fullscreen + Wake Lock; migration 224 panel mode; size presets / Full-width / Reset-layout. P11-b/c queued |  |
| Sandbox dev panel | 2026-04-19 | `/widgets/dev#tools` passes bot/channel context; `requires_*_context` flags; sidebar grouped by `source_integration` | (in [[Track - Widget Dashboard]]) |
| Widget Dashboard P5 | 2026-04-18 | HA/Grafana grid (`react-grid-layout/legacy`), `EditPinDrawer`, `RecentTab`, sample_payload seeds. HTML widget output v1 + bot-scoped iframe auth | [[Track - Widget Dashboard]] |
| Home Assistant integration | 2026-04-16 | Skill + (legacy) carapace moved from mission_control; `tool_widgets` for HassTurnOn/Off + HassLightSet | `integrations/homeassistant/` |
| Excalidraw | shipped 2026-04-12 | Tools-only diagram integration. Test-server verify + unit tests pending |  |
| E2E Testing | 308+ tests, cron 6h | OpenAI native provider smoke landed | [[E2E Testing Roadmap]] |
| Google Workspace | partial | Token refresh + Drive folder. Shifting to community MCP server | [[Track - Google Workspace]] |
| UI Design | canonical spec 2026-04-23 | `agent-server/docs/guides/ui-design.md` is target spec. Adoption + debt migration in [[Track - UI Vision]] | [[Track - UI Polish]] / [[Track - UI Vision]] |
| UI Polish | per-channel terminal mode 2026-04-21 | Pass 1 done. Channel command-first composer mode; rich tool-result rendering | [[Track - UI Polish]] |
| PWA & Push | 2026-04-19 | SW + Web Push + bot-callable `send_push_notification` + scoped `POST /api/v1/push/send` | [[Track - PWA & Push]] |
| Slack Depth | shipped 2026-04-17 | 5 phases: mentions/threads/reactions, scheduled/pin/bookmark/App Home, `EPHEMERAL`, `MODALS`, recipe in [[Integration Depth Playbook]] | [[Track - Slack Depth]] |

## Technical Debt
_None load-bearing right now._

## Not Currently Building
Template onboarding, ephemeral Project instances, workflow visual builder, new retrieval mechanisms, multi-tenancy.

## Next Phase: Integration Depth — remaining integrations
Discord audit next (following the playbook), then BlueBubbles. GitHub distinct surface v1 shipped as the repo dashboard preset/widget (issues / PRs / check runs + confirmed issue close/reopen); remaining GitHub depth should build on that surface rather than start a parallel one. Onboarding polish (`docker compose up` → working agent), progressive disclosure in admin UI, docs refresh, Flynn Thoughts test case remain queued.

## Principles
- If the user has to choose, we failed
- Explain by showing, not by labeling
- Composition over configuration
- Trust the pipeline — fix mechanisms, don't add config knobs

## Canonical Guides
Index: `agent-server/docs/guides/index.md`. These win against other docs when they disagree. Update the matching guide in the same pass as any architectural change.

## Related
- [[INDEX]] — start-here navigation map
- [[Architecture]] — subsystem map and request flow
- [[Architecture Decisions]] — load-bearing decisions
- [[Loose Ends]] — bugs, gotchas, things to verify
- [[Open Issues]] — untriaged review findings (accumulative)
- [[Ideas & Investigations]] — parking lot
