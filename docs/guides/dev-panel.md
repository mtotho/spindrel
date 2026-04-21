# Developer Panel

The developer panel at `/widgets/dev` is the hands-on workbench for everything tool-related: browse the tool catalog, edit widget templates with live preview, call any tool with arbitrary args and see its rendered widget, and inspect recent tool results to reverse-engineer a tool's output shape before writing a template.

Think of it as Postman for Spindrel tools plus a widget authoring IDE, with one bonus trick: every rendered widget dispatches real actions against a real bot context — so the preview is exactly what users see, not a mock.

---

## Getting there

- Direct URL: `/widgets/dev`
- From a dashboard, use the **Add widget** split-button and pick **Developer tools**.
- Deep link a tab: `/widgets/dev#tools`, `#templates`, `#library`, `#recent`.

The panel honors a `?from=<slug>` origin hint — when you arrive from a specific dashboard, the back-arrow in the PageHeader returns there, and the DashboardTargetPicker in the tab bar pre-fills the pin target.

---

## The four tabs

| Tab | What it's for |
|---|---|
| **Library** | Browse reusable HTML/widget-library entries from core, bot, and workspace scopes. Preview them and pin them directly. |
| **Templates** | Author / edit / fork packages: YAML + Python + sample payload with live preview. |
| **Call tools** | Pick a tool, fill the args form, run it, render the widget against the real envelope. Pin the result to a dashboard. |
| **Recent** | Inspect recent tool invocations across the server. Filter by tool or bot. Import-into-Templates handoff seeds the editor with a real payload. |

Each tab is a plain hash-routed component; switching tabs preserves the other tabs' state within the session.

---

## Call tools — the sandbox

This is where most of the workbench's power lives. Source: `ui/app/(app)/widgets/dev/ToolsSandbox.tsx`.

### Grouped tool list

The left rail lists every tool visible to you. **Built-in** tools (core local tools) come first, then each integration gets its own collapsible group — `Frigate`, `Home Assistant`, `Web Search`, etc. Each tool shows per-item icons flagging its context requirements:

- 🤖 `Bot` icon — tool calls `current_bot_id.get()` somewhere; you must pick a bot before running.
- `#` icon — tool calls `current_channel_id.get()`; you must pick a channel.

These come from the `@register(..., requires_bot_context=True, requires_channel_context=True)` flags on the tool's decorator. Without them, the backend can't tell which tools read ambient context, so the sandbox would silently return empty data from tools that seemed to "work." The Pin button is gated until selection is complete for a tool that declares either requirement.

### Bot + channel context — sticky

A `BotPicker` and `ChannelPicker` sit always-visible above the args form. Selections are persisted in `localStorage` (`spindrel:widgets:dev:context`) so reloading the page keeps the same sandbox identity. Changing either resets the envelope preview — it's a new context, a new result.

Under the hood, the POST to `/api/v1/admin/tools/{tool_name}/execute` includes the `bot_id` and `channel_id`, the endpoint sets `current_bot_id` / `current_channel_id` ContextVars around the tool call, and any tool that reads them returns real data — workspace files, channel memories, bot-authored skills, and so on (`app/routers/api_v1_admin/tools.py:143`).

### The args form

`ToolArgsForm` auto-generates input fields from the tool's JSON Schema. Objects and arrays get JSON editors; primitives get typed inputs. Defaults pre-fill. The form validates at execute time, not on every keystroke.

### Render + raw panels

After execute, the result shows in two co-equal panels:

- **Rendered widget** — the actual `RichToolResult` render pipeline, including inline action dispatch (buttons work, toggles work, state polls work). Button/toggle dispatches from the sandbox are *real*, not mocked.
- **Raw Result (JSON)** — the full response body in a collapsible `JsonTreeRenderer`. Stays co-equal with the rendered widget in layout — it's intentional, not demoted. You want to see the raw when a template is eating a field.

### Pin to dashboard

An **action bar** below the panels lets you pin the current envelope to any dashboard. The `DashboardTargetPicker` in the tab header controls the target. The pin carries the sandbox's bot + channel context with it, so the resulting dashboard pin authenticates as that bot, polls its tool with that channel's scope, and so on.

### MCP / client tool restriction

The admin execute endpoint only supports **local (Python) tools**. MCP tools and client tools return 400 from `/api/v1/admin/tools/{tool_name}/execute`. The reason: MCP tools may have side effects the backend can't preview safely, and client tools run in the browser — the server doesn't know how to dispatch them. The sandbox filters both out of the tool list.

If you need to preview a widget template for an MCP tool, use the Templates tab — the package editor's live preview uses a sample payload, not a real execution, so no tool-type gate applies.

---

## Templates — the package editor

Source: `ui/app/(app)/widgets/dev/editor/WidgetEditor.tsx`, surrounded by `EditorPane` (left) and `PreviewPane` (right).

A widget package has three pieces, edited side-by-side with live preview:

