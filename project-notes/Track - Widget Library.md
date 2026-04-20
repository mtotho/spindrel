---
tags: [widgets, library, sdk, track]
status: active
updated: 2026-04-20
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
| 3 | Skill reorg: `skills/html_widgets.md` → `skills/widgets/` folder | pending |
| 4 | `preview_widget` tool wrapping existing preview endpoints | pending |
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

Natural next block is Phase 3 (skill reorg): `skills/html_widgets.md` → `skills/widgets/` folder with a decision-tree `SKILL.md`, per-format docs (templates/html/suites/chips), and an `errors.md` keyed by error string. Items 4–6 fan out from there.

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
