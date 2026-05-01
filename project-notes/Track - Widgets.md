---
tags: [agent-server, track, widgets, dx]
status: active
updated: 2026-05-01 (widget stream load-shedding)
---
# Track — Widget System DX + Robustness

## North Star
Make the tool widget definition system a **first-class, documented, validated, and low-friction** surface — so adding a widget is a 10-minute task, malformed templates fail at registration (not runtime), and new features extend the system instead of bypassing it.

Reference doc: [[Widget Authoring]]. Implementation artifact: plan file at `~/.claude/plans/deep-plotting-mochi.md` (review + prioritized roadmap). Flagship catalog plan: `~/.claude/plans/happy-cuddling-noodle.md`.

## Status

| # | Phase | What | Status |
|---|-------|------|--------|
| P0-3 | Docs + track file | [[Widget Authoring]] reference + this file | **done** (2026-04-17) |
| P0-1 | Component-tree schema | Pydantic model + registration-time validation | **done** (2026-04-17) — JSON Schema artifact + TS hoist deferred (see §Follow-ups) |
| P0-2 | Tool output schemas | Declare `output_schema` on tools; static `{{var}}` resolution checks | deferred |
| P1-1 | Template fragments + state_poll default | `fragments:` block, `{type: fragment, ref}` resolver, `state_poll.template` defaults to `template` | **done** (2026-04-17) — `with:` overlays deferred (see §Follow-ups) |
| P1-2 | Expression grammar | `and` / `or` / `not` / ternary in `{{...}}` | deferred |
| P1-3 | Extensible pipe-filter registry | Integrations declare `widget_filters:` in manifest | deferred |
| P1-4 | Unify TaskRunEnvelope / InlineApprovalReview | Route task widgets through MIME dispatch | deferred |
| P2-1 | Separate `display_label` from key-carry | Add explicit `context:` block | deferred |
| P2-2 | `display: panel` end-to-end | Define panel host, route envelopes | deferred |
| P2-3 | Pinned-widget envelope write-back | Persist state_poll refresh into `channel.config.pinned_widgets` | deferred |
| P2-4 | Registration-time test harness | Render every `sample_payload`; CI guardrail | deferred |
| P2-5 | Hot-reload manifest widgets | Parity with DB-backed packages | deferred |
| P2-6 | Admin playground | In-app widget preview + live validation | deferred |
| P3-1 | HTML widget catalog + frontmatter | Workspace scanner for `**/widgets/**/*.html` + files referencing `window.spindrel.*`; YAML frontmatter convention in leading HTML comment; "HTML widgets" tab on `AddFromChannelSheet`; dev-panel Library restructured into Tool renderers vs HTML widgets sections | **done** (2026-04-19) |

## Follow-ups (extracted from P0-1 / P1-1 shipping)

