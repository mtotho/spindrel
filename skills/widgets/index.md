---
name: HTML Widgets
description: Decision tree for building interactive HTML widgets with `emit_html_widget` — which file to read next based on what you're building (inline one-shot, path-mode dashboard, backend handlers, shared-DB suite, chart, chip for the header band, styling question, error lookup)
triggers: emit_html_widget, html widget, interactive widget, custom widget, build a widget, mini dashboard, render html, iframe widget, workspace html, live dashboard, bespoke ui, project status dashboard, status board, tool control panel, chart widget, chip widget, header chip
category: core
---

# HTML Widgets — where to start

When the user asks for something you can't render with the standard component widgets — a chart, a custom layout, a mini-dashboard, a scraped page distilled into a card, an interactive control — emit an **HTML widget**. You write the HTML (and optionally JavaScript + CSS); it renders inside a sandboxed iframe in the chat bubble. The user can pin the result to their dashboard.

Unlike any string you might return as Markdown, an HTML widget can:

- Run JavaScript (fetch app data, handle clicks, update itself)
- Call the app's own API at `/api/v1/...` (same-origin — auth comes along for free)
- **Trigger backend tools** via `POST /api/v1/widget-actions` (run `fetch_url`, `generate_image`, whatever — the fresh result flows back as a new envelope)
- Re-render automatically when a workspace file changes (path mode)
- Persist state to a workspace JSON file and read it back next time
- Run server-side Python handlers on its own SQLite DB (Phase B — see `handlers.md`)

## When to Use Which Widget

| Situation | Use |
|---|---|
| Entity detail, toggle, or status card that fits the component grammar | Component widgets (YAML template) |
| Chart, table, free-form layout, or anything not in the grammar | `emit_html_widget` |
| User says "make me a custom widget for X" | `emit_html_widget` |
| User says "show me X live / as a dashboard" | `emit_html_widget` (usually path mode) |
| User says "build a status board / project dashboard / control panel" | `emit_html_widget` + a bundle (see `html.md`) |
| One-off inline result | Normal text/Markdown reply (no widget needed) |

Default to component widgets when a template exists; reach for HTML when the component grammar doesn't cover it.

## Decision tree — which sub-skill do you need?

```
Start: what do you want to render?
│
├─ Entity card, toggle, status, detail grid
│     → Component widget (YAML template). Not this skill.
│
├─ Chart, table, free-form layout, scraped page distilled
│     → HTML widget. Continue.
│
├─ One-shot, ephemeral, no backend state
│     → widgets/html  (inline mode)
│
├─ Dashboard that remembers — live project status, feed, control panel
│     → widgets/html  (path mode) + widgets/dashboards
│
├─ Need to call backend tools from the widget
│     → widgets/sdk  (spindrel.callTool) + widgets/tool-dispatch
│
├─ Need live updates from channel events (new messages, turns, tool activity)
│     → widgets/sdk  (spindrel.stream)
│
├─ Need server-side Python handlers
│     → widgets/manifest + widgets/handlers
│
├─ Want bots to read or mutate this widget's state in chat
│     → widgets/bot-callable-handlers
│
├─ Need per-widget SQLite storage
│     → widgets/manifest + widgets/db
│
├─ Need multiple widgets sharing one DB on the same dashboard
│     → widgets/suites
│
├─ Chip — compact 180×32 widget for the channel header band
│     → widgets/chips
│
├─ Styling / theme / dark mode / sd-* question
│     → widgets/styling
│
└─ Widget not rendering / blank / CSP error / 422 / silent crash
      → widgets/errors
```

Each of the target skills is loadable via `get_skill(skill_id="widgets/<name>")`. Read the one the current task needs — don't preload all of them.

## The canonical shape — path-mode bundle

The default shape is a **folder on disk** that you iterate on: `index.html` + `state.json` + optional assets, path-moded as the widget target, living in a well-known location the user can find. See `widgets/html.md` for the bundle layout and path grammar.

