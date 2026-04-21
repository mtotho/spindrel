---
tags: [widgets, library, sdk, track]
status: active
updated: 2026-04-20 (Phase 4 `preview_widget` tool shipped — dry-run feedback loop with structured `{ok, envelope, errors[]}` output)
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
| 5 | Chips as first-class: `spindrel.layout` + 3 reference chips + `layout_hints` frontmatter + `skills/widgets/chips.md` | pending |
| 6 | MC SDK dogfood pass — rewrite `mc_{timeline,kanban,tasks}` to use `form`/`ui.table`/`bus` | pending |
| 7 | Ship next 5 rich widgets: `ha_device_list`, `plex_now_playing`, `calendar_list_events`, `gmail_list_messages`, `list_traces` | pending |

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

## MVP decision — FS-backed, not DB-backed

Per-bot and workspace-scoped widgets will live under `<ws_root>/.widget_library/<name>/` on the host FS (not a `bot_widgets` DB table as originally sketched in the plan). Trade-off: file-backed reuses all existing file-op machinery for free, survives workspace persistence exactly like any other bot file, and listing is a directory walk. DB-backed can come later if we need cross-workspace reuse, but the FS approach unblocks authoring without a migration.

## Key Invariants

- **Bots never touch filesystem paths for widget source.** They address `widget://core/<name>/...`, `widget://bot/<name>/...`, `widget://workspace/<name>/...` via existing `read_file`/`write_file`/`str_replace`/`list_files`. Core library (`app/tools/local/widgets/`) is read-only to bots at runtime.
- **One net-new API**: `widget_library_list` for metadata-rich listing. Everything else reuses existing file ops.
- **Bot-authored widgets are HTML + SDK only.** No server-side Python handlers (`@on_action`/`@on_cron`/`@on_event`) — those require bot-Python sandboxing and stay core-only. SDK's `db.exec`/`api`/`callTool` covers mutation needs.
- **SQLite for bot suites works via written-schema, not written-files.** Bot writes `suite.yaml` + `migrations/*.sql`; `resolve_suite_db_path` creates the DB on first pin; `acquire_db` runs migrations on first read (Phase B.6 fix).
- **`library_ref` is canonical.** `path=` stays for power-user / core refs. `html=` is for one-shot ephemera only.

## References

- Plan file: `~/.claude/plans/breezy-imagining-conway.md` (approved 2026-04-20)
- Prior tracks: `Track - Widget Dashboard.md` (shipped), `Track - Widgets.md` (if exists), `Track - Widget SDK.md` (if exists)
- Related Loose Ends: `{{config.*}}` collision, `widget_db._BUILTIN_WIDGET_DIR` parents[2] bug, chip editor fidelity
- Key files: `app/tools/local/file_ops.py`, `app/tools/local/emit_html_widget.py`, `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx`, `skills/html_widgets.md`