- **Widget stream load-shedding shipped** (2026-05-01) — HTML widgets now prefer the host channel stream broker even during iframe startup by waiting briefly before direct SSE fallback, and the broker clears stale same-iframe subscriptions on probe plus replaces duplicate sub ids. Direct fallback still works for standalone/no-host widgets but clears reconnect timers on unsubscribe. Large active chat streams also throttle live markdown/transcript rendering past 8k chars so token bursts do not force full markdown reparses every frame. New invariant: channel dashboards should have one host channel SSE plus broker fan-out, not one direct `/widget-actions/stream` socket per pinned iframe.
- **Spatial widget stewardship exact-preview guard shipped** (2026-04-30) — bot-owned Spatial Canvas widget tools now enforce the full loop: inspect the scene, preview the exact intended pin/move/resize/remove operation, then mutate only if the previewed action/target/widget and material parameters match. This closes the "bot made a pile of useless widgets" gap by making the skill/preset/tooling prove its intended visual change before creating or moving channel-orbit widgets.
- **Channel widget projection + dashboard canvas polish shipped** (2026-04-30) — channel-associated widgets now auto-project across the channel dashboard and Spatial Canvas in both directions, with paired delete/unpin semantics and shared native widget instances where applicable. The channel dashboard canvas keeps grid-cell persistence but makes interaction more spatial: deeper/slower zoom, click-only spatial handoff, exact Spatial Canvas backdrop, a dedicated Frame dashboard control, fixed-size move handles for narrow tiles, live resize preview, stable guide labeling, and farther/clearer nearby-channel ghosts.
- **Channel dashboard freeform canvas shipped** (2026-04-29) — desktop channel dashboards now render on a spatial-style pan/zoom canvas with current-size max zoom, fit/actual-size controls, freeform placement outside the guided header/rail/dock lanes, a one-time `grid_config.canvas_mode=freeform_v1` origin marker so existing layouts do not jump, viewport-centered placement for newly added widgets, and an explicit click-only handoff to the Spatial Canvas after deep zoom-out. The canvas reuses the Spatial Canvas starfield/grid background, keeps nearby channel ghosts outside the guided frame with real channel names/colors, and the pin host exposes compact header-lane chips plus a larger edit-mode move handle for narrow or iframe-heavy widgets. The refreshed `channel-widget-usefulness` screenshot bundle captures the freeform dashboard surface.
- **In-context widget authoring receipts shipped** (2026-04-29) — bots can now finish create/update/debug/check/improve runs with `publish_widget_authoring_receipt`, which reuses the durable widget receipt table but marks rows as `kind=authoring` and captures library refs, touched files, health status/summary, check phases, screenshot evidence when compact enough, affected pins, and next actions. The widget usefulness drawer/settings summary now show recent bot widget activity rather than only bot-applied changes, and the widget skill set gained `widgets/authoring_runs` so the bot loop has an explicit receipt step after full checks and pin health.
- **Bot widget authoring DX spine shipped** (2026-04-29) — bot-authored widget work now starts with `prepare_widget_authoring`, then uses `check_html_widget_authoring` or `check_widget_authoring` before emit/pin, and finishes with `check_widget` only after a real pin exists. The agent-capability manifest now exposes widget-authoring readiness, missing tools/skills, and the HTML/tool-widget check availability, and the shared Agent readiness UI shows that status in bot/channel/composer surfaces. Standalone HTML/library widgets can declare metadata in HTML frontmatter and run the same preview/static/runtime health path before pinning. New screenshot artifact: `channel-widget-authoring-readiness.png` in the `channel-widget-usefulness` bundle verifies the settings Agent readiness row and HTML full-check badge.
- **Widget health loop shipped** (2026-04-29) — pinned and draft widgets now have a first-class health read model through `widget_health_checks`, `check_widget`, `check_dashboard_widgets`, and `/api/v1/widgets/.../health` routes. Health combines static envelope/source lint, recent per-pin debug events, and opportunistic browser smoke when the local browser runtime is configured; dashboard pin reads, `describe_dashboard`, chat-side widgets, full-page pins, and the dashboard page now surface the latest health summary. New invariant: bots should preview/check widgets before or immediately after pinning, and use `inspect_widget_pin` only when health indicates raw trace evidence is needed.
- **Widget authoring runtime feedback shipped** (2026-04-29) — draft tool-widget YAML now has one shared authoring check behind `/api/v1/admin/widget-packages/authoring-check`, the Templates tab **Full Check** button, and the bot-facing `check_widget_authoring` tool. The check validates YAML/Python/schema, renders the preview envelope, runs static health, and can open the draft envelope in the real widget host through Playwright with screenshot artifacts. New invariant: tool-widget authors should not treat live preview as enough; use the shared full check before saving or relying on a new renderer.
- **Widget usefulness recommendation layer shipped** (2026-04-29) — channel dashboards now have a shared read-only usefulness assessment through `assess_widget_usefulness` and `/api/v1/admin/channels/{channel_id}/widget-usefulness`. The assessment combines pin layout, latest health, duplicate/overlap signals, chat visibility under channel layout mode, context-export coverage, actionability hints, and Project-bound metadata. New invariant: recurring widget improvement should start with this structured assessment, then use health/trace tools only for deeper evidence. Agency is not global: some bots/channels/widgets may later be allowed to apply changes, while others stay propose-only, and that must be governed by policy rather than a single system-wide toggle.
- **Widget agency policy shipped** (2026-04-29) — channel settings now carry `widget_agency_mode` with `propose` as the default and `propose_and_fix` as the opt-in for bot-applied dashboard fixes. Bot-facing channel-dashboard mutation tools enforce this server-side for channel dashboards, so scheduled widget healthchecks can run with approval skipping while still falling back to proposals unless the channel explicitly allows fixes. The quick Widget Improvement Healthcheck now posts channel-visible proposals/receipts and can use safe dashboard tools only when policy permits.
- **Widget agency receipts shipped** (2026-04-29) — bot-applied channel-dashboard changes now persist as `widget_agency_receipts` with action, reason, affected pins, compact before/after snapshots, bot/session/correlation/task metadata, and a channel API. Dashboard mutation tools accept an optional `reason` and record receipts only for channel dashboards. The usefulness UI now only lists one-click **widget fixes**; advisory-only findings stay out of that drawer until they have a direct apply action, while recent bot widget activity remains visible as receipts.
- **Widget improvement bot-loop E2E shipped** (2026-04-29) — `tests/e2e/scenarios/test_widget_improvement_loop.py` now proves the full usefulness loop through real bot/task execution. It seeds duplicate native dashboard pins, creates ordinary scheduled tasks from the `widget_improvement_healthcheck` run preset, verifies `propose` mode produces proposals without mutation or receipts, verifies `propose_and_fix` mode removes a duplicate and records an `unpin_widget` receipt, and smoke-tests a chat-triggered usefulness request with no mutation.
- **Human-facing widget usefulness review shipped** (2026-04-29) — channel dashboards now show a read-only usefulness review strip/drawer backed by the shared assessment, with safe focus/edit-layout/settings actions only. Channel Settings -> Dashboard shows the same assessment as a compact summary above dashboard configuration. New screenshot bundle: `channel-widget-usefulness` captures the dashboard strip, drawer, and settings summary; it stages real dashboard pins and uses a narrow browser shim for the assessment endpoint while the shared e2e API lags this branch.
- **Widget improvement preset shipped** (2026-04-29) — Channel Settings -> Tasks can create a weekly `Widget Improvement Healthcheck` scheduled task from the quick automations launcher. It preloads the widget skills and read-only inspection tools into a normal channel-scoped task, keeping heartbeat free for general channel work while still giving widget-heavy channels an easy recurring review path. The launcher and desktop/mobile review drawer are covered by the `channel-quick-automations` screenshot bundle.
- **Dashboard pin config NUX shipped** (2026-04-29) — `EditPinDrawer` now leads with schema-backed Widget settings, hides raw JSON behind Advanced JSON by default when schema coverage is complete, and keeps JSON visible for unsupported/missing schema cases. The dashboard route supports `?edit_pin=<pin_id>` so screenshots and links can open a pin editor directly. New screenshot bundle: `dashboard-pin-config-editor` captures desktop and mobile editor states against a staged real channel dashboard pin.
- **Widget refresh load-shedding shipped** (2026-04-28) — pinned and inline widgets now auto-refresh only when their contract/envelope is state-poll capable, visible, and expanded; background-tab and offscreen refreshes are paused; refresh timers use jitter; and frontend requests coalesce through `/widget-actions/refresh-batch`. The backend batch endpoint deduplicates identical state-poll work without crossing bot/channel identity boundaries, then applies each widget's own metadata and persists refreshed dashboard pin envelopes.
- **Widget contract model is now explicit and canonical** (2026-04-22) — `app/services/widget_contracts.py` now normalizes the public widget model into `definition_kind`, `binding_kind`, `instantiation_kind`, `auth_model`, `state_model`, `refresh_model`, `theme_model`, `supported_scopes`, and `actions`, with optional `config_schema` alongside it. This contract now ships on tool previews, widget presets, library/catalog entries, native widgets, and persisted pins so the UI/docs no longer need to infer behavior from source paths or runtime heuristics.
- **Dashboard pins now persist canonical widget provenance** (2026-04-23) — `widget_dashboard_pins` now carries `widget_origin`, `provenance_confidence`, `widget_contract_snapshot`, and `config_schema_snapshot`. Pins created with explicit caller-supplied origin are written as `authoritative`; inferred/legacy rows stay `inferred` and self-heal on read. Load-bearing invariant: pin reads should resolve metadata from `widget_origin` first and fall back to snapshots, not reconstruct everything from envelope heuristics.
- **Runtime config vocabulary is now `widget_config` first** (2026-04-23) — the widget template engine now exposes `result.*`, `widget_config.*`, `binding.*`, and `pin.*`, while keeping `config.*` only as a compatibility alias. HTML-backed tool widgets now expose `window.spindrel.result`, `window.spindrel.widgetConfig`, and `window.spindrel.widgetContext`; `window.spindrel.toolResult` remains the compatibility object for older widgets.
- **Canonical runtime vocabulary cleanup follow-through shipped** (2026-04-23) — the remaining public docs, UI comments, and shipped HTML widgets were updated to use `{{widget_config.*}}` and `window.spindrel.result` / `window.spindrel.widgetConfig` as the primary language. Frigate/OpenWeather/Excalidraw/core HTML widgets still tolerate `toolResult` where compatibility matters, but the primary exemplars and tests are now canonical-first.
- **Presentation intent is now a first-class contract** (2026-04-23) — widget metadata now carries `widget_presentation` alongside `widget_contract`, with `presentation_family`, `panel_title`, `show_panel_title`, and `layout_hints` resolved across tool widgets, HTML widgets, native widgets, presets, and serialized pins. New invariant: semantic/runtime kind lives in `widget_contract`; authored host-surface intent lives in `widget_presentation`.
- **`layout_hints` now have one real meaning** (2026-04-23) — generic pin creation and both dashboard editors now consume `widget_presentation.layout_hints` the same way: `preferred_zone` seeds initial placement when callers do not pass an explicit zone, and `min_cells` / `max_cells` clamp default tile size plus later resize bounds. New invariant: `layout_hints` are host placement/size defaults, not a proxy for widget-internal responsiveness.
- **Dashboard pins now snapshot presentation metadata too** (2026-04-23) — `widget_dashboard_pins` now persists `widget_presentation_snapshot` beside the existing provenance/contract/schema snapshots. New invariant: pin recovery should not have to rediscover chip/card/panel intent or panel-title metadata from fragile envelope fields when the live source is unavailable.
- **Host rendering now resolves through one policy object** (2026-04-23) — frontend pinned-widget rendering now threads a resolved host policy (`zone`, `presentationFamily`, `wrapperSurface`, `titleMode`, hover-scrollbar behavior, fill-height) instead of reading dashboard chrome, panel metadata, and per-pin title flags ad hoc in multiple places. New invariant: placement zone, authored presentation, and host chrome are separate inputs that collapse only at the final render boundary.
- **Canonical taxonomy is now definition-kind first** (2026-04-22) — the product language is locked around `tool_widget`, `html_widget`, and `native_widget`, with presets treated as an instantiation path rather than a fourth widget kind. Load-bearing invariant: a YAML tool widget using `html_template` is still a tool widget, not a standalone HTML widget.
- **Component-widget design language is now part of the contract** (2026-04-23) — component/YAML widgets should render as low-chrome native controls, not debug visualizations. Cards adapt across compact/standard/expanded density from host layout/size; chip widgets remain explicit chip variants. New component hints: common `priority`, `properties.variant=metadata`, and toggle `description` / `on_label` / `off_label`.
- **Shared widget-sync protocol is now source-aware** (2026-04-23) — cross-surface envelope broadcasts now carry a source signature (`tool_name + widget_config`) plus update kind (`state_poll` vs `tool_result`). `PinnedToolWidget` uses that to adopt same-signature poll updates, ignore different-config sibling polls, and only locally re-poll on foreign tool-result invalidations. Load-bearing invariant: duplicate refreshable widgets for the same entity must not trigger recursive `/widget-actions/refresh` storms.
- **HA preset variant contract tightened** (2026-04-23) — `toggle_chip` and `light_card` are now distinct in the actual renderer contract, not just in preset names. Brightness is exclusive to `light_card`; `toggle_chip` for a light must stay a pure toggle chip; runtime “show/hide brightness” buttons were removed because the preset/builder config already owns that choice.
- **Canonical widget inventory started and modernized** (2026-04-23) — `agent-server/docs/reference/widget-inventory.md` now tracks shipped native widgets, core/local tool widgets, core/local HTML bundles, integration tool widgets, and preset entry points with a standard-alignment status (`Current`, `Partial`, `Legacy`, `Needs audit`). The native section was later expanded in the same day to cover the real shipped set rather than just Notes/Todo, and the inventory now also marks the standalone HTML `context_tracker` bundle as legacy/superseded by the native surface.
- **Canonical widget-system doc now names the shipped native widgets concretely** (2026-04-23) — `docs/guides/widget-system.md` now includes a "shipped native widgets" section that spells out the current native refs, primary scope, and where authoritative data lives (`widget_instances.state`, shared host/file state, or transcript/planning state in the special `core/plan_questions` case). New invariant: people should not have to read `native_app_widgets.py`, `pinned_panels.py`, and plan-mode docs side-by-side just to know whether a native widget is instance-backed or transcript-native.
- **Agent Smell joined the native dashboard set** (2026-04-25) — `core/agent_smell_native` is a first-party dashboard widget backed by live host aggregation from trace events and tool calls, not widget-local persistence. New invariant: investigation widgets that expose trace evidence should route evidence clicks through the shared trace inspector.
- **Mission Control snapshot replaced the Command Center native payload** (2026-04-28) — `core/command_center_native` keeps its widget ref for compatibility but now labels/renders as Mission Control. It reads `/workspace/mission-control` and summarizes active missions, bot lanes, Attention signals, and spatial readiness. It is convenience UI only and does not export prompt context.
- **GitHub Repo Dashboard joined the preset catalog** (2026-04-27) — `integrations/github` now ships a React tool widget + `github-repo-dashboard` preset over `github_repo_dashboard`. It shows repo health, commits, PRs, issues, latest workflow runs, and latest release; channel pins can infer `github:owner/repo`, while world pins use the new custom-capable repo picker. Issue close/reopen is intentionally narrow and confirmation-gated through `github_set_issue_state`, with widget tool dispatch now running policy checks before invocation.
- **Full-page pin host now honors available height** (2026-04-27) — `/widgets/pins/:pinId` no longer carries the old dashboard-detail desktop height cap, and HTML widget iframes explicitly allow sandboxed popup escapes for `_blank` external links while still blocking top navigation. Invariant: fullscreen pin pages should let the host flex column own height; external links belong in new tabs, not iframe top navigation.
- **Pinned-widget context export is now an explicit contract, not a `plain_body` side effect** (2026-04-23) — `widget_contract.context_export` now normalizes across native widgets, tool-widget definitions, and HTML manifests with `enabled`, `summary_kind`, and `hint_kind`. Chat-profile assembly reads serialized channel-dashboard pins, enriches only export-enabled widgets, and injects concise live summaries plus optional action hints; `describe_dashboard()` now exposes the same `context_summary` / `context_hint` rows for inspection. New invariant: only widgets that explicitly opt into context export are allowed into the prompt, and native widgets should summarize authoritative live state rather than stale preview copy.
- **Pinned-widget context is now visible in debug surfaces and can be disabled per channel** (2026-04-23) — the shared pinned-widget export path now produces a structured snapshot (`rows`, `skipped`, char counts, exact prompt block) that powers chat `/context`, admin `context-preview`, prompt assembly, and context estimation. Channels now expose `pinned_widget_context_enabled` in settings/config, defaulting to on but explicitly suppressing prompt injection when off. New invariant: pinned-widget context should be inspectable as data, not inferred from one synthetic system block, and channel authors own whether their dashboard acts as chat context.
- **Preset zone hints are now host-real, not aspirational** (2026-04-23) — `preferred_zone: chip` no longer dies as a conceptual hint while pinning into grid. Preset pinning now resolves `chip -> header` with a `4x1` default layout, and `header` itself is defined as a floating two-row top rail. Load-bearing invariant: `chip` is an authoring alias / compact widget family, not a persisted dashboard zone.
- **Dashboard pin editing is now schema-aware where possible** (2026-04-22) — `EditPinDrawer` renders simple typed controls from `config_schema` before falling back to raw JSON, which closes the most obvious DX gap in per-pin config editing.
- **Known follow-up: persisted instantiation provenance is still incomplete** (2026-04-22) — preset-created pins now stamp `source_instantiation_kind="preset"`, but older pins and some non-preset pin flows are still inferred best-effort on read. A future hardening pass should persist instantiation/source metadata across every pin creation path.
- **Preset dependency boundaries now validate at registration** (2026-04-23) — `widget_presets:` can declare `tool_family` plus explicit `tool_dependencies`; `app/services/widget_presets.py` validates that the backing tool, binding-source tools, and explicit dependencies stay inside the declared family and rejects invalid binding schemas. Serialized presets expose `dependency_contract` so UI/bots can see the family/tools before placement.
- **Home Assistant presets are now official-lane only** (2026-04-23) — all four HA presets render through `GetLiveContext`, bind options via `GetLiveContext`, and target official action tools by friendly name (`HassTurnOn`, `HassTurnOff`, `HassLightSet`). Community `ha_get_state` remains a standalone community-lane tool widget but is not part of these presets. New invariant: one HA preset should never silently require both HA MCP server families.
- **Older widget entries backfilled to current standard** (2026-04-23) — added missing `sample_payload` / `config_schema` coverage across HA, GitHub, Frigate snapshot, OpenWeather, and Web Search so dev preview and dashboard config surfaces have real contracts instead of guesswork.