Inline mode (`emit_html_widget(html="...")`) is for one-off snapshots — a single view of data you already have in the turn. Anything the user will see more than once should be path-mode.

## Reactive controls — the rule authors keep missing

For control widgets (Home Assistant panels, mini dashboards with buttons, toggles, sliders), **`window.spindrel.callTool()` does not automatically re-render your widget**.

It only:

- runs the backend tool
- returns the fresh envelope to your JS
- leaves `window.spindrel.toolResult` alone unless the host later pushes a separate refresh

So after a click, the widget author must do one of these on purpose:

1. **Patch local in-memory state and re-render the affected section immediately**.
2. **Use the returned envelope from `callTool()` as the next source of truth and re-render from it**.
3. **Kick off a follow-up state read** (`spindrel.api(...)` or another tool call) and reconcile when it returns.

Do **not** assume the tile will become reactive just because the button call succeeded.

Also, avoid the "whole widget reload" feel:

- Do not call `location.reload()`.
- Do not rebuild the entire app root on every click unless the widget is tiny.
- Keep a local `state` object, mark only the clicked control busy, and re-render only the panel/card that changed.
- Treat host-driven refreshes (`onToolResult`, `onReload`) as reconciliation, not as the primary click response.

If you're building a live control surface, read `widgets/tool-dispatch.md` after this file. That's where the concrete click→state-update pattern lives.

## When NOT to use this skill

- Simple text / Markdown reply → just reply normally.
- Entity detail the existing `tool_widgets:` templates already cover → component widget is nicer.
- A link or file the user wants to open → `send_file` or a plain URL.
- Reusable across channels → author under `widget://bot/<name>/...` (bot-private library) or `widget://workspace/<name>/...` (shared-workspace library). Bundles live once in the library and render anywhere via `library_ref="<name>"`.

## Workflow — build an evolving dashboard

When the user says *"build me a dashboard for X"*:

1. **Discover** — `list_api_endpoints(scope="...")` to see what your bot can read/write. Build from what you have, not what you wish you had. `widget_library_list()` to see what bundles already exist.
2. **Pick a scope** — `widget://bot/<name>/...` (your bot's own library, always available) or `widget://workspace/<name>/...` (shared with every bot in this workspace, shared-workspace bots only). `widget://core/...` is read-only.
3. **Pick an archetype** — status (RMW `state.json`), feed (poll API), control panel (dispatch tools), KB reader (workspace files + markdown). Most real dashboards mix two. See `widgets/dashboards.md`.
4. **One-shot the bundle** — `file(create, path="widget://bot/<name>/index.html", content=<full doc>)` plus any `widget://bot/<name>/state.json` defaults. Use `sd-*` classes; use `window.spindrel.api()` for every GET; use `spindrel.callTool` for triggering work.
5. **Emit** — `emit_html_widget(library_ref="<name>", display_label="<Name>")`. The library resolves bot → workspace → core for unscoped refs; prefix with `bot/` or `workspace/` to disambiguate. User pins it to the dashboard.
6. **Iterate** — tweaks via `file(edit, path="widget://bot/<name>/index.html", ...)`. The pinned widget refreshes within ~3 s. No re-emit needed. When you hit a suspicious error — a CSP rejection, a missing manifest field, a path that won't resolve — call **`preview_widget(...)`** first with the same args you'd pass to `emit_html_widget`; it returns structured `{ok, envelope, errors}` so you can fix the bundle before the next emit. See `widgets/html.md#dry-run-first`.
7. **Record it** — leave breadcrumbs in `memory/MEMORY.md` + `memory/reference/<name>.md` so future-you knows the widget exists and where to find it. See `widgets/dashboards.md#remember-what-you-built`.

## See also

- [Widget Dashboards](../widget_dashboards.md) — the `describe_dashboard` / `pin_widget` / `move_pins` / `unpin_widget` / `promote_panel` / `demote_panel` tool suite for reading, proposing, and modifying dashboard layouts. `emit_html_widget` shows a widget in chat; `pin_widget` places a library widget on the dashboard.
