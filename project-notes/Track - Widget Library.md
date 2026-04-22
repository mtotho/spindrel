---
tags: [widgets, library, sdk, track]
status: active
updated: 2026-04-21 (native Todo widget + native Notes draft-sync fix)
---

# Track — Widget Library

## North Star

Unify the three parallel widget systems (YAML templates, HTML widgets, suites) under a single tool-mediated library surface. Bots author widgets via existing file ops over a `widget://` virtual path namespace — no new CRUD tool surface, one metadata listing tool. Core widgets stay in-repo; bot-authored widgets live in a `bot_widgets` DB table. `emit_html_widget(library_ref=<name>)` is the canonical emission path.

Adjacent: make chips a first-class authoring target, close the AI feedback loop with a `preview_widget` tool, reorganize the 1657-line skill into a proper folder, and dogfood the SDK in Mission Control so the flagship suite actually demonstrates the SDK it ships with.

## Status

| Phase | Description | Status |
|---|---|---|
| 1a | `widget_library_list` tool (core scope) + `emit_html_widget(library_ref=...)` for core widgets — 18 new tests | **complete** (2026-04-20) |
| 1b | `widget://core\|bot\|workspace/<name>/...` virtual paths in `file_ops._resolve_path` + `widget_library_list` / `emit_html_widget` read bot+workspace scopes — new `app/services/widget_paths.py`, ~20 new tests | **complete** (2026-04-20) |
| 2 | In-repo tidy: `*.widgets.yaml` → `widgets/<name>/template.yaml`; flatten `widgets/suites/` | **complete** (2026-04-20) |
| 3 | Skill reorg: `skills/html_widgets.md` → `skills/widgets/` folder | **complete** (2026-04-20) |
| 4 | `preview_widget` tool wrapping existing preview endpoints | **complete** (2026-04-20) |
| 5 | Chips as first-class: `spindrel.layout` + 3 reference chips + `layout_hints` frontmatter + `skills/widgets/chips.md` | **complete** (2026-04-20) |
| 6 | Bot↔widget handler bridge + reference Todo widget (replaces MC dogfood — MC deleted) | **complete** (2026-04-20) |
| 6.5 | `pin_widget(source_kind="library")` + `/html-widget-content/library` endpoint + renderer branch — closes the bot authoring → dashboard placement loop | **complete** (2026-04-20) |
| 7 | Ship next 5 rich widgets: `ha_device_list`, `plex_now_playing`, `calendar_list_events`, `gmail_list_messages`, `list_traces` | pending |
| 8 | UI picker for library widgets — `AddFromChannelSheet` "Library" tab + channel-dashboard "Developer tools" split-button | **complete** (2026-04-21) |
| 9 | `sd-*` v2 DX layer: Lucide icon sprite + styled controls (`sd-check`, `sd-radio`, `sd-switch`, `sd-input-group`, `sd-row`, `sd-tag--removable`, `sd-menu`, `sd-tooltip`, `sd-modal`) + `spindrel.ui.icon/autogrow/menu/tooltip/confirm` + Todo widget rebuild as reference | **complete** (2026-04-21) |
| 10 | Unify Library + HTML widgets tabs; filter tool-renderer template entries out of Library; envelope-shape index + `inspect_widget_pin` debug recipe in `skills/widgets/errors.md` | **complete** (2026-04-21) |
| 11 | Dev Panel Library uses same `WidgetLibrary` component as Add-Widget sheet; new `/library-widgets/all-bots` endpoint unions every bot's `.widget_library/` with `bot_id`+`bot_name` per entry; inline preview expansion with Live/Source/Manifest tabs; new `/widget-manifest` endpoint; bot-authorship badge on `widget://bot/` rows; tool renderers moved to their own tab inside Library | **complete** (2026-04-21) |
| 12 | Authored-widget SDK panel titles: `panel_title` + `show_panel_title` metadata, library/catalog/envelope propagation, and host-owned panel chrome across dashboard/chat/mobile panel surfaces | **complete** (2026-04-21) |
| 13 | Widget theme library: immutable `builtin/default`, custom theme CRUD/fork, global default + per-channel `widget_theme_ref`, renderer resolution, `/widgets/dev#themes`, and bot theme management/apply-to-channel | **complete** (2026-04-21) |
| 14 | Library context repair: Add Widget resolves bot/workspace library visibility from channel/bot context instead of `Runs as`, dev-panel all-bots library accepts `channel_id`, shared widget metadata grows `theme_support` + `group_kind/group_ref`, and tool-renderer packages expose suite/package grouping | **complete** (2026-04-21) |
| 15 | Bot-facing widget authoring guidance: tool descriptions and widget skills now reflect the repaired library model, `suite`/`package` grouping, and the HTML-vs-template decision split | **complete** (2026-04-21) |
| 16 | Direct tool-renderer instantiation from the unified library UI: run with args, preview the active renderer, and pin the configured adhoc instance from the Tool renderers tab | **complete** (2026-04-21) |
| 17 | Public template-widget instantiate/preview path + `pin_widget` parity for template/tool-renderer refs | **complete** (2026-04-21) |
| 18 | First-party native app widgets: `native_app` catalog entries, instance-backed pins, unified `invoke_widget_action` bot tool, declared action schemas, and native Notes proving widget | **complete** (2026-04-21) |

Phase 1a + 1b shipped 2026-04-20 — bots can now list, emit, and author widget bundles end-to-end. The seam lives in `app/services/widget_paths.py` (one resolver, three scopes) and is re-used by `file_ops._resolve_path`, `widget_library.widget_library_list`, and `emit_html_widget._load_library_widget` so there is a single source of truth for `widget://` resolution and the read-only contract on `core`.

Phase 2 shipped 2026-04-20 — in-repo core layout now mirrors the library API one-to-one:
- Every core widget lives in its own folder `app/tools/local/widgets/<tool_name>/` containing a `template.yaml` (component-tree templates and tool-renderer HTML wrappers) or a `suite.yaml` (multi-widget bundle with shared SQLite).
- The four legacy flat files `admin.widgets.yaml`, `bot_skills.widgets.yaml`, `image.widgets.yaml`, `tasks.widgets.yaml` were split per-tool into six folders (`get_system_status`, `manage_bot_skill`, `generate_image`, `list_tasks`, `schedule_task`, `get_task_result`) with the tool-name wrapper key stripped — the folder name IS the tool name.
- The standalone `widgets/suites/mission-control/` folder was flattened up one level to `widgets/mission-control/` — suites are now siblings of the other widget folders, discoverable by the presence of `suite.yaml`.
- `widget_templates.load_widget_templates_from_manifests`, `widget_packages_seeder._collect_sources`, `html_widget_scanner._collect_tool_renderer_paths`, and `widget_suite._discovery_roots` all walk the new layout. The file-ops resolver and library listing were already layout-agnostic via Phase 1b's `widget_paths.scope_root`, so they needed no changes.
- `widget_library._SKIP_NAMES` dropped `"suites"` — the dir is gone; `"examples"` stays because the SDK smoke corpus is not a library entry.