- **Home Assistant adaptive entity widget landed** (2026-04-22) — `integrations/homeassistant/integration.yaml:ha_get_state` now renders four shapes off one tool contract: sensor card, light card, toggle chip, and generic entity/value chip. `state_poll.args.entity_id` reads `{{config.entity_id}}`; `app/services/dashboard_pins.py` seeds that config from `display_label` once at pin-create time so refresh no longer depends on label scraping after the pin exists.
- **Widget presets landed as a first-class surface** (2026-04-22) — integrations can now declare `widget_presets:` alongside `tool_widgets:`. `app/services/widget_presets.py` resolves preset metadata, binding-source options, preview, and pinning through the existing widget engine, and `/api/v1/widgets/presets*` powers both Add Widget and `/widgets/dev`. New invariant: presets own guided binding inputs; tool renderers remain the advanced “render a tool result” path.
- **Preset binding sources now execute through shared tool-name normalization** (2026-04-22) — the Home Assistant picker failure (`Tool 'GetLiveContext' not found`) came from preset bindings executing manifest-declared bare tool names literally while runtime MCP tools were namespaced (`homeassistant-GetLiveContext`). `app/services/tool_execution.py` now resolves canonical tool names before both context validation and execution, and widget-actions/admin direct tool execution reuse that same path instead of carrying parallel MCP-prefix logic. New invariant: preset bindings, widget actions, and other non-agent runtime callers all share the same bare-name MCP recovery path.
- **Widget Builder is now route-backed instead of local-modal state** (2026-04-22) — the dashboard page now drives the Add Widget surface off URL state (`builder`, `builder_tab`, `builder_q`, `builder_preset`, `builder_step`) so refresh/back-forward restore the open builder and selected preset flow. The old narrow side sheet is restyled into a wide bottom-attached overlay and the presets pane now uses a 3-region builder layout (catalog / configure / preview) instead of stacking everything into one cramped column.
- **Preset builder fallback/layout hardening** (2026-04-22) — `WidgetPresetsPane` no longer flips the whole configure form into manual-entry mode off one shared source-error string; picker fallback is now field-specific so unrelated fields keep their real options. Builder mode also uses the safer responsive split again: `xl` two-column with preview below, `2xl` three-column. Invariant: stacked/early-split modes should stay normal document flow; split-pane overflow behavior belongs only at the widest layout.
- **Generic entity-property selection is the right `Entity Chip` abstraction** (2026-04-22) — after browser review, the Home Assistant `Entity Chip` flow was corrected away from scene/domain filtering. The preset should keep all entities available and instead expose dependent property pickers driven from the selected entity option's metadata (`meta.properties`, e.g. `name`, `state`, `last_changed`, `last_updated`, `attr:<key>`). Invariant: generic entity presets stay broad; integration-specific variants like Light Card can narrow the entity set, but the reusable builder pattern for generic entities is "bind resource first, then choose which surfaced properties to render."
- **Preset builder interaction model tightened** (2026-04-22) — the builder pane now treats preset switching as optimistic local UI state even though the selection is also mirrored into route params, uses searchable portal pickers for binding fields instead of native selects, and auto-runs preview once required fields are satisfied. Invariant: the builder should feel like a live configurator, not a form that requires hidden/offscreen submit steps before anything responds.
- **Preset builder preview/pin hardening** (2026-04-22) — follow-up browser debugging exposed three concrete regressions after the initial builder interaction pass:
  - preset pinning crashed in `pin_dashboard_widget_preset()` because the route called `preview_envelope_to_dict(...)` without importing it
  - the first optimistic preset-selection implementation could still roll a click back immediately by mirroring stale controlled URL state into local state
  - builder preview was still forcing `RichToolResult` through a no-op dispatcher, so Home Assistant toggles/sliders rendered but could not dispatch real actions
  Fixes landed in the shared runtime path:
  - the pin route now imports the serializer correctly
  - controlled `selectedPresetId` only syncs into optimistic local state when that prop actually changes
  - builder preview now passes real `channelId` / `botId` context into `RichToolResult`
  - Home Assistant `ha_get_state` now emits shared `chip_text`, `chip_color`, and `toggle_target_entity_id` fields so preview and `state_poll` stay aligned and actions target the exact entity id
  New invariant: builder preview must use the same widget-action dispatch path as live widgets; never fake interactivity in preview with a no-op dispatcher.
