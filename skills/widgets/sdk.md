---
name: window.spindrel SDK — helpers, streams, UI, forms
description: Full reference for the `window.spindrel` API — identity, authed network (`api`/`apiFetch`), workspace files, `data`/`state` versioned JSON, `bus` pubsub, `stream` SSE channel events, `cache` TTL+dedup, `notify` toasts, `log` ring buffer, `ui.status`/`ui.table`/`ui.chart` helpers, declarative `form`, `autoReload`. Read this when the widget needs anything beyond static HTML.
triggers: window.spindrel, spindrel.callTool, spindrel.api, spindrel.apiFetch, spindrel.data, spindrel.state, spindrel.bus, spindrel.stream, spindrel.cache, spindrel.notify, spindrel.log, ui.chart, ui.table, ui.status, spindrel.form, spindrel.loadAsset, spindrel.autoReload, renderMarkdown, channel event stream
category: core
---

# `window.spindrel` — SDK reference

Every widget gets a helper object injected automatically. No imports, no setup:

```js
// Identity
window.spindrel.channelId                  // emitting channel UUID, or null
window.spindrel.botId                      // your bot id (the one running this)
window.spindrel.botName                    // display name, e.g. "crumb"
window.spindrel.dashboardPinId             // UUID when pinned to a dashboard, else undefined
window.spindrel.widgetPath                 // path of this widget's HTML (e.g. "widget://bot/x/index.html"), null for inline widgets
window.spindrel.resolvePath(input)         // resolve a relative path (./ or ../) against widgetPath's directory (see "Relative paths" below)

// Authenticated network
window.spindrel.api(path, options?)        // authed fetch → parsed body (JSON/text), throws on !ok
window.spindrel.apiFetch(path, options?)   // authed fetch → raw Response (for blobs, streams, binary)

// Workspace files (text)
window.spindrel.readWorkspaceFile(path)           // string contents, throws if missing
window.spindrel.writeWorkspaceFile(path, content) // PUT, overwrite
window.spindrel.listWorkspaceFiles({include_archive?, include_data?, data_prefix?})

// Workspace assets (binary — images, icons, PDFs, audio, video)
window.spindrel.loadAsset(path)                   // → object URL (blob:) ready for <img src>, <video src>, etc.
window.spindrel.revokeAsset(url)                  // free the object URL (optional; iframe teardown frees everything)

// Channel attachments (tool-returned attachment_id → image/video/binary)
window.spindrel.loadAttachment(id)                // → object URL (blob:) for <img src> / <video src>. Use when a tool returns an attachment_id (e.g. frigate_snapshot, generate_image).
window.spindrel.revokeAttachment(url)             // free the object URL

// Rendering helpers
window.spindrel.renderMarkdown(text)       // HTML-safe Markdown → HTML string (see "Markdown Rendering" below)

// Tool dispatch — see widgets/tool-dispatch.md for full details
window.spindrel.callTool(name, args, opts?) // run a backend tool; returns fresh envelope, throws on failure
window.spindrel.toolSchema(name)            // → {name, kind, input_schema, returns_schema|null}. Look up a tool's expected return shape before writing extraction code. `returns_schema` is null for MCP tools — fall back to inspecting the real response via the Inspector / inspect_widget_pin (see "Inspecting a pinned widget" below).

// JSON state — read/merge/write over workspace files, deep-merge semantics
window.spindrel.data.load(path, defaults?)           // parsed object (defaults deep-merged underneath); returns defaults if file missing
window.spindrel.data.patch(path, patch, defaults?)   // RMW atomically; returns the new state
window.spindrel.data.save(path, object)              // overwrite (escape hatch)

// Event subscriptions — return an unsubscribe function
window.spindrel.onToolResult(cb)   // fires whenever the envelope is refreshed (state_poll, callTool result, etc.)
window.spindrel.onConfig(cb)       // fires when this pin's widget_config changes (debounced — only on actual change)
window.spindrel.onTheme(cb)        // fires when the app switches light/dark mode

// Widget-to-widget pubsub (bus) — channel-scoped
window.spindrel.bus.publish(topic, data)        // broadcast to peers in the same channel
window.spindrel.bus.subscribe(topic, cb)        // returns unsubscribe

// Live channel events (stream) — SSE over the channel event bus; returns unsubscribe
window.spindrel.stream("new_message", cb)               // single kind
window.spindrel.stream(["turn_started","turn_ended"], cb)
window.spindrel.stream(["tool_activity"], filter, cb)   // + client-side predicate

// Widget reload signal — widget.py handler called ctx.notify_reload()
window.spindrel.autoReload(renderFn)     // runs renderFn() now + on every reload; returns unsubscribe
window.spindrel.onReload(cb)             // lower level: cb fires on each reload only; returns unsubscribe

// TTL cache with inflight dedup — drop-in for "fetch X but only once per 30s"
window.spindrel.cache.get(key, ttlMs, fetcher)  // returns cached | awaits fetcher | dedups concurrent callers
window.spindrel.cache.set(key, value, ttlMs)
window.spindrel.cache.clear(key?)

// Host-chrome toasts + uncaught-error banner + log ring
window.spindrel.notify(level, message)          // level: "info" | "success" | "warn" | "error"
window.spindrel.log.info|warn|error(...args)    // forwarded to the pin's debug event ring — visible in the Widget Inspector (pin menu → Bug icon) and via the inspect_widget_pin tool

// Minimal UI helpers (sd-* styled)
window.spindrel.ui.status(el, state, {message?, height?})  // state: "loading" | "error" | "empty" | "ready"
window.spindrel.ui.table(rows, columns, {emptyMessage?})   // returns HTML string — set innerHTML or append
window.spindrel.ui.chart(el, data, {type?, height?, color?, min?, max?, showAxis?, format?})  // SVG sparkline / line / bar / area
window.spindrel.ui.icon(name, {size?, tone?, className?})  // returns <svg class="sd-icon">…</svg> string (Lucide subset sprite)
window.spindrel.ui.autogrow(textarea, {maxHeight?})        // textarea grows to fit content; returns teardown fn
window.spindrel.ui.menu(anchorEl, items, {minWidth?})      // popover menu, keyboard nav + outside-click dismiss
window.spindrel.ui.tooltip(el, text, {delay?})             // hover/focus tooltip; returns teardown fn
window.spindrel.ui.confirm({title, body, confirmLabel?, cancelLabel?, danger?})  // → Promise<boolean>

// Versioned state.json — wraps spindrel.data with schema migrations
window.spindrel.state.load(path, {schema_version, migrations, defaults})  // runs migrations on load, persists bumped version
window.spindrel.state.save(path, object)           // write; preserves __schema_version__ from disk when omitted
window.spindrel.state.patch(path, patch, spec)     // RMW deep-merge with migrations

window.spindrel.form(el, {fields, onSubmit, initial?, submitLabel?, submittingLabel?, resetOnSubmit?})

// Tool result / config
window.spindrel.toolResult                 // current envelope payload (see declarative widgets)
window.spindrel.theme                      // resolved design tokens (see widgets/styling.md)

// Server-side SQLite (requires widget.yaml + path mode) — see widgets/db.md
window.spindrel.db.query(sql, params?)
window.spindrel.db.exec(sql, params?)
window.spindrel.db.tx(fn)

// Server-side Python handlers — see widgets/handlers.md
window.spindrel.callHandler(action, args)
```

