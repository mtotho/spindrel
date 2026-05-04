---
tags: [spindrel, roadmap, master]
status: active
updated: 2026-05-03
---
# Agent Server — Roadmap

Where the project stands. **Read [[../AGENTS]] first** for navigation. For *why* → [[architecture-decisions]]. For *how* → [[architecture]] + `spindrel/docs/guides/`. For bugs → [[inbox]].

## Product Identity
**"Best self-hosted personal AI agent."** Target: runs Ollama/local models, wants more than chat, values self-hosting. Auto-discovery is the killer feature — bots need only `model` + `system_prompt`.

## Current Phase: Active Product Buildout
Feature work, structural cleanup, and bug fixing all in scope. Keep new mechanisms deep and documented; update the owning track when shipping cross-cutting work.

## Up Next
Ready-to-launch work — decision-complete plans or queued track phases that an agent or operator could pick up today. Keep this list to **5–8 items**. When work starts, the row moves into [[#Active]]; when the plan ships, it moves to `docs/plans/completed/`. See `.spindrel/WORKFLOW.md` for the contract.

| Item | Source |
|---|---|
| Mid-turn chat followup absorption (planned) | [`docs/plans/mid-turn-chat-followup-absorption.md`](plans/mid-turn-chat-followup-absorption.md) |
| Mission Control dissolution → single Errors tab | [`docs/plans/mission-control-dissolution.md`](plans/mission-control-dissolution.md) |
| Orchestrator dissolution (delete bot + skills cluster) | [`docs/plans/orchestrator-dissolution.md`](plans/orchestrator-dissolution.md) |
| Project Factory cohesion pass (5 phases) | [`docs/plans/project-factory-cohesion.md`](plans/project-factory-cohesion.md) |
| Project Factory issue substrate (file-based intake) | [`docs/plans/project-factory-issue-substrate.md`](plans/project-factory-issue-substrate.md) |
| Project run-environment preflight | [`docs/plans/project-run-environment-preflight.md`](plans/project-run-environment-preflight.md) |
| Security track cleanup (bring track to spec) | [`docs/plans/security-track-cleanup.md`](plans/security-track-cleanup.md) |

## Plans
Open plans in `docs/plans/`. Executed plans live in `docs/plans/completed/` for decision history.

| Plan | Status |
|---|---|
| [Mid-turn chat followup absorption](plans/mid-turn-chat-followup-absorption.md) | planned |
| [Mission Control dissolution](plans/mission-control-dissolution.md) | active |
| [Orchestrator dissolution](plans/orchestrator-dissolution.md) | active |
| [Project Factory cohesion](plans/project-factory-cohesion.md) | active |
| [Project Factory issue substrate](plans/project-factory-issue-substrate.md) | active |
| [Project run-environment preflight](plans/project-run-environment-preflight.md) | active |
| [Security track cleanup](plans/security-track-cleanup.md) | active |
| [User Knowledge Graph](plans/user-knowledge-graph.md) | active (track shipped 2026-05-04 — verify) |

## Completed (monitor only)
Full detail in [[completed-tracks]].

| Area | One-line |
|---|---|
| Security hardening foundation | Tool policy, scoped API keys, injection fixes, capability approval, endpoint catalog |
| Auto-discovery | Skill auto-enrollment, hybrid tool RAG, capability RAG, approval gate |
| Workflows | **DEPRECATED** — superseded by task pipelines. UI hidden, backend dormant. See [[automations]] |
| Memory hygiene | Two job types (Maintenance + Skill Review), cross-channel curation, 80+ tests |
| Multi-bot channels | Unified `prepare_bot_context()` pipeline, identity/routing fixes |
| Skill simplification | All 7 phases done. See [[skill-simplification]] |
| Sub-agent system | Experimental readonly sidecars only |
| Declarative integrations | YAML-only, bundled MCP, visual/YAML editor |
| Web-native Phase 2 | Metro→Vite, expo-router→react-router v7, all RN→HTML |
| Integration delivery | Bus + outbox + renderer abstraction. See [[integration-delivery]] |
| Workspace container collapse | Subprocess-based `exec_tool`, container lifecycle deleted (2026-04-14) |
| Workspace singleton | Single workspace, bootstrap-owned membership (2026-04-10) |
| User Management | Admin-vs-user experience locked down (8 phases). See [[user-management]] |
| Web-Native Phase 3 | Tailwind cleanup, sidebar redesigned, `PageHeader` unified, column-reverse hack removed |
| Chat State Rehydration | Channel-scoped `/approvals`, ToolCall upsert, `GET /channels/{id}/state` snapshot. See [[chat-state-rehydration]] |
| Knowledge Base convention | Auto `knowledge-base/` per channel & bot; two narrow search tools. See [[indexing-and-search]] |
| Context Estimation | Single tokenizer (`app/agent/tokenization.py`); real API `prompt_tokens` in header |
| Temporal Context | `app/services/temporal_context.py` plain-English block; 35 tests |
| Slack Depth | 5 phases (mentions/threads/reactions, scheduled/pin/bookmark/App Home, EPHEMERAL, MODALS). See [[slack-depth]] |
| Streaming Architecture Phase 1 | Bus carries data + seq + replay. Phases 3–5 deferred. See [[streaming-architecture]] |
| Integration Delivery | Phases A–G + UI + bus restructure. H acceptance gaps + ~10 polish remain as inbox items. See [[integration-delivery]] |
| System Health Visibility | Rotating JSONL + `read_container_logs` / `get_recent_server_errors` + daily summary + `DailyHealthLandmark` |
| `browser_live` integration | MV3 Chrome-extension bridge, 5 tools, pairing token. See `integrations/browser_live/README.md` |
| ChatGPT OAuth Provider | `openai-subscription` provider, device-code flow, `OpenAIResponsesAdapter` |
| Image Generation | `generate_image` first-class. Migration 246 + capability flag + Gemini multimodal edit + Responses API |
| Standing Orders | Native widget + cron seam; `spawn_standing_order` tool; tick engine. See [[widget-sdk]] |
| HTML Widget Catalog | `app/services/html_widget_scanner.py` walks `**/widgets/**`, frontmatter parse, mtime memo |
| Excalidraw | Tools-only diagram integration |
| Mid-Turn Chat Followup Absorption | `chat_late_input` + pre-LLM drain. See `docs/plans/completed/mid-turn-chat-followup-absorption.md` |

## Active

| Area | Latest | One-line | Track |
|---|---|---|---|
| Security Architecture | 2026-05-02 | Red-team R1–R3 + R2 Phase 2 + R4 Phase 1 shipped. R4 Phase 2 (UI self-target badge, delegation-chain tracing) and container sudoers queued. Phase detail in track. | [[security]] |
| Agent Quality Observability | 2026-05-03 | Deterministic post-turn trace auditor + versioned findings + Daily Health counts; OTel/W3C trace cleanup anchors here. | [[agent-quality-observability]] |
| Context Surface Governance | 2026-05-01 | Metadata-owned tool exposure + context-budget governance so normal turns don't ambiently load specialized/admin/widget schemas. | [[context-surface-governance]] |
| Agent-first capability surface | 2026-04-30 | `/api/v1/agent-capabilities` + `list_agent_capabilities` / `run_agent_doctor`; readiness across API/tools/skills/Project/harness/widgets; `llms.txt` discovery. | [[mission-control-vision]] / `docs/guides/discovery-and-enrollment.md` |
| Mission Control Vision | 2026-04-30 | Operator Map north star plus active review deck: rough conversational issue notes and autonomous bot blockers now converge into Attention-backed Issue Work Packs before Project coding runs launch. | [[mission-control-vision]] |
| Projects | 2026-04-30 | First-class shared roots inside the singleton Workspace. Fresh instances, setup commands, coding-run receipts, review sessions, task-scoped execution grants, and Issue Work Pack launch provenance are now the v0 path toward reviewable agent implementation runs. | [[projects]] |
| Harness SDK | 2026-04-27 | External agent harnesses as a real runtime lane. Phases 3–6 v1 shipped; scheduled harness heartbeats/tasks now run real harness turns with per-run model/effort | [[harness-sdk]] |
| Notifications | 2026-04-27 | Reusable targets plus durable per-user/session unread read-state, cross-session UI badges/toasts, and unread reminder plumbing | [[notifications]] |
| Spatial Canvas | 2026-04-26 | Workspace-scope infinite plane replacing `HomeGrid`. Channels as draggable tiles, bots as actors, Attention Beacons, zoom-dive to dashboards. `Ctrl+Shift+Space` toggles overlay | [[spatial-canvas]] |
| Integration Contract | 2026-04-23 | Canonical guide at `docs/guides/integrations.md`; `chat_hud` retired in favor of dashboard widgets; `integration_id == "x"` boundary fixes via hook registry; pytest drift gate | [[integration-contract]] |
| Integration Rich Results | 2026-04-24 | Slack-led v1: `rich_tool_results` capability, `tool_result_rendering` matrix, SDK portable-card boundary, Slack Block Kit + approval split + depth contract tests | [[integration-rich-results]] |
| Local machine control | 2026-04-25 | Pluggable providers, probe readiness, session leases. `local_companion` recoverable launcher + reconnecting Linux service. Shared broker / packaging remain | [[local-machine-control]] |
| Provider Refactor | Phases 5+6 shipped 2026-04-24 | Capability metadata (`extra_headers`/`extra_body`/cache flag), catalog auto-refresh, `/admin/usage` Providers tab. Phases 3–4 queued | [[provider-refactor]] |
| Provider-dialect templating | v1 2026-04-19 | `prompt_style` capability flag; `{% section %}` markers rewritten per model. XML-on-Anthropic eval pending | [[experiments]] |
| Programmatic Tool Calling | 2026-04-19 | `run_script` collapses 10–50 dispatches; `register(returns=...)` + `list_tool_signatures`; lint pin |  |
| Docs Refresh | 2026-04-26 | README/docs index audit. Harness positioning corrected. Screenshot heroes / workflow deprecation / MkDocs verify remain | [[docs-refresh]] |
| Task Sub-Sessions | Phases 6–9 shipped 2026-04-21 | Threads + scratch chat; thread_ts mirroring; first-class scratch sessions (titles/promote/per-session history); pipeline-as-chat refactor. Phase 3 interactive push-back queued | [[task-sub-sessions]] |
| Bot Audit Pipelines | demoted 2026-04-20 | Only `analyze_discovery` featured; configurator skill + `propose_config_change` replaces ambient config-fix | [[automations]] |
| Configurator skill | 2026-04-20 | Folder-layout `skills/configurator/{index,bot,channel,integration}.md` + safety-tier `propose_config_change` |  |
| Automations | Phases 1–5 shipped 2026-04-17 | Per-channel pipeline subs, cron, `fail_if`, `pipeline_mode`, channel `PipelinesTab` | [[automations]] |
| Test Quality | Q-SEC sweep closed 2026-04-24 | ~1195+ tests, 13 real bugs fixed, 0 open drift-pinned bugs. Q-CONC + Q-CHURN backlog | [[test-quality]] |
| Experiments / Autoresearch | 2026-04-18 | Knob → apply → evaluate → score → record → propose → loop. Phase 1a/1b shipped; Phase 2 (`experiment.iterate.yaml`) next | [[experiments]] |
| Code Quality | 2026-04-29 | Ambient Ousterhout/deep-module cleanup; verify-first scans (no stale cluster numbers). | [[code-quality]] |
| Architecture Deepening | 2026-05-03 | Rolling candidate list from `improve-codebase-architecture` skill. Tool Surface composition shipped (candidate #1, 3240→2401 LOC). 11 remain. Log: `docs/deepening-log.md`. | [[architecture-deepening]] |
| Orchestrator dissolution | started 2026-05-03 | Retire the orchestrator system bot and `skills/orchestrator/` cluster so any default bot is capable. Pipelines, base prompt, and seeded bot all need coordinated removal. | [[orchestrator-dissolution]] |
| Bot-readable internal docs | started 2026-05-03 | Give runtime bots a way to read `/app/docs/` so canonical guides are reachable. Unblocks demoting oversized reference skills (`widgets/sdk`, `pipelines/authoring`, etc.) without stranding content. | [[bot-readable-docs]] |
| Memory & Knowledge admin | 2026-04-24 | `/admin/learning` reframed; read-first unified search across bot memory + KBs + history + dreaming | (in admin UI) |
| Wyoming Voice | Phase 1 + 3 + 4 shipped | Scaffold + ESPHome + satellite. Wake-word routing / streaming TTS / ESPHome wake remain |  |
| Widget SDK | A + B.0–B.6 shipped | iframe SDK + handler bridge (Todo widget); `@on_event` channel subs + `widget_suite.py` shared-DB suites | [[widget-sdk]] |
| Widget Primitives | Phase 1 shipped 2026-04-24 | `image` v2 (aspect, auth, lightbox, overlays). `tiles` v2 / `timeline` / ISO-8601 / frigate port queued | [[widget-primitives]] |
| Interactive Tool Result Widgets | Phases 0–5 shipped | `sd-*` CSS, design-token vars, dark-mode propagation; `state_poll` + per-pin config + tiles + hover-reveal (77 tests) | [[widgets]] |
| Channel Dashboards + OmniPanel | 2026-04-19 | Implicit dashboard at `channel:<uuid>`, lazy-create + cascade-delete; OmniPanel mini-view; migrations 213+215 | [[widget-dashboard]] |
| Mobile + layout_mode | 2026-04-20 | Tabbed `MobileChannelDrawer`; `channel.config["layout_mode"]` (full / rail-header-chat / rail-chat / dashboard-only); `<768px` editor gate |  |
| Chat zones via dashboard | P12 shipped 2026-04-20 | `channel_chat_zones.classify_pin` recomputes `rail`/`dock_right`/`header_chip` per read |  |
| Kiosk + panel-mode | P9–P11a shipped 2026-04-19 | `?kiosk=1`, `useKioskMode`, Fullscreen + Wake Lock; migration 224 panel mode; size presets / Full-width / Reset-layout. P11-b/c queued |  |
| Sandbox dev panel | 2026-04-19 | `/widgets/dev#tools` passes bot/channel context; `requires_*_context` flags; sidebar grouped by `source_integration` | (in [[widget-dashboard]]) |
| Widget Dashboard P5 | 2026-04-18 | HA/Grafana grid (`react-grid-layout/legacy`), `EditPinDrawer`, `RecentTab`, sample_payload seeds. HTML widget output v1 + bot-scoped iframe auth | [[widget-dashboard]] |
| Home Assistant integration | 2026-04-16 | Skill + (legacy) carapace moved from mission_control; `tool_widgets` for HassTurnOn/Off + HassLightSet | `integrations/homeassistant/` |
| E2E Testing | 308+ tests, cron 6h | OpenAI native provider smoke landed | [[e2e-testing-roadmap]] |
| Google Workspace | partial | Token refresh + Drive folder. Shifting to community MCP server | [[google-workspace]] |
| UI Design | canonical spec 2026-04-23 | `spindrel/docs/guides/ui-design.md` is target spec. Adoption + debt migration in [[ui-vision]] | [[ui-polish]] / [[ui-vision]] |
| UI Polish | per-channel terminal mode 2026-04-21 | Pass 1 done. Channel command-first composer mode; rich tool-result rendering | [[ui-polish]] |
| PWA & Push | 2026-04-19 | SW + Web Push + bot-callable `send_push_notification` + scoped `POST /api/v1/push/send` | [[pwa-and-push]] |

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
Index: `spindrel/docs/guides/index.md`. These win against other docs when they disagree. Update the matching guide in the same pass as any architectural change.

## Related
- [[../AGENTS]] — start-here navigation map
- [[architecture]] — subsystem map and request flow
- [[architecture-decisions]] — load-bearing decisions
- [[inbox]] — bugs, gotchas, things to verify
- [[open-issues]] — untriaged review findings (accumulative)
- [[Ideas & Investigations]] — parking lot