- **Transform-only preset previews + stacked-flow scrolling** (2026-04-22) — a later browser pass exposed that some preset widgets were still only previewing correctly by accident:
  - `render_preview_envelope()` only applied code transforms when a widget already had a static `template.components` list, which broke transform-first widgets like Home Assistant `ha_get_state`
  - stacked builder mode still had overflow clipping in places where it should have behaved like normal document flow
  - tool actions inside builder preview needed to refresh back into the preset preview, not leave the surface on the action tool's envelope
  Fixes:
  - preview rendering now runs transforms against an empty component list when there is no static template
  - builder preview owns its local interactive state again: widget-config actions patch local config + rerun preview, tool actions dispatch then rerun preview
  - stacked builder flow now allows vertical overflow, with `overflow-hidden` reserved for the wider split layouts only
  New invariant: transform-driven widgets must preview correctly even with no static top-level template, and stacked builder mode should behave like a scrollable document, not a prematurely split pane.
- **Canonical widget-system docs + in-product contract surfacing** (2026-04-22) — added `agent-server/docs/guides/widget-system.md` as the single system-level explanation and changed the surrounding widget docs to point back to it instead of each re-explaining taxonomy in slightly different terms. The library preview and pin editor now surface an explicit runtime contract view covering runtime kind, auth actor, state authority, refresh model, theme path, and declared actions. New invariant: the human UI should expose the same widget-lane distinctions that were already present in the runtime/API contract, especially the difference between presets, tool renderers, HTML widgets, and native widgets.
- **Preset binding-option requests no longer depend on dotted path segments** (2026-04-22) — `POST /api/v1/widgets/presets/{preset_id}/binding-options` now accepts `source_id` in the JSON body, with the old `.../binding-options/{source_id}` path kept for compatibility. Frontend calls the body-based route first and falls back to the legacy path on 404 so `homeassistant.entities`-style ids stop depending on proxy/path behavior.
- **Widget Builder chrome should match the chat dock shell, not modal cards** (2026-04-22) — use one strong outer container with square edges and sparse separators, then keep catalog / configure / preview panes visually adjacent instead of wrapping each region in its own rounded bordered card.
- **Expression grammar still constrains widget authoring** — this HA pass had to push the variant branching into `widget_transforms.py` because the template engine still lacks `and` / `or` / ternary / prefix tests. That keeps P1-2 (`and` / `or` / `not` / ternary) relevant for lowering authoring friction on bindable integration widgets.
- **JSON Schema artifact** at `ui/src/types/widget-components.schema.json` generated from `ComponentBody.model_json_schema()` — enables future admin playground (P2-6) to lint YAML live. Small script under `scripts/`.
- **TS type hoist**: lift the `ComponentNode` union out of `ui/src/components/chat/renderers/ComponentRenderer.tsx` into `ui/src/types/widgets.ts` so the renderer imports from a single source of truth. Today Pydantic is the canonical schema for validation, but the TS is still a manual parallel.
- **`with:` overlays on fragments**: per-ref variable overrides (`{type: fragment, ref: X, with: {bot_id: "{{override}}"}}`). Not needed by the refactored `schedule_task`; add if a second widget wants the same fragment but against different keys.
- **Refactor `list_tasks` detail mode** to share fragments with `schedule_task` — large remaining duplication between the two.