Theme library metadata:

- `window.spindrel.theme.themeRef` — active theme ref, e.g. `builtin/default` or `custom/home-light`
- `window.spindrel.theme.themeName` — display name
- `window.spindrel.theme.isBuiltin` — whether the active theme is immutable builtin

Use these for diagnostics or theme-aware behavior. Do not branch on exact refs unless the user explicitly asked for theme-specific behavior.

## api() vs apiFetch()

`api(path, options)` is a thin `fetch` wrapper — attaches `Authorization: Bearer <short-lived bot token>`, sets `Content-Type: application/json`, parses JSON responses, and throws on non-2xx. **Always use this or `apiFetch` instead of raw `fetch()`**; raw fetch won't be authenticated.

`apiFetch(path, options)` is the same auth but returns the raw `Response` object. Reach for it when you need headers or streaming. For images from channel attachments, use `loadAttachment(id)` — it hides the `<img>`/auth dance and registers the object URL for you:

```js
const env = await window.spindrel.callTool("frigate_snapshot", { camera });
const url = await window.spindrel.loadAttachment(env.attachment_id);
document.querySelector("img").src = url;
```

## Inspecting a pinned widget (the authoring loop)

Widgets are written ahead of any real invocation, so the bot doesn't actually see the envelope shape a tool returns until the widget runs. Guessing — `env.data.state || env.body.data.state || env.result.data.state` — is an anti-pattern and the #1 cause of broken widgets.

