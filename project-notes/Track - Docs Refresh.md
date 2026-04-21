---
tags: [agent-server, track, docs, active]
status: active
updated: 2026-04-21 (docs audit — README/setup/architecture drift + browser_live/widget-library gaps)
---

# Track - Docs Refresh

## North Star
`docs/` reflects the post-polish product: fresh screenshots of the web-native UI, complete coverage of the April 12–19 feature wave, no references to deprecated features (workflows, per-bot workspaces, old HUD), and a clear showcase of widgets, pipelines, providers, and integrations.

## Why this track exists
`docs/` hasn't had a meaningful update since **2026-04-07**. Since then the product shipped: Widget Dashboards + Interactive HTML Widgets + Dev Panel, Task Sub-Sessions, Task Pipelines (all 5 phases; Workflows deprecated), Chat State Rehydration, ChatGPT Subscription OAuth provider, PWA + Push, the full Web-Native UI conversion (Metro→Vite, RN→HTML, Tailwind), unified PageHeader, OmniPanel rail redesign, Home Assistant integration, Excalidraw integration, Slack Depth, capability gating, `search_tools`, temporal context.

Concrete gaps:
- **All 37 images are ≥12 days old.** Several capture deprecated UI (workflow editor, old bots list pre-sidebar, old workspace model, pre-web-native HUD).
- **5 docs are missing entirely** (sub-sessions, chat-state-rehydration, pwa-push, dev-panel, providers).
- **5 docs need major rewrites** (`workflows.md` full replacement, `bot-skills.md`, `setup.md`, `slack.md`, `widget-templates.md`).
- **10 docs need minor section edits.**
- The `index.md` Features list still leads with "Workflows" and omits 8+ shipped features.

## Status