Result: `widget_library_list(scope="core")` returns 12 entries (6 template, 4 html, 1 suite, 1 html). `scan_suites()` finds `mission-control` at the new location. Pre-existing `TestJsonPatchOp` failures remain out of scope; all other widget unit + integration tests pass (269 + 22).

Phase 3 shipped 2026-04-20 — `skills/html_widgets.md` (1657 lines) split into `skills/widgets/` folder with 11 sub-skills keyed off the folder-layout scanner a parallel session wired into `app/services/file_sync.py::_walk_skill_files` + `app/agent/skills.py::list_available_skills`. Layout:

- `skills/widgets/index.md` — decision tree + triggers for the generic "build a widget" query; each branch cross-links to one of the detail files.
- `skills/widgets/html.md` — `emit_html_widget` modes, bundle layout, path grammar, sandbox + `extra_csp`, auth (bot not viewer).
- `skills/widgets/sdk.md` — full `window.spindrel` surface: `api`/`apiFetch`, workspace files + `loadAsset`, `data`/`state`, `bus`, `stream`, `cache`, `notify`, `log`, `ui.status`/`table`/`chart`, `form`, `renderMarkdown`.
- `skills/widgets/dashboards.md` — `state.json` pattern, four archetypes, "remember what you built" memory convention + workflow.
- `skills/widgets/tool-dispatch.md` — `/api/v1/widget-actions` envelope, truncation rules (`callTool` bypass), output-shape discovery.
- `skills/widgets/manifest.md` — `widget.yaml` schema + validation rules.
- `skills/widgets/db.md` — `spindrel.db` + migrations + WAL.
- `skills/widgets/handlers.md` — `widget.py` `@on_action`/`@on_cron`/`@on_event` + `ctx` surface + `autoReload` loop.
- `skills/widgets/suites.md` — `suite.yaml` + dashboard-slug-scoped shared DB + `pin_suite`.
- `skills/widgets/styling.md` — `sd-*` vocabulary + CSS vars + `spindrel.theme` + dark mode.
- `skills/widgets/errors.md` — symptom → fix lookup (422, CSP, blank iframe, path mismatch, scope_denied, `truncated` on `callTool`) + the full Common-Mistakes anti-pattern list.

Each sub-file has its own frontmatter with narrow `triggers:` so RAG retrieval can land on the right document instead of dumping all 1657 lines. Skill IDs produced: `widgets` + 10 sub-IDs (`widgets/html`, `widgets/sdk`, `widgets/dashboards`, `widgets/tool-dispatch`, `widgets/manifest`, `widgets/db`, `widgets/handlers`, `widgets/suites`, `widgets/styling`, `widgets/errors`) — verified by `list_available_skills(Path('skills'))`. Chips content deferred to Phase 5 alongside the `spindrel.layout` API + reference chips + `layout_hints` frontmatter — documenting an unbuilt API would have been a stub.

Reference updates in the same commit: `skills/widget_dashboards.md:169` links to `widgets/index.md` with a pointer list of all sub-skills; `tests/unit/test_widget_preamble_helpers.py` swapped its `SKILL_DOC` pointer for a helper that concatenates every `.md` under `skills/widgets/` so the existing `assert needle in text` assertions keep catching missing helper docs. 218 tests green locally (widget preamble + file sync + widget manifest/db/events/suite/scanner/flagship — the only failures are pre-existing `ModuleNotFoundError: croniter` on host Python, unrelated).

Phase 4 shipped 2026-04-20 — `preview_widget` tool closes the AI feedback loop for HTML-widget authoring. Same input shape as `emit_html_widget` (`library_ref` / `html` / `path` + `js` / `css` / `extra_csp` / `display_label` / `display_mode`), returns structured `{ok, envelope?, errors: [{phase, message, severity}]}` instead of emitting anything to chat. Phases surfaced:

