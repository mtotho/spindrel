# UI Components — Canonical Shared Controls

This guide is the component catalog for Spindrel UI work. `ui-design.md` owns visual principles; this file owns exact shared controls to use before creating local variants.

## Rule

Do not hand-roll dropdowns, prompt textareas, setting rows, action buttons, badges, or empty states when a shared component exists. If the shared component is missing a capability, extend it once and migrate callers.

## Selectors

Use `ui/src/components/shared/SelectDropdown.tsx` for custom dropdowns.

- Use for searchable lists, grouped lists, entity pickers, model/bot/channel/tool/workflow selectors, and any select that should not inherit browser-native styling.
- Default popover width is clamped for readability. Do not match a full-width settings row unless the list is genuinely short and static.
- `SelectInput` and model pickers must not open page-wide popovers just because their trigger sits in a full-width form row.
- Chrome is fixed: `rounded-md`, `bg-input` trigger, low-opacity selected rows, no `shadow-xl`, no filled blue trigger/action, no decorative border stack.
- Group options with `group` / `groupLabel`; search text with `searchText`; custom rows with `renderOption`.
- Keep native `<select>` only through `SelectInput` for tiny static choices. `SelectInput` delegates to `SelectDropdown` and enables search only when option count is high.

Domain wrappers that must use `SelectDropdown`:

- `LlmModelDropdown` for LLM and embedding model selection.
- `BotPicker` for bot/entity selection.
- `ChannelPicker` for channel/entity selection.
- `ToolSelector` for tool binding.
- `WorkflowSelector` for workflow binding.
- Prompt template insertion, task step controls, preset option pickers, pin scope bot selection, and schema enum/boolean fields should also route through `SelectDropdown`.

## Prompt Editors

Use `PromptEditor` from `ui/src/components/shared/LlmPrompt.tsx`. `LlmPrompt` is a compatibility alias and should not grow new behavior.

- Prompt areas must be comfortably editable by default: minimum height at least 160px, vertical resize, mono text, visible char/token estimate.
- Every prompt editor gets an `Expand` action that opens the fullscreen editor with the same autocomplete and generation behavior.
- Prompt autocomplete remains the `@` tag menu. Do not build a second completion menu.
- Generate actions are quiet text actions. No filled blue/green prompt buttons for routine generation or completion.
- Workspace-backed prompt editors should reuse the same sizing/action language even when they need Save/Cancel/Unlink controls.

## Source Text Editors

Use `SourceTextEditor` from `ui/src/components/shared/SourceTextEditor.tsx` for literal source strings such as YAML, JSON, Python, Markdown, and plain text blobs.

- Use it before creating page-local source/code textareas. Extend the shared component when syntax highlighting, line numbers, read-only display, validation status, search highlighting, or tab indentation needs to improve.
- Keep file ownership separate: workspace/file inspectors own target props, fetching, loading/error state, preview toggles, fallback links, and chrome; `SourceTextEditor` owns rendering or editing the already-loaded text string.
- Do not use `PromptEditor` or rich-text/Tiptap editors for YAML, JSON, manifests, or source files.
- Do not auto-format YAML unless the workflow explicitly accepts comment/ordering loss. Prefer validation plus highlighted structure for hand-authored manifests.

## Date And Time

Use `DateTimePicker` and `TimePicker` from `ui/src/components/shared/DateTimePicker.tsx`.

- Do not use native `type="time"` or `datetime-local` controls in settings surfaces; browser chrome/icons are inconsistent and can fail dark mode.
- `TimePicker` is the canonical time-only control for schedules, quiet hours, and time windows.
- `DateTimePicker` is the canonical absolute date+time control for task starts and scheduled execution.
- Date/time pickers should stay low-chrome: muted trigger icon, `rounded-md`, no `shadow-xl`, no filled accent selected day, no browser-native picker icon.

## Settings Controls

Use `FormControls.tsx` and `SettingsControls.tsx`.

- `Section`: title/description/action only; no section card chrome.
- `FormRow`: label, control, optional description.
- `ActionButton`: primary is transparent accent text; secondary is muted text; danger is text-danger. Filled accent is reserved for rare final confirmation.
- `SettingsControlRow`: logical row item with low tonal fill. Add borders only for expanded inline forms.
- `SettingsMeter`: canonical current/projected meter for cost, quota, capacity, and threshold progress. Use it instead of local progress bars when a value may have a projected extension.
- `EmptyState`: dashed low-chrome placeholder.
- `StatusBadge`, `InfoBanner`, and `SaveStatusPill`: semantic state only, not decoration.
- `QuietPill`: low-emphasis metadata tags inside dense rows. Use this for archived-section tags, compact row labels, and other metadata that should not compete with the row title.
- Light-mode contrast for these controls is owned by the global surface tokens first. If many shared controls look washed out, tune the shared opacity recipes here once instead of adding page-local backgrounds, borders, or extra accent colors.

