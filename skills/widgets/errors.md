---
name: Widget errors — error-string to fix lookup
description: Error-keyed troubleshooting for HTML widgets. When the user reports "the widget is blank / 422 / CSP-blocked / says Workspace file not found / silently crashes / has a stale pin", this skill maps the symptom to the root cause. Also covers the generic Common-Mistakes anti-pattern list (raw fetch, hex colors, hand-rolled forms, swallowed errors).
triggers: widget error, widget iframe blank, widget 422, CSP blocked widget, widget not loading, widget not rendering, Workspace file not found, widget truncated body null, widget scope_denied, widget silent crash, hand-rolled form widget, raw fetch widget, inline hex widget
category: core
---

# Widget errors — symptom → fix lookup

When something's wrong, search this file for the exact error string or symptom. Each row is symptom → likely cause → fix (with pointers to the detail skill).

## Widget won't load / blank iframe

| Symptom | Cause | Fix |
|---|---|---|
| Widget body is blank, no errors visible | `html=` passed an empty string, or `path=` resolved to an empty file | Inspect the file with `file(read, path=...)` before emitting; if inline, log the string length before passing to `emit_html_widget`. |
| Red banner "Widget auth failed" | Bot has no API key configured | Ask the user to provision an API key in the admin UI — bot scopes are the widget's ceiling. See `widgets/html.md#auth`. |
| Red error-boundary banner with a **Reload** button | Uncaught JS error or unhandled promise rejection in the widget | Click Reload to remount. Then fix the JS — check the browser devtools console and `window.spindrel.log` via the Dev Panel's Widgets → Dev → Recent → "Widget log" subtab. |
| Widget shows "loose" badge in the catalog | `.html` is matched only by the `window.spindrel.*` reference heuristic, not by living under a library bundle | Move into `widget://bot/<name>/index.html` (or `widget://workspace/<name>/...`). See `widgets/html.md#widget-metadata-yaml-frontmatter`. |
| Card title falls back to slug (`project-status` instead of `Project status`) | Missing, malformed, or mis-placed YAML frontmatter | Frontmatter must be the very first thing in the file. See `widgets/html.md#widget-metadata-yaml-frontmatter`. |

## Network / API errors

| Symptom | Cause | Fix |
|---|---|---|
| **422 Unprocessable Entity** on API calls from the widget | You used raw `fetch()` instead of `window.spindrel.api()` — bearer token missing | Switch every API call to `window.spindrel.api(path)` / `apiFetch(path)`. Raw `fetch` is never authed in a widget. See `widgets/html.md#auth`. |
| **401 Unauthorized** on `/api/v1/...` | Bot's API key scopes too narrow for the endpoint | Ask the user to broaden the bot's scopes via admin UI. Widgets cannot escalate. |
| Cross-origin fetch fails with CSP violation in console | Iframe CSP blocks cross-origin network by default | Either (a) fetch server-side from the bot turn and inline JSON, or (b) dispatch `fetch_url` via `callTool`, or (c) whitelist the specific origin via `extra_csp={...}` on `emit_html_widget`. See `widgets/html.md#loading-third-party-scripts--tiles--fonts-extra_csp`. |
| Widget logs `replay_lapsed` on `spindrel.stream` | Server replay ring wasn't big enough to cover the reconnect gap | Widget should refetch baseline state from the API in its `stream` callback when it sees `replay_lapsed`. See `widgets/sdk.md#spindrelstreamkinds-filter-cb---live-channel-events`. |

## Tool dispatch errors

| Symptom | Cause | Fix |
|---|---|---|
| `callTool` throws "tool not found" | Typo in tool name, or tool is not exposed to the bot | Check `list_api_endpoints()` or the admin Tools catalog; confirm the bot can call it from the chat first. |
| `callTool` returns `{ok: false, error: "scope_denied: ..."}` (from a `widget.py` handler) | `permissions.tools` allowlist doesn't include the tool, OR the bot's own scopes don't cover it | Add the tool to `permissions.tools` in `widget.yaml`; then confirm the bot has the scope. See `widgets/handlers.md#manifest-allowlist`. |
| Envelope body is `null` with `truncated: true` after a `callTool` | **This is a bug** — `callTool` bypasses the 4 KB cap. Report it. | Don't add defensive null-handling; file a bug. See `widgets/tool-dispatch.md#truncation---does-not-apply-to-calltool`. |
| `JSON.parse(env.plain_body)` throws | `plain_body` is a short human preview (≤200 chars), not the full payload | Parse `env.body` instead. See `widgets/tool-dispatch.md#the-envelope-shape`. |