Instead, use the ambient trace. Every `callTool` / `loadAttachment` / `loadAsset` invocation a pinned widget makes is auto-captured server-side (last 50 per pin), along with uncaught JS errors, unhandled promise rejections, `console.*` output, and `spindrel.log.*` entries.

Two readers of that same ring:

- **Human** — the Inspector side-panel. On any pinned widget, hover the tile → click the Bug icon → drawer opens with a newest-first timeline, expandable request/response JSON per event, copy-JSON, clear, pause.
- **Bot** — the `inspect_widget_pin(pin_id, limit?)` tool. Call it after pinning a widget you just authored; it returns the same timeline as JSON. Read the `response` field on the most recent `tool-call` event — that's the ground truth for extraction paths.

Iteration recipe:

1. `toolSchema(toolName)` — if `returns_schema` is present, code against it.
2. If `returns_schema` is null (MCP tool), emit widget v1 as a best-effort probe. Optionally wrap the first `callTool` in a `try { ...; spindrel.log.info("shape", env); } catch (e) { spindrel.log.error(e.message); }` so the shape is guaranteed to appear in the Inspector timeline.
3. Pin the widget, then call `inspect_widget_pin(pin_id)` to read the real response shape.
4. Rewrite extraction against the confirmed path. **One path, not a fallback chain.**
5. Re-emit; confirm the Inspector shows only clean tool-call rows and no `error` / `rejection` events.

Canonical shapes for the two tools people hit first:

- `frigate_snapshot` → `{attachment_id, filename, size_bytes, camera, message, client_action}`. Extraction: `env.attachment_id`, feed into `loadAttachment(id)`.
- `ha_get_state` → `{data: {entity_id, state, attributes: {unit_of_measurement, friendly_name, ...}, last_changed}}`. Extraction: `env.data.state`, `env.data.attributes.unit_of_measurement`. One level of `data:` wrap — no fallback chain.

## Reacting to live updates

The host pushes fresh data into the iframe without reloading — after a `state_poll` refresh, after a `callTool` result, or when the app switches dark mode. Use the subscription helpers:

```js
// Re-render whenever the envelope is refreshed
const off = window.spindrel.onToolResult((envelope) => render(envelope));

// React to config changes (e.g. user toggled a pin setting from the EditPinDrawer)
window.spindrel.onConfig((config) => {
  applyConfig(config);  // fires only when config actually changes
});

// Re-theme SVG/canvas widgets on light/dark switch
window.spindrel.onTheme((theme) => {
  redraw(theme.accent, theme.isDark);
});

// Each helper returns an unsubscribe function
off();
```

Under the hood these attach to the `spindrel:toolresult` and `spindrel:theme` DOM events on `window`. `onConfig` is sugar over `toolresult` that debounces — your callback only fires when `toolResult.config` actually changed, not on every envelope refresh.

For control surfaces, don't treat `onToolResult` or `autoReload` as the primary click-response path. Keep local per-surface state and rerender only the touched row/card first; use subscriptions for later reconciliation. The concrete pattern lives in `widgets/tool-dispatch.md` under "Control dashboards — split state by surface, not by 'one big refresh'".

## Bundled assets (images, icons, media)

The sandbox blocks cross-origin network but allows `data:` / `blob:` / same-origin images. Since `<img src>` can't carry a bearer token (and workspace files are bearer-authed), use **`window.spindrel.loadAsset(path)`** to fetch a binary file with auth and get back a `blob:` object URL you can drop into any `src` attribute:

```js
// widget emitted from widget://bot/home-control/index.html
const logoUrl = await window.spindrel.loadAsset("./assets/logo.svg");
document.getElementById("logo").src = logoUrl;

// Works for <video>, <audio>, <a download>, anything that takes a same-origin URL
document.getElementById("clip").src = await window.spindrel.loadAsset("./media/intro.mp4");
```

The object URLs stay valid for the lifetime of the iframe. If you're loading many large assets and want to free memory explicitly, call `window.spindrel.revokeAsset(url)`.

Supported MIME types are whatever the workspace `/files/raw` endpoint serves — common image formats, PDFs, SVG, short audio/video clips.

## Channel attachments (images/files from the conversation)

Widgets often want to show **attachments** — images pasted into chat, files uploaded by the user, screenshots dropped by an integration. Two paths:

### (a) Pre-download into the bundle — best for "fixed" widgets

In the bot turn before emitting, use the `save_attachment` tool to copy attachments into the widget bundle, then reference them with `loadAsset` (or directly):

```
list_attachments(channel_id=<id>)
  → [{id: "abc-123...", filename: "sunrise.jpg", mime_type: "image/jpeg", size: 240_000}, ...]

save_attachment(attachment_id="abc-123...",
                path="widget://bot/gallery/assets/sunrise.jpg")

emit_html_widget(library_ref="gallery", ...)
```

Inside the widget:
```js
document.getElementById("photo").src = await window.spindrel.loadAsset("./assets/sunrise.jpg");
```

This baked-in pattern is durable — attachments can be deleted from the channel, but the widget's copy lives in the bundle.

### (b) Fetch live from the channel — best for "browse all attachments" dashboards

The widget reads the attachment list from the API and renders each one as an image via `apiFetch` → blob → object URL:

```js
const list = await window.spindrel.api(
  "/api/v1/attachments?channel_id=" + window.spindrel.channelId + "&limit=20"
);
for (const att of list) {
  if (!att.mime_type.startsWith("image/")) continue;
  const r = await window.spindrel.apiFetch("/api/v1/attachments/" + att.id + "/file");
  if (!r.ok) continue;
  const url = URL.createObjectURL(await r.blob());
  const img = document.createElement("img");
  img.src = url;
  img.alt = att.filename;
  document.getElementById("gallery").appendChild(img);
}
```

The `/api/v1/attachments/<id>/file` endpoint is authed — `apiFetch` attaches the widget's bearer automatically.

**When to use which**: pre-download (a) if the widget is meant to persist a specific set of assets as part of its design. Fetch-live (b) if the widget is about whatever's in the channel right now.

Use the `list_attachments` tool from the bot turn to discover IDs; use `/api/v1/attachments?channel_id=...` from inside the widget to browse live.

## Relative paths

Inside a path-mode widget, you know where your bundle lives but you don't want to hard-code it. `readWorkspaceFile`, `writeWorkspaceFile`, and all `data.*` helpers accept **relative paths** that resolve against `dirname(widgetPath)`:

```js
// widget emitted from widget://bot/project-status/index.html
const state = await window.spindrel.data.load("./state.json");
// → reads widget://bot/project-status/state.json

const sibling = await window.spindrel.readWorkspaceFile("../shared/config.json");
// → reads widget://bot/shared/config.json
```

Rules:

- `./foo` and `../foo` — resolved against the widget's directory. Requires library-ref or path mode (`widgetPath` is null for inline widgets).
- `foo/bar` with no leading `./` or `/` — treated as a bare path, resolved against the workspace the widget was emitted from.
- `/workspace/...` (leading slash) — currently throws inside iframes; use `./foo` / `../foo` for everything inside your own bundle, and `spindrel.api(...)` for anything that needs to reach another channel or workspace.
- `..` that escapes the bundle throws before hitting the backend.

Use `window.spindrel.resolvePath(input)` directly if you need the resolved string for your own bookkeeping (e.g. logging, debugging).

## `spindrel.data` — RMW JSON state

`window.spindrel.data` reads/writes workspace JSON files with deep-merge semantics. Great for mutable state that's small and local (a few KB) and doesn't need a schema.

- **`load(path, defaults?)`** — reads the file, parses JSON, and deep-merges it on top of `defaults`. If the file is missing or empty, returns a deep clone of `defaults`. Without `defaults`, returns the raw parsed object. Throws on invalid JSON.
- **`patch(path, patch, defaults?)`** — load → deep-merge `patch` on top → save → return. Objects are merged recursively; **arrays are replaced, not concatenated**. If you need append semantics, do `data.patch(path, { items: [...old.items, newItem] })` explicitly.
- **`save(path, object)`** — blind overwrite. Use for full-document replacement; prefer `patch` when you only know a few fields.

**Why RMW matters**: if two copies of the widget are open, naive `save(patch)` loses concurrent edits. `patch` reads fresh each time, so two copies stay coherent.

**First-run safety**: the file doesn't have to exist. `load` returns defaults on miss; `patch` creates it.

See `widgets/dashboards.md` for the full `state.json` pattern with an end-to-end example.

## `spindrel.state` — versioned state with schema migrations