## Phase detail

### P0-3 — Docs + Track (done)
Shipped [[Widget Authoring]] + this track file + Roadmap link. Covers: three pathways, component reference, pipe reference, `when`/`each`, `state_poll`, transforms, fragments, pinned widgets, testing, file layout.

### P0-1 — Component-tree schema (done)
- `app/schemas/widget_components.py` — Pydantic discriminated union over every renderer-supported type, permissive-where-templated / strict-on-structure (extra fields rejected, unknown types warn not error for forward-compat).
- `app/services/widget_package_validation.py` — new `_validate_parsed_definition()` helper + `_validate_component_list()` runs the tree.
- `app/services/widget_templates.py:_register_widgets` now calls the validator at boot; errors log + skip, warnings log + register.
- Tests added to `tests/unit/test_widget_package_validation.py` including a "validate every shipped core widget" smoke test.

### P3-1 — HTML widget catalog + frontmatter (done, 2026-04-19)

Before this phase: HTML widgets were undiscoverable. The only way to pin one was to remember its absolute workspace path and emit it from a bot turn. `AddFromChannelSheet` had no Templates tab at all; `/widgets/dev#library` showed only tool-renderer packages but labeled them "templates," blurring two different concepts.

Shipped:
- **`app/services/html_widget_scanner.py`** — walks a channel workspace for `**/widgets/**/*.html` ∪ any `.html` whose body references `window.spindrel.`; parses a leading YAML frontmatter block inside an HTML comment; memoizes parsed metadata by `(channel_id, path, mtime)` with no TTL (mtime is authoritative). Negative results (non-widgets) also cached so re-scans don't re-read them.
- **`GET /api/v1/channels/{id}/workspace/html-widgets`** — returns the scanner's entries. Same auth as the other channel-workspace endpoints.
- **Frontmatter convention** — Jekyll/Hugo-style leading `<!-- --- ... --- -->` block with `name`, `description`, `display_label`, `version`, `author`, `tags`, `icon`. Only `name` is required; everything else has sensible defaults (e.g. slug fallback, `version: "0.0.0"`).
- **"HTML widgets" tab on `AddFromChannelSheet`** — lists scanner output for the current channel. Loose-file entries get an amber "loose" badge. Pin synthesizes an `emit_html_widget` path-mode envelope so the existing renderer handles it — no new rendering code.
- **Dev-panel Library restructure** — `/widgets/dev#library` now leads with an explainer banner ("two kinds of widgets, answering different questions"), renders the existing `WidgetLibraryTab` labeled "Tool renderers," then a new `HtmlWidgetsLibrarySection` with a channel picker + Copy path / Source actions.
- **Skill docs** — `skills/html_widgets.md` gains a `Widget metadata — YAML frontmatter` section and a nudge in "Remember What You Built."

Storage model deferred: this ships as **registry-only** (no DB rows for HTML widgets). Revisit if/when favorites, cross-channel search, or version-bump-notify become real needs.

Tests: 25 new unit tests (`test_html_widget_scanner.py` + `test_widget_scanner_endpoint.py`). UI `tsc --noEmit` clean. Manual smoke pending e2e.

### P1-1 — Template fragments + state_poll default (done)
- `app/services/widget_fragments.py` — resolver inlines `{type: fragment, ref: <name>}` nodes (list bodies spread, dict bodies replace 1:1) at registration time; cycle-detected.
- Validator validates fragment bodies as components so typos don't slip through.
- `_register_widgets` now: (a) validates, (b) resolves fragments, (c) defaults `state_poll.template` to `template` when omitted, (d) caches expanded definition.
- `app/tools/local/tasks.widgets.yaml:schedule_task` refactored to use `cancel_task_button` + `edit_task_links` fragments in both `template` and `state_poll.template`.
- 22 new unit tests across `tests/unit/test_widget_fragments.py` and `tests/unit/test_widget_templates.py::TestRegisterWidgetsFragments`. Full widget test suite (135 tests) passes.

## Key invariants
- **MIME dispatch stays the seam.** New content types route cleanly; interactive widgets stay on `application/vnd.spindrel.components+json`.
- **Backwards-compatible additions only** — existing `*.widgets.yaml` and integration manifests keep working without edits.
- **No runtime surprises** — every widget either validates at registration or is flagged `is_invalid`.
- **Schema has one source of truth** — Pydantic drives the JSON Schema which drives the TS types. If they drift, CI fails.

---

## Flagship Catalog (Phase 0 + Phase 1+)

Widgets that showcase what HTML buys over components (SVG charts, media viewers, free-form layout, fine animation, brushing/filtering). Prioritized for the post-`frigate_snapshot` era.

### Phase 0 — Widget theme / DX layer (done, 2026-04-19)

Shipped so every HTML widget inherits the app's design language automatically — no more hand-rolled hex colors, dark-mode-correct by default.

- `ui/src/components/chat/renderers/widgetTheme.ts` (new) — `buildWidgetThemeCss` emits `--sd-*` CSS variables + `sd-*` utility/component classes (card / btn / chip / stack / grid / tile / progress / spinner / skeleton / input). `buildWidgetThemeObject` exposes tokens to SVG/canvas widgets as `window.spindrel.theme`.
- `InteractiveHtmlRenderer.tsx` — reads `useThemeStore`, injects `<style id="__spindrel_theme">` + `<html class="dark">` + theme object into iframe bootstrap.
- `skills/html_widgets.md` — new **Styling** section documenting the `sd-*` vocabulary + Do/Don't table. Common Mistakes extended with "inline hex colors" entry.
- `integrations/frigate/widgets/frigate_snapshot.html` — migrated as the canonical reference (14 lines of inline CSS → 0).

### Phase 1 status

| # | Widget | Tool | Status |
|---|--------|------|--------|
| 1 | **Frigate events timeline** | `frigate_get_events` | **done** (2026-04-19) — `integrations/frigate/widgets/frigate_events_timeline.html` — SVG time-axis with per-camera lanes, label-colored pills, filter chips (`sd-chip-*` palette), detail panel on click, refresh dispatch, state_poll every 60s. |
| 2 | HA room dashboard v1 | `GetLiveContext` | **blocked** — existing component widget (integration.yaml:228-307) is comprehensive; upgrade replaces it (design call). Also: HTML mode doesn't run top-level transforms (only state_poll transforms) — widget_templates.py:502-511. One-line engine fix, but needs user sign-off on the replace-vs-add-new-tool-variant decision. |
| 3 | `get_trace` waterfall | `get_trace` | **blocked** — detail mode returns text, not JSON. widget_templates.py silently skips non-JSON tool results. Needs additive `format: "text"\|"json"` param on the tool with state_poll.args.format="json". Low-risk but touches a core tool. |

Bug fixes shipped alongside Phase 1 (from user testing the first flagship):