1. **YAML template** — declarative shape (`template:` or `html_template:`), `state_poll`, `default_config`, `display_label`, etc.
2. **Python transform** — optional `transform(data, components)` and `state_poll_transform(raw_result, widget_meta)` functions.
3. **Sample payload** — a JSON blob the preview feeds through substitution + transform.

Every keystroke (debounced) re-runs the pipeline and re-renders. YAML errors surface as inline validation issues; Python compile errors surface with line numbers; runtime errors in the transform fall back to the substituted components with a warning.

### Seed vs User packages

Packages fall into two sources:

| Source | What it is | Editable? |
|---|---|---|
| `seed` | Hydrated from integration YAML on every boot | No — fork to edit |
| `user` | Created or forked in the UI | Yes |

Fork a seed to produce a user package; edits land on the fork, the seed stays canonical. Exactly one package per tool is `is_active` at any time — the active user package overrides the seed; deleting a user package falls back to the newest non-orphan seed.

### Cross-reference to Widget Templates

The package model, YAML grammar, substitution syntax, `state_poll`, transforms, trust model — all live in the [Widget Templates](widget-templates.md) reference. The dev panel is the interactive shell over that grammar.

---

## Recent — working from real data

The Recent tab is the most underused path and often the fastest one. Use it when:

- A tool exists with no package yet — you want to see the actual result shape.
- A package is stale — the tool's result has drifted.
- You're writing a template and want a real, non-synthetic sample payload.

The tab lists recent tool invocations filtered by tool name, bot, or free-text. Clicking a row:

- Shows the recorded raw result in a preview panel.
- Exposes an **Import into Templates** button that seeds the Templates tab's editor with the tool + a sample payload matching that invocation, so you can start authoring a package from ground-truth output.

Pin-a-generic-view is also available on this tab — useful for sending a one-off envelope to a dashboard without authoring a package first (the renderer uses its generic fallback).

---

## Library — reusable widget bundles

The Library tab is distinct from the Templates catalog. It surfaces **library widgets** discoverable from three scopes:

| Scope | What it means |
|---|---|
| `core` | Built-in library widgets shipped with Spindrel |
| `bot` | Bot-authored widgets under that bot's library directory |
| `workspace` | Shared workspace-authored widgets |

Core widgets always show. Bot/workspace widgets require a bot selection so the panel can resolve the right workspace roots and auth context.

### What you do here

- Browse the catalog returned by `GET /api/v1/widgets/library-widgets`
- Preview a library widget with the real renderer
- Pin it directly to a dashboard
- See whether an item is already pinned

Library widgets are usually HTML-backed bundles, not per-tool template packages. The pin stores the `library_ref`, and the rendered envelope carries `source_kind: "library"` / `source_library_ref` so the runtime can load the bundle body later.

### Preview behavior

Preview uses the same `RichToolResult` pipeline as chat and dashboards. If the widget needs a bot context for auth and you have not selected one, the panel shows that explicitly rather than silently rendering a broken iframe.

This is also where the split between **authoring a reusable bundle** and **authoring a template for a tool result** becomes obvious:

- **Library** = reusable widget bundle you can pin directly
- **Templates** = renderer logic for a tool's result envelope

Use Library when you want a concrete widget asset. Use Templates when you want "tool X should render like Y."

---

## Keyboard + UX tips

- `/widgets/dev` remembers the last-visited tab via the URL hash — deep link to `/widgets/dev#tools` to land directly in the sandbox.
- The tab bar's Docs button opens an in-page modal with the full [Widget Templates](widget-templates.md) reference. No round-trip to an external site.
- Collapsed tool groups in the sandbox persist to `localStorage` — your usual working set stays expanded.
- The DashboardTargetPicker is contextual: when you land from `?from=<slug>`, it pre-selects that dashboard so a pin goes home.

---

## Reference

| What | Where |
|---|---|
| Panel entry | `ui/app/(app)/widgets/dev/index.tsx` |
| Tools sandbox | `ui/app/(app)/widgets/dev/ToolsSandbox.tsx` |
| Template editor | `ui/app/(app)/widgets/dev/editor/WidgetEditor.tsx` |
| Recent tab | `ui/app/(app)/widgets/dev/RecentTab.tsx` |
| Library tab | `ui/app/(app)/widgets/LibraryWidgetsTab.tsx` |
| Admin execute endpoint | `app/routers/api_v1_admin/tools.py:143` |
| Tool context flags | `@register(requires_bot_context=True, requires_channel_context=True)` |

## See also

- [Widget Templates](widget-templates.md) — the declarative package grammar.
- [HTML Widgets](html-widgets.md) — bot-authored HTML, runtime `emit_html_widget`.
- [Widget Dashboards](widget-dashboards.md) — where pins live, the OmniPanel rail, edit mode.
- [Custom Tools & Extensions](custom-tools.md) — writing local tools with `@register`.