Wraps `spindrel.data` with schema migrations so bundle shape changes are safe across deploys.

```js
// Schema history:
//   v1: { text: string }
//   v2: { markdown: string, createdAt: number, updatedAt: number }

const state = await window.spindrel.state.load("./state.json", {
  schema_version: 2,
  defaults: { markdown: "", createdAt: 0, updatedAt: 0 },
  migrations: [
    {
      from: 1,
      to: 2,
      apply: (s) => ({
        markdown: s.text || "",
        createdAt: s.createdAt || Date.now(),
        updatedAt: Date.now(),
      }),
    },
  ],
});

await window.spindrel.state.save("./state.json", {
  ...state,
  markdown: "hello world",
  updatedAt: Date.now(),
});
```

**How it works.** `state.load` reads the file, inspects `__schema_version__` (or treats a missing field as v1), runs each matching migration in order up to `schema_version`, persists the upgraded state back to disk, and returns the object with `__schema_version__` stamped. `state.save` / `state.patch` are thin wrappers over `data.save` / `data.patch` that preserve the version field and apply the same per-path in-iframe mutex (so two `await`s kicked off side-by-side don't lose the intermediate write).

**Migration contract.**

- Each migration is `{ from: N, to: N+1, apply(state) → state }` — one hop at a time. A missing step throws at load time so bundle upgrades fail loud.
- Migrations should be **idempotent**. If `state.load` persists a partially-migrated state and then throws, the next call re-reads the disk file; running the same migration twice must land on the same output. Test it.
- Migrations run on a deep-cloned object; the return value is what gets persisted. Return `state` to mutate in place, or a fresh object to replace wholesale.

**Downgrade refusal.** If the file was written by a newer bundle (`file_version > declared`), `state.load` throws rather than silently dropping fields. Widgets that roll back after a schema bump need to either pin to the old version or clear the file.

**Concurrency caveat.** The per-path mutex covers one iframe. Two widgets in different iframes (or two tabs on the same dashboard) sharing the same `widget://<scope>/<name>/state.json` inherit the same RMW race as `spindrel.data.patch` — last write wins. If this matters, write small and scope each widget's state to its own path (common) or use `spindrel.db` (backend-serialized; see `widgets/db.md`).

**Not in client-side `state`.** Multi-step migration chains (`{from: 1, to: 3}`), down-migrations, transactional rollback of a failed migration, cross-bundle state sharing. If a migration throws mid-way, the disk file keeps its old version; next load retries the same step.

## Bus — talk to peer widgets on the same dashboard

```js
// Control panel widget publishes after a successful action
window.spindrel.bus.publish("items_changed", { id: 42 });

// Feed widget listens and re-fetches
const off = window.spindrel.bus.subscribe("items_changed", () => reloadFeed());
// call off() from teardown; iframe unload also cleans up
```

Scope is **channel-scoped** — both widgets must be pinned on the same channel dashboard (or in the same channel chat) to see each other. User-dashboard pubsub lands when the dashboard slug threads through the iframe (Phase B). Falls back silently on browsers without `BroadcastChannel`.

## `spindrel.stream(kinds, filter?, cb)` — live channel events

Subscribes the widget to the channel's event bus over SSE. Use this for anything that wants to react to activity in the channel without polling — new messages, turn start / end, context-budget ticks, tool activity, etc.

```js
// One kind:
const off = window.spindrel.stream("new_message", (event) => {
  renderMessage(event.payload.message);
});

// Multiple kinds:
const off = window.spindrel.stream(
  ["turn_started", "turn_ended"],
  (event) => updateStatus(event.kind, event.payload.bot_id),
);

// With a client-side filter:
const off = window.spindrel.stream(
  ["tool_activity"],
  (event) => event.payload?.tool_name === "fetch_url",
  (event) => log(event),
);

// Full form — subscribe to a specific (non-host) channel or pass since:
const off = window.spindrel.stream(
  { kinds: ["context_budget"], channelId, since: lastSeq },
  (event) => updateGauge(event.payload),
);

// Stop: call the returned unsubscribe.
off();
```

- `cb` receives the wire event `{kind, channel_id, seq, ts, payload}` — the same shape the web UI gets. Each `ChannelEventKind` has its own payload schema (see `app/domain/payloads.py`).
- Kind strings are validated client-side; typos throw immediately.
- Auto-reconnects on network drops with exponential backoff; the last seen `seq` is passed as `since=` so the replay ring fills the gap.
- On `replay_lapsed` the widget gets a host toast ("Stream replay lapsed") AND the callback fires so the widget can refetch baseline state.
- On server shutdown the stream closes quietly (no reconnect).

**`spindrel.stream` vs `spindrel.bus`** — `bus` is `BroadcastChannel`, widget↔widget only, same browser, cross-window only. `stream` is server SSE — cross-client, includes the bot's own activity, survives page reloads via replay. Use `bus` for presentation-layer pubsub between pinned copies; use `stream` for "react to what the agent is doing."

**Reference widget** — `app/tools/local/widgets/context_tracker/index.html` pins a live context-window gauge driven entirely by `spindrel.stream([context_budget, turn_started, turn_ended, turn_stream_tool_start], ...)`.

## Cache — TTL + inflight dedup

```js
// Called by 3 widgets on page load; only one actual fetch fires
const forecast = await window.spindrel.cache.get(
  "weather:philly",
  5 * 60_000,                                    // 5 min TTL
  () => window.spindrel.callTool("get_weather", { location: "philly" }),
);
```

`get()` returns the cached value if fresh, shares an inflight promise across concurrent callers, and re-fetches on expiry. On fetcher error, the cache entry is cleared so the next call retries instead of sticking on the error.

## Notify — surface status as a toast

```js
try {
  await window.spindrel.callTool("run_backup", {});
  window.spindrel.notify("success", "Backup started.");
} catch (e) {
  window.spindrel.notify("error", e.message);
}
```

Renders as a toast banner in the widget chrome (not inside your widget DOM — stays out of your layout). Auto-dismisses after 4s; user can click to dismiss early. Four levels: `info` / `success` / `warn` / `error` with the matching semantic token colors.

## Log — buffered, host-forwarded

```js
window.spindrel.log.info("fetched", data.length, "items");
window.spindrel.log.error("parse failed:", err);
```

Writes to an in-iframe ring buffer (last 200 entries, inspectable via `log.buffer()`) AND posts each entry to the host, where the Dev Panel's **Widgets → Dev → Recent → "Widget log"** subtab renders them in a filterable, per-pin-attributed list (newest first, level filter, click to expand). Host-side ring buffer caps at 500 entries. Use instead of `console.log` when you want the messages visible to anyone editing the widget without opening browser devtools — and when you want to trace a log line back to one concrete pin.

## ui.status + ui.table — skip the CSS

```js
const listEl = document.getElementById("items");
window.spindrel.ui.status(listEl, "loading");
try {
  const rows = await window.spindrel.api("/api/v1/tasks?limit=20");
  if (!rows.length) {
    window.spindrel.ui.status(listEl, "empty", { message: "No tasks yet." });
  } else {
    listEl.innerHTML = window.spindrel.ui.table(rows, [
      { key: "title", label: "Task" },
      { key: "status", label: "Status" },
      { key: "updated_at", label: "Updated", format: (v) => new Date(v).toLocaleDateString() },
      { key: "id", label: "", html: true, format: (id) => `<a href="/tasks/${id}">→</a>` },
    ]);
  }
} catch (e) {
  window.spindrel.ui.status(listEl, "error", { message: e.message });
}
```

`ui.status(el, state, opts)` replaces the element's contents with an `sd-*` styled skeleton / empty / error block (or clears it when state is `"ready"`). `ui.table(rows, columns)` returns an HTML string — set `innerHTML` or append wherever. Column options: `{key, label, align?, format?(v, row), html?}`. Set `html: true` to pass pre-rendered HTML through unescaped.

## ui.chart — sparkline / line / bar / area

```js
const el = document.getElementById("trend");

// Sparkline — defaults: 40px tall, theme.accent, no axis, fills container width.
window.spindrel.ui.chart(el, [0.12, 0.19, 0.24, 0.31, 0.42, 0.55, 0.61], {
  type: "area",       // "line" (default) | "bar" | "area"
  min: 0, max: 1,     // auto from data if omitted
});

// With axis + custom format
window.spindrel.ui.chart(el, requests, {
  type: "bar",
  height: 80,
  showAxis: true,
  format: (v) => v.toLocaleString(),
});

// Points form — x is used only for spacing; omit it for even spacing.
window.spindrel.ui.chart(el, [{x:0,y:1},{x:2,y:4},{x:5,y:3}]);
```

`chart(el, data, opts)` replaces the element's contents with an inline SVG. Options:

| Opt | Default | Purpose |
|-----|---------|---------|
| `type` | `"line"` | One of `line`, `bar`, `area`. |
| `height` | `40` | SVG height in px. Width stretches to container. |
| `color` | `spindrel.theme.accent` | Stroke / fill colour. |
| `min`, `max` | auto | Y-axis bounds. Omit for auto-fit; pass both for absolute scaling (e.g. `0`/`1` for a percent). |
| `strokeWidth` | `1.5` | Line / area stroke width (kept crisp at any size via `vector-effect="non-scaling-stroke"`). |
| `showAxis` | `false` | Reserves 28px on the left and renders min/max tick labels. |
| `format` | `String` | Formatter for axis labels. |
| `emptyMessage` | `"No data"` | Shown via `sd-empty` when `data` is empty. |
| `label` | — | `<title>` text for accessibility / hover tooltip. |

**Data shapes accepted**: `number[]`, `{y}[]`, or `{x,y}[]`. `x` is used only for spacing; omit for even spacing (the common sparkline case).

Re-call on every update — the SVG is rebuilt cheaply. For a rolling series, keep a `const values = []` and `values.push(...); if (values.length > CAP) values.splice(0, values.length - CAP); chart(el, values, opts)`.

**Not in the built-in chart**: tooltips on hover, axes beyond min/max ticks, multi-series overlays, colour palettes for categorical bars. If you need those, inline a tiny third-party lib — the goal here is "sparkline under a stat card", not Grafana.

## ui.icon — inline SVG icons

Every widget iframe ships a curated Lucide subset as an inline SVG sprite at
the top of `<body>`. Reference it from HTML or JS:

```html
<svg class="sd-icon"><use href="#sd-icon-check"/></svg>
<svg class="sd-icon sd-icon--lg sd-icon--accent"><use href="#sd-icon-bell"/></svg>
```

```js
// Dynamic — returns an <svg> string suitable for innerHTML or concat.
buttonEl.innerHTML = window.spindrel.ui.icon("trash", { size: "sm", tone: "danger" });
```

Options: `size` = `"sm"` (14px) | `"lg"` (20px) | `"xl"` (28px); `tone` =
`muted` | `dim` | `accent` | `success` | `danger` | `warning`; `className`
appended as-is. Unknown names log a warning and render an empty `<svg>`.

See `widgets/styling.md` for the full icon list.

## ui.autogrow — textarea that grows to fit content

```js
const teardown = window.spindrel.ui.autogrow(textareaEl, { maxHeight: 240 });
// Call teardown() on cleanup (optional — iframe unmount frees everything).
```

The textarea gets `data-autogrow="true"` + `resize: none`; height recalculates
on every `input` event. Caps at `maxHeight` (default 240px) then scrolls.

## ui.menu — popover menu anchored to an element

```js
openBtn.addEventListener("click", () => {
  window.spindrel.ui.menu(openBtn, [
    { label: "Edit",   icon: "pencil",  onSelect: () => startEdit() },
    { label: "Share",  icon: "send",    kbd: "⌘S", onSelect: () => share() },
    { divider: true },
    { label: "Delete", icon: "trash",   danger: true, onSelect: () => confirmDelete() },
  ]);
});
```

Handles positioning (flips above the anchor when the viewport is tight),
keyboard (ArrowUp/Down/Enter/Escape), outside-click dismissal, and entry
animation. Items: `{label, icon?, kbd?, danger?, onSelect()}` or
`{divider: true}`. Returns `{close()}` for programmatic dismissal.
`opts.minWidth = "anchor"` makes the menu width match the trigger.

## ui.tooltip — hover/focus tooltip

```js
window.spindrel.ui.tooltip(infoIconEl, "Last synced 3m ago");
```

Attaches `mouseenter` / `mouseleave` / `focus` / `blur` listeners. Default
`delay: 200ms`. Returns a teardown function.

## ui.confirm — promise-based confirm modal

```js
const ok = await window.spindrel.ui.confirm({
  title: "Delete todo?",
  body: "This can't be undone.",
  confirmLabel: "Delete",
  danger: true,
});
if (ok) await sp.callHandler("delete_todo", { id });
```

Backdrop click, Escape, and Cancel all resolve `false`; Enter and Confirm
resolve `true`. `danger: true` styles the confirm button as a danger
action and focuses the Cancel button by default (safer default for
destructive ops). Omit `body` to render a title-only modal.

## form — declarative, validated, sd-* styled

```js
const el = document.getElementById("add-task");
const f = window.spindrel.form(el, {
  fields: [
    { name: "title",   label: "Title",   required: true, placeholder: "What needs doing?" },
    { name: "notes",   label: "Notes",   type: "textarea" },
    { name: "priority", label: "Priority", type: "select",
      options: [{ value: "low", label: "Low" }, { value: "med", label: "Medium" }, { value: "high", label: "High" }],
      initial: "med" },
    { name: "pinned",  label: "Pin it",  type: "checkbox" },
  ],
  initial: { priority: "med" },
  submitLabel: "Add task",
  submittingLabel: "Adding…",
  resetOnSubmit: true,
  onSubmit: async (values, { api }) => {
    await api("/api/v1/tasks", { method: "POST", body: JSON.stringify(values) });
    window.spindrel.bus.publish("items_changed", {});
    window.spindrel.notify("success", "Task added.");
  },
});

// Programmatic control
f.set({ priority: "high" });  // patch values
f.reset();                     // back to initial
await f.submit();              // trigger submit externally
```

Fields support `text` / `textarea` / `select` / `checkbox` / any `<input type=...>`. `validate` is called per-field — return a string to surface an error under the field, or nothing to pass. Required validation is automatic. Submit is disabled while running; errors from `onSubmit` show inline *and* fire a `notify("error", ...)`. `resetOnSubmit: true` clears fields back to `initial` after a successful submit.

## Error boundary

Uncaught iframe errors and unhandled promise rejections surface a red banner above the widget with a **Reload** button. Users can recover from a widget crash without refreshing the page; the Reload button remounts the iframe (state inside the iframe is lost, state in `state.json` / `widget_config` survives).

## Markdown rendering

Use **`window.spindrel.renderMarkdown(text)`** — HTML-escapes the source first, then transforms. Safe to `innerHTML` bot-authored prose.

Supported: headings (`#` through `####`), bold (`**x**`), italic (`*x*`), inline code (`` `x` ``), fenced code blocks (```` ```lang ... ``` ````), unordered + ordered lists (`-` / `1.`), blockquotes (`>`), links (`[text](url)`), paragraphs.

Not supported: tables, footnotes, inline HTML passthrough, definition lists, images (use `<img>` directly — CSP allows `data:` + `blob:` + same-origin). If you need more, inline `marked.min.js` into the widget bundle and reference it as `<script src="marked.min.js"></script>` in path-mode — the CDN path is CSP-blocked but same-bundle JS works.

```js
const html = window.spindrel.renderMarkdown("# Hello\n\nSome **bold** text.");
document.getElementById("out").innerHTML = html;
```

Returns `""` for `null` / `undefined` input.

## Useful API endpoints

| Endpoint | For |
|---|---|
| `GET /api/v1/channels` | List channels |
| `GET /api/v1/channels/{id}/messages/search?limit=N` | Recent messages (no `q` = newest first) |
| `GET /api/v1/channels/{id}/state` | Active turns + pending approvals snapshot |
| `GET /api/v1/channels/{id}/workspace/files` | Workspace file tree |
| `GET /api/v1/channels/{id}/workspace/files/content?path=...` | Read a workspace file |
| `PUT /api/v1/channels/{id}/workspace/files/content?path=...` | Write a workspace file |
| `GET /api/v1/admin/tasks?channel_id=...` | Tasks (filter by channel/status/bot) |
| `GET /api/v1/admin/tool-calls/recent` | Recent tool-call envelopes |
| `GET /api/v1/bots/me` | Bot's own config |
| `POST /api/v1/widget-actions` | **Dispatch a tool / API call / config patch** — see `widgets/tool-dispatch.md` |

For the exhaustive list filtered by your scopes, call `list_api_endpoints()`.

## See also

- `widgets/tool-dispatch.md` — `/api/v1/widget-actions` envelope + `callTool` pattern
- `widgets/html.md` — bundle layout, sandbox, auth
- `widgets/dashboards.md` — archetypes, `state.json` pattern
- `widgets/db.md` — `spindrel.db` server-side SQLite
- `widgets/handlers.md` — `window.spindrel.callHandler` + `widget.py`
- `widgets/styling.md` — `sd-*` vocabulary, `window.spindrel.theme`