- **Frigate snapshot dup** — `_download_media` in `integrations/frigate/tools/frigate.py` was creating an attachment AND returning `client_action`, producing two image copies in the web UI (one inline via orphan-linking, one in the widget). Fix: when a widget is registered for the tool, `create_attachment` is called with `channel_id=None` so persist_turn's orphan-linking skips it. `client_action` stays untouched (Slack / Discord / BlueBubbles consume it via a separate channel that never rendered widgets).
- **Widget auth UX** — `app/routers/api_v1_widget_auth.py` mint endpoint now names the bot by `display_name` and points at `Admin → Bots → {name} → Permissions` instead of generic "admin UI". `ApiError` exported from `ui/src/api/client.ts` with a `.detail` getter that extracts FastAPI's `{detail: "..."}` body. `InteractiveHtmlRenderer` surfaces the backend detail in the auth banner with a **Retry** button (`tokenQuery.refetch()`) so users don't wait for the 12-min react-query interval after granting scopes.
- **Preamble strip orphan `<script>`** (latent, surfaced by the dup-suppression fix) — `TOOL_RESULT_PREAMBLE_RE` in `InteractiveHtmlRenderer.tsx` only matched `window.spindrel.toolResult = ...;</script>`, leaving an orphan `<script>window.spindrel = window.spindrel || {};` opening tag in the iframe body. The browser saw an unclosed script and parsed the following HTML as JS — `Uncaught SyntaxError: Unexpected token '<' at about:srcdoc:2:1` in console, empty widget body. The old behavior was masked because the inline image attachment was rendering the snapshot. Fix: widened the regex to `<script>\s*window\.spindrel\s*=\s*window\.spindrel\s*\|\|\s*\{\};\s*window\.spindrel\.toolResult\s*=\s*([\s\S]+?);\s*<\/script>` — tightly anchored on the exact init signature so it can't accidentally swallow bot-authored script tags that happen to mention `window.spindrel.toolResult`.
- **Token race — 422 on widget initial fetch** — `window.spindrel.apiFetch` fired the iframe's initial-paint fetches synchronously at iframe load, but the bot widget-auth JWT is minted async by react-query AFTER mount. First fetch went out without `Authorization` → 422 Unprocessable Entity at `/api/v1/attachments/{id}`. User saw "Image fetch failed (check bot's attachments:read scope)" even though scopes were granted. Fix: added a `tokenReady` promise inside the `spindrelBootstrap` script. `apiFetch` awaits it when `state.token` is null. `__setToken` resolves it on first mint arrival. Single mount delay (~100ms), no perceptible pause; subsequent fetches are synchronous because the promise is already resolved.

### Phase 2 status

Top four shipped 2026-04-19. Plan: `~/.claude/plans/memoized-gathering-abelson.md`.

| # | Widget | Tool | Status |
|---|--------|------|--------|
| 1 | **`generate_image`** | `generate_image` | **done** (2026-04-19) — `app/tools/local/widgets/image.html` — responsive gallery (1/2/auto-fit grid), click-to-lightbox, three regen buttons ("Try again", "Brighter", "Different angle", "More detail") that dispatch `generate_image` with mutated prompts via `/api/v1/widget-actions`. Tool now returns `prompt` + canonical `images: [{attachment_id, filename}]` in the JSON so the widget can show thumbnails without unwrapping `client_action`. Widget-aware attachment suppression added: when a widget is registered, `create_attachment` uses `channel_id=None` (same pattern as `frigate_snapshot`) so the web orphan-linker doesn't double-display. |
| 2 | **`get_weather`** | `get_weather` | **done** (2026-04-19) — `integrations/openweather/widgets/get_weather.html` — replaces the component widget in `openweather/integration.yaml:110-126`. SVG hourly chart (640×180) with temp curve + precip bars + y-axis grid + x-axis hour ticks, daily forecast `.sd-tiles` (7-day), alerts `.sd-error` banner, `°F`/`°C` + "Feels like" toggles in header. State_poll keeps `include_daily` + `include_hourly` on and respects per-pin `units`. |
| 3 | **`web_search`** | `web_search` | **superseded 2026-04-23** — the earlier HTML iframe widget was removed. Web Search now opts into the generic `core.search_results` React renderer via `view_key` and keeps only a component-template fallback for unsupported clients. |
| 4 | **`frigate_list_cameras`** | `frigate_list_cameras` | **done** (2026-04-19) — `integrations/frigate/widgets/frigate_list_cameras.html` — 2×N camera wall (220px min-tile auto-fill), per-tile 10s snapshot refresh via dispatched `frigate_snapshot` calls (JS parses the attachment_id out of the returned HTML envelope preamble), click→full-bleed lightbox. Header controls: bounding-box toggle + pause-polling toggle. State_poll (300s) refreshes the camera list itself to catch add/remove. Completes the Frigate story (pairs with the events-timeline widget). |
| 5 | **`create_excalidraw` / `mermaid_to_excalidraw`** | Excalidraw | **done** (2026-04-19) — `integrations/excalidraw/widgets/create_excalidraw.html` — shared widget (both tools return the same shape: attachment_id + filename + mime). Renders via `apiFetch(/api/v1/attachments/{id})` → blob → `<img>`, click→lightbox, header Download button. `_deliver()` refactored to return `attachment_id` + use the new `create_widget_backed_attachment` helper so web orphan-linking is suppressed (previously the rendered diagram appeared twice: once from the orphan-linked attachment, once from the widget). Validated the pattern is now reusable — this was the extraction trigger. |

### Bot-authored dashboard DX — DX-1 shipped, DX-2 through DX-5 queued (2026-04-19)

Skill-driven effort to turn bot-authored HTML widgets into pro-grade dashboards. Plan: `~/.claude/plans/memoized-mixing-teapot.md`.

