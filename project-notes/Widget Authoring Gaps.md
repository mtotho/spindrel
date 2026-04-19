---
tags: [agent-server, reference, widgets, authoring, dev-panel]
status: reference
updated: 2026-04-18
---
<!-- 2026-04-18 session 19: P4 consolidation shipped — items 1 and 8 of the gap list are done.
     Kept for reference of items 2–7, 9 which remain open. -->

# Widget Authoring — Gaps & Unification Notes

Companion to [[Track - Widget Dashboard]]. Captures the real unification question that surfaced during P6 planning: **there is no duplicate UI to merge** across `/admin/widget-packages/new`, `/admin/widget-packages/[id]`, and `/widgets/dev` — the gap is a *missing bridge* from the sandbox layer (ephemeral) to the library layer (persistent). This note seeds a future `Track - Widget Authoring UX`.

## What exists today

**Five authoring entry points, one editor.** All five converge on `ui/app/(app)/admin/widget-packages/[packageId]/index.tsx` (341 lines) with `isNew` branching (line 70). Route structure is already DRY — no merge work.

| Entry | Route | File |
|---|---|---|
| Unscoped "New package" | `/admin/widget-packages/new` | `admin/tools/index.tsx` |
| Tool-scoped "New" | `/admin/widget-packages/new?tool=X` | `admin/tools/library/ToolGroup.tsx` |
| Tool-scoped "Create one" + "New variant" | same | `admin/tools/[toolId]/ToolWidgetSection.tsx` |
| Edit | `/admin/widget-packages/{id}` | `admin/tools/library/PackageCard.tsx` |
| Fork | `/admin/widget-packages/{forked_id}` | `PackageCard.tsx` |

The **editor surface** is ~1400 lines of mature code:
- `EditorPane.tsx` (183) — YAML + Python + Sample JSON tabs, colorized CodeEditor
- `PreviewPane.tsx` (194) — 500 ms debounced live preview (blocked until first save)
- `WidgetPackageHeader.tsx` (158) — fork/activate/delete
- `WidgetLibraryTab.tsx` + `PackageCard.tsx` (516) — discovery, search, filter
- Validation with line-number errors (400 ms debounced), Pydantic schema gate

**Two layers, intentionally separate.**
- `/admin/widget-packages/*` — persistent library (mature)
- `/widgets/dev` — ephemeral sandbox. P3 shipped the Tools tab + "Pin to dashboard" + MCP execute; P6 (2026-04-18) added a generic-view fallback so untemplated tools can be pinned as static cards.

The track explicitly positions P4 Templates tab as a *stateless YAML evaluator* (paste YAML + sample → preview) and P4 Recent as a *ToolCall history loader that imports into the Library editor*. These are integration points, not replacements.

## The real gap: sandbox → library bridge

The user spotted this in the P6 planning session: *"am I just trying to implement the UI-based template builder from another direction?"* The answer is yes when the generic-view widget gets sophisticated (tree picker, per-field style, pipes). So P6 deliberately stayed minimal — the rich authoring surface is the Library editor. But the **transition between the two layers is missing**. Today a user running a tool in `/widgets/dev#tools` has to:

1. Open `/admin/tools#library` in a new tab
2. Find the tool, click "New variant"
3. Manually re-enter the tool name, copy the sample payload from the sandbox, start from `BLANK_YAML`

That's where the gap lives — not in the surfaces themselves.

### Reusable primitive: `render_generic_view`

`app/services/generic_widget_view.py::render_generic_view()` (P6) auto-picks a component tree from any JSON. It has three consumption points:

1. **Pin as static card** (shipped P6 — via `POST /api/v1/admin/widget-packages/generic-render`)
2. **Future: seed `widget_config`** for a v1.1 configurable generic view (field selections, per-field labels/styles) — still pin-flow, no new editor
3. **Future: seed starter YAML** for "Save as template" — instead of `BLANK_YAML`, the Library editor opens with an auto-derived template that already renders something reasonable for the tool's shape

## Gaps to elevate the Library editor to the canonical authoring place

Prioritized by user-visible win:

1. ~~**Sandbox → Library bridge**~~ — **shipped 2026-04-18 (session 19)**. Solved differently than originally proposed: instead of a "Save as template from adhoc run" button in `/widgets/dev#tools`, P4 made the Templates tab itself the canonical editor. Sandbox users who want to persist a template now navigate to `#templates`, type their YAML with live preview via `preview-inline`, and click "Save to library." No sessionStorage bridge needed — the editor is the bridge. An "Import from real tool call" affordance (item 2) will cover the original "seed sample payload from a live ToolCall" use case.
2. **"Import from real tool call"** on the Library editor's Sample tab — pulls a `ToolCall` row's `arguments` + `result_text` as the sample payload. Same plumbing as P4 Recent tab.
3. **GUI field-path picker** — visual tree over the sample JSON; click a leaf → inserts `{{path}}` at cursor.
4. **Component type picker** — autocomplete / dropdown for the ~15 known types (currently only reachable via `WidgetTemplatesDocsModal`).
5. **Per-field style selector** — dropdowns for `color`, `variant`, `layout`. Cheap once (4) exists.
6. **Drag-reorder components** — visual reorder on top of YAML.
7. **`state_poll` and `default_config` form builders** — structured forms instead of raw YAML.
8. ~~**Live preview for new drafts**~~ — **shipped 2026-04-18 (session 19)**. `PreviewPane` now branches on `isNew || !packageId` and calls `previewWidgetInline()` for drafts, `previewWidgetPackage()` for saved packages. "Save the package first to enable live preview" empty state replaced with a friendly "Start typing a YAML template" state.
9. **LSP / schema hints** — inline autocomplete. Highest effort, lowest priority.

## Effort sizing

The hard parts (validation, preview, CRUD, live rendering) are done. Items 1, 2, and 8 are small (together ~300–500 LoC, touch existing files, reuse existing endpoints). Items 3–7 are the polish-to-canonical range (~600–1000 LoC). Not a greenfield build.

## Recommendation

Items 1 and 8 shipped as part of P4 (2026-04-18, session 19). Next: item 2 (Import from real tool call) pairs naturally with P5 Recent tab. After that, items 3–7 constitute a potential future `Track - Widget Authoring UX` for the long-tail polish sprint (tree picker, component type dropdown, per-field style, drag-reorder, form builders). Item 9 (LSP hints) remains lowest priority.

## References

- Plan (P4): `~/.claude/plans/glimmering-tumbling-sky.md`
- Plan (P6): `~/.claude/plans/concurrent-greeting-dahl.md`
- Code (editor, now canonical): `ui/app/(app)/widgets/dev/editor/` (lifted from the old `admin/widget-packages/[packageId]/` in P4)
- Code (library list, reused): `ui/app/(app)/admin/tools/library/`
- Code (dev panel shell): `ui/app/(app)/widgets/dev/`
- Generic view primitive: `app/services/generic_widget_view.py` + `app/routers/api_v1_admin/widget_packages.py::generic_render`
