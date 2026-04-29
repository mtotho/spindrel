---
name: Widget errors — error-string to fix lookup
description: Error-keyed troubleshooting for HTML widgets. Use when the widget is blank / returns 422 / is CSP-blocked / throws "TypeError Failed to fetch" / says Workspace file not found / silently crashes / renders but shows empty cells or fallback strings despite a successful tool call. Maps each symptom to the root cause, and documents the `inspect_widget_pin` debug recipe that closes the authoring loop. Also includes the canonical envelope-shape index for commonly-called tools so extraction paths can be written against confirmed shapes instead of guessed.
triggers: widget error, widget iframe blank, widget 422, CSP blocked widget, TypeError Failed to fetch, widget Failed to fetch, widget shows fallback, widget shows Snapshot failed, widget shows dashes, widget shows undefined, widget not loading, widget not rendering, Workspace file not found, widget truncated body null, widget scope_denied, widget silent crash, hand-rolled form widget, raw fetch widget, inline hex widget, inspect_widget_pin, envelope shape, envelope extraction path, frigate_snapshot shape, ha_get_state shape, fallback chain widget
category: core
---

# Widget errors — symptom → fix lookup

When something's wrong, search this file for the exact error string or symptom. Each row is symptom → likely cause → fix (with pointers to the detail skill).

## Silent extraction failures — the #1 class of bug

The widget loads, the tool call returns `{ok: true, envelope}`, and yet the DOM shows `"—"`, `"undefined"`, `"Snapshot failed"`, an empty cell, or a broken image. The tool succeeded. Your extraction path is wrong.

| Symptom | Cause | Fix |
|---|---|---|
| `callTool(...)` returned a non-null envelope but the widget renders a fallback string, empty text, or broken image | Your extraction path read a key that doesn't exist — e.g. you typed `env.data.x` when the payload lives at `env.x`, or vice versa. Classic smell: `env.data.x \|\| env.body.data.x \|\| env.result.data.x` fallback chain. | **STOP. Do not add another `\|\|` branch.** Pin the widget, then from the next bot turn call `inspect_widget_pin(pin_id=<id>)`, find the most recent `{kind:"tool-call", ok:true}` event, and read its `response` field verbatim. That is the envelope shape. Rewrite extraction against exactly one confirmed path. See [Inspecting a pinned widget](#inspecting-a-pinned-widget--the-debugging-recipe) below. |
| Widget shows `NaN`, `[object Object]`, or `null` stringified in the DOM | You pulled a value from the envelope but didn't unwrap it — `env.data` is an object, not a number; `env.messages` is an array, not a string | `inspect_widget_pin` → read `response` → pick the exact leaf (`env.data.state`, `env.messages[0].content`, etc.) |
| Widget mostly works but one field is blank | One extraction path out of many is wrong. You won't find this by reading your code. | `inspect_widget_pin` and diff the confirmed `response` against your extraction. Unknown envelope shapes → check [Envelope-shape index](#envelope-shape-index--canonical-tool-responses). |

**Imperative:** never type `env.X || env.body.Y || env.result.Z` over envelope paths. Fallback chains silently return `undefined` when all branches miss and turn a 5-second `inspect_widget_pin` fix into a multi-turn guessing game. If you catch yourself typing `||` between two envelope-path candidates, stop and call `inspect_widget_pin` instead.

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
| **`TypeError: Failed to fetch`** in the widget console | The iframe CSP blocked a cross-origin `fetch()` before the request even left the browser. Browsers surface blocked-by-CSP and blocked-by-CORS as a generic `TypeError: Failed to fetch` — the real reason shows as a separate `Refused to connect to ...` CSP violation line just above it. | Don't `fetch()` third-party URLs from inside the iframe. Route it through the backend: `window.spindrel.callTool("fetch_url", {url})` returns the body inline. If you genuinely need direct cross-origin from the iframe, whitelist the host via `extra_csp={"connect_src": ["https://api.example.com"]}` on `emit_html_widget`. For same-origin `/api/v1/...` calls: use `window.spindrel.api(path)` — raw `fetch()` has no bearer and will 422. |
| Widget logs `replay_lapsed` on `spindrel.stream` | Server replay ring wasn't big enough to cover the reconnect gap | Widget should refetch baseline state from the API in its `stream` callback when it sees `replay_lapsed`. See `widgets/sdk.md#spindrelstreamkinds-filter-cb---live-channel-events`. |