- **Skill rewrite** — `skills/html_widgets.md` (416 → 690 lines): bundle layout conventions (`/workspace/channels/<id>/data/widgets/<slug>/` vs `/workspace/widgets/<slug>/`), tool dispatch via `/api/v1/widget-actions` as a first-class section, the `state.json` RMW pattern, four dashboard archetypes (status / feed / control panel / KB reader), `/widget-actions` vs `spindrel.api()` decision table, DX roadmap appendix.
- **DX-1 — `window.spindrel.renderMarkdown(text)`** shipped. Minimal CommonMark-ish renderer (headings, bold/italic, inline code, fenced code, lists, blockquotes, links, paragraphs) baked into `spindrelBootstrap` in `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx`. HTML-escapes source first; safe for bot-authored prose. 16/16 extraction tests pass via node eval. UI tsc clean.
- **DX-2 — `window.spindrel.callTool(name, args, opts?)`** shipped. One-line wrapper over `POST /api/v1/widget-actions` dispatch:"tool"; auto-fills `bot_id` + `channel_id`; `opts.extra` flows `display_label` / `widget_config` / `source_record_id` / `dashboard_pin_id` through; returns fresh envelope or throws. Skill's control-panel archetype now uses it; Tool Dispatch section rewritten around it. 4/4 extraction tests pass (basic, opts.extra, missing-name, server-error). UI tsc clean.
- **DX-3 — `window.spindrel.data` helper** shipped. `load(path, defaults?)` / `patch(path, patch, defaults?)` / `save(path, object)` with deep-merge semantics (arrays replaced, not concatenated). First-run-safe (missing file → defaults clone); throws on invalid JSON; `patch` reads fresh each time so two open copies stay coherent. Collapses the state-dashboard boilerplate to three methods. Skill's `state.json` pattern section rewritten around it. 8/8 extraction tests pass (missing+defaults, save/load round-trip, no-defaults, deep-merge patch, patch-on-missing, array replacement, invalid-JSON, defaults immutability). UI tsc clean.
- **DX-4 — event subscription wrappers** shipped. `onToolResult(cb)` + `onTheme(cb)` wrap the existing `spindrel:toolresult` / `spindrel:theme` DOM events and return unsubscribe fns. `onConfig(cb)` is sugar over `toolresult` that debounces on actual `toolResult.config` change (JSON-stringify compare) so callbacks don't fire on every envelope refresh. Skill's "Reacting to live updates" section replaces the old raw-addEventListener guidance. 6/6 extraction tests pass (basic fire, unsubscribe removal, onTheme, onConfig debounce semantics, non-function callbacks throw for both wrappers). UI tsc clean.
- **DX-5a — relative-path resolution in helpers** shipped. `window.spindrel.widgetPath` is set to the envelope's `source_path` (null for inline); `readWorkspaceFile`, `writeWorkspaceFile`, and `data.*` accept `./foo` / `../foo` and resolve against `dirname(widgetPath)`. New `window.spindrel.resolvePath(input)` exposed for bookkeeping. Added `normalizePath` (strips `./`, collapses `..`, rejects workspace-root escape) + `resolvePath` (path-grammar dispatcher) to the bootstrap. `/workspace/...` absolute paths currently throw with a clear DX-5b pointer. `sourcePath` threaded `wrapHtml` → `spindrelBootstrap`. 13/13 extraction tests pass (plain, redundant segments, relative resolution, deep parent traversal, escape-throws, absolute rejected, inline-widget guards, empty/non-string guards, root-widget relative). UI tsc clean.
- **DX-5b — non-channel workspace root (`/workspace/widgets/<slug>/`)** — deferred (not a quick slice). Needs cross-cutting backend work: new non-channel root in `app/services/workspace.py`, non-channel-scoped workspace-file endpoint, path resolver in `emit_html_widget.py`, extending the iframe file-polling query beyond channel scope, and making the `file` tool (currently channel-scoped) write into the new root. Best as its own session with a proper plan — too easy to cause silent bugs.
- **DX-5c — bundled asset loading via `loadAsset`** shipped. `window.spindrel.loadAsset(path)` + `revokeAsset(url)` in the bootstrap. Fetches via `apiFetch` against the existing channel `/workspace/files/raw` endpoint, blobs the response, returns a `blob:` object URL. Same-origin by construction (no CSP changes). Supports the full `resolvePath` grammar (relative paths against widget bundle). Skill's "Bundled assets" section documents `<img>` / `<video>` / `<audio>` use. 5/5 extraction tests pass (basic load, revoke, revoke-unknown-ignored, 404-throws, absolute path). UI tsc clean.
- **DX-5c-full — `<base href>` native asset loading** — deferred. "Drop `<img src="assets/logo.svg" />` and have it work" needs a signed-URL token pattern OR a service worker to inject `Authorization` headers OR a public asset endpoint. All three are real security design calls. `loadAsset` shipped as the pragmatic unlock that doesn't commit us to a stance.

### Follow-up policy — new bots auto-mint read-only widget scopes (2026-04-21)

Interactive HTML widgets run as the emitting bot, so a brand-new bot with no
API key produced immediate `/widget-auth/mint` 400s until an admin manually
visited the Permissions tab. New bots now auto-mint a minimal scoped key at
create time with `attachments:read` + `channels:read` only. This covers the
stock widget runtime helpers (`loadAttachment`, channel-workspace asset reads,
channel-bound dashboard reads) without silently granting mutation access.
Bots that truly need writes or broader API use still widen scopes explicitly
under Admin → Bots → Permissions.

### Session-local plan mode for widget work (done, 2026-04-21)

Shipped a first real "plan first, execute later" loop without reviving the removed generic plans system:

- Backend:
  - new `app/services/session_plan_mode.py` owns the strict Markdown contract, file pathing, revision metadata, approval state, and step auto-advance rules
  - `/sessions/{id}/plans`, `/sessions/{id}/plan`, `/sessions/{id}/plan/{approve,exit,resume}`, and `/sessions/{id}/plan/steps/{step_id}/status` landed on the UI sessions router
  - `_load_messages()` now injects session plan-mode context so the agent sees planning/executing rules every turn
  - `file` tool mutations are gated during planning: only the canonical plan file may be edited
- Artifact shape:
  - single canonical file at `channels/<channel-id>/.sessions/<session-id>/plans/<task-slug>.md`
  - strict headings + stable step ids in Markdown; no DB plan table
  - progress is tracked inline in the same file
- UI:
  - plan mode entry moved into the composer as a low-chrome pill/dropdown
  - default chat places the plan control just left of the model picker; terminal mode places it under the input on the right opposite the model picker
  - existing session can enter plan mode mid-conversation; no scratch/planner session split
  - `/plan` is available in channel/session/thread chat surfaces and toggles the existing session plan state via the shared slash-command backend
  - entering plan mode is now mode-only: the toggle no longer creates a placeholder plan or mounts page-level chrome
  - the first real plan appears only when the agent calls `publish_plan`, which writes the canonical Markdown file and emits an in-feed plan envelope rendered through the existing `RichToolResult` path
  - plan updates are transcript-first now; the top-of-channel `SessionPlanCard` mount was removed and the transcript plan card owns approve/exit/step actions

Verification:

- `pytest agent-server/tests/unit/test_session_plan_mode.py -q` → `7 passed`
- `cd agent-server/ui && npx tsc --noEmit`
- `python -m py_compile app/services/session_plan_mode.py app/routers/sessions.py app/services/slash_commands.py app/tools/local/publish_plan.py`

Integration note:

- Added `tests/integration/test_slash_commands.py::test_plan_command_for_session_returns_side_effect`, but the shared integration harness still stalled before returning a trustworthy completion signal for this file in-session.

Known limitation:

- execution is still session-turn-driven rather than a fully automatic background step runner; the transcript-first publish/render path is now in place, but the executor itself is not yet a detached loop

Follow-up hardening (2026-04-22):

- Tightened the injected plan-mode runtime contract so the model is now told, every turn, to:
  - ask at most 1-3 focused clarifying questions before drafting
  - avoid giant freeform markdown proposals in plain chat
  - prefer the dedicated question/publish tools instead of hand-formatting planning UI in prose
- Added `ask_plan_questions`, a local tool that emits a transcript-native `core/plan_questions` native-app card for structured planning Q&A.
  - Supports `text`, `textarea`, and `select` fields.
  - Intended flow: ask structured questions first, then `publish_plan` once key scope answers are in.
- The plan-questions card now feeds answers back into the composer for review/send, keeping the planning interaction transcript-first without inventing a second approval surface.
- Cold-start hardening: `ask_plan_questions` moved its `ToolResultEnvelope` import to call time and now has a registry bootstrap test alongside `publish_plan`, preventing another local-tool discovery circular import from slipping in.

### Phase 0.6 — Plan mode + widget revision artifacts docs pass (done, 2026-04-21)

Follow-up docs pass after session-local plan mode landed:

- added a canonical `docs/guides/plan-mode.md` guide instead of scattering behavior across Slack/Discord docs
- removed stale Slack/Discord `/plan` docs so the old integration surface stops competing with the new session-local web plan mode
- updated `skills/widgets/index.md` to tell widget authors when to use plan mode and how widget bundle revisions now show up as active-plan artifacts via `widget_version_history`, `rollback_widget_version`, `widget_library_list`, and `describe_dashboard`