## Admin Entity Catalogs

Use dense row catalogs for admin lists that need to scan, filter, and fit on mobile.

- Prefer `SettingsSearchBox`, `SelectInput`, `SettingsStatGrid`, `SettingsGroupLabel`, `SettingsControlRow`, `QuietPill`, and `StatusBadge` before creating a page-local card grid.
- Rows must be mobile-safe by default: wrap controls, use `min-w-0`, truncate long ids/models/paths, and avoid fixed card minimums that can force horizontal page scroll.
- Entity rows should expose operational signals that change what an admin does next: source type, file-backed configuration, access warnings, recent usage, readiness, and direct drilldown actions.
- Detail editors with many settings should group by workflow with a stable section nav and preserve legacy hash links where possible. Avoid one long flat tab list for 10+ sections.

## Source File Inspection

Use `SourceFileInspector` from `ui/src/components/shared/SourceFileInspector.tsx` when a row, search result, or activity item opens a workspace-backed source file.

- File-backed actions should open the file in place instead of navigating to a broad owner page and calling it "Open source".
- The inspector is read-only today: source/preview toggle, in-file find, copy, owner metadata, and a fallback "Open location" action for rows that cannot resolve a file target.
- Pages should pass an explicit `workspace_id` and workspace-relative `path`. Do not infer paths client-side from display text.
- Do not create one-off drawers for memory logs, knowledge files, prompt files, or history sources. Extend this shared component once if richer file previews, diffs, edits, or history are needed.

## Trace Inspection

Use the global trace inspector controller from `ui/src/stores/traceInspector.ts` when a dashboard, anomaly row, usage row, or activity item opens a trace by `correlation_id`.

- Trace-backed drilldowns should use `TraceActionButton` or call `openTraceInspector({ correlationId, title?, subtitle? })` before navigating users to `/admin/logs/:correlationId`.
- `TraceActionButton` is the default for visible trace actions in rows, cards, alerts, scheduled runs, heartbeat history, and task surfaces. Use `iconOnly` only inside already-dense rows with a tooltip/title.
- `TraceInspectorRoot` is mounted once in `AppShell` and portals a modal right-side drawer to `document.body`; pages must not mount their own trace drawers.
- `TraceTimeline` owns summary-first trace rendering shared by the drawer and `/admin/logs/:correlationId`: event filtering, in-trace find support, compact metadata, and collapsed raw payloads.
- Do not create page-local trace drawers for usage, scheduled tasks, heartbeat runs, memory activity, or debugging tables. Extend `TraceInspectorRoot` / `TraceTimeline` once when richer trace preview behavior is needed.

## Charts

Use `SimpleCharts.tsx` for low-chrome admin charts before introducing a chart dependency.

- `LineChart` is for compact trend lines where axes and labels are enough.
- `BarChart` is for ranked breakdowns.
- `TimelineChart` is for investigation timelines with anomaly markers and optional row selection.
- Keep chart color choices token-driven. Do not pass raw hex/RGBA chart colors from pages.

## Review Checklist

- A dropdown or selector imports `SelectDropdown` or an approved wrapper.
- A prompt imports `PromptEditor` or `LlmPrompt`.
- A source/code/YAML textarea imports `SourceTextEditor` or a documented domain wrapper around it.
- A date/time control imports `DateTimePicker` or `TimePicker`; no native browser date/time inputs in settings.
- Widget, task, and prompt-template configuration surfaces do not ship native `<select>` or local portal dropdowns unless they are documented specialized controls.
- Routine settings actions are not filled blue buttons.
- Dense-row metadata uses `QuietPill`; reserve `StatusBadge` for actual state.
- File-backed source links use `SourceFileInspector`; non-file fallbacks say "Open location", not "Open source".
- Trace-backed drilldowns use `openTraceInspector`; non-trace fallbacks navigate with a clear destination label.
- Popovers are not page-wide and do not use shadow stacks.
- Knowledge/help copy is typography-led; do not turn every explanatory sentence into a faded panel.
