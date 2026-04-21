---
name: Widgets
description: Decision tree for building widgets across the three current lanes — template/tool-renderer widgets for bounded server-driven UI, HTML widgets for free-form iframe-backed bundles, and first-party native app widgets for flagship built-in React surfaces. Covers library authoring under `widget://`, grouping with `suite`/`package`, themes, dashboards, and which follow-up skill to read next.
triggers: emit_html_widget, html widget, template widget, yaml widget, tool renderer, interactive widget, custom widget, build a widget, mini dashboard, render html, iframe widget, workspace html, live dashboard, bespoke ui, project status dashboard, status board, tool control panel, chart widget, chip widget, header chip, panel title, sticky widget title, suite widget, package widget
category: core
---

# Widgets — where to start

Treat **widget** as the umbrella term. There are currently three implementation paths:

- **Template widget** — YAML/tool-renderer path. Use this for bounded, server-driven UI that already fits the component grammar or should stay close to tool results.
- **HTML widget** — iframe-backed bundle emitted with `emit_html_widget`. Use this for free-form layouts, charts, mini-apps, richer local interactivity, or when the component grammar is the wrong shape.
- **Native app widget** — first-party React widget shipped in the app (for example `notes_native`). Not bot-authored. Use this when the built-in library already exposes an official widget with persistent state and rich host integration.

HTML widgets can:

- Run JavaScript (fetch app data, handle clicks, update itself)
- Call the app's own API at `/api/v1/...` (same-origin — auth comes along for free)
- **Trigger backend tools** via `POST /api/v1/widget-actions` (run `fetch_url`, `generate_image`, whatever — the fresh result flows back as a new envelope)
- Re-render automatically when a workspace file changes (path mode)
- Persist state to a workspace JSON file and read it back next time
- Run server-side Python handlers on its own SQLite DB (Phase B — see `handlers.md`)

## When to Use Which Widget

| Situation | Use |
|---|---|
| Entity detail, toggle, status card, or bounded dashboard tile that fits the component grammar | Template widget / YAML renderer |
| Tool result should stay server-driven and refresh through tool actions + polls | Template widget / YAML renderer |
| Chart, table, free-form layout, or anything not in the grammar | HTML widget via `emit_html_widget` |
| User says "make me a custom widget for X" and the UI is bespoke | HTML widget |
| User says "show me X live / as a dashboard" | Usually an HTML bundle; use template only if the layout is simple and renderer-driven |
| User says "build a status board / project dashboard / control panel" | Usually HTML widget + bundle (see `html.md`) |
| User says "place the built-in Notes / official first-party widget" | Native app widget from the library, not a new HTML bundle |
| One-off inline result | Normal text/Markdown reply (no widget needed) |

Default to template widgets when a good renderer already exists; reach for HTML when the component grammar or server-driven model does not cover the request cleanly.

Bot control rule:

- Discover widgets through the shared library/catalog tools.
- Place them with `pin_widget`.
- Interact with pinned widgets through `invoke_widget_action`.
- Always inspect the widget's declared action schema first (`describe_dashboard` exposes `available_actions`; library metadata exposes actions for native widgets).

## The unified operator loop

Treat widgets with one operational loop regardless of runtime kind:

1. Discover through the shared catalog.
2. Place with `pin_widget`.
3. Inspect declared actions before operating.
4. Invoke through `invoke_widget_action`.

The interface is unified even though the runtime is not. Bots should think in terms of library entries, pins, widget instances, and declared actions — not iframe handlers vs native React internals.

Theme note:

- The widget theme system is currently implemented for **HTML widgets**.
- Keep shared widget naming generic, but do not promise template-widget theme parity yet.

## Decision tree — which sub-skill do you need?