Docs follow-up (2026-04-22):

- promoted plan-mode docs from the short guide into a deeper golden doc at `docs/planning/session-plan-mode.md`
- the old guide at `docs/guides/plan-mode.md` is now just a pointer, to avoid the behavior/spec drifting across multiple files
- the widgets skill now points directly at the canonical planning doc when widget work should go through plan mode

Plan-process hardening (2026-04-23):

- Added visible `planning_state` capsule so planning back-and-forth no longer depends only on live transcript history before `publish_plan`.
- `ask_plan_questions` now records structured answers into `planning_state` before sending the normal answer message.
- Added `plan_adherence` execution evidence ledger and surfaced latest evidence/adherence state through runtime/plan payloads.
- Tool dispatch now blocks mutating execution when the accepted revision/current-step contract is invalid, blocked, or pending replan.
- `request_plan_replan` remains allowed as the explicit blocked/executing escape hatch, then returns the session to planning with the previous accepted revision preserved.
- Added deterministic turn-end supervision: missing execution outcomes create `pending_turn_outcome`, block further mutating tools, and require `record_plan_progress` or `request_plan_replan`.
- Added `record_plan_progress` for `progress`, `verification`, `step_done`, `blocked`, and `no_progress`; latest/pending outcomes now surface through runtime payloads and plan cards.
- Added on-demand semantic adherence review on the normal plan card. It reconstructs persisted turn evidence by `correlation_id`, stores verdict history in `plan_adherence.semantic_reviews`, and exposes `runtime.semantic_status` plus `latest_semantic_review`.
- Remaining gap: judge calibration/evals and any future auto-review or hard-gating policy, not the existence of the semantic review loop itself.

### Phase 0.5 — Engine addition: `widget_config` rides into `toolResult.config` (done, 2026-04-19)

Slice 0 of the plan. Previously `apply_widget_template` computed `data_with_config` but only passed `data` into `_build_html_widget_body` — HTML widgets couldn't read their own pin config. Changed both call sites (`widget_templates.py:511` + `widget_templates.py:641` in `apply_state_poll`) to pass `data_with_config`, so widget JS now reads `window.spindrel.toolResult.config.*` natively. No renderer changes needed.

`InteractiveHtmlRenderer.tsx` also gained a `dashboardPinId?: string` prop; `RichToolResult` threads it through from `PinnedToolWidget` so widget JS can read `window.spindrel.dashboardPinId` and target `widget_config` dispatches at the correct pin. Inline chat widgets leave it undefined — config changes stay local-only.

Test update: `tests/unit/test_widget_templates_html.py::test_preamble_excludes_widget_config` inverted to `test_preamble_includes_merged_widget_config` + added `test_preamble_uses_default_config_when_no_pin_overrides`. Adjacent test `test_preamble_carries_tool_result_json` loosened to check tool-result fields individually + assert `config` present.

### Phase 2 — Tier 2+ remaining candidates (unscheduled)

Ordered roughly by projected value-per-token. Each is a standalone session.

- **`list_attachments`** — masonry gallery, type-filter chips, full-screen lightbox with arrow-key nav. Per-item "Describe" button dispatches `describe_attachment`.
- **`github_get_pr`** — inline diff viewer (Prism.js inlined), file-tree sidebar, review/merge/close action bar. Component widget already exists → HTML upgrade replaces it.
- **`list_tasks`** — week-view calendar with scheduled runs as draggable bars; past-run status bubbles below. Drag dispatches `update_task`.
- **`search_history` / `read_conversation_history`** — threaded transcript with author avatars, timestamp clustering, click-to-jump (postMessage up to parent channel).
- **`sonarr_calendar`** — month/week grid with poster thumbs per day; click → wanted status + "search now".
- **`sonarr_series` / `radarr_movies` (search)** — TMDB/TVDB poster grid with year / genres / rating overlay + "Add" dispatch.
- **`check_gmail_status`** — inbox preview rows (sender / subject / snippet), per-row Reply (modal) / Archive (dispatch) / Open in Gmail.
- **`sonarr_queue` / `radarr_queue`** — smooth-animated progress bars, ETA countdown tickers, per-item Cancel / Prioritize dispatch. (Originally proposed as alternative Tier 1 pick — lives here until a self-hoster with an active queue validates live.)

### Phase 3 — Supporting widgets

Smaller targets — ship opportunistically when touching the area.

- `file` (list) — tree viewer, size + mtime, icon by type
- `file` (read diff) — side-by-side diff pane with Prism highlighting
- `search_workspace` / `search_channel_workspace` — matches with line context + jump-to-file
- `list_pipelines` — catalog with "Run" buttons + last-run status dots
- `bot_skills` — skill ring chart + "enroll/unenroll" actions (component widget exists → HTML upgrade)
- `fetch_url` — reader-mode with table-of-contents sidebar

### Widget-engine gaps surfaced by this catalog

These are ENGINE changes (fit [[Track - Widgets]] proper, not the catalog):

- **HTML mode top-level transform** — currently only state_poll transforms run in HTML mode (widget_templates.py:502-511). Blocks widgets that need server-side data reshaping on first render (e.g. HA dashboard parsing the YAML text).
- **JSON-format mode for text tools** — widgets silently skip tools returning non-JSON. Either widen the engine to accept `{text: str}` wrapping, or document that widget-backed tools must emit JSON. Affects `get_trace` waterfall.
- **Widget-aware attachment suppression** — extracted 2026-04-19. Helper `app/services/attachments.py::create_widget_backed_attachment(*, tool_name, ...)` checks `get_widget_template(tool_name)` and forwards to `create_attachment` with `channel_id=None` whenever a widget is registered. Three call sites converted: `integrations/frigate/tools/frigate.py::_download_media` (snapshot + event_snapshot + event_clip), `app/tools/local/image.py::generate_image_tool`, `integrations/excalidraw/tools/excalidraw.py::_deliver` (both excalidraw tools). `client_action` stays on in all three — Slack/Discord consume it as their rendering path. Unit test: `tests/unit/test_widget_backed_attachment.py`.
- **Favicon proxy** — shipped 2026-04-19 at `/api/v1/favicon?domain=` for the `web_search` widget. Thin LRU-cached httpx GET against `www.google.com/s2/favicons`. Requires `chat` scope. First general-purpose proxy for widget use; future widgets can consume it too.

---

## References
- Engine: `app/services/widget_templates.py`
- Envelope: `app/agent/tool_dispatch.py` (`ToolResultEnvelope`, three-path dispatch)
- DB seeding: `app/services/widget_packages_seeder.py`, model: `app/db/models.py:WidgetTemplatePackage`
- Renderer: `ui/src/components/chat/renderers/ComponentRenderer.tsx`
- Card (polling + pinning + dispatch): `ui/src/components/chat/WidgetCard.tsx`
- Dispatcher: `ui/src/components/chat/RichToolResult.tsx`
- Bypass examples: `ui/src/components/chat/TaskRunEnvelope.tsx`, `ui/src/components/chat/InlineApprovalReview.tsx`
- Tests: `tests/unit/test_widget_templates.py`, `test_widget_package_validation.py`, `test_widget_package_loader.py`, `test_widget_context.py`, `test_widget_actions_state_poll.py`