## Path / file errors

| Symptom | Cause | Fix |
|---|---|---|
| `Workspace file not found (or path escapes workspace)` from `emit_html_widget` | Tried to emit a file that doesn't exist, or mixed up grammar between the `file` and `emit_html_widget` tools | Author bundles under `widget://bot/<name>/...` via `file(create, ...)` and emit with `emit_html_widget(library_ref="<name>")` — one grammar, both tools agree. See `widgets/html.md#path-grammar`. |
| Relative path `./state.json` throws from inside the iframe | Inline widget (no `widgetPath`) — relative paths require library-ref or path mode | Switch to library-ref mode: write the bundle with `file(create, path="widget://bot/<name>/...", ...)` and emit with `emit_html_widget(library_ref="<name>")`. See `widgets/sdk.md#relative-paths`. |
| `widget://core/...` write rejected | Core library is read-only at runtime (ships in-repo, version-controlled) | Author under `widget://bot/<name>/...` instead. To fork a core widget, `file(read, path="widget://core/<name>/index.html")` → `file(create, path="widget://bot/<name>/index.html", content=...)`. |
| `widget://workspace/...` rejected with "requires a shared workspace" | Bot isn't a member of a shared workspace, so the workspace scope has no on-disk root | Use `widget://bot/<name>/...` instead — bot scope is always available. Shared-workspace membership is a bot-config concern the user has to enable. |
| `extra_csp` validation error ("invalid origin") | Passed a full URL, wildcard, or non-https scheme | Origins only (`https://host[:port]`), no `*`, no `'self'`, no `data:` / `blob:` / `http:`. Max 10 per directive. See `widgets/html.md#loading-third-party-scripts--tiles--fonts-extra_csp`. |

## State / DB errors

| Symptom | Cause | Fix |
|---|---|---|
| `state.load` throws "downgrade refused" | Disk file's `__schema_version__` is higher than declared `schema_version` | The widget was downgraded after a schema bump — either pin to the old version or clear `state.json` and let defaults repopulate. |
| `spindrel.db` throws "inline widget" / "no pin" | `spindrel.db` requires path-mode + `dashboardPinId` | Emit in path mode and let the user pin it. Inline widgets can't use the server DB. See `widgets/db.md`. |
| Migration error on open time ("gap in migrations") | `widget.yaml` migrations aren't contiguous `from: N → to: N+1` | Fix the manifest. See `widgets/db.md#schema-migrations`. |
| Two tabs write `state.json`, last write wins | RMW race — `spindrel.data.patch` is serialized per-iframe, not cross-iframe | Move the state to `spindrel.db` (backend-serialized), or accept the race. See `widgets/db.md`. |

## Common anti-patterns — wrong vs right