| Phase | Area | Status |
|---|---|---|
| A | Screenshot punch list — staged + captured | pending |
| B | Rewrite stale docs (1 full + 4 major edits) | **complete** — `workflows.md` deprecation stub shipped; `bot-skills.md` gained "Ephemeral Skill Injection" (@-tags + pipeline `execution_config.skills` + sub-session scope + mechanism comparison); `setup.md` gained `openai-subscription` provider row + "ChatGPT Subscription (OAuth, no API key)" subsection (device-code flow, model allowlist, billing config, caveats, disconnect); `slack.md` already has full Slack Depth coverage (App Home, Shortcuts, Modals, Ephemeral, Reactions, Threads); `widget-templates.md` already reframed with 3-mode picker + html-widgets cross-link. |
| C | Minor section edits (10 files) | **partial** — shipped: `index.md` Features + Guides, `api.md` scopes + new widget/state endpoints, `how-spindrel-works.md` (capability gating + search_tools + pipelines + sub-sessions + workspace singleton + rehydration), `heartbeats.md` (workflow→pipeline clarified, `run_pipeline` example), `delegation.md` (vs subagents vs pipelines comparison), `chat-history.md` (rehydration section), `migration.md` (singleton narrative), `mcp-servers.md` (HA integration note). Still pending: `templates-and-activation.md` (minimal language changes needed — may skip). |
| D | Create missing docs (5–7 new files) | **complete** — shipped all 7 in session 19: `task-sub-sessions.md`, `chat-state-rehydration.md`, `pwa-push.md`, `dev-panel.md`, `providers.md`, `homeassistant.md`, `excalidraw.md`. Each one prove-before-propose'd against source. Capabilities + Workspace-files guides (8–9 in the original plan) stayed optional and are parked — existing how-spindrel-works.md and migration.md cover them. |
| E | Update `index.md` + nav | **partial** — Features + Guides table updated with all 7 new-guide rows (`providers`, `homeassistant`, `excalidraw`, `task-sub-sessions`, `dev-panel`, `chat-state-rehydration`, `pwa-push`). Remaining: `mkdocs.yml` `nav:` if present (didn't touch — unclear whether one is used). |
| F | Delete workflow docs + stale images, add deprecation redirects | pending |

Each phase is independently sized for its own session. Sequence: **A first** (everything below references screenshots), then **B + C in parallel** (touch different files), then **D** (new docs use new screenshots), then **E** (index update rolls up new files), then **F** (cleanup).

### 2026-04-21 audit follow-up

Post-session audit against code + commits from **2026-04-07 → 2026-04-21** found the April 19 docs pass landed cleanly for `docs/index.md` and the new guides, but three older entry points are still materially stale:

- **`README.md`** is still pre-pipelines / pre-web-native / pre-current-integrations: leads with "workflows", shows `workflow-editor-1.png`, says UI is `Expo/React`, still lists Mission Control but omits Home Assistant / Excalidraw / browser_live / widget dashboards / sub-sessions / providers / PWA.
- **`docs/setup.md`** still documents `workflows/`, `ui/` as "React Native/Expo", `mission_control/` as a live integration folder, and a Docker workspace-container model that no longer matches the current subprocess-first / single-workspace docs elsewhere.
- **`docs/reference/architecture.md`** still has a full "Workflows" section (`workflow_executor.py`, `workflows/*.yaml`, `workflow_runs`) instead of the task-pipeline + sub-session model.

New doc gaps introduced by the April 20–21 wave:

- **No docs page / nav entry for `browser_live`** even though `integrations/browser_live/README.md` is the canonical operator-facing setup.
- **Widget Library flow is under-documented**: `/widgets` Add-sheet **Library** tab, `GET /api/v1/widgets/library-widgets`, bot/workspace/core scopes, and the dashboard-header **Developer tools** split-button are not captured in `widget-dashboards.md` / `dev-panel.md`.
- **Scratch-session history / server-owned current scratch pointer** (`/api/v1/sessions/scratch/current|reset|list`, `ScratchViewer`) are not covered in `task-sub-sessions.md`.
- **Panel-mode dashboards / promote-to-panel flow** are called out in roadmap/track docs but not in the user docs.

Small correctness fixes needed when touching docs:

- `guides/dev-panel.md` references `ui/app/(app)/widgets/dev/LibraryTab.tsx`, but the shipped file is `LibraryWidgetsTab.tsx`.
- README/docs still contain broad **Mission Control** framing in places where the codebase has moved to widget suites / task widgets / general dashboards. Audit each mention instead of blanket-deleting — some `mc_*` widgets still exist.

### 2026-04-21 progress — priority entry points updated

Shipped the first cleanup pass on the three highest-value stale entry points:

- **`README.md`** rewritten away from workflows / Expo-era language toward pipelines, sub-sessions, widgets, current integrations, providers, and push. Removed dead workflow screenshot references and inserted explicit screenshot placeholders where new captures still need to land.
- **`docs/setup.md`** updated to stop advertising `workflows/`, `mission_control/`, React Native/Expo UI, and long-lived per-bot workspace containers as the primary model. Reframed workspace docs around the current single-workspace + subprocess-first execution model, with Docker sandboxes called optional.
- **`docs/reference/architecture.md`** replaced the workflow section with a task-pipeline + sub-session section and updated configuration/database language accordingly.

Still next in queue from the audit:

- Add a proper `browser_live` guide under `docs/guides/` and wire it into nav/index.
- Update `dev-panel.md`, `widget-dashboards.md`, and `task-sub-sessions.md` for widget-library flow, dashboard "Developer tools" entry, scratch history/current-pointer endpoints, and panel mode.

### 2026-04-21 progress — second docs batch

Shipped the next missing-docs pass:

- **New guide:** `docs/guides/browser-live.md` covering pairing, architecture, safety model, and operator flow. Wired into both `docs/index.md` and `mkdocs.yml`.
- **`docs/guides/dev-panel.md`** updated for the current dashboard entry point (`Add widget` split-button → `Developer tools`), the Library tab's actual purpose (core/bot/workspace library widgets via `/api/v1/widgets/library-widgets`), and the correct shipped file reference (`LibraryWidgetsTab.tsx`).
- **`docs/guides/task-sub-sessions.md`** updated for the current scratch-session model: `/sessions/scratch/current`, `/reset`, `/list`, cross-device current-pointer behavior, `ScratchHistoryModal`, and `ScratchViewer`.

Remaining docs from the audit are now narrower:

- `widget-dashboards.md` still needs panel-mode / promote-to-panel coverage and a brief note about the Library-tab pin flow.
- `api.md` could use explicit mention of `/api/v1/widgets/library-widgets`, scratch endpoints, and browser_live admin endpoints if we want the API guide to stay exhaustive.

### 2026-04-21 progress — third docs batch

Closed the remaining narrow user-doc gaps from the audit:

- **`docs/guides/widget-dashboards.md`** now covers the Add-widget split-button, Library-tab pin flow, and panel mode / promote-to-panel behavior.
- **`docs/guides/api.md`** now explicitly documents `/api/v1/widgets/library-widgets`, panel-mode endpoints, scratch current/reset/list routes, and the `browser_live` admin endpoints outside `/api/v1/`.

At this point the original audit's concrete gaps are mostly closed. Remaining work is now polish-oriented rather than "missing core docs":

- broader terminology cleanup where older "Mission Control" framing may still be too dominant
- screenshot replacement as the new image set lands
- optional additional API-guide exhaustiveness passes when new endpoints ship

### 2026-04-21 progress — integration transparency page

Added a new public guide, **`docs/guides/integration-status.md`**, linked from `docs/index.md` and `mkdocs.yml`.

Purpose:

- Give users an explicit, dated, non-marketing snapshot of integration maturity
- Mark integrations conservatively as `working`, `working (beta)`, `partial`, `untested`, or `experimental`
- Make it easy to say things like "Slack is solid, Discord is not yet validated, BlueBubbles is partial" without hiding that reality inside roadmap prose

Intentional omission:

- **Gmail** left out of the matrix per current product direction ("on the way out")

### 2026-04-21 progress — high-level feature readiness page

Added a second transparency-oriented guide, **`docs/guides/feature-status.md`**, linked from `docs/index.md` and `mkdocs.yml`.

Purpose:

- Give users a product-level readiness map separate from the integration matrix
- Cover the high-level features people actually evaluate: discovery, self-improving agents, markdown/file memory, archived chat history, pipelines/heartbeats, provider support, widgets, extensibility, command execution, APIs, security posture, mobile/PWA, backup/setup, etc.
- Keep the labels blunt (`working`, `working (beta)`, `partial`, `advanced`, `experimental`, `deprecated`) instead of collapsing everything into a generic feature list

Follow-up refinement the same day:

- Split the page into **readiness** and **confidence** instead of pretending those are the same thing
- Confidence is now explicitly grounded in operator usage feedback (e.g. command palette = high confidence from constant use; usage tracking = working but medium confidence because cost estimates are best-effort; tool policies = works but not yet polished; webhooks = documented but low-confidence due to limited recent exercise)
- Added a **provider/model snapshot** subsection to `feature-status.md` so the page now captures operator-tested provider paths and model families (Claude via LiteLLM, anthropic-compatible MiniMax, Gemini via LiteLLM, GPT-5.4 via LiteLLM + openai-subscription, local Ollama models, image-generation paths, embeddings options).
- Final gap pass tightened the transparency matrix with several user-visible capabilities that were still undercounted: tool approval flow, temporal context awareness, scratch/side-thread sessions, push notifications, `run_script` programmatic orchestration, channel integration bindings/outbound delivery, and endpoint-catalog discoverability.
- Later truthfulness pass de-emphasized templates/activation as a primary product story, removed `Mission Control` + `Gmail` from promoted nav/index/README surfaces, added a dedicated `programmatic-tool-calling.md` guide for `run_script`, and marked the older client/voice surfaces as low-confidence rather than promoting them.

### What shipped in session 19 (Phase B finish + Phase D + Phase E nav)

**Phase D — all 7 missing guides created** (this session)

| New file | Size | Key content |
|---|---|---|
| `docs/guides/task-sub-sessions.md` | 147 lines | Mental model (channel / sub-session / bus), anchor cards (`inline` vs `sub_session` flavors), run modal + bottom-right dock, `sub_session_bus.resolve_bus_channel_id` walk, one-bus-two-filters diagram, lifecycle (tile click → pre-run → streaming → settle), follow-up-turn support via `resolve_sub_session_entry`, push-back composer as future work, ephemeral skill injection cross-link |
| `docs/guides/chat-state-rehydration.md` | 118 lines | `/api/v1/channels/{id}/state` snapshot shape, 10-min active-turn window + terminal-Message exclusion, pending-approval + orphan handling, `useChannelState` hook + `rehydrateTurn` idempotent seed + 3s ghost-grace, three fire moments (mount / `replay_lapsed` / tab-wake), migration 207 DB upsert/UPDATE, why the 256-event replay buffer went away |
| `docs/guides/pwa-push.md` | 128 lines | Install paths per platform (iOS 16.4+ PWA only), VAPID keypair setup, subscribe / unsubscribe flow via `/api/v1/push/*`, `send_push_notification` tool params + gating + prompting pattern, `only_if_inactive` + `/api/v1/presence/heartbeat` 2-minute window, `POST /api/v1/push/send` scoped endpoint for scripts, troubleshooting table |
| `docs/guides/dev-panel.md` | 123 lines | `/widgets/dev` four-tab layout (Library / Templates / Call tools / Recent), grouped tool list + `requires_bot_context` / `requires_channel_context` icons, sticky bot+channel picker + localStorage persistence, render + Raw-Result-stays-co-equal panels (honors feedback_raw_result_stays), Pin-to-dashboard flow, admin-execute local-only gate, Templates editor seed vs user fork |
| `docs/guides/providers.md` | 148 lines | All 7 provider types + feature matrix, per-type walkthroughs, ChatGPT Subscription OAuth detail (model allowlist, device-code flow, public Codex client_id, `OpenAIResponsesAdapter` translation, billing pre-fill), Ollama full capabilities, LiteLLM pricing pull, `openai-compatible` as escape hatch, Anthropic direct vs compatible |
| `docs/guides/homeassistant.md` | 130 lines | MCP-based architecture (Spindrel → HA MCP → HA), official vs community servers (intent-based vs low-level), `where: type=entity \| pluck: name \| first` targeting pattern, widget-by-widget walkthrough (`HassTurnOn/Off`, `HassLightSet` brightness slider, `ha_get_state`, `ha_search_entities`, `GetLiveContext` dashboard), shared `_ha_state_poll` anchor, carapace+skill bundle |
| `docs/guides/excalidraw.md` | 103 lines | Two-tool surface (`create_excalidraw` for JSON, `mermaid_to_excalidraw` for Mermaid), server-side Chrome + Node auto-deps, Chrome auto-detection order (setting → env → well-known paths), SVG-default / PNG-on-request, pin + lightbox widget, troubleshooting |

**Phase E — `index.md` + `mkdocs.yml` nav updated**

- `docs/index.md` — added 7 new rows to the Guides table in sensible neighborhoods (Providers next to Setup, Task Sub-Sessions next to Pipelines, Dev Panel next to Widget Templates, Chat State Rehydration next to Chat History, PWA/Push near Chat History, Home Assistant + Excalidraw next to Slack/Discord).
- `mkdocs.yml` — rebuilt `nav:` to cover the 30-doc catalog. Added `Pipelines` / `Task Sub-Sessions` / `Sub-Agents` / `Bot Skills` / `MCP Servers` / `Tool Policies` / `Command Execution` / `Widget Templates` / `Dev Panel` / `Chat State Rehydration` / `PWA & Push` / `E2E Testing` which had silently been missing from nav despite existing as docs. Moved Providers into Getting Started. Moved Slack/Discord/BlueBubbles/Gmail/HA/Excalidraw under Integrations. Renamed the Workflows entry to "Workflows (deprecated)". Every nav entry verified to exist on disk.

---

### What shipped in session 19 (Phase B finish)

**Phase B — closed**

- `docs/guides/bot-skills.md` — appended **Ephemeral Skill Injection (Pipelines, Tasks, and `@`-tags)** section covering:
  - `@`-tag flow (`resolve_tags` → `set_ephemeral_skills` → "Tagged skill context" block, one turn, bypasses similarity threshold).
  - Task `skills:` via `execution_config.skills` — injects "Webhook skill context" for the run without enrolling; pipelines swap skill bundles per-run.
  - Sub-session scope — pipeline runs are their own Session, so ephemeral skills don't leak to other conversations on the channel. Cross-link to [[Task Sub-Sessions]] (D-phase doc).
  - Mechanism-comparison table: Enrolled vs RAG vs `@`-tag vs `execution_config.skills`.
- `docs/setup.md` — added `openai-subscription` + `ollama` to the provider-types table, then added **ChatGPT Subscription (OAuth, no API key)** subsection under the Providers section: model allowlist (`gpt-5-codex`, `gpt-5`, `gpt-5-mini`, `o4-mini`), device-code connect walkthrough, pre-filled plan-billing config, ToS disclaimer, Codex-Responses-API-only caveat with the `OpenAIResponsesAdapter` translation note, public Codex CLI client_id explanation, disconnect behavior.

**Phase B entries already done prior to this session (re-audited)**

- `slack.md` — full Slack Depth coverage already present: App Home, Shortcuts, Modals, Ephemeral Replies (`respond_privately`), Reactions as Intents, Threads, scope table. Only remaining ask is the `slack-app-home.png` + `slack-modal.png` screenshots (Phase A).
- `widget-templates.md` — already has "Picking a mode" table with 3 modes (component template / HTML template / runtime `emit_html_widget`) and cross-links to [[html-widgets]] and [[widget-dashboards]] guides.

**Verification note — prove before propose**

Before writing the pipeline ephemeral-skills section, verified the mechanism against code:
- `app/routers/api_v1_admin/tasks.py:129,183` — `skills: Optional[list[str]]` on `TaskCreateIn` / `TaskUpdateIn`.
- `app/agent/tasks.py:1065-1072` — task loop reads `execution_config.skills`, calls `set_ephemeral_skills(...)` before context assembly.
- `app/agent/context_assembly.py:1160-1177` — injected as "Webhook skill context" into the system messages; explicitly filtered against `bot.skill_ids` so already-enrolled skills aren't double-injected.

Before writing the OAuth setup section, verified:
- `app/services/provider_drivers/openai_subscription_driver.py:44` — `CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"`.
- `app/routers/api_v1_admin/openai_oauth.py` — the 4 endpoints (start / poll / status / disconnect) mounted under `/providers/openai-oauth/...`.
- Tokens persist encrypted into `ProviderConfig.config['oauth']`; 10-min refresh leeway.

---

### What shipped in the 2026-04-19 continuation session

No screenshots captured (Phase A still requires e2e staging). Text-only work:

**Phase B — shipped**
- `docs/guides/workflows.md` — replaced with a deprecation stub pointing at `pipelines.md`. Explains the why, the mapping table (Workflows → Pipelines), and the migration steps.

**Phase C — shipped**
- `docs/index.md` — rewrote Features list: removed the stale Workflows bullet, added Widget Dashboards + HTML Widgets, Task Pipelines + Sub-Sessions, Chat State Rehydration, Sub-Agents, PWA + Push, ChatGPT Subscription provider, capability gating, `search_tools`. Updated subtitle. Added row for `widget-templates.md` and replaced the Workflows row with a Sub-Agents row.
- `docs/guides/api.md` — corrected scope table (pipelines use `tasks:*`, not a nonexistent `pipelines:*` scope). Added new "Channel State, Widgets, and Dashboards" section documenting `/api/v1/channels/{id}/state`, `/api/v1/widget-actions`, `/api/v1/widget-actions/refresh`, `/api/v1/widgets/dashboard`, `/api/v1/widget-auth/mint`, `/api/v1/favicon`.
- `docs/guides/how-spindrel-works.md` — added Capability Gating section, Semantic Tool Fallback section (`search_tools`), Pipelines + Sub-Sessions section, Workspace singleton section, Chat State Rehydration section, updated Key Concepts Summary table.
- `docs/guides/heartbeats.md` — clarified that `workflow_id` is deprecated, added pipeline-launch-from-prompt pattern using `run_pipeline`. Updated config reference table and Daily example.
- `docs/guides/delegation.md` — added Delegation vs Sub-Agents vs Pipeline Sub-Sessions comparison table.
- `docs/guides/chat-history.md` — added Rehydration on Reconnect section covering `/api/v1/channels/{id}/state` semantics.
- `docs/migration.md` — inline comment on the workspace root clarifying singleton model (`{root}/bot/{bot_id}/channels/{channel_id}/`).
- `docs/guides/mcp-servers.md` — admonition above the HA walkthrough pointing at the native `homeassistant` integration as an alternative.

**Verification note — prove before propose caught two errors**
1. Initially wrote `pipelines:read`/`pipelines:write` into `api.md` scope table. Verified against `app/services/api_keys.py` — no such scope exists. Corrected to retain `workflows:*` (still active on deprecated router) and added the note that pipelines authorize via `tasks:*`.
2. Initially wrote `pipeline_id` / `pipeline_session_mode` as heartbeat config fields. Verified against `app/db/models.py` + `app/services/heartbeat.py` — only `workflow_id` / `workflow_session_mode` exist on the Heartbeat model. Corrected: pipelines are launched from the heartbeat prompt via the `run_pipeline` tool (confirmed in `app/tools/local/pipelines.py:141,188`).

Also corrected an over-eager claim about the HA integration's widgets (wrote "camera snapshot" — not true, HA has light/switch widgets only; Frigate has the cameras).

---

## Phase A — Screenshot Punch List

All screenshots come from the **e2e instance** at `10.10.30.208`, not the production main instance. Stage real data before capturing. Widget dashboards need real pinned tool results; pipelines need a real run history.

### Flagship (must have — fresh captures)

| File | Route / State | Destination | Replaces |
|---|---|---|---|
| `home.png` | `/` with 4-5 channels, recent activity visible | `index.md` hero | — |
| `chat-main.png` | `/channels/<id>` with thinking indicator expanded, inline tool-result widget, OmniPanel rail showing 2 pinned widgets, Slack HUD in right panel | `index.md`, `how-spindrel-works.md` | `chat-screenshot-2.png` |
| `chat-pipeline-live.png` | `/channels/<id>/runs/<taskId>` PipelineRunLive modal mid-execution, 2 steps done + 1 running | `pipelines.md`, `index.md` | — |
| `widget-dashboard.png` | `/widgets/<slug>` with 6–8 pinned widgets (weather / web search / Frigate / image / Excalidraw), edit mode off | NEW `widget-dashboards.md` hero | — |
| `widget-dashboard-edit.png` | same dashboard, edit mode on, rail-zone guide lines visible | `widget-dashboards.md` | — |
| `html-widget-hero.png` | bot-built HTML dashboard (project-status archetype) showing `@botname` chip and live data tiles | NEW `html-widgets.md` hero | — |
| `dev-panel-tools.png` | `/widgets/dev#tools` with tool selected, args form filled, rendered envelope below | NEW `dev-panel.md`, `html-widgets.md` | — |
| `omnipanel-mobile.png` | mobile bottom sheet in "tall" snap, Widgets tab active | `index.md`, `how-spindrel-works.md` | — |

### Admin (must have)

| File | Route / State | Destination | Replaces |
|---|---|---|---|
| `admin-bots-list.png` | `/admin/bots` with 3+ bots, cost badges | `index.md`, `how-spindrel-works.md` | `bots-list-1-v1.png` |
| `admin-bot-edit.png` | bot editor on System Prompt tab | `how-spindrel-works.md` | — |
| `admin-providers.png` | `/admin/providers` showing all 7 provider types incl. `openai-subscription` | `setup.md`, NEW `providers.md` | `providers-screen-v1.png` |
| `admin-providers-oauth.png` | ChatGPT Subscription edit page mid device-code flow | NEW `providers.md` | — |
| `admin-tools-catalog.png` | `/admin/tools` with Library tab open | `custom-tools.md` | — |
| `admin-tasks-calendar.png` | `/admin/tasks` week view with 3-4 scheduled runs | `pipelines.md`, `heartbeats.md` | — |
| `admin-tasks-editor.png` | pipeline editor with 4-step pipeline, one step expanded | `pipelines.md` | — |
| `admin-integrations-list.png` | `/admin/integrations` with 6+ integrations, process status dots | `how-spindrel-works.md` | `integration-edit-v2.png` |
| `admin-learning.png` | `/admin/learning` overview with activity chart + skill ring + heatmap | `bot-skills.md` | `bot-skills-learning-1.png` |
| `admin-approvals.png` | `/admin/approvals` with 3 pending approvals | `how-spindrel-works.md` | `approval-gate-web.png` |
| `admin-mcp.png` | `/admin/mcp-servers` | `mcp-servers.md` | `mcp-list.png` |
| `admin-secrets.png` | `/admin/secret-values` with 4 entries | `secrets.md` | `secret-store.png` |
| `admin-usage.png` | `/admin/usage` with multi-provider chart | `usage-and-billing.md` | `usage-and-forecast.png`, `useage-alerts.png` |
| `admin-diagnostics.png` | `/admin/diagnostics` | `setup.md` | `security-diagnostics.png` |

### Feature / showcase

| File | Route / State | Destination |
|---|---|---|
| `pipeline-prerun-modal.png` | `/channels/<id>/pipelines/<id>` pre-run modal with 2 param fields | `pipelines.md` |
| `sub-session-anchor.png` | chat anchor card in parent channel pointing to running sub-session | NEW `task-sub-sessions.md` |
| `approval-inline-chat.png` | approval card inline in chat (not admin queue) | NEW `chat-state-rehydration.md` |
| `push-notification.png` | browser push notification from `send_push_notification` | NEW `pwa-push.md` |
| `channel-dashboard-rail.png` | OmniPanel left mini-view of the dashboard's rail zone | `widget-dashboards.md` |
| `setup-wizard.png` | setup wizard covering new provider type | `setup.md` (replaces all `setup-*.png`) |
| `slack-app-home.png` | Slack App Home tab rendered by Spindrel | `slack.md` |
| `slack-modal.png` | Slack Modal opened via `open_modal` tool | `slack.md` |
| `homeassistant-widget.png` | HA light-control widget with brightness slider | NEW `homeassistant.md` |
| `excalidraw-widget.png` | Excalidraw canvas inline in chat | NEW `excalidraw.md` |

### Widget catalog (one screenshot per template)

For `html-widgets.md` + `widget-dashboards.md`:

- `integrations/frigate/widgets/frigate_snapshot.html`
- `integrations/frigate/widgets/frigate_list_cameras.html`
- `integrations/frigate/widgets/frigate_events_timeline.html`
- `integrations/openweather/widgets/get_weather.html`
- `integrations/web_search/widgets/web_search.html`
- `integrations/excalidraw/widgets/create_excalidraw.html`
- `app/tools/local/widgets/image.html`

Plus **one bot-authored HTML dashboard** (not a template file) — ideally the project-status archetype used for the hero.

### Delete after replacement

- `workflow-editor-1.png`, `workflow-2-chat.png` — workflows deprecated; no replacement needed.
- `channel-integration-config.png`, `integration-chat-hud.png`, `integration-edit-v2.png` — pre-web-native HUD; replace with `admin-integrations-list.png` + `chat-main.png`.
- `setup-8-first-channel-2.png`, `setup-9-first-channel-2.png`, `ingestion-integration-1.png` — currently unreferenced; verify and delete.

---

## Phase B — Docs Rewrite / Major Edits

| File | Severity | Action |
|---|---|---|
| `guides/workflows.md` | **full rewrite** | Replace body with "Workflows are deprecated — see [Pipelines](pipelines.md)." Keep historical reference only. |
| `guides/bot-skills.md` | major edit | Add Task Sub-Sessions section and pipeline `skills:` ephemeral injection. Refresh learning screenshots. |
| `setup.md` | major edit | Add `openai-subscription` to provider table. Add OAuth device-code flow subsection. Swap all `setup-*.png`. |
| `guides/slack.md` | major edit | Expand ephemeral / modals / App Home / shortcuts / reactions to full Slack Depth coverage. Add `slack-app-home.png` + `slack-modal.png`. |
| `widget-templates.md` | major edit | Reframe opening to clearly separate three widget modes: (1) component template, (2) HTML template (per-tool), (3) runtime `emit_html_widget`. Cross-link to `html-widgets.md`. |

## Phase C — Minor Section Edits

| File | Action |
|---|---|
| `index.md` | Rewrite Features: remove Workflows bullet → replace with Pipelines. Add bullets for Widget Dashboards, HTML Widgets, Sub-Sessions, PWA/Push, Subagents, Auto-discovery, Capability gating. Swap hero image to `home.png`. |
| `guides/how-spindrel-works.md` | Add Task Sub-Sessions, capability gating, workspace singleton to the mental model. |
| `guides/heartbeats.md` | Add `pipeline_id` trigger (heartbeats can launch pipelines). Refresh `channel-heartbeat.png`. |
| `guides/templates-and-activation.md` | Workspace singleton context; remove per-bot scope wording. |
| `guides/delegation.md` | Add comparison: `delegate_to_agent` vs `spawn_subagents` vs Sub-Sessions. |
| `guides/api.md` | Add `/api/v1/channels/{id}/state`, `/api/v1/widget-actions`, `/api/v1/widgets/dashboard`, `/api/v1/pins/layout`, `/api/v1/favicon`, `/api/v1/widget-auth/mint`. |
| `guides/chat-history.md` | Add Chat State Rehydration snapshot + approval queue. |
| `migration.md` | Workspace singleton narrative; single `/workspace/` path. |
| `guides/mcp-servers.md` | Note that HA now has an in-tree integration as an alternative to ha-mcp. |

**Leave alone (already current):** `guides/pipelines.md`, `guides/subagents.md`, `guides/html-widgets.md` (intro level; supplement with new `dev-panel.md` deep-dive), `guides/widget-dashboards.md`, `guides/ingestion.md`, `docker-deployment.md`, `backup.md`, `reference/architecture.md`, `reference/rag-pipeline.md`, all `integrations/*` docs.

## Phase D — Missing Docs to Create

Each new file gets a purpose line + bullet outline so the writing session has a blueprint.

1. **`docs/guides/task-sub-sessions.md`** — pipeline-as-chat metaphor, modal vs bottom-dock, parent/child event routing via `sub_session_bus`, anchor cards, push-back composer.
2. **`docs/guides/chat-state-rehydration.md`** — `/api/v1/channels/{id}/state` snapshot, `useChannelState` + `rehydrateTurn`, approval pipeline, orphan card handling, reconnect/replay.
3. **`docs/guides/pwa-push.md`** — installing the PWA, enabling browser push, using `send_push_notification` from bots, subscription management, `POST /api/v1/push/send`.
4. **`docs/guides/dev-panel.md`** — `/widgets/dev`, Tools sandbox, Recent tab, Templates editor, bot/channel context selectors, Pin flow, MCP execute restriction.
5. **`docs/guides/providers.md`** — full provider catalog (7 types), feature matrix (OAuth / API key / local / streaming / tool-call / plan-billing), ChatGPT Subscription OAuth walkthrough, plan-billing note, model allowlist.
6. **`docs/guides/homeassistant.md`** — HA MCP setup, entity selection via `where: type=entity | pluck: name | first`, light/switch widgets (HassTurnOn/Off + HassLightSet with brightness slider), GetLiveContext state poll.
7. **`docs/guides/excalidraw.md`** — diagram-in-chat integration (runs in Chrome on the server), widget embed, collaborative canvas.
8. **`docs/guides/capabilities.md`** *(optional — may be folded into `how-spindrel-works.md`)* — promote carapaces section into its own guide; capability gating, auto-discovery, approval pipeline, `search_tools` as semantic fallback.
9. **`docs/guides/workspace-files.md`** *(optional — may fold into migration or how-spindrel-works)* — workspace singleton model, `file` tool, `/workspace/` path grammar, channel vs bot roots, DX-5b caveats.

Ship (1)–(7) in phase D. (8) and (9) are candidates to split later if the existing docs grow too dense.

## Phase E — Index + Nav Updates

- `docs/index.md` — replace hero image, rewrite Features list, add table rows for each new guide (1)–(7), replace "Workflows" row with a deprecation note pointing at Pipelines.
- Check for `mkdocs.yml` in the repo root — if present, update `nav:`. If not, the `index.md` table drives nav.
- `docs/CNAME` — no action.

## Phase F — Cleanup

- Delete orphan / unreferenced images after replacements land.
- `grep -rn "workflow" docs/ --exclude=workflows.md` — retarget surviving mentions to `pipelines.md`.
- `grep -rn "per-bot workspace\|workspace bot" docs/` — rewrite to singleton.
- `grep -rn "Metro\|React Native\|Expo" docs/` — retarget.

---

## Showcase Content Blocks (referenced by multiple docs)

### Supported Providers (for `providers.md` + `index.md`)
- `litellm` — LiteLLM proxy (100+ providers via unified API)
- `openai` — OpenAI API (GPT-4, GPT-3.5, GPT-5 family)
- `openai-compatible` — OpenAI-compatible proxies (Ollama, vLLM, OpenRouter)
- `anthropic` — Anthropic API (Claude)
- `anthropic-compatible` — Anthropic-compatible proxies
- `ollama` — Ollama (local model runner)
- `openai-subscription` — ChatGPT OAuth device-code flow, plan billing, Codex Responses API

Feature matrix columns: OAuth / API-key / local / streaming / tool-call / plan-billing / cost-tracked.

### Supported Integrations (for `index.md` + integration landing)

One-liner per integration, pulled from each `integrations/<name>/integration.yaml`:

- `arr` — Sonarr / Radarr / Lidarr media automation
- `bluebubbles` — iMessage via BlueBubbles
- `claude_code` — Claude Code CLI integration
- `discord` — Discord bot (text + voice)
- `excalidraw` — Collaborative whiteboard, diagram-in-chat
- `firecrawl` — Web scraping via Firecrawl
- `frigate` — NVR cameras + detections + event timeline
- `github` — PRs, issues, code push, releases
- `gmail` — Email ingestion + digest
- `google_workspace` — Docs, Sheets, Drive
- `homeassistant` — Device control + automations
- `ingestion` — Content feeds + security pipeline
- `mission_control` — Orchestration dashboard
- `openweather` — Weather + forecasts
- `slack` — Socket Mode bot with Slack Depth (ephemeral, modals, App Home, reactions, shortcuts)
- `vscode` — VS Code integration
- `web_search` — SearXNG / Tavily / DuckDuckGo
- `wyoming` — STT / TTS over Wyoming protocol

### Showcase Widgets (for `widget-dashboards.md` + `html-widgets.md`)
`frigate_snapshot`, `frigate_list_cameras`, `frigate_events_timeline`, `get_weather`, `web_search`, `create_excalidraw`, `image`, plus one bot-authored HTML dashboard (archetype: project status / recent-activity feed / tool-trigger control panel / embedded KB reader).

### Showcase Pipelines (for `pipelines.md`)
- One audit pipeline end-to-end — `analyze_discovery` is the most legible
- One scheduled task — a daily digest is the most relatable

---

## Key invariants

- **Never cite "freeze" as a scope cap.** The freeze is on new features/mechanisms/tables — not on docs accuracy.
- **Docs-refresh is polish work and fully in-scope.**
- **Screenshots come from the e2e instance** (`10.10.30.208`), not the production main instance. See `feedback_never_touch_main_instance.md`.
- **Widget dashboards require real pinned tool results** — stage them on e2e before capturing.
- **Pipelines require a real run history** — stage via `run_pipeline` on e2e.
- **Slack Depth screenshots require a live Slack workspace** — can use the existing dev workspace tied to e2e.

## References

- Current docs inventory: `/home/mtoth/personal/agent-server/docs/`
- Current images: `/home/mtoth/personal/agent-server/docs/images/` (37 files)
- Feature catalog: [[Roadmap]] (Active + Completed sections)
- Widget files: `integrations/*/widgets/*.html`, `app/tools/local/widgets/*.html`
- UI routes: `ui/app/(app)/` file-based routing (react-router v7)
- New features since 2026-04-07: session logs in `vault/Sessions/agent-server/2026-04-{12..19}-*.md`
- Planning file: `~/.claude/plans/jazzy-honking-quiche.md`