```
Start: what do you want to render?
│
├─ Entity card, toggle, status, detail grid, tool result card
│     → Template widget / tool renderer. Prefer the YAML path.
│
├─ Need a free-form layout, chart, table, mini app, or richer local JS
│     → HTML widget. Continue.
│
├─ Need a built-in first-party widget like Notes with richer host-native UX
│     → Native app widget. Do not author this via HTML/YAML; place the existing library entry.
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
│     → Use `invoke_widget_action`; for HTML handler authoring also read widgets/bot-callable-handlers
│
├─ Need per-widget SQLite storage
│     → widgets/manifest + widgets/db
│
├─ Need multiple related widgets sharing one DB or grouped in the catalog
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

The default HTML shape is a **folder on disk** that you iterate on: `index.html` + `state.json` + optional assets, emitted by `library_ref`, living in a well-known library location the user can find. See `widgets/html.md` for the bundle layout and path grammar.

Inline mode (`emit_html_widget(html="...")`) is for one-off snapshots — a single view of data you already have in the turn. Anything the user will see more than once should be path-mode.

## Panel titles — when to use them

If the widget is meant to act like a panel surface rather than just a tile, give the bundle host-owned panel chrome:

- Use `panel_title` + `show_panel_title: true` when the title should stay visible while the widget body scrolls.
- Use this for dashboard main panels, chat side panels, rail/dock panels, and mobile widget-drawer panels.
- Keep using `display_label` for the generic library/card label everywhere else.
- Do **not** use `panel_title` just to duplicate a small in-widget heading; if the title belongs inside the content and should scroll away with the body, keep it in the HTML instead.

If you need the exact field shape or examples, read `widgets/html.md` or `widgets/manifest.md`.

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

## Native app widgets — what bots should assume

Native app widgets are:

- first-party library entries
- placeable through `pin_widget`
- bot-operable through `invoke_widget_action`
- not authored through `emit_html_widget`, `preview_widget`, or `widget://...`

So:

- if the user asks for a **new custom widget**, stay in the template/HTML lanes
- if the user asks to **use an existing official widget**, check the library for a `native_app` entry first

## When NOT to use this skill

- Simple text / Markdown reply → just reply normally.
- Entity detail the existing `tool_widgets:` templates already cover → component widget is nicer.
- A link or file the user wants to open → `send_file` or a plain URL.
- Reusable across channels → author under `widget://bot/<name>/...` (bot-private library) or `widget://workspace/<name>/...` (shared-workspace library). Bundles live once in the library and render anywhere via `library_ref="<name>"`.

## Workflow — build an evolving dashboard

When the user says *"build me a dashboard for X"*:

1. **Discover** — `list_api_endpoints(scope="...")` to see what your bot can read/write. Build from what you have, not what you wish you had. `widget_library_list()` to see what bundles already exist.
2. **Pick a scope** — `widget://bot/<name>/...` (your bot's own library, always available) or `widget://workspace/<name>/...` (shared with every bot in this workspace, shared-workspace bots only). `widget://core/...` is read-only.
3. **Decide template vs HTML** — template if the renderer/model is already a good fit; HTML if you need bespoke layout, local interactivity, or theme-aware styling.
4. **Pick an archetype** — status (RMW `state.json`), feed (poll API), control panel (dispatch tools), KB reader (workspace files + markdown). Most real dashboards mix two. See `widgets/dashboards.md`.
5. **One-shot the bundle** — `file(create, path="widget://bot/<name>/index.html", content=<full doc>)` plus any `widget://bot/<name>/state.json` defaults. Use `sd-*` classes; use `window.spindrel.api()` for every GET; use `spindrel.callTool` for triggering work.
6. **Group it if it belongs with siblings** — set exactly one of `suite:` or `package:` in the HTML frontmatter or `widget.yaml`. Use a group when the widget is part of a related family the library should show together.
7. **Preview** — call `preview_widget(...)` with the same args you plan to emit. Catch manifest, library-ref, and CSP problems before the next user-visible step.
8. **Emit or pin** — `emit_html_widget(library_ref="<name>", display_label="<Name>")`. The library resolves bot → workspace → core for unscoped refs; prefix with `bot/` or `workspace/` to disambiguate. User pins it to the dashboard.
9. **Iterate** — tweaks via `file(edit, path="widget://bot/<name>/index.html", ...)`. The pinned widget refreshes within ~3 s. No re-emit needed.
10. **Record it** — leave breadcrumbs in `memory/MEMORY.md` + `memory/reference/<name>.md` so future-you knows the widget exists and where to find it. See `widgets/dashboards.md#remember-what-you-built`.

## See also

- [Widget Dashboards](../widget_dashboards.md) — the `describe_dashboard` / `pin_widget` / `move_pins` / `unpin_widget` / `promote_panel` / `demote_panel` tool suite for reading, proposing, and modifying dashboard layouts. `emit_html_widget` shows a widget in chat; `pin_widget` places a library widget on the dashboard.