- `input` — mutually-exclusive-mode / bad enum
- `library_ref` — scope/name resolution (shadows `emit_html_widget`'s `_load_library_widget`)
- `manifest` — bundle's `widget.yaml` fails `parse_manifest` (missing `name`, bad event kind, bad `extra_csp`, etc.). New in preview: when `library_ref` resolves, the manifest gets parsed before the envelope build so a broken manifest surfaces here instead of only at suite-acquire / event-subscribe time.
- `csp` — `extra_csp` sanitizer rejection
- `path` — workspace file not found, non-channel absolute path, missing channel context

Lives at `app/tools/local/preview_widget.py` — thin wrapper over `emit_html_widget`'s private helpers (`_load_library_widget`, `_assemble_inline_body`, `_derive_plain_body`, `_CHANNEL_PATH_RE`, `_CORE_WIDGETS_DIR`, `_LIBRARY_NAME_RE`). No refactor of the emit tool itself — scope matches the CLAUDE.md "no premature abstraction" rule; the two tools share source via direct module import, not a pulled-up helper module. 18 new unit tests (`tests/unit/test_preview_widget.py`) — input validation (3), inline mode (4), library ref + manifest parse (5), CSP validation (2), path mode (4). Skill updates: `skills/widgets/html.md` gains a "Dry-run first: preview_widget" section between the two-modes table and the sandbox docs; `skills/widgets/index.md` step 6 of the "build an evolving dashboard" workflow references it; `skills/widgets/errors.md` anti-pattern table adds an "emit and hope" → "preview_widget first" row.

Natural next block is Phase 5 (chips as first-class — needs `spindrel.layout` preamble injection) or Phase 6 (MC SDK dogfood). Items 5–7 still fan out independently.

Phase 5 shipped 2026-04-20 — chips are now a first-class authoring target. Four pieces landed together:

- **`window.spindrel.layout` preamble** — `InteractiveHtmlRenderer` takes a new optional `layout?: "chip" | "rail" | "dock" | "grid"` prop, threaded through `wrapHtml` and `spindrelBootstrap` into the iframe `<script>` block so widget JS can branch on host zone. `RichToolResult` forwards it; `PinnedToolWidget` infers it from scope (`compact: "chip"` → `"chip"`, otherwise `"grid"`) with an explicit override for rail/dock cases. `WidgetRailSection` accepts a `widgetLayout` prop (renamed to avoid shadowing the RGL layout state) — `OmniPanel` passes `"rail"`, `WidgetDockRight` passes `"dock"`. Inline chat renders default to `"grid"` in the renderer's `wrapHtml` call so widget JS never sees `null`.
- **`layout_hints` manifest field** — new `LayoutHints` dataclass in `app/services/widget_manifest.py` (`preferred_zone`, `min_cells`, `max_cells`). Validator rejects non-enum `preferred_zone` values (enum: `chip` / `rail` / `dock` / `grid`), non-int or <1 cell values, unknown cell keys, `min > max`, and non-mapping roots. Nine new unit tests cover each rejection + happy-path round-trip. Advisory only — the field informs the dashboard editor (when it wires up, in a later phase) but is not enforced server-side.
- **Three reference chip widgets** — `chip_status` (colored dot + label), `chip_metric` (label + tabular numeric + delta), `chip_toggle` (label + persisted switch via `spindrel.state`). Each ~40 lines of HTML + CSS + JS in `app/tools/local/widgets/<name>/`, sized for 180×32 in chip mode and padded card otherwise. The branching pattern is: read `window.spindrel.layout` at boot, reflect it into `data-layout=` on the root, let the stylesheet do the rest. All three manifests carry `layout_hints.preferred_zone: chip` + `max_cells: {w: 4, h: 1}`. **Removed 2026-04-21 session 01** — the bundles were never wired to real data (demo-only) and cluttered the Library tab. A future HTML-widget-UX session will reintroduce reference chips as part of a broader authoring-UX pass. `skills/widgets/chips.md` "Reference chips" section dropped in the same commit; the rest of the chip skill (layout, `spindrel.layout` branching, `layout_hints`, pitfalls) stays.
- **`skills/widgets/chips.md`** — new sub-skill doc covering the 32 px height constraint, `spindrel.layout` branching pattern, `layout_hints` field, the three reference chips, common pitfalls (wrong padding, tight polling, label overflow, ephemeral state on inline renders), dry-run-first via `preview_widget`. Index decision tree (`skills/widgets/index.md`) gains a chip branch; description/triggers updated so RAG lands here on chip queries. Widget preamble helpers test still passes (57 / 57) since that harness concatenates all `skills/widgets/*.md`.

No new API surface — chips reuse `emit_html_widget(library_ref=...)` + `widget_library_list`. Scope at the library level is unchanged; the chip flavor is entirely on the renderer boundary + manifest + three new bundles.

Phase 6 shipped 2026-04-20 — the MC suite was trashed after honest review ("it was a mess UX wise to touch. it did not look good") and replaced with two things: (1) the **bot↔widget handler bridge** — a generic mechanism that lets any widget's `@on_action` handlers become bot-callable tools via a new declarative `handlers:` block in `widget.yaml`; and (2) a **single polished Todo widget** as the reference implementation. Apple-style: one killer widget that doesn't do much.

- **Manifest surface** — new `HandlerSpec` dataclass in `app/services/widget_manifest.py` + `handlers:` block in `widget.yaml`. Fields per handler: `name` (must match `@on_action`), `description`, `triggers`, `args` (JSON-Schema fragment), `returns`, `bot_callable` (defaults false), `safety_tier` (readonly / mutating / exec_capable, defaults mutating). Validation rejects: non-enum safety_tier, `bot_callable: true` without description, duplicate handler names, non-mapping args, non-boolean bot_callable, bad handler name regex. Ten new `TestHandlerSpec` cases — all green.
- **Dynamic tool source** — new `app/services/widget_handler_tools.py`. `list_widget_handler_tools(db, bot_id, channel_id)` walks pins visible to the caller (channel dashboard + bot-owned dashboards anywhere) and yields `widget.<slug>.<handler>` tool schemas for every `bot_callable: true` handler. `resolve_widget_handler(db, tool_name, bot_id, channel_id)` is the inverse. Slug collisions disambiguate with a short pin-id hash. Broken-manifest pins log-and-skip rather than poisoning the whole pool.
- **Context-assembly integration** — `app/agent/context_assembly.py` injects widget-handler schemas into `pre_selected_tools` + `_authorized_names` after the `current_injected_tools` merge and before the capability gate. Runs regardless of `tool_retrieval` so pinned widget handlers always surface. Failure-tolerant — enumeration errors log and continue without blocking the turn.
- **Dispatch branch** — `app/agent/tool_dispatch.py` adds `elif is_widget_handler_tool_name(name):` which re-resolves the pin at call time (guards against the pin being removed mid-turn) and invokes `widget_py.invoke_action(pin, handler, args)`. Handler runs under the pin's `source_bot_id` — iframe / cron / event identity parity. Error cases (missing pin, unknown handler, timeout, unexpected exception) all return sanitized JSON to the LLM instead of raising.
- **Reference Todo widget** — `app/tools/local/widgets/todo/`. Single-table schema (`todos(id, title, done, position, created_at, updated_at)`); four bot-callable handlers (`list_todos` readonly, `add_todo` / `toggle_done` / `delete_todo` mutating). iframe: ~170 LOC HTML+CSS+JS with `sd-*` vocabulary, hover-revealed delete, done-items slide to bottom, dark-mode correct via design tokens. No drag-reorder in v1 (deferred — use hover affordances instead).
- **Docs** — new `skills/widgets/bot-callable-handlers.md` covers opt-in, description guidance, identity model, safety-tier semantics, and the Todo widget as canonical example. `skills/widgets/index.md` decision tree gains "Want bots to read/mutate this widget's state in chat?" branch. `skills/widgets/handlers.md` gets a pointer to the new doc. `skills/widgets/manifest.md` schema section shows `handlers:` + `layout_hints:` alongside existing blocks.
- **Side-effect fixes** — `app/services/widget_db.py::_BUILTIN_WIDGET_DIR` `parents[2]` → `parents[1]` (was the open Loose Ends bug — every built-in bundle's `spindrel.db` was writing into the read-only image layer). `app/services/widget_manifest.py::_validate_db` migration contiguity rule now starts from 0 (matches `run_migrations` reality; suite manifest was already correct). Existing `test_full_manifest` + `test_migration_schema_version_mismatch_raises` updated to the corrected convention.
- **Tests** — 10 new `TestHandlerSpec`, 16 new `test_widget_handler_tools`, 8 new `test_todo_widget`, 3 new `test_todo_bot_bridge` integration tests (pin → iframe add → bot list, pin → bot add → iframe query, handler-tool surface enumeration). All green. Widget preamble harness still 57/57.

**MC deletion.** `mc_timeline` / `mc_kanban` / `mc_tasks` / `mission-control` bundles and `tests/integration/test_mc_suite.py` all `git rm`'d. Suite infrastructure (`app/services/widget_suite.py`, `db.shared` manifest key, `pin_suite` / `list_suites` tools) stays — those are sound primitives without a current user.

Phase 6.5 shipped 2026-04-20 — `pin_widget(widget="<name>", source_kind="library")` closes the bot authoring → dashboard placement loop. Before this, bots could author + preview + emit widget-library bundles but had to hand off to the user (via `emit_html_widget(library_ref=...)`) for the actual pin — there was no `library` source_kind on `pin_widget`, and `scan_channel` prunes the hidden `.widget_library/` dir, so the bundles were invisible to every pin path.

- **Resolver** — new `_resolve_library_entry` in `app/tools/local/dashboard_tools.py` normalizes `widget` (accepts `"name"`, `"<scope>/<name>"`, or a full `widget://<scope>/<name>/...` URI — trailing path stripped) and reuses `_load_library_widget` from `emit_html_widget.py`. Bot registry miss degrades to a standalone-bot layout so shared-workspace lookup isn't load-bearing on the common path.
- **Envelope branch** — `_envelope_for_entry` now emits `{source_kind: "library", source_library_ref: "<scope>/<name>"}` with no `source_path` / `source_channel_id`; the pin record still carries `source_kind="adhoc"` at the DB level (envelope is what the renderer reads).
- **`_load_library_widget` factored** — now takes `ws_root` / `shared_root` explicitly so the content API can resolve against a specific bot without the agent-runtime context var. `emit_html_widget` and `preview_widget` call sites updated to pass them in.
- **Content endpoint** — `GET /api/v1/widgets/html-widget-content/library?ref=<scope>/<name>&bot_id=<id>` serves the bundle's current `index.html`. Pairs with the sibling builtin / integration endpoints; returns the same `{path, content}` shape so the renderer stays uniform. Core scope resolves without a `bot_id` (in-repo content); bot / workspace scopes require one.
- **Renderer** — `InteractiveHtmlRenderer.tsx` adds a `"library"` branch to `pathMode` + `contentEndpoint`; polls the new endpoint at the same ~3 s cadence as path-mode channel widgets. `source_library_ref` added to `ToolResultEnvelope` (`ui/src/types/api.ts`) with the `source_kind` union widened to include `"library"`. `source_kind` defaults to `"library"` when an envelope carries `source_library_ref` without an explicit kind (back-compat for older library emits).
- **`emit_html_widget` self-describes** — envelope now stamps `source_kind: "library"` alongside `source_library_ref` so chat-emitted library widgets take the same render path as pinned ones.
- **Tests** — 5 new `TestPinWidgetLibrary` cases (bot-scope pin, explicit scope prefix, `widget://` URI input, duplicate refusal, not-found error) + 4 new `TestLibraryContentEndpoint` cases (core, bot, 404, 400-on-bad-scope) + `source_kind` assertion added to the existing `test_library_ref_resolves_core_widget`. 122 widget tests total remain green.
- **Skill doc** — `skills/widgets/dashboards.md` step 5 now covers `pin_widget(source_kind="library")` as the direct-pin alternative to hand-off-to-user emission.

Phase 8 shipped 2026-04-21 — users can now pin bot- and workspace-authored library widgets directly through the UI without the bot's help, and developer tools are reachable from every dashboard (including channel-scoped ones) via a split-button menu that preserves channel context.

- **New endpoint** `GET /api/v1/widgets/library-widgets?bot_id=<id>` in `app/routers/api_v1_dashboard.py` returns `{core, bot, workspace}`. Core always fills; bot/workspace require a `bot_id`. Unknown bot → 404. Thin wrapper over `widget_library._iter_core_widgets` + `_iter_scope_dir` so the tool and the sheet surface exact-same metadata (name, scope, format, display_label, description, version, tags, icon, updated_at).
- **New UI component** `ui/app/(app)/widgets/LibraryWidgetsTab.tsx` — sectioned list with Core / Bot / Workspace groups, scope-chip filter row, existing-pin dimming (`library:<scope>/<name>` identity), click-to-preview expand with `RichToolResult` + NOOP dispatcher (readonly preview, same pattern as Recent-calls + From-channel tabs), confirm/cancel footer.
- **`AddFromChannelSheet` integration** — new `Tab = "library"` variant. `PinScopePicker` reused so bot choice drives the bot/workspace scopes. Pin action posts `source_kind: "adhoc"` + `source_bot_id` + `tool_args: { library_ref: "<scope>/<name>" }` with an envelope carrying `source_kind: "library"` + `source_library_ref` — DB-level source_kind stays "adhoc", the envelope drives the renderer, matching Phase 6.5's convention.
- **Types** — `WidgetLibraryEntry` + `WidgetLibraryCatalog` in `ui/src/types/api.ts`.
- **Channel-dashboard "Developer tools" split-button** — `ui/app/(app)/widgets/index.tsx`'s lone "Add widget" button is now a split button: primary action opens the sheet; attached caret opens a small menu with "Developer tools" routed to `/widgets/dev?from=<slug>`. Existing `?from=` plumbing already carries channel context into the dev-panel back-nav + `DashboardTargetPicker` seed, so the developer tools panel lands on the originating channel's dashboard for pin-target selection. Removed the separate channel-hidden `Developer panel` link — the menu entry is always present, including on channel-scoped dashboards where it was previously invisible.
- **Tests** — 3 new `TestLibraryWidgetsEndpoint` cases (core-only without bot_id / bot-scope enumeration / unknown bot 404) in `tests/integration/test_widget_catalog_api.py`. Full catalog + dashboard-tools suites 41/41 green, widget-library + widget-paths unit 32/32 green, UI tsc clean.

Deferred to a future polish pass: inline delete/rename gestures on library tab rows. The existing HTML-widgets tab UX is already decent — Library tab matches its feel.

Phase 9 shipped 2026-04-21 — `sd-*` v2 DX layer closes the "widgets look austere" gap before the Phase 7 rich-widget batch. Changes:
- **New `ui/src/components/chat/renderers/widgetIcons.ts`** — curated 60-icon Lucide (MIT) SVG sprite emitted once per iframe `<body>`; `<svg class="sd-icon"><use href="#sd-icon-<name>"/></svg>` references are O(1) with no extra request.
- **`ui/src/components/chat/renderers/widgetTheme.ts` extended** (~220 → ~490 lines): `.sd-check` (animated check-mark draw via `stroke-dasharray`), `.sd-radio` (dot fill), `.sd-switch` (thumb slide), `.sd-input-group` (leading-icon + trailing-action pattern), `.sd-row` + `.sd-row__title/meta/actions` (hover-revealed action cluster), `.sd-list` / `.sd-list--divided`, `.sd-section`, `.sd-tag` + `.sd-tag__remove`, `.sd-menu`, `.sd-tooltip`, `.sd-modal`, `.sd-kbd`, `.sd-icon` + tone modifiers, `.sd-anim-fade-in/pop`, `.sd-is-loading` spinner overlay. All motion gated on `prefers-reduced-motion: no-preference`. `.sd-empty` gains optional `__icon/title/subtitle/cta` children (backward compatible).
- **`window.spindrel.ui.*` grew**: `icon(name, {size, tone})`, `autogrow(textarea)`, `menu(anchorEl, items)` (keyboard nav + outside-click), `tooltip(el, text)`, `confirm({title, body, danger})` → `Promise<boolean>`.
- **Todo widget rebuild** (`app/tools/local/widgets/todo/index.html`, v1.1.0) — now uses `sd-input-group` with leading plus icon + trailing primary button, `sd-check` animated rows with trash-icon hover action, structured empty state with `list` icon, `sd-anim-fade-in` on newly-added items and fade-out on delete. Handler contract (`list_todos`/`add_todo`/`toggle_done`/`delete_todo`) unchanged.
- **Docs**: `skills/widgets/styling.md` gains a "Component cookbook (sd-* v2)" section with copy-pasteable snippets; `skills/widgets/sdk.md` documents the five new `ui.*` helpers.
- **Size**: preamble grew from ~32 KB to ~54 KB per iframe (gzip ≈ 15 KB). tsc clean; 64 widget-related unit tests green locally (`test_todo_widget`, `test_emit_html_widget`, `test_preview_widget`).

Phase 10 shipped 2026-04-21 — two gaps surfaced in the kitchen-dashboard session closed. (A) The Library tab was a parallel second system that didn't show bot-authored widgets and surfaced junk: tool-renderer `template.yaml` entries (`get_task_result`, `manage_bot_skill`, `schedule_task`, `list_tasks`, `get_system_status`) with no way to pin them (they need runtime tool args). Meanwhile the "HTML widgets" tab covered builtin + integration + channel but missed `widget://bot/…` + `widget://workspace/…`. Two tabs, overlapping, neither complete. (B) The bot-debug loop — `inspect_widget_pin` tool shipped 2026-04-21 session 3 but `skills/widgets/errors.md` never grew an entry for the symptoms bots actually hit (success-but-empty-UI, `TypeError: Failed to fetch`), so bots defaulted to writing `env.data.x || env.body.data.x || env.result.data.x` fallback chains that silently returned `undefined`.

- **Unified `/widgets/library-widgets` endpoint** (`app/routers/api_v1_dashboard.py`) now returns five scopes — `core`, `integration`, `bot`, `workspace`, `channel` — with a single entry shape (`WidgetLibraryEntry`) covering both `widget://` scopes and scanner-sourced ones. New `_scanner_entry_to_library` adapter normalizes `HtmlWidgetEntry` → library entry, preserving `path` / `integration_id` / `channel_id` so the pin envelope can route content fetches through the matching `/html-widget-content/*` endpoint. Accepts optional `channel_id` query param; `bot_id` unlocks bot + workspace scopes as before. `_iter_core_widgets` template-format entries are filtered at the endpoint boundary.
- **`widget_library_list` bot tool** (`app/tools/local/widget_library.py`) now also excludes `template`-format entries from the default listing. Pass `format="template"` to inspect them. Tool description updated.
- **Frontend unification**: `ui/app/(app)/widgets/LibraryWidgetsTab.tsx` grew two new sections ("Integrations", "Channel workspace") alongside the existing Core / Bot / Workspace sections. `envelopeForLibraryEntry` is scope-aware — scanner scopes synthesize `source_kind: "integration" / "channel"` envelopes (same shape the old HtmlWidgetsTab produced) so the renderer + pin-dedup identity stay unchanged. `libraryPinIdentity` widened to handle both `library:<ref>` and `<kind>::<path>` shapes. `AddFromChannelSheet.tsx` deleted its `html-widgets` tab + state + fetch; `HtmlWidgetsTab.tsx` removed from the tree. Dev-panel `HtmlWidgetsLibrarySection.tsx` stays on the old `/html-widget-catalog` endpoint as an inspection-only surface (repo-wide browse + copy-source) — kept separate because its goal is "what's in the repo", not "what can I pin here".
- **`skills/widgets/errors.md` rewritten**: new "Silent extraction failures" section at the top with the success-but-empty-UI symptom → `inspect_widget_pin` fix row; `TypeError: Failed to fetch` literal entry under Network errors; new "Envelope-shape index" table documenting canonical shapes for the 12 most-called tools (frigate_snapshot flat / ha_get_state with one `data` wrapper etc.) so bots can code against confirmed paths without guessing; new "Inspecting a pinned widget" recipe section detailing the five-step debug loop with example event JSON. Imperative "never type `||` between two envelope paths" rule threaded through both the new section and the anti-pattern table. `skills/widgets/tool-dispatch.md` "Knowing the output shape before you call" section trimmed — duplicate canonical shapes pulled out, now points at the central envelope-shape index.
- **Tests**: 2 new `tests/unit/test_widget_preamble_helpers.py::test_skill_doc_documents_debug_loop_recipe` assertions (inspect_widget_pin mentioned, TypeError: Failed to fetch literal, frigate_snapshot / ha_get_state + canonical extraction paths greppable). 2 new `TestLibraryWidgetsEndpoint` cases (`test_core_excludes_template_renderer_entries`, `test_integration_scope_is_populated`). Existing `test_core_only_without_bot_id` updated to the 5-scope shape + `format ∈ {html, suite}` tightening. 117 widget tests green in Docker; skill-doc tests green locally (Dockerfile.test excludes `ui/`).

Phase 12 shipped 2026-04-21 — authored widgets can now declare a host-owned panel title that renders outside the widget body anywhere the host presents the widget in a panel surface.

- **New metadata contract** — `panel_title` and `show_panel_title` are now valid in HTML frontmatter and `widget.yaml`. `display_label` stays the generic library/card label; `panel_title` is distinct host chrome. `widget_manifest.parse_manifest` validates both fields and `html_widget_scanner` merges them with manifest precedence over frontmatter.
- **Library/catalog propagation** — scanner entries, `widget_library_list`, `/api/v1/widgets/library-widgets`, `emit_html_widget(library_ref=...)`, `preview_widget(library_ref=...)`, and the shared `ToolResultEnvelope` all now preserve `panel_title` / `show_panel_title`, so authored widgets keep the metadata whether they are previewed, emitted to chat, or pinned from the library.
- **Panel-surface rendering** — `PinnedToolWidget` now has an explicit `panelSurface` mode. On panel surfaces, authored widgets with `show_panel_title: true` render a dedicated host header row using `panel_title` (falling back to the resolved display name). That header sits outside the widget body and replaces the old compact title treatment on those surfaces. The new contract is wired through dashboard panel mode, rail/dock surfaces, chat side-panel hosts, and the mobile widget drawer so the behavior is consistent instead of mobile keeping its old special-case title/height treatment.
- **Docs/tests** — `skills/widgets/html.md` and `skills/widgets/manifest.md` now document the new host-chrome contract. Added regression coverage for manifest validation, scanner metadata extraction + manifest override precedence, library-ref envelope propagation in both `emit_html_widget` and `preview_widget`, and `/widgets/library-widgets` returning the new fields for authored widgets. Local targeted pytest selections for the new panel-title cases passed under `.venv`; plain host `pytest` still misses `croniter`, so widget verification should continue using the repo venv or Docker image.

Phase 13 shipped 2026-04-21 — the shared HTML widget SDK now has a first-class theme library instead of one hardcoded renderer stylesheet.

- **Persistence + defaults** — new `widget_themes` table stores named custom themes (light tokens, dark tokens, custom CSS, fork source, author metadata). `builtin/default` is virtual + immutable; global default is now `WIDGET_THEME_DEFAULT_REF`.
- **Resolution model** — effective theme precedence is `channel.config.widget_theme_ref` → global default → `builtin/default`. Public `/api/v1/widgets/themes/resolve` returns the resolved theme payload for a channel so the renderer does not guess.
- **Renderer integration** — `InteractiveHtmlRenderer` now resolves the active widget theme per channel, compiles iframe CSS from its tokens, appends theme custom CSS, and injects `themeRef`, `themeName`, and `isBuiltin` on `window.spindrel.theme`.
- **Human controls** — `/widgets/dev` gained a `Themes` tab for listing/forking/creating/editing themes and applying them globally or to the current channel. Channel settings `General` also gained a widget-theme selector for the per-channel override.
- **Bot controls** — new control-plane tool `manage_widget_theme` supports `list|get|create|fork|update|delete|apply_channel`; `manage_channel` also accepts `widget_theme_ref`.
- **Docs** — `skills/widgets/styling.md`, `skills/widgets/html.md`, `skills/widgets/sdk.md`, and `skills/configurator/channel.md` now document the immutable builtin theme, per-channel theme refs, and the rule that widgets should keep using `sd-*` + `window.spindrel.theme` rather than vend their own global stylesheet copies.
- **Verification** — `npx tsc --noEmit` clean in `ui/`; targeted Python syntax compile on the new/changed backend files clean. Manual browser QA for `/widgets/dev#themes` is still pending.

Phase 14 shipped 2026-04-21 — repaired the library surfaces that had drifted out of sync and threaded the first shared grouping/theming metadata through the catalog.

- **Add Widget sheet no longer hides bot/workspace widgets behind `Runs as`.** `WidgetLibrary` now separates pin-auth bot identity from library-resolution bot identity. In pin mode, bot/workspace entries resolve through `libraryBotId` (channel bot fallback when `Runs as = You`) while core/integration/channel entries still keep user auth unless a bot is explicitly selected. This closes the "bot-authored widgets disappear unless I flip Runs as to a bot" regression.
- **Dev panel library now carries channel context.** `/widgets/dev?from=channel:<id>` now passes `originChannelId` into `LibraryTab`, and `/api/v1/widgets/library-widgets/all-bots` accepts `channel_id` so the same unified library surface can populate the `channel` section instead of hardcoding it empty.
- **Workspace entries in the all-bots catalog now keep a representative bot context.** The all-bots endpoint annotates shared-workspace rows with the first bot that discovered them so live preview/source fetches for `widget://workspace/...` can resolve through `/html-widget-content/library`.
- **Shared widget metadata widened without pretending template-theme parity exists.** Library entries now surface `widget_kind`, `widget_binding`, `theme_support`, and optional `group_kind` / `group_ref`. HTML/library entries report `theme_support: html`; template/tool renderers are left theme-neutral for now.
- **Suite/package grouping is now first-class metadata.** `widget.yaml`, HTML frontmatter, and template package YAML can declare `suite:` or `package:`. HTML scanner + `widget_library_list` normalize those into `group_kind/group_ref`; admin widget-package list/detail responses expose the same grouping so the "Tool renderers" tab can badge related definitions. Existing `suite.yaml` bundles also surface as `group_kind: suite`.
- **Verification** — `ui` `npx tsc --noEmit` clean; touched backend files pass `python -m py_compile`. Added integration assertions for `group_kind/group_ref` on library widgets and `channel_id` support on the all-bots catalog. Direct `pytest tests/integration/test_widget_catalog_api.py -q` remained unreliable under the current shell wrapper and did not return a trustworthy completion signal in-session.

Phase 15 shipped 2026-04-21 — aligned the bot-facing authoring surfaces with the repaired library model so bots get the correct guidance instead of defaulting every widget ask to HTML.

- **Tool descriptions now reflect the real split.** `emit_html_widget`, `preview_widget`, `widget_library_list`, and `pin_widget` now describe HTML widgets as the iframe-backed path rather than the umbrella term for every widget, and they point bots at `widget://bot/...` / `widget://workspace/...` for reusable bundles.
- **Grouping is now part of authoring guidance.** The tool descriptions and widget skills now tell authors to set exactly one of `suite:` or `package:` when a widget belongs to a related family, matching the catalog metadata surfaced in Phase 14.
- **Skills start from template-vs-HTML instead of HTML-first.** `skills/widgets/index.md` now routes authors through the actual decision tree: prefer template/tool-renderer widgets when the renderer already fits; reach for HTML when the UI needs free-form layout, local JS, or current widget-theme support.
- **Docs now call out the theme boundary honestly.** HTML widget docs mention that the widget theme system currently applies to HTML widgets; template-widget theme parity remains follow-up work.
- **Supporting skills updated.** `widgets/html.md`, `widgets/manifest.md`, and `widgets/dashboards.md` now cover grouping, preview-before-emit, and the current reusable-library authoring flow.

Verification:

- Touched backend tool files pass `python -m py_compile`.
- No product/UI behavior changed in this phase, so no new browser-flow verification was required beyond the already-completed Phase 14 library repair checks.

Phase 16 shipped 2026-04-21 — the unified library's Tool renderers tab is no longer just a browse-only package list.

- **Tool renderers can now be configured and previewed directly inside the shared library UI.** `WidgetLibrary` now mounts a dedicated `ToolRenderersPane` that groups renderer packages by tool, shows the active package, collects tool args, and runs the real tool to preview the resulting widget envelope inline.
- **Add Widget can now pin configured template-widget instances from the same tab.** In pin mode, the renderer pane reuses the existing `adhoc` dashboard pin shape: execute tool with args, render the active widget template, then persist `tool_name` + `tool_args` + preview envelope through `pinWidget(...)`. That closes the old "Tool renderers are discoverable but only usable via Recent calls" gap.
- **Pin scope stays aligned with the existing Add Widget controls.** The renderer flow treats `Runs as` as the authoritative bot scope in pin mode. If `Runs as = You`, bot-required renderers stay blocked with an explicit message rather than silently pinning under some other bot identity.
- **Channel dashboards keep renderer instances bound to their own channel context.** When the library opens inside a channel dashboard, the renderer pane fixes `source_channel_id` to that channel for both preview and pin so later refreshes and actions keep running in the same channel context.
- **This phase is UI-layer unification, not a new public widget-preview API.** The renderer pane currently reuses the existing admin tool execution / preview endpoints that were already backing the developer tooling; a future pass can add a user-safe widget-facing instantiate API if non-admin surfaces need to decouple from those routes.

Verification:

- `cd /home/mtoth/personal/agent-server/ui && npx tsc --noEmit` clean after extracting `ToolRenderersPane` and wiring it into the shared library surface.

Phase 17 shipped 2026-04-21 — template-widget instantiation now has a shared public preview path, and bot/dashboard tools can use the same capability.

- **New public widget preview endpoint** — `POST /api/v1/widgets/preview-for-tool` now executes a tool with optional `tool_args`, `source_bot_id`, and `source_channel_id`, then renders the active template/tool-renderer widget for that tool into a normal pin-ready envelope. The route lives on the regular widget/dashboard surface rather than under admin-only widget-package APIs.
- **Shared backend services now own the real work.** Tool execution with ContextVars moved into `app/services/tool_execution.py`, and active-template resolution + envelope rendering moved into `app/services/widget_preview.py`. The admin tool execute route and admin `preview-for-tool` route now reuse those helpers instead of carrying their own copies of the logic.
- **Public tool signatures now expose context requirements.** `/api/v1/tools/{tool}/signature` includes `requires_bot_context` and `requires_channel_context`, so non-admin widget/library surfaces can build argument/context forms without depending on the admin tools catalog.
- **Shared library renderer preview is no longer admin execute + admin preview chained together.** `ToolRenderersPane` now uses the public tool-signature endpoint for argument metadata and the new public widget preview endpoint for execution + rendering. The package list still comes from the existing widget-package catalog, but the instantiate path itself is no longer tied to admin-only preview semantics.
- **`pin_widget` gained template/tool-renderer parity.** `pin_widget(source_kind='library', widget='<tool_name>', tool_args={...})` now instantiates a template widget, renders its envelope, and persists it as the existing `adhoc` pin shape with `tool_name`, `tool_args`, and optional `widget_config`. Duplicate detection now covers that instantiated-template path as well.
- **Bot-facing tool copy updated.** `pin_widget` and `widget_library_list` now describe template/tool-renderer widgets as directly pinnable/instantiable via `tool_args` instead of browse-only entries.

Verification:

- Touched backend files pass `python -m py_compile`.
- `cd /home/mtoth/personal/agent-server/ui && npx tsc --noEmit` reached the targeted file checks and the only surfaced regression in-session (`ToolRenderersPane` stale `tool` reference) was fixed; the wrapper did not return a final clean completion signal afterward.
- Added targeted integration coverage for the new public preview endpoint and the `pin_widget` template-tool-renderer path, but the same shell-wrapper issue that affected earlier `pytest` runs in this track prevented a trustworthy final completion signal from the targeted commands in-session.

Phase 18 shipped 2026-04-21 — the unified widget interface now covers a third runtime kind, `native_app`, without inventing a second bot UX.

- **New first-party widget kind** — added `native_app` as a catalog/runtime kind beside `html` and `template`. Initial shipped entry is `core/notes_native`, exposed through the same library/catalog surfaces as the other widget kinds with `widget_ref`, supported scopes, and declared action metadata.
- **Instance-backed persistence for stateful native widgets** — new `widget_instances` table stores `widget_kind`, `widget_ref`, scope linkage, `config`, and `state`. Dashboard pins now carry an optional `widget_instance_id`; `native_app` pins resolve to a stable widget instance instead of storing all meaningful state in the adhoc pin envelope.
- **Unified bot action tool** — new `invoke_widget_action` local tool gives bots one interaction surface across widget kinds. Runtime dispatch stays kind-aware underneath:
  - HTML widgets route to existing bot-callable `@on_action` handlers
  - native app widgets route to the new native widget registry/service
  - only actions with declared schemas are exposed through the tool
- **Declared action schemas are now first-class catalog data** — native widget specs define `action_manifest` entries with `args_schema` / optional `returns_schema`; HTML widget library entries surface bot-callable handler schemas from `widget.yaml` / manifest metadata so bots can inspect before invoking instead of guessing payloads.
- **Native Notes proving widget** — `core/notes_native` ships as the first `native_app`:
  - rendered by a new `NativeAppRenderer` path in the React UI
  - persistent note body stored in `widget_instances.state`
  - direct inline editing in the UI via the shared widget-actions plumbing
  - bot action support through `invoke_widget_action`
- **Shared placement/catalog semantics kept intact** — `widget_library_list`, `/api/v1/widgets/library-widgets*`, `pin_widget`, dashboard pin serialization, and `describe_dashboard` now surface native widget metadata/action availability without changing the existing HTML/template mental model.
- **Docs/skills updated** — `skills/widgets/index.md` and `skills/widgets/bot-callable-handlers.md` now teach the three-lane model (`template` / `html` / `native_app`), the unified bot tool, and the rule that bots must inspect declared action schemas before calling actions.

Verification:

- `python -m py_compile` passed for touched backend files
- `pytest tests/unit/test_widget_library_list.py -q` passed (`11 passed`)
- `npx tsc --noEmit` passed in `ui/`
- Targeted native integration coverage was added to `tests/integration/test_dashboard_tools.py`, but the current shell wrapper again failed to produce a trustworthy completion signal for the focused `pytest -k native` run in-session

Follow-up polish landed later the same day:

- **Wrapper chrome now owns the outer title/background contract.** Per-pin `widget_config.show_title` remains the title-bar override, and a new sibling `widget_config.wrapper_surface` (`inherit` / `surface` / `plain`) lets the host wrapper decide whether it draws the outer shell or leaves the widget on a plain transparent surface.
- **Native Notes was simplified into an always-editable scratchpad.** The explicit edit/save mode, internal title, and action button were removed; Notes now renders as a single autosaving textarea so the host wrapper's title bar is the only outer header.
- **Old HTML Notes is retired from discovery, not deleted.** The legacy `notes` HTML bundle still exists for compatibility with existing pins and direct refs, but it no longer appears in core library/catalog listing. New Notes placements go through `notes_native`.
- **`wrapper_surface=plain` now works cleanly for HTML widgets too.** Pinned interactive HTML widgets no longer keep the old extra host padding/inset in plain mode, and the iframe runtime now exposes the host shell hint as `window.spindrel.hostSurface` plus `data-spindrel-host-surface` / `data-sd-host-surface` attributes so widget CSS can intentionally drop or keep its own inner card without the host trying to rewrite arbitrary styles.

Later on 2026-04-21, Phase 18 grew a second first-party native app and retired the old production Todo bundle:

- **`core/todo_native` now replaces the old HTML Todo widget.** Native Todo ships through the same library/catalog surfaces as Notes, stores its items in `widget_instances.state`, and exposes explicit bot/UI actions for add, toggle, rename, delete, reorder, and clear-completed.
- **The old production Todo bundle was deleted rather than hidden.** `app/tools/local/widgets/todo/` and its prod-only bridge tests were removed so new behavior cannot silently route through the legacy `widget.py` handler path.
- **Native Notes picked up a draft-safe renderer sync fix while this landed.** The React renderer now refuses to clobber a local notes draft with an older incoming envelope, which matches the user report of “typed text disappears without an error” and keeps the native Todo form from inheriting the same bug.

Verification:

- `python -m py_compile app/services/native_app_widgets.py app/tools/local/widget_library.py`
- `./node_modules/.bin/tsc --noEmit --pretty false` returned exit code 0 in `ui/`
- Focused `pytest` commands for the new native widget tests and native dashboard/catalog integration were added/run with timeouts, but the current shell wrapper still failed to emit trustworthy pass/fail lines before timing out in-session

## MVP decision — FS-backed, not DB-backed

Per-bot and workspace-scoped widgets will live under `<ws_root>/.widget_library/<name>/` on the host FS (not a `bot_widgets` DB table as originally sketched in the plan). Trade-off: file-backed reuses all existing file-op machinery for free, survives workspace persistence exactly like any other bot file, and listing is a directory walk. DB-backed can come later if we need cross-workspace reuse, but the FS approach unblocks authoring without a migration.

## Key Invariants

- **Bots never touch filesystem paths for widget source.** They address `widget://core/<name>/...`, `widget://bot/<name>/...`, `widget://workspace/<name>/...` via existing `read_file`/`write_file`/`str_replace`/`list_files`. Core library (`app/tools/local/widgets/`) is read-only to bots at runtime.
- **One net-new API**: `widget_library_list` for metadata-rich listing. Everything else reuses existing file ops.
- **Bot-authored widgets are HTML + SDK only.** No server-side Python handlers (`@on_action`/`@on_cron`/`@on_event`) — those require bot-Python sandboxing and stay core-only. SDK's `db.exec`/`api`/`callTool` covers mutation needs.
- **SQLite for bot suites works via written-schema, not written-files.** Bot writes `suite.yaml` + `migrations/*.sql`; `resolve_suite_db_path` creates the DB on first pin; `acquire_db` runs migrations on first read (Phase B.6 fix).
- **`library_ref` is canonical.** `path=` stays for power-user / core refs. `html=` is for one-shot ephemera only.
- **`panel_title` is host chrome, not widget content.** It only affects panel surfaces and only when `show_panel_title: true`; `display_label` remains the generic widget/library label used outside panel chrome.
- **The wrapper owns outer chrome.** Title bars and outer surfaced-vs-plain shell treatment are host concerns (`show_title`, `wrapper_surface`); widgets own only their inner composition.
- **Library discovery and pin auth are distinct concerns.** `Runs as` controls eventual pin auth; bot/workspace library enumeration may resolve through the current channel's bot even when pin auth remains user-scoped.
- **Theme support must stay explicit.** The unified catalog can badge/filter `theme_support`, but only HTML widgets participate in the widget theme system today.
- **Related-widget grouping uses one shared metadata shape.** Public catalog/package responses should prefer `group_kind/group_ref` over inventing separate UI-only `suite` and `package` code paths.
- **Product-level widget interfaces are unified; runtime substrates are not.** Library discovery, placement, and bot action invocation should look uniform across `html`, `template`, and `native_app`, but backend dispatch remains widget-kind-specific.
- **`native_app` is first-party only.** Native React widgets are for core / vetted shipped integrations only; bots and workspace users do not author them directly.

## Current Assessment

### Gaps

- **Schema inspection is stronger in bot/tool surfaces than in human UI.** Bots can inspect `available_actions`, but the shared library and pin-management UI still do not foreground action schemas strongly for human operators.
- **Integration verification is still weaker than the implementation.** The native Notes path and unified action tool have targeted coverage, but the current shell/test wrapper still makes focused integration confirmation unreliable in-session.

### Double Down

- **Declared action schemas as the contract.** Keep pushing more widget operations behind explicit schemas instead of informal payload conventions.
- **One library / one placement model / one bot action tool.** The unified interface is paying off; future widget work should preserve that surface instead of adding kind-specific bot ergonomics first.

### Needs Improvement

- **Authoring guidance is still HTML-heavy in some deeper docs.** The umbrella docs now acknowledge `native_app`, but some sub-skills still read as if HTML is the only interactive lane.
- **Action discoverability after pinning needs a better operational story.** `describe_dashboard.available_actions` works, but there is not yet a dedicated “inspect widget contract” surface that makes instance id, action schemas, and scope rules easy to audit.

## References

- Plan file: `~/.claude/plans/breezy-imagining-conway.md` (approved 2026-04-20)
- Prior tracks: `Track - Widget Dashboard.md` (shipped), `Track - Widgets.md` (if exists), `Track - Widget SDK.md` (if exists)
- Related Loose Ends: `{{config.*}}` collision, `widget_db._BUILTIN_WIDGET_DIR` parents[2] bug, chip editor fidelity
- Key files: `app/tools/local/file_ops.py`, `app/tools/local/emit_html_widget.py`, `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx`, `skills/html_widgets.md`