## Tool dispatch errors

| Symptom | Cause | Fix |
|---|---|---|
| `callTool` throws "tool not found" | Typo in tool name, or tool is not exposed to the bot | Check `list_api_endpoints()` or the admin Tools catalog; confirm the bot can call it from the chat first. |
| `callTool` returns `{ok: false, error: "scope_denied: ..."}` (from a `widget.py` handler) | `permissions.tools` allowlist doesn't include the tool, OR the bot's own scopes don't cover it | Add the tool to `permissions.tools` in `widget.yaml`; then confirm the bot has the scope. See `widgets/handlers.md#manifest-allowlist`. |
| Envelope body is `null` with `truncated: true` after a `callTool` | **This is a bug** — `callTool` bypasses the 4 KB cap. Report it. | Don't add defensive null-handling; file a bug. See `widgets/tool_dispatch.md#truncation---does-not-apply-to-calltool`. |
| `JSON.parse(env.plain_body)` throws | `plain_body` is a short human preview (≤200 chars), not the full payload | Parse `env.body` instead. See `widgets/tool_dispatch.md#the-envelope-shape`. |

## Envelope-shape index — canonical tool responses

Commonly-called tools and their confirmed envelope shapes. Code against these exact paths — no fallback chains. For any tool NOT in this table, call `inspect_widget_pin(pin_id)` after the first invocation and read the `response` field of the `tool-call` event; that's the ground truth. If a shape in this table has drifted (describe_dashboard → envelope doesn't match), report it — the table lives here so it can be corrected in one place.

| Tool | Extraction path | Shape summary |
|---|---|---|
| `frigate_snapshot` | `env.attachment_id` → `loadAttachment(id)` for image URL | `{attachment_id, filename, size_bytes, camera, message, client_action}` — flat, no `data` wrapper |
| `frigate_list_cameras` | `env.cameras[]` | `{cameras: [{name, ...}], count}` |
| `ha_get_state` | `env.data.state`, `env.data.attributes.unit_of_measurement`, `env.data.attributes.friendly_name` | `{data: {entity_id, state, attributes: {...}, last_changed, last_updated}}` — one `data` wrapper |
| `ha_list_entities` | `env.data[]` | `{data: [{entity_id, state, attributes}, ...]}` |
| `fetch_url` | `env.body_text` (HTML/JSON/text raw) | `{body_text, status, content_type, final_url}` |
| `web_search` | `env.results[]` | `{results: [{title, url, snippet, favicon?}, ...], query}` |
| `generate_image` | `env.attachment_id` → `loadAttachment(id)` | `{attachment_id, filename, prompt, size_bytes}` — flat |
| `get_weather` / `openweather_forecast` | `env.current`, `env.hourly[]`, `env.daily[]` | `{current, hourly, daily, location}` |
| `list_channels` | `env.channels[]` | `{channels, count}` |
| `read_conversation_history` | `env.messages[]` | `{messages: [{role, content, ts, ...}], truncated}` |
| `list_sub_sessions` | `env.sessions[]` | `{sessions, count}` |
| `describe_dashboard` | `env.dashboard` + `env.pins[]` | `{dashboard, pins, channel_layout_mode, widget_health}` |
| Any `widget.<slug>.<handler>` (bot-callable handler) | As declared in `widget.yaml` `handlers.<name>.returns` | Call `spindrel.toolSchema(name)` for the exact JSON-Schema |

**Rule of thumb** (never a substitute for `inspect_widget_pin`, just a default bias):

- Attachment-producing tools (`frigate_snapshot`, `generate_image`) return `attachment_id` at the top level — no wrapping.
- Integration `*_get_*` / `*_list_*` tools (HA, arr stack) wrap the payload in one `data:` layer.
- Local/search tools (`web_search`, `list_channels`, `list_tasks`) return an array or object directly under a named key at the top level (`results`, `channels`, `tasks`).

