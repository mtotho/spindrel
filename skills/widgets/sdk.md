---
name: window.spindrel SDK — entry point
description: Routing skill for `window.spindrel` — the helper object every widget iframe gets. The full SDK reference is `get_doc("reference/widgets/sdk")`; this skill points at the right sibling skill (db, handlers, suites, tool_dispatch, errors, styling, html) before you fetch.
triggers: window.spindrel, spindrel.callTool, spindrel.api, spindrel.apiFetch, spindrel.data, spindrel.state, spindrel.bus, spindrel.stream, spindrel.cache, spindrel.notify, spindrel.log, ui.chart, ui.table, ui.status, spindrel.form, spindrel.loadAsset, spindrel.autoReload, renderMarkdown, channel event stream
category: core
---

# `window.spindrel` — entry point

`window.spindrel` is the helper object every widget iframe gets — identity, authed network, workspace files, JSON state, pubsub, SSE channel events, TTL cache, toasts, log ring, `sd-*` UI helpers (`ui.status`, `ui.table`, `ui.chart`, `ui.menu`, `ui.confirm`, …), declarative `form`, and `autoReload`.

**The full reference moved out of skills.** It's now a doc:

```
get_doc("reference/widgets/sdk")
```

Fetch it when the widget needs anything beyond static HTML. The body is large (~640 lines) — there's no point keeping it resident.

## When to fetch the SDK reference vs another skill

If the widget is mostly working and you have a focused question, prefer the narrow skill. Reach for `get_doc("reference/widgets/sdk")` only when you actually need the API surface in front of you.

| You need… | Fetch this |
|---|---|
| The full API surface (helpers, streams, ui, forms) | `get_doc("reference/widgets/sdk")` |
| Backend dispatch envelope, `callTool` shape, truncation rules | skill `widgets/tool_dispatch` |
| Server-side Python handlers (`@on_action`, `@on_cron`, `ctx.db`) | skill `widgets/handlers` |
| Per-bundle SQLite (`spindrel.db.query/exec/tx`, migrations) | skill `widgets/db` |
| Multi-bundle suites sharing a DB | skill `widgets/suites` |
| Bundle layout, sandbox, CSP, frontmatter, auth | skill `widgets/html` |
| `sd-*` vocabulary, theme tokens, dark mode | skill `widgets/styling` |
| Widget is broken / blank / showing fallback | skill `widgets/errors` |

## Rules of thumb

- **Never raw `fetch()`** — use `window.spindrel.api(path)` (parsed) or `apiFetch(path)` (raw `Response`); raw fetch isn't authenticated.
- **Don't guess envelope shapes.** Pin first, then `inspect_widget_pin(pin_id)` to read the real `response`. One extraction path, not a fallback chain. The `widgets/errors` skill has the full recipe.
- **Use the iframe-injected helpers, not your own copies.** `data` / `state` for JSON, `cache` for TTL+dedup, `notify` for toasts, `log.*` for traceable diagnostics, `ui.*` for skeleton / table / chart / menu / confirm.
- **Subscribe, don't poll.** `onToolResult`, `onConfig`, `onTheme`, `stream(kinds, cb)` for channel events, `bus.subscribe` for peer widgets, `autoReload(renderFn)` when a `widget.py` calls `ctx.notify_reload()`.
- **For control surfaces, keep local per-surface state.** Don't lean on `onToolResult` / `autoReload` as the primary click-response path — see `widgets/tool_dispatch` "Control dashboards" section.

## See also

- `get_doc("reference/widgets/sdk")` — the full API surface in one place
- skill `widgets` — decision tree for which widget kind to build
- skill `widgets/html` — bundle layout, sandbox, frontmatter, auth