| Wrong | Right | Why |
|---|---|---|
| Returning HTML as Markdown or a code fence | `emit_html_widget(html=...)` | Only this tool gets you interactivity + pin-to-dashboard |
| `fetch("/api/v1/...")` inside the widget | `window.spindrel.api("/api/v1/...")` | Only `spindrel.api` attaches the bearer. Raw `fetch` → 422. |
| `fetch("https://api.example.com/...")` from widget JS | Prior tool call fetches it; inline the data OR dispatch `fetch_url` | CSP blocks cross-origin; iframe can only hit same-origin |
| Guessing API paths | `list_api_endpoints()` first, copy the exact path | You only see endpoints your scopes cover. Saves a roundtrip of 403s. |
| Hitting REST endpoints to "run a tool" | `window.spindrel.callTool(name, args)` | Tools don't have REST endpoints; `callTool` is the dispatcher shortcut. |
| Hand-rolling the 15-line `/api/v1/widget-actions` fetch | `window.spindrel.callTool(name, args)` | One line, auto-fills `bot_id`/`channel_id`, throws on error. |
| Inline hex colors (`#fff`, `#1f2937`, `rgb(59,130,246)`) | `var(--sd-*)` variables or `sd-*` classes | Hex drifts from the theme and breaks dark mode. |
| Hand-rolled `.card { border: 1px solid #e5e7eb; ... }` | `class="sd-card"` | The vocabulary already covers this. |
| `html=...` + `path=...` together | Exactly one | Tool errors — pick inline OR path |
| Path mode pointing at a non-existent file | Create the file first with `file(create, ...)` | Tool refuses if the path doesn't resolve |
| `file(create, path="data/widgets/foo/index.html")` + `emit_html_widget(path="data/widgets/foo/index.html")` | `file(create, path="widget://bot/foo/index.html")` + `emit_html_widget(library_ref="foo")` | `widget://` is one grammar both tools agree on; library-ref emission reuses the same bundle across channels and cron contexts. Channel-scoped paths work, but the bundle is then tied to one channel. |
| Emitting a just-authored bundle and hoping it renders | Call `preview_widget(library_ref=..., ...)` first; inspect `errors[]` | Dry-run catches manifest / CSP / path / library_ref errors as structured output before the user pins anything. See `widgets/html.md#dry-run-first`. |
| Shipping a widget without updating `memory/MEMORY.md` | Add index entry + `memory/reference/<slug>.md` same turn | Future turns lose the bundle. You'll rebuild or debug blind. |
| Dumping loose `.html` at the workspace root | Put each widget in its own bundle folder | Bundles move/rename/delete atomically; the root stays legible |
| Blind-overwriting `state.json` | Read-merge-write; use `spindrel.state.load` + `state.save` when the bundle's shape might change over time | Two open copies stay coherent; schema_version + migrations make shape changes safe across deploys |
| Skipping `display_label` | Always supply one | Blank headers on the dashboard are ugly + fail the pinned-widget context hint |
| Asking the user to "broaden your admin key" so your widget works | Ask them to broaden YOUR BOT's scopes via admin UI | The widget uses your bot's key, not the user's session. |
| Hand-rolling a form with `<input>` / state tracking / validation / submit-disable | `window.spindrel.form(el, {fields, onSubmit, ...})` | Declarative — validation + error surfaces + submitting state + sd-* styling for free. |
| Hand-rolling a `<table>` + empty-state + loading skeleton | `window.spindrel.ui.status(el, "loading")` + `ui.table(rows, cols)` + `ui.status(el, "empty")` | One-liners that stay on-brand and dark-mode-safe. |
| Inlining Chart.js or hand-writing SVG for a small sparkline | `window.spindrel.ui.chart(el, values, { type: "area", min: 0, max: 1 })` | Native `spindrel.theme.accent`, crisp strokes at any width, no 60 KB JS. |
| Swallowing errors with `try { ... } catch {}` | `catch (e) { window.spindrel.notify("error", e.message); }` | Toasts surface through host chrome above the widget; user sees what failed. |
| `console.log("debug:", x)` | `window.spindrel.log.info("debug:", x)` | Ring-buffered, forwarded to Widgets → Dev → Recent → "Widget log" with per-pin attribution; visible without opening browser devtools. |
| `setInterval(() => fetchShared(), 5000)` in every widget that shares data | One widget fetches + `window.spindrel.bus.publish("X_changed", data)`; peers subscribe | One fetch instead of N; widgets stay in sync without polling races. |
| `setInterval(() => refetchChannelState(), 2000)` to see new messages / turns | `window.spindrel.stream("new_message", cb)` | SSE over the channel event bus — zero poll latency, no wasted round-trips, auto-replays missed events on reconnect. |
| Using `spindrel.bus` to hear what the bot is doing | `spindrel.stream(["turn_started","turn_ended","tool_activity"], cb)` | `bus` is `BroadcastChannel` — widget↔widget only. The agent doesn't post there. `stream` is the backend bus. |

## See also

- `widgets/html.md` — sandbox, auth, path grammar
- `widgets/sdk.md` — `window.spindrel` API surface
- `widgets/tool-dispatch.md` — envelope shape, truncation, dispatch types
- `widgets/db.md` + `widgets/handlers.md` — backend-capable widgets
- `widgets/styling.md` — sd-* vocabulary and theme