When the guess and `inspect_widget_pin` disagree, inspect_widget_pin is right. Update this table in the same edit so the next widget gets the right prior.

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
| Pinning a widget and never checking it | `check_widget(pin_id=...)`; if failing, then `inspect_widget_pin(pin_id)` for raw evidence | Health checks persist a concise pass/warn/fail summary for dashboard UI and future bot turns; the inspector remains the detailed trace. |
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
| `env.data.state \|\| env.body.data.state \|\| env.result.data.state` fallback chain | `inspect_widget_pin(pin_id)` → read the `response` field → write one exact path | Fallback chains silently evaluate to `undefined` when every branch misses. The tool succeeded — the bytes are somewhere; guessing is slower and more expensive than inspecting. |
| Widget shows a fallback / blank cell and you add another `\|\|` branch "just in case" | STOP. Call `inspect_widget_pin`. | Every extra `\|\|` buries the real bug further. `inspect_widget_pin` returns the exact envelope in one turn — one minute of reading beats ten minutes of guessing. |
| Authoring a widget v2 against a prior about envelope shape | Emit v1 + `spindrel.log.info("shape", await callTool(...))` → pin it → `inspect_widget_pin` → write v2 against the logged shape | Priors disagree (`frigate_snapshot` flattens; `ha_get_state` wraps in `data:`). No general rule works across the tool surface. |

## Inspecting a pinned widget — the debugging recipe

When a widget renders but the data is wrong (blank cells, `"—"`, `"undefined"`, `"Snapshot failed"`, broken image), the correct next step is **always** the same five-step loop. Do this before adding any defensive null-handling, before adding another `||` branch, and before asking the user.

1. **Pin the widget.** `pin_id` is returned by `pin_widget(source_kind="library", widget="<name>")` or visible on an existing pin via `describe_dashboard`. For inline-emitted widgets the user has to pin it in the UI first — ask them once, it's the prerequisite for the rest of the loop.
2. **Call `inspect_widget_pin(pin_id=<uuid>)`** from the next bot turn. Reads the per-pin ambient trace ring — every `callTool` request+response pair, every `loadAttachment` roundtrip, every `window.onerror` / unhandled rejection, every `console.*` and `spindrel.log.*` entry. Newest-first.
3. **Find the most recent `{kind: "tool-call", ok: true}` event.** Read its `response` field verbatim. That IS the envelope shape — not a prior, not a guess, not what the [Envelope-shape index](#envelope-shape-index--canonical-tool-responses) table says. The table is a default; `response` is truth.
4. **Rewrite extraction against ONE confirmed path.** One expression. No `||`. No defensive null-handling on top of a `callTool` that returned `ok: true`.
5. **Re-emit the bundle** via `emit_html_widget(library_ref="<name>")` or edit with `file(edit, path="widget://bot/<name>/index.html", ...)`. The pinned widget auto-refreshes within ~3s — no need to re-pin.

**What the events look like:**

```json
{
  "kind": "tool-call",
  "tool": "frigate_snapshot",
  "args": {"camera": "kitchen"},
  "ok": true,
  "response": {"attachment_id": "abc...", "filename": "kitchen.jpg", "size_bytes": 48213, "camera": "kitchen", "message": "...", "client_action": null},
  "durationMs": 412
}
```

Extraction against that is `env.attachment_id`, not `env.data.attachment_id`, not `env.body.data.attachment_id`. Write the one path; update the [Envelope-shape index](#envelope-shape-index--canonical-tool-responses) if the tool wasn't there yet.

**When `inspect_widget_pin` returns 0 tool-call events** but the widget is blank: the widget isn't calling the tool at all (JS bug blocking the call). Look for `error` / `rejection` events in the same response — those pinpoint the blocker with line + column. If the log is also empty, the widget probably failed to load its JS — check the `load-attachment` or CSP error rows.

**When you see both `ok: true` AND an `error`/`rejection` event** after it: the tool call succeeded but the downstream DOM code threw. The stack trace in the error event points at the extraction-or-render bug directly.

## See also

- `widgets/html.md` — sandbox, auth, path grammar
- `widgets/sdk.md` — `window.spindrel` API surface
- `widgets/tool_dispatch.md` — envelope shape, truncation, dispatch types
- `widgets/db.md` + `widgets/handlers.md` — backend-capable widgets
- `widgets/styling.md` — sd-* vocabulary and theme
