---
name: HTML Widgets
description: How to build interactive HTML widgets and bot-authored dashboards with emit_html_widget — inline vs workspace-backed, bundle layout, YAML frontmatter for catalog discoverability, state.json pattern, tool dispatch via /widget-actions, sd-* design vocabulary, when to pick this over component widgets
triggers: emit_html_widget, html widget, interactive widget, custom widget, build a widget, chart widget, mini dashboard, render html, iframe widget, workspace html, live dashboard, bespoke ui, project status dashboard, status board, tool control panel
category: core
---

# HTML Widgets — `emit_html_widget` Tool Guide

When the user asks for something you can't render with the standard component widgets — a chart, a custom layout, a mini-dashboard, a scraped page distilled into a card, an interactive control — emit an HTML widget. You write the HTML (and optionally JavaScript + CSS); it renders inside a sandboxed iframe in the chat bubble. The user can pin the result to their dashboard.

Unlike any string you might return as Markdown, an HTML widget can:

- Run JavaScript (fetch app data, handle clicks, update itself)
- Call the app's own API at `/api/v1/...` (same-origin — auth comes along for free)
- **Trigger backend tools** via `POST /api/v1/widget-actions` (run `fetch_url`, `generate_image`, whatever — the fresh result flows back as a new envelope)
- Re-render automatically when a workspace file changes (path mode)
- Persist state to a workspace JSON file and read it back next time

This skill teaches you to build **real dashboards** — not one-off fetches. The default shape is a folder on disk that you iterate on: `index.html` + `state.json` + optional assets, path-moded as the widget target, living in a well-known location the user can find.

## When to Use Which Widget

| Situation | Use |
|---|---|
| Entity detail, toggle, or status card that fits the component grammar | Component widgets (YAML template) |
| Chart, table, free-form layout, or anything not in the grammar | `emit_html_widget` |
| User says "make me a custom widget for X" | `emit_html_widget` |
| User says "show me X live / as a dashboard" | `emit_html_widget` (usually path mode) |
| User says "build a status board / project dashboard / control panel" | `emit_html_widget` + a bundle (see below) |
| One-off inline result | Normal text/Markdown reply (no widget needed) |

Default to component widgets when a template exists; reach for HTML when the component grammar doesn't cover it.

## Widget Bundles — Where to Put Your Files

A widget is a **folder**, not a single HTML file. Put everything the widget needs in one directory and path-mode the `index.html` inside it.

```
<widget-root>/<widget-slug>/
├── index.html          ← the widget itself (emit_html_widget path target)
├── state.json          ← mutable state the widget reads/writes (optional)
├── data.json           ← static bundled data (optional)
├── README.md           ← your own notes about what this widget does (optional)
├── styles.css          ← extra styles beyond the sd-* vocabulary (optional)
└── assets/             ← images, icons, sub-data files (optional)
```

### Widget metadata — YAML frontmatter

Every `index.html` should open with a YAML frontmatter block inside an HTML comment. The workspace scanner parses it and surfaces your widget in the "HTML widgets" tab of the Add-widget sheet with a proper name, description, and tags — without frontmatter, the card falls back to the bundle slug (`project-status` instead of `Project status`), which reads like an error.

```html
<!--
---
name: Project status              # shown as the card title
description: Live phase tracker with RMW state.json
display_label: Project status     # defaults to name — used on the pinned widget chrome
version: 1.2.0                    # bump when you make a meaningful change
author: crumb                     # bot or user who authored the widget
tags: [dashboard, project]        # filters in the catalog
icon: activity                    # lucide-react icon name (see https://lucide.dev)
---
-->
<div class="sd-card">...</div>
```

Rules:

- **Must be the very first thing in the file.** Leading whitespace is fine; any HTML or text before the comment block disqualifies it.
- **Only `name` is required.** Everything else has sensible fallbacks (`display_label` → `name`, `version` → `"0.0.0"`, `tags` → `[]`, etc.). Still, description + tags dramatically improve discoverability — write one good sentence for `description` so the user recognizes what they're pinning.
- **Bump `version` when you change the widget.** Semver — patch for bug fixes, minor for new features, major for incompatible state-shape changes. This is how you (or a future turn) know whether a pinned widget is running the latest code.
- **Malformed YAML is silently ignored** — the scanner won't crash over a bad block, but your widget will show up with slug-fallback defaults. If the card looks wrong, check the frontmatter.

The scanner walks any `.html` under a directory named `widgets/` plus any `.html` anywhere in the channel workspace that references `window.spindrel.*`. Files matched only by the second rule show a "loose" badge — move them into a `widgets/<slug>/` folder to clear it.

### Path grammar — use absolute `/workspace/channels/<channel_id>/...` for both tools

The cleanest pattern is **symmetric**: pass the same absolute path to `file` and `emit_html_widget`. Both accept the `/workspace/channels/<channel_id>/...` form, and using it removes any ambiguity about where the file lands.

```
# 1. WRITE the bundle
file(create,
     path="/workspace/channels/<CHANNEL_ID>/data/widgets/project-status/index.html",
     content="<!doctype html>...")

# 2. EMIT the widget — same absolute path
emit_html_widget(
    path="/workspace/channels/<CHANNEL_ID>/data/widgets/project-status/index.html",
    display_label="Project status")
```

Your **current channel ID** is in your system context (pinned-widget chrome + turn context). You can also discover it inside the widget at runtime via `window.spindrel.channelId`.

**Why this form is better** than the relative shortcut:

- Works **even when you're outside a channel** (cron-triggered tasks, autoresearch, task pipelines). Relative paths require a current channel to scope against; absolute paths carry their own target channel.
- Lets you emit widgets that target a **different channel** than the one you're replying in — useful for cross-channel dashboards.
- Matches what the `file` tool needs anyway (its relative paths are rooted at the bot workspace, not the channel workspace), so you avoid the two-grammar trap.

### Shortcut: relative paths (in-channel only)

`emit_html_widget` still accepts channel-workspace-relative paths like `data/widgets/foo/index.html` when you're inside a channel — it scopes them to the current channel. But be aware:

- The `file` tool's relative paths resolve to the **bot workspace** (`{ws}/{bot}/`), not the channel workspace. So `file(path="data/widgets/foo/index.html")` + `emit_html_widget(path="data/widgets/foo/index.html")` point at **different files**. You'll see `Workspace file not found (or path escapes workspace)`.
- If you go the relative-path route, use `file(path="channels/<CHANNEL_ID>/data/widgets/foo/index.html")` (note the `channels/<id>/` prefix) so both tools land on the same file.

**Recommended**: just use the absolute form everywhere. It's longer to type, but it's the form that always works.

**Non-channel absolute paths** (`/workspace/widgets/<slug>/...`) are reserved for DX-5b and currently rejected with a clear error.

### The bundle shape

Each widget is a folder:

```
/workspace/channels/<channel_id>/data/widgets/<widget-slug>/
├── index.html          ← the widget itself (emit_html_widget path target)
├── state.json          ← mutable state the widget reads/writes (optional)
├── data.json           ← static bundled data (optional)
├── README.md           ← your own notes about what this widget does (optional)
├── styles.css          ← extra styles beyond the sd-* vocabulary (optional)
└── assets/             ← images, icons, sub-data files (optional)
```

Scope rules:

| Scope | Root | Status |
|---|---|---|
| **Channel-specific** — tied to this channel's data or project | `/workspace/channels/<channel_id>/data/widgets/<slug>/` (file tool) → `data/widgets/<slug>/` (emit_html_widget) | **Default.** Works today. |
| **Non-channel-scoped** — reusable across channels | `/workspace/widgets/<slug>/` | **Queued (DX-5b).** Not resolvable yet; passing a `/workspace/widgets/...` path currently fails. Stick to channel-scoped. |

Conventions:

- **Slug is kebab-case**: `project-status`, `sprint-burndown`, `sonarr-queue`, `home-control`.
- **Always path-mode** for anything you want to iterate on — inline mode is for one-off snapshots. Path mode hot-reloads within ~3 s of a file edit.
- **Relative paths work inside the bundle** — `./state.json`, `../shared/config.json`, `./assets/logo.svg` resolve against the widget's `index.html` directory inside the iframe. See "Relative paths" below.
- **One folder per widget.** Keep the tree legible; a bundle can then be renamed/moved/deleted atomically.

Discover the current channel id at runtime:

```js
window.spindrel.channelId   // the emitting channel's UUID, or null if unbound
```

If you're building inside an ephemeral widget-dashboard session: you inherit the parent channel's workspace and channel context, so use the parent channel's ID in `/workspace/channels/<parent_channel_id>/data/widgets/<slug>/` with the `file` tool. (Non-channel roots arrive with DX-5b.)

## The Two Modes

| Mode | Signature | When | Auto-updates |
|---|---|---|---|
| **Inline** | `emit_html_widget(html=..., js?, css?, display_label?)` | One-off snapshot. You assemble the widget from data you already have. | No — static snapshot |
| **Path** | `emit_html_widget(path="data/widgets/foo/index.html", display_label?)` — channel-workspace-relative | You wrote (or will iterate on) a workspace file. The widget re-renders when the file changes. | Yes — polls the file every 3 s |

Exactly one of `html` / `path` is required.

### Inline Example

```
emit_html_widget(
  html='''
  <h3 style="margin:0 0 8px">Channels</h3>
  <ul id="list"><li>loading…</li></ul>
  <button id="refresh" class="sd-btn">Refresh</button>
  ''',
  js='''
  async function load() {
    const data = await window.spindrel.api("/api/v1/channels");
    document.getElementById("list").innerHTML =
      data.map(c => `<li>${c.name}</li>`).join("");
  }
  document.getElementById("refresh").addEventListener("click", load);
  load();
  ''',
  display_label="Channels"
)
```

### Path Example (the default for dashboards)

```
1. file(create, path="/workspace/channels/<CHANNEL_ID>/data/widgets/project-status/index.html", content="<html>… full doc …</html>")
2. file(create, path="/workspace/channels/<CHANNEL_ID>/data/widgets/project-status/state.json", content='{"phase":"Planning","progress":0}')
3. emit_html_widget(path="/workspace/channels/<CHANNEL_ID>/data/widgets/project-status/index.html", display_label="Project status")

Same path for both tools. `emit_html_widget` parses the `/workspace/channels/<channel_id>/` prefix and scopes to that channel regardless of whether you're currently in it.
```

After pinning, further edits to files in that bundle refresh the pinned widget within ~3 seconds. Iterate on the folder; no need to re-emit.

### Optional: claim the dashboard's main area (`display_mode="panel"`)

For widgets meant to BE the dashboard — a single self-contained mini-app rather than one tile among many — pass `display_mode="panel"` to hint that the user should pin it as the dashboard panel:

```
emit_html_widget(
    path="/workspace/channels/<CHANNEL_ID>/data/widgets/control-room/index.html",
    display_label="Control room",
    display_mode="panel",
)
```

The hint pre-checks the **Promote to dashboard panel** option in EditPinDrawer. The user still confirms via the drawer; promotion flips `widget_dashboard.grid_config.layout_mode` to `panel` and renders this widget filling the dashboard's main area while every other pin stacks in a 320px rail strip alongside it. Only one pin per dashboard can be the panel pin (server-enforced via a partial unique index).

Default is `display_mode="inline"` — normal grid tile. Don't reach for `panel` unless the widget is genuinely the *whole* point of its dashboard; multiple inline tiles are usually a better composition.

## What the Sandbox Allows

The widget runs in an iframe with `sandbox="allow-scripts allow-same-origin"` and a tight CSP:

- **Allowed**: inline `<script>` / `<style>`, same-origin `fetch("/api/v1/...")`, `data:` / `blob:` images.
- **Blocked**: cross-origin network (`fetch("https://example.com/...")` will fail), popups, form submissions that navigate, top-level navigation.

If you need external data, have a prior tool call fetch it and inline the JSON into the widget — or trigger `fetch_url` from the widget via the tool dispatcher (see below).

### Loading third-party scripts / tiles / fonts (`extra_csp`)

Some widgets need to pull in external libraries that can't be inlined — Google Maps, Mapbox, Stripe Elements, YouTube embeds, Chart.js CDN, Google Fonts. Pass `extra_csp` to `emit_html_widget` to append the specific origins to the CSP for this widget only:

```python
emit_html_widget(
    path="data/widgets/home-map/index.html",
    display_label="Home map",
    extra_csp={
        "script_src":  ["https://maps.googleapis.com", "https://maps.gstatic.com"],
        "connect_src": ["https://maps.googleapis.com"],
        "img_src":     ["https://maps.gstatic.com", "https://maps.googleapis.com"],
        "style_src":   ["https://fonts.googleapis.com"],
        "font_src":    ["https://fonts.gstatic.com"],
    },
)
```

Rules the validator enforces:

- Concrete `https://host[:port]` origins only — no `*`, no `data:` / `blob:` / `http:`, no CSP keywords (`'self'`, `'unsafe-*'`).
- Max 10 origins per directive.
- Origin-only — pass `https://maps.googleapis.com`, not `https://maps.googleapis.com/maps/api/js`.
- Supported directives (snake_case): `script_src`, `connect_src`, `img_src`, `style_src`, `font_src`, `media_src`, `frame_src`, `worker_src`.

The default CSP (`'self'` + `'unsafe-inline'` scripts/styles, `data:` + `blob:` images) stays in place — your extras are **appended**, not replacements. Widgets that don't need external origins keep the tight default; only the specific widget that asks for Maps is granted Maps.

Common presets worth memorizing:

- **Google Maps JS API**: `script_src` + `connect_src` + `img_src` on `https://maps.googleapis.com` + `https://maps.gstatic.com`; `style_src` `https://fonts.googleapis.com`; `font_src` `https://fonts.gstatic.com`.
- **Mapbox GL**: `script_src` `https://api.mapbox.com`; `connect_src` `https://api.mapbox.com https://events.mapbox.com`; `img_src` `https://api.mapbox.com`.
- **YouTube embed**: `frame_src` `https://www.youtube.com` (or `https://www.youtube-nocookie.com`).
- **Stripe Elements**: `script_src` + `frame_src` `https://js.stripe.com`; `connect_src` `https://api.stripe.com`.

## Auth — widgets run as YOU (the bot), not as the viewer

When you emit a widget, the envelope captures your bot id. At render time the host mints a **short-lived (15 min) bearer token scoped to your bot's API key** and injects it into `window.spindrel.api()`. Consequences:

- **Use `window.spindrel.api(path)`**, not raw `fetch(path)`. Only `api()` attaches the bearer — a bare `fetch` will come back 422 (missing Authorization header) or 401.
- **Your bot's scopes are the ceiling.** If your bot's API key doesn't have `channels:read`, your widget can't call channel endpoints. Ask the user to broaden scopes via the admin UI; don't try to work around it.
- **You inherit nothing from the viewing user.** An admin looking at your widget does NOT lend you their admin scopes. This is how bot-authored JS is prevented from issuing privileged calls in someone else's session.
- **The widget chrome shows `@your-bot-name`** in the bottom-left of the rendered card. That's the user's cue that your widget is acting with your credentials.

If your bot has no API key configured, the widget renders but `api()` calls will surface a clear "Widget auth failed" banner — the user needs to provision a key before the widget works.

## The `window.spindrel` Helper

Every widget gets a helper object injected automatically. No imports, no setup:

```js
// Identity
window.spindrel.channelId                  // emitting channel UUID, or null
window.spindrel.botId                      // your bot id (the one running this)
window.spindrel.botName                    // display name, e.g. "crumb"
window.spindrel.dashboardPinId             // UUID when pinned to a dashboard, else undefined
window.spindrel.widgetPath                 // absolute-within-channel path of this widget's HTML (e.g. "data/widgets/x/index.html"), null for inline widgets
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

// Rendering helpers
window.spindrel.renderMarkdown(text)       // HTML-safe Markdown → HTML string (see "Markdown Rendering" below)

// Tool dispatch
window.spindrel.callTool(name, args, opts?) // run a backend tool; returns fresh envelope, throws on failure (see "Tool Dispatch" below)

// JSON state — read/merge/write over workspace files, deep-merge semantics
window.spindrel.data.load(path, defaults?)   // parsed object (defaults deep-merged underneath); returns defaults if file missing
window.spindrel.data.patch(path, patch, defaults?) // RMW atomically; returns the new state
window.spindrel.data.save(path, object)      // overwrite (escape hatch)

// Event subscriptions — return an unsubscribe function
window.spindrel.onToolResult(cb)   // fires whenever the envelope is refreshed (state_poll, callTool result, etc.)
window.spindrel.onConfig(cb)       // fires when this pin's widget_config changes (debounced — only on actual change)
window.spindrel.onTheme(cb)        // fires when the app switches light/dark mode

// Widget-to-widget pubsub (bus) — channel-scoped; see "SDK framework" below
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
window.spindrel.log.info|warn|error(...args)    // ring buffer (200) + live in Widgets → Dev → Recent → "Widget log"

// Minimal UI helpers (sd-* styled)
window.spindrel.ui.status(el, state, {message?, height?})  // state: "loading" | "error" | "empty" | "ready"
window.spindrel.ui.table(rows, columns, {emptyMessage?})   // returns HTML string — set innerHTML or append
window.spindrel.ui.chart(el, data, {type?, height?, color?, min?, max?, showAxis?, format?})  // SVG sparkline / line / bar / area

// Versioned state.json — wraps spindrel.data with schema migrations
window.spindrel.state.load(path, {schema_version, migrations, defaults})  // runs migrations on load, persists bumped version
window.spindrel.state.save(path, object)           // write; preserves __schema_version__ from disk when omitted
window.spindrel.state.patch(path, patch, spec)     // RMW deep-merge with migrations

window.spindrel.form(el, {fields, onSubmit, initial?, submitLabel?, submittingLabel?, resetOnSubmit?})

// Tool result / config
window.spindrel.toolResult                 // current envelope payload (see declarative widgets)
window.spindrel.theme                      // resolved design tokens (see Styling)
```

### Reacting to live updates

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

### Bundled assets (images, icons, media)

The sandbox blocks cross-origin network but allows `data:` / `blob:` / same-origin images. Since `<img src>` can't carry a bearer token (and workspace files are bearer-authed), use **`window.spindrel.loadAsset(path)`** to fetch a binary file with auth and get back a `blob:` object URL you can drop into any `src` attribute:

```js
// widget emitted from data/widgets/home-control/index.html
const logoUrl = await window.spindrel.loadAsset("./assets/logo.svg");
document.getElementById("logo").src = logoUrl;

// Works for <video>, <audio>, <a download>, anything that takes a same-origin URL
document.getElementById("clip").src = await window.spindrel.loadAsset("./media/intro.mp4");
```

The object URLs stay valid for the lifetime of the iframe. If you're loading many large assets and want to free memory explicitly, call `window.spindrel.revokeAsset(url)`.

Supported MIME types are whatever the workspace `/files/raw` endpoint serves — common image formats, PDFs, SVG, short audio/video clips.

### Channel attachments (images/files from the conversation)

Widgets often want to show **attachments** — images pasted into chat, files uploaded by the user, screenshots dropped by an integration. Two paths:

#### (a) Pre-download into the bundle — best for "fixed" widgets

In the bot turn before emitting, use the `save_attachment` tool to copy attachments into the widget bundle, then reference them with `loadAsset` (or directly):

```
list_attachments(channel_id=<id>)
  → [{id: "abc-123...", filename: "sunrise.jpg", mime_type: "image/jpeg", size: 240_000}, ...]

save_attachment(attachment_id="abc-123...",
                path="/workspace/channels/<CHANNEL_ID>/data/widgets/gallery/assets/sunrise.jpg")

emit_html_widget(path="/workspace/channels/<CHANNEL_ID>/data/widgets/gallery/index.html", ...)
```

Inside the widget:
```js
document.getElementById("photo").src = await window.spindrel.loadAsset("./assets/sunrise.jpg");
```

This baked-in pattern is durable — attachments can be deleted from the channel, but the widget's copy lives in the bundle.

#### (b) Fetch live from the channel — best for "browse all attachments" dashboards

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

### Relative paths

Inside a path-mode widget, you know where your bundle lives but you don't want to hard-code it. `readWorkspaceFile`, `writeWorkspaceFile`, and all `data.*` helpers accept **relative paths** that resolve against `dirname(widgetPath)`:

```js
// widget emitted from data/widgets/project-status/index.html
const state = await window.spindrel.data.load("./state.json");
// → reads data/widgets/project-status/state.json

const sibling = await window.spindrel.readWorkspaceFile("../shared/config.json");
// → reads data/widgets/shared/config.json
```

Rules:

- `./foo` and `../foo` — resolved against the widget's directory. Requires path mode (`widgetPath` is null for inline widgets).
- `foo/bar` with no leading `./` or `/` — treated as channel-workspace-absolute as-is (current default). `data.load("data/widgets/other/state.json")` works unchanged.
- `/workspace/...` (leading slash) — **reserved for DX-5b** and currently throws. When that ships, it will let widgets target non-channel bundles and explicit channel roots.
- `..` that escapes the workspace root throws before hitting the backend.

Use `window.spindrel.resolvePath(input)` directly if you need the resolved string for your own bookkeeping (e.g. logging, debugging).

### api() vs apiFetch()

`api(path, options)` is a thin `fetch` wrapper — attaches `Authorization: Bearer <short-lived bot token>`, sets `Content-Type: application/json`, parses JSON responses, and throws on non-2xx. **Always use this or `apiFetch` instead of raw `fetch()`**; raw fetch won't be authenticated.

`apiFetch(path, options)` is the same auth but returns the raw `Response` object. Reach for it when you need a blob (images, video, downloads), headers, or streaming:

```js
const r = await window.spindrel.apiFetch("/api/v1/attachments/" + id,
  { headers: { Accept: "image/*" } });
if (!r.ok) throw new Error("HTTP " + r.status);
img.src = URL.createObjectURL(await r.blob());
```

## Tool Dispatch — Making Things Happen

Dashboards aren't just read surfaces. You trigger work from a widget by dispatching a **tool call** through the host, which runs the tool under your bot's scopes and pushes the fresh result back into the widget.

The endpoint is `POST /api/v1/widget-actions`. Three dispatch types:

| `dispatch` | Purpose |
|---|---|
| `"tool"` | Run a named tool (any tool your bot can call) |
| `"api"` | Call a whitelisted admin/channel endpoint (`/api/v1/admin/tasks` or `/api/v1/channels/*`) |
| `"widget_config"` | Patch this pin's `widget_config` (for declarative html_template widgets) |

### The tool-dispatch pattern

Use `window.spindrel.callTool(name, args, opts?)` — it wraps the endpoint, auto-fills `bot_id` + `channel_id`, and throws on failure so you can `try/catch` cleanly:

```js
document.getElementById("run").addEventListener("click", async () => {
  try {
    const env = await window.spindrel.callTool("fetch_url", {
      url: "https://example.com",
    });
    document.getElementById("out").textContent = env.body_text;
  } catch (e) {
    document.getElementById("out").textContent = "Failed: " + e.message;
  }
});
```

Returns the fresh envelope (same shape as `window.spindrel.toolResult`) on success, or `null` if the tool produced no envelope. Throws with the server's error message on non-ok response.

### The envelope shape

Every envelope — whether returned from `callTool`, pushed into `window.spindrel.toolResult`, or received via `onToolResult` — has the same fields:

| Field | Type | What it carries |
|---|---|---|
| `content_type` | string | MIME-ish type, e.g. `"application/json"`, `"text/markdown"`, `"text/plain"`, `"application/vnd.spindrel.html+interactive"` |
| `body` | string \| null | **The full tool output** as a string. JSON tools ship a JSON-encoded string — parse with `JSON.parse(env.body)`. |
| `plain_body` | string | Short preview (≤200 chars for default envelopes, ≤800 for opt-in). **Never** the full payload — don't parse it. |
| `display` | `"badge" \| "inline" \| "panel"` | Renderer hint for the chat bubble. Widgets can ignore. |
| `truncated` | boolean | `true` means `body` was dropped because the underlying payload exceeded the inline cap. **Never true for `callTool` results** (see below). |
| `byte_size` | integer | Actual UTF-8 size of the full payload, even when `body` is null. |
| `record_id` | string \| null | Persisted `tool_calls` row id. Not addressable from widget auth — informational only. |
| `tool_name` | string | The tool that produced this envelope. |

**`body` vs `plain_body`** — `body` is what you parse; `plain_body` is a short human-readable preview for the chat badge. They are not interchangeable. `JSON.parse(env.plain_body)` will fail on any non-trivial payload because `plain_body` is truncated by design.

### Truncation — does not apply to `callTool`

The LLM turn loop caps envelope `body` at 4 KB to protect the model's context window. When that cap fires, `body` becomes `null`, `truncated` becomes `true`, and the UI lazy-fetches the full content through a session-scoped endpoint.

**`callTool` bypasses this cap.** Widget-actions dispatch returns the full `body` regardless of size — widgets can always `JSON.parse(env.body)` without worrying about truncation. Two consequences:

- Your widget can safely call `callTool` against tools that return large JSON (directory listings, API dumps, many-row queries) without seeing `body: null`.
- **Don't defensively handle `truncated: true` on `callTool` results.** If you see it, it's a bug worth reporting — not an expected state.

The only content type that was already exempt from the cap — `application/vnd.spindrel.html+interactive` — stays exempt everywhere.

**`opts.extra`** passes through additional widget-actions fields when you need them:

```js
await window.spindrel.callTool("web_search", { query: "docs" }, {
  extra: {
    display_label: "Docs search",        // lets state_poll fetch fresh state after
    widget_config: { starred: [...] },   // current pin config for {{config.*}} substitution
    dashboard_pin_id: window.spindrel.dashboardPinId,
    source_record_id: someRecordId,
  }
});
```

**Working exemplars in-tree** — read these before writing yours:

- `integrations/web_search/widgets/web_search.html` — Summarize button dispatches `fetch_url`.
- `app/tools/local/widgets/image.html` — regen buttons dispatch `generate_image` with mutated prompts.

(These were written before `callTool` shipped; they build the body by hand. The behavior is identical — `callTool` is the shorter way.)

### Constraints

- Tool runs under your bot's scopes. If the tool needs a capability your bot doesn't have, the dispatch fails cleanly — don't try to work around it.
- The `state_poll` cache (for declarative widgets) has a 30 s TTL keyed by `(tool, args)`; mutations invalidate it.
- `dispatch:"api"` is **whitelisted** to `/api/v1/admin/tasks` and `/api/v1/channels/*`. For any other endpoint, use `spindrel.api()` directly. `callTool` is only for tool dispatch — for `dispatch:"api"` or `dispatch:"widget_config"`, use `spindrel.api("/api/v1/widget-actions", ...)` directly.

### Knowing the output shape before you call

There's no dedicated output-schema field on tools today, but three practical ways to learn what a tool returns:

1. **Widget-template `sample_payload`** — integration tool packs declare a `sample_payload` block in `*.widgets.yaml` (e.g. `app/tools/local/tasks.widgets.yaml`, `app/tools/local/admin.widgets.yaml`). When present, it's the de facto output contract — the shape the template's `{{field}}` substitutions expect. Read it from the bot turn before emitting the widget.
2. **`GET /api/v1/admin/tools/{tool_name}`** — returns the input schema + description + the active widget package name; use that name to locate the widgets.yaml above. Input-shape authoritative, output-shape indirect.
3. **Call it once from the bot turn, inspect, then write the widget.** The most reliable path: dispatch the tool in the same conversation before authoring the widget, copy the JSON structure out of the envelope body, and shape your widget around it. Live output trumps any doc.

For MCP tools, the upstream protocol only ships `inputSchema` — `outputSchema` isn't exposed. Fall back to path (3).

## Discovering what endpoints your widget can hit

Don't guess URLs or copy examples blindly — **call `list_api_endpoints` BEFORE writing the widget** and use the result as ground truth. It returns only the endpoints your bot's scoped API key can hit.

```
list_api_endpoints(scope="channels")   # → all channel endpoints in your scope
list_api_endpoints(scope="admin")       # → admin endpoints (if you have them)
list_api_endpoints()                    # → everything your bot can touch
```

Then inside the widget, use those exact paths with `window.spindrel.api()`:

```js
const state = await window.spindrel.api(
  "/api/v1/channels/" + window.spindrel.channelId + "/state"
);
```

Note the division of labor:

- **`spindrel.api()`** = read state, call regular endpoints.
- **`/api/v1/widget-actions` (dispatch:"tool")** = trigger a tool. Use this when you'd otherwise be wishing for a REST endpoint that "runs X for me".

## The `state.json` Pattern — Dashboards That Remember

Most real dashboards keep a little state that outlives the current render: which phase a project is in, which items are starred, what the user's last filter was. Put it in a JSON file in the widget's bundle and use `window.spindrel.data` to read/merge/write it:

```html
<!-- data/widgets/project-status/index.html (emitted from a channel chat) -->
<div class="sd-card">
  <header class="sd-card-header">
    <h3 class="sd-title" id="title">Project status</h3>
    <span class="sd-meta" id="updated"></span>
  </header>
  <div class="sd-card-body sd-stack">
    <div class="sd-mono" id="phase-line"></div>
    <div class="sd-progress" id="prog" style="--p: 0"></div>
    <ul id="milestones" class="sd-stack-sm"></ul>
  </div>
  <div class="sd-card-actions">
    <button class="sd-btn" id="refresh">Refresh</button>
    <button class="sd-btn sd-btn-primary" id="advance">Advance phase</button>
  </div>
</div>

<script>
const FILE = "./state.json";  // relative to this widget's directory
const DEFAULTS = {
  title: "Untitled",
  phase: "Planning",
  progress: 0,
  milestones: [],
  updated_at: null,
};

async function refresh() {
  render(await window.spindrel.data.load(FILE, DEFAULTS));
}

async function advance(next) {
  const state = await window.spindrel.data.patch(FILE, {
    phase: next,
    updated_at: new Date().toISOString(),
  }, DEFAULTS);
  render(state);
}

function render(s) {
  document.getElementById("title").textContent = s.title;
  document.getElementById("phase-line").textContent = `Phase: ${s.phase}`;
  document.getElementById("prog").style.setProperty("--p", s.progress);
  document.getElementById("updated").textContent = s.updated_at
    ? `Updated ${new Date(s.updated_at).toLocaleString()}`
    : "";
  document.getElementById("milestones").innerHTML = s.milestones
    .map(m => `<li>${m.done ? "✓" : "◯"} ${m.text}</li>`)
    .join("");
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("advance").addEventListener("click", () =>
  advance(prompt("Next phase?") || "Planning")
);
refresh();
</script>
```

### `spindrel.data` semantics

- **`load(path, defaults?)`** — reads the file, parses JSON, and deep-merges it on top of `defaults`. If the file is missing or empty, returns a deep clone of `defaults`. Without `defaults`, returns the raw parsed object. Throws on invalid JSON.
- **`patch(path, patch, defaults?)`** — load → deep-merge `patch` on top → save → return. Objects are merged recursively; **arrays are replaced, not concatenated**. If you need append semantics, do `data.patch(path, { items: [...old.items, newItem] })` explicitly.
- **`save(path, object)`** — blind overwrite. Use for full-document replacement; prefer `patch` when you only know a few fields.

**Why RMW matters**: if two copies of the widget are open, naive `save(patch)` loses concurrent edits. `patch` reads fresh each time, so two copies stay coherent. This is the same pattern `web_search.html` uses for its `starred[]` list (hand-rolled, pre-`data` helper).

**First-run safety**: the file doesn't have to exist. `load` returns defaults on miss; `patch` creates it.

## Dashboard Archetypes

Four shapes to recognize. They compose — a real dashboard is usually a mix.

### A. Live Project Status (RMW state)

You want to show where a project stands and let the user advance it. See the `state.json` example above. Use when the user says *"build me a status dashboard for <project>"* or *"I want a live view of where we are on <thing>"*.

Key moves:
- Bundle under `data/widgets/<project>-status/` (channel-scoped). Non-channel roots arrive with DX-5b.
- `state.json` holds the single source of truth. Never duplicate into the HTML.
- Buttons save patches; `state_poll` not needed because the file drives everything.

### B. Recent-Activity Feed (poll the API)

Stream the last N messages / tasks / events for a channel as live-updating cards.

```js
async function refresh() {
  const cid = window.spindrel.channelId;
  const messages = await window.spindrel.api(
    `/api/v1/channels/${cid}/messages/search?limit=20`
  );
  document.getElementById("feed").innerHTML = messages
    .map(m => `
      <div class="sd-card">
        <div class="sd-card-body">
          <div class="sd-meta">${m.role} · ${new Date(m.created_at).toLocaleTimeString()}</div>
          <div>${m.content}</div>
        </div>
      </div>
    `)
    .join("");
}
setInterval(refresh, 5000);
refresh();
```

Use when: *"what's been going on in this channel"*, *"show me recent X"*, *"live feed of Y"*. Prefer a 5–10 s poll interval; anything faster hammers the bot's rate limits.

### C. Tool-Trigger Control Panel (one-click actions)

Buttons that run backend tools on click. No state needed; the tool does the work.

```html
<div class="sd-card">
  <header class="sd-card-header"><h3 class="sd-title">Quick actions</h3></header>
  <div class="sd-card-actions sd-hstack">
    <button class="sd-btn sd-btn-primary" data-tool="run_backup">Run backup</button>
    <button class="sd-btn" data-tool="sync_inbox">Sync inbox</button>
    <button class="sd-btn sd-btn-danger" data-tool="flush_cache">Flush cache</button>
  </div>
  <div id="status" class="sd-meta"></div>
</div>
<script>
document.querySelectorAll("button[data-tool]").forEach(btn => {
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "…";
    try {
      await window.spindrel.callTool(btn.dataset.tool, {});
      document.getElementById("status").textContent = `✓ ${btn.dataset.tool} ran`;
    } catch (e) {
      document.getElementById("status").textContent = `✗ ${e.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
});
</script>
```

Use when: *"give me one-click access to X"*, *"I want buttons for my common Y"*. Pair with optimistic-update patterns (disable → "…" → show result).

### D. Embedded Knowledge-Base Reader

Read markdown files from the workspace and render them via the bundled renderer:

```js
async function loadNote(path) {
  const md = await window.spindrel.readWorkspaceFile(path);
  document.getElementById("doc").innerHTML = window.spindrel.renderMarkdown(md);
}
```

Pair with a file picker (`listWorkspaceFiles` + a `<select>`) to browse a whole `notes/` folder. Use when: *"let me browse project notes"*, *"show me the README as a dashboard"*, *"embed this doc alongside the live data"*.

## Markdown Rendering

Use **`window.spindrel.renderMarkdown(text)`** — HTML-escapes the source first, then transforms. Safe to `innerHTML` bot-authored prose.

Supported: headings (`#` through `####`), bold (`**x**`), italic (`*x*`), inline code (`` `x` ``), fenced code blocks (```` ```lang ... ``` ````), unordered + ordered lists (`-` / `1.`), blockquotes (`>`), links (`[text](url)`), paragraphs.

Not supported: tables, footnotes, inline HTML passthrough, definition lists, images (use `<img>` directly — CSP allows `data:` + `blob:` + same-origin). If you need more, inline `marked.min.js` into the widget bundle and reference it as `<script src="marked.min.js"></script>` in path-mode — the CDN path is CSP-blocked but same-bundle JS works.

```js
const html = window.spindrel.renderMarkdown("# Hello\n\nSome **bold** text.");
document.getElementById("out").innerHTML = html;
```

Returns `""` for `null` / `undefined` input.

## When to Use `/widget-actions` vs `spindrel.api()`

| Need | Use |
|---|---|
| Read state (`GET /api/v1/...`) | `spindrel.api()` directly |
| Trigger a tool / mutate through a tool | `spindrel.callTool(name, args)` — returns fresh envelope |
| Patch this pin's `widget_config` | `POST /api/v1/widget-actions` with `dispatch:"widget_config"` |
| Hit one of the whitelisted admin endpoints | Either works; `dispatch:"api"` keeps scopes tight |
| Raw response (blob, stream, binary) | `spindrel.apiFetch()` |
| Read/write a workspace file | `spindrel.readWorkspaceFile` / `writeWorkspaceFile` |

## Scroll Behavior

The iframe auto-sizes to content height, capped at 800px. Taller content scrolls **inside** the iframe (native browser scrollbar). You don't need to wrap anything in your own scroll container. Dynamic content (async fetches, intervals) triggers a re-measure automatically.

## Useful API Endpoints

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
| `POST /api/v1/widget-actions` | **Dispatch a tool / API call / config patch (see above)** |

For the exhaustive list filtered by your scopes, call `list_api_endpoints()`.

## Styling — Use the `sd-*` Vocabulary

Every widget iframe auto-inherits the app's design language: colors, spacing, typography, and component classes. **Use these instead of inline hex colors or bespoke CSS.** Widgets that lean on the vocabulary look like part of the app, stay correct in both light and dark mode, and survive future theme changes.

### CSS variables

Every token from the host theme is available as a CSS variable:

```
--sd-surface              --sd-text           --sd-accent          --sd-success
--sd-surface-raised       --sd-text-muted     --sd-accent-hover    --sd-warning
--sd-surface-overlay      --sd-text-dim       --sd-accent-muted    --sd-danger
--sd-surface-border                           --sd-accent-subtle   --sd-purple
                                              --sd-accent-border
```

Plus subtle/border variants for status colors (`--sd-success-subtle`, `--sd-danger-border`, etc.), overlay tints (`--sd-overlay-light`, `--sd-overlay-border`), spacing (`--sd-gap-xs/sm/md/lg`, `--sd-pad-sm/md/lg`), radii (`--sd-radius-sm/md/lg`), and typography (`--sd-font-sans`, `--sd-font-mono`, `--sd-font-size`).

```css
.my-chart-bar { fill: var(--sd-accent); }
.my-error    { color: var(--sd-danger); }
```

### Utility / component classes

Prefer these over hand-rolled CSS:

| Purpose | Class |
|---|---|
| Vertical layout | `sd-stack`, `sd-stack-sm`, `sd-stack-lg` |
| Horizontal layout | `sd-hstack`, `sd-hstack-sm`, `sd-hstack-between` |
| Responsive auto-fit grid | `sd-grid`, `sd-grid-2`, `sd-tiles` (smaller tiles) |
| Card surface | `sd-card`, `sd-card-header`, `sd-card-body`, `sd-card-actions` |
| Framed media region | `sd-frame`, `sd-frame-overlay` (centered status text) |
| Bordered tile | `sd-tile` |
| Text | `sd-title`, `sd-subtitle`, `sd-meta`, `sd-muted`, `sd-dim`, `sd-mono` |
| Button | `sd-btn`, `sd-btn-primary`, `sd-btn-subtle`, `sd-btn-danger` |
| Form controls | `sd-input`, `sd-select`, `sd-textarea` |
| Status chip | `sd-chip`, `sd-chip-accent/success/warning/danger/purple` |
| Progress bar | `sd-progress` (+ `style="--p: 60"` for 60%) + color variants |
| Feedback | `sd-error`, `sd-empty`, `sd-skeleton`, `sd-spinner`, `sd-divider` |

Toggle buttons work via `aria-pressed="true"` — the base `.sd-btn` handles the pressed styling:

```html
<div class="sd-card">
  <header class="sd-card-header">
    <h3 class="sd-title">Driveway</h3>
    <span class="sd-meta">Updated 30s ago</span>
  </header>
  <div class="sd-frame"><img src="…" /></div>
  <div class="sd-card-actions">
    <button class="sd-btn" aria-pressed="true">Bounding boxes</button>
    <button class="sd-btn sd-btn-primary">Refresh</button>
  </div>
</div>
```

### `window.spindrel.theme` (for SVG / canvas widgets)

When you're drawing programmatically — SVG chart fills, canvas strokes — use `window.spindrel.theme` instead of hard-coded hex:

```js
const accent = window.spindrel.theme.accent;
const isDark = window.spindrel.theme.isDark;
svg.innerHTML = `<rect fill="${accent}" .../>`;
```

Available keys: `isDark`, `surface`, `surfaceRaised`, `surfaceOverlay`, `surfaceBorder`, `text`, `textMuted`, `textDim`, `accent`, `accentHover`, `accentMuted`, `success`, `warning`, `danger`, `purple`.

### Dark mode

The iframe receives `<html class="dark">` when the app is in dark mode. CSS variables adjust automatically — you usually don't need to branch. For JS that needs to decide (e.g., chart background), check `window.spindrel.theme.isDark`.

### Do / Don't

| Don't | Do | Why |
|---|---|---|
| `style="color: #1f2937; background: #f9fafb"` | `style="color: var(--sd-text); background: var(--sd-surface-raised)"` or `class="sd-card"` | Hex colors drift from the app theme and break dark mode silently. |
| `style="font-family: sans-serif"` | Inherit body default (`var(--sd-font-sans)`) | The theme already sets a system font matching the app. |
| Custom card component from scratch | `class="sd-card"` + `sd-card-header` + `sd-card-body` | Consistency across widgets. |
| `<button style="padding: 3px 8px; border: 1px solid #e5e7eb; ...">` | `<button class="sd-btn">` | Fewer lines, on-brand, dark-mode correct. |
| `border-bottom: 1px solid #e5e7eb` between bars | Spacing + `sd-card` separation | Gratuitous borders look like low-polish admin chrome. |
| Hard-coded success green (`#16a34a`) | `class="sd-chip-success"` or `var(--sd-success)` | Same color in one place; updates ripple. |

## Layout & Sizing

- The iframe auto-resizes to content height (up to 800px). Taller content scrolls inside the iframe.
- Cards fill available width on the dashboard grid. Let the user resize from the dashboard; don't set fixed widths.
- The theme stylesheet handles reset (box-sizing, margin/padding), scrollbar styling, table borders, code blocks, links. You rarely need a `<style>` block — reach for `sd-*` classes and `var(--sd-*)` first.

## Display Label

Always set `display_label` — it appears on the dashboard card header, in the "Updated Xm ago" chip, and in the pinned-widget context block you get on future turns. Without it the card shows generic text.

## Remember What You Built

Widgets disappear from your attention once they're pinned. A future turn might be the first time in a week you're aware of the dashboard — and without breadcrumbs, you'll rebuild things that already exist, or forget design decisions that will bite you.

Frontmatter inside the `.html` is the first breadcrumb — it's what the catalog shows and what a future you sees when scanning `data/widgets/` listings. The reference file below is the second. Write both.

**Required after every new widget you ship:**

### 1. Add an index entry to `memory/MEMORY.md`

Under a `## Widgets I've built` section (create it if missing), add one line:

```markdown
## Widgets I've built
- **Project status** — `/workspace/channels/<cid>/data/widgets/project-status/` — live phase tracker with RMW state.json. Notes: `memory/reference/project-status.md`.
- **Home control** — `/workspace/channels/<cid>/data/widgets/home-control/` — one-click scenes + device toggles via `callTool("HassTurnOn", ...)`. Notes: `memory/reference/home-control.md`.
```

Format: `**<display_label>** — <absolute bundle path> — <one-line what it does>. Notes: <reference file>.`

### 2. Create `memory/reference/<widget-slug>.md` with the widget's design memory

Template:

```markdown
# <display_label>

**Path**: `/workspace/channels/<cid>/data/widgets/<slug>/`
**Pinned**: <yes/no + dashboard location>
**Shipped**: <YYYY-MM-DD>

## What it does
One-paragraph summary.

## Data sources
- Tools it calls (via `spindrel.callTool`)
- Endpoints it reads (via `spindrel.api`)
- Files it reads/writes (`./state.json`, `./data.json`, etc.)

## State shape
If the widget uses `state.json`, paste the schema here with field semantics.

## Design decisions
- Why RMW over `state_poll`? (or vice versa)
- Why this archetype and not another?
- Chrome/density choices

## Known rough edges / TODO
- …
```

### Why this matters

- The user's next turn may say *"the project-status widget is showing the wrong phase"* — without the index, you waste tool calls hunting for the file. With the index, you land on it in one step.
- Design decisions ("I chose RMW because two copies of the widget can be open") evaporate between sessions if they're not written down. The `reference/` file is where they live.
- When multiple widgets interact (control panel dispatches `run_backup`, which writes `state.json`, which project-status reads), the `reference/` files are the only place that mapping lives coherently.

**Rule of thumb**: if you created the widget in this turn, you haven't finished shipping it until both files exist.

## SDK framework — Phase A helpers (2026-04-19)

Widgets used to re-implement forms, tables, caches, and toast notifications from scratch. The bootstrap now ships a small framework so you don't.

**Scope.** Pure client-side. No new backend calls, no schema changes. Works in every existing widget the moment the iframe loads. Phase B adds the backend half (`spindrel.db`, `widget.py` handlers, cron, SSE streams); Phase C makes widgets the presentation layer of integrations. See the `Track - Widget SDK` for the full arc.

### Bus — talk to peer widgets on the same dashboard

```js
// Control panel widget publishes after a successful action
window.spindrel.bus.publish("items_changed", { id: 42 });

// Feed widget listens and re-fetches
const off = window.spindrel.bus.subscribe("items_changed", () => reloadFeed());
// call off() from teardown; iframe unload also cleans up
```

Scope is **channel-scoped** right now — both widgets must be pinned on the same channel dashboard (or in the same channel chat) to see each other. User-dashboard pubsub lands when the dashboard slug threads through the iframe (Phase B). Falls back silently on browsers without `BroadcastChannel`.

### Cache — TTL + inflight dedup

```js
// Called by 3 widgets on page load; only one actual fetch fires
const forecast = await window.spindrel.cache.get(
  "weather:philly",
  5 * 60_000,                                    // 5 min TTL
  () => window.spindrel.callTool("get_weather", { location: "philly" }),
);
```

`get()` returns the cached value if fresh, shares an inflight promise across concurrent callers, and re-fetches on expiry. On fetcher error, the cache entry is cleared so the next call retries instead of sticking on the error.

### Notify — surface status as a toast

```js
try {
  await window.spindrel.callTool("run_backup", {});
  window.spindrel.notify("success", "Backup started.");
} catch (e) {
  window.spindrel.notify("error", e.message);
}
```

Renders as a toast banner in the widget chrome (not inside your widget DOM — stays out of your layout). Auto-dismisses after 4s; user can click to dismiss early. Four levels: `info` / `success` / `warn` / `error` with the matching semantic token colors.

### Log — buffered, host-forwarded

```js
window.spindrel.log.info("fetched", data.length, "items");
window.spindrel.log.error("parse failed:", err);
```

Writes to an in-iframe ring buffer (last 200 entries, inspectable via `log.buffer()`) AND posts each entry to the host, where the Dev Panel's **Widgets → Dev → Recent → "Widget log"** subtab renders them in a filterable, per-pin-attributed list (newest first, level filter, click to expand). Host-side ring buffer caps at 500 entries. Use instead of `console.log` when you want the messages visible to anyone editing the widget without opening browser devtools — and when you want to trace a log line back to one concrete pin.

### ui.status + ui.table — skip the CSS

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

### ui.chart — sparkline / line / bar / area

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

**Not in Phase A**: tooltips on hover, axes beyond min/max ticks, multi-series overlays, colour palettes for categorical bars. If you need those, inline a tiny third-party lib or wait for Phase B — the goal here is "sparkline under a stat card", not Grafana.

### state — versioned `data.load` with schema migrations

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

**Concurrency caveat.** The per-path mutex covers one iframe. Two widgets in different iframes (or two tabs on the same dashboard) sharing the same `data/widgets/<slug>/state.json` inherit the same RMW race as `spindrel.data.patch` — last write wins. If this matters, write small and scope each widget's state to its own path (common) or wait for Phase B's `spindrel.db` (backend-serialized).

**Not in Phase A.** Multi-step migration chains (`{from: 1, to: 3}`), down-migrations, transactional rollback of a failed migration, cross-bundle state sharing. If a migration throws mid-way, the disk file keeps its old version; next load retries the same step.

### form — declarative, validated, sd-* styled

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

### Error boundary — no more silent crashes

Uncaught iframe errors and unhandled promise rejections now surface a red banner above the widget with a **Reload** button. Users can recover from a widget crash without refreshing the page; the Reload button remounts the iframe (state inside the iframe is lost, state in `state.json` / `widget_config` survives).

### `spindrel.stream(kinds, filter?, cb)` — live channel events (Phase A.2b)

Subscribes the widget to the channel's event bus over SSE. Use this for
anything that wants to react to activity in the channel without polling —
new messages, turn start / end, context-budget ticks, tool activity, etc.

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

- `cb` receives the wire event `{kind, channel_id, seq, ts, payload}` — the
  same shape the web UI gets. Each `ChannelEventKind` has its own payload
  schema (see `app/domain/payloads.py`).
- Kind strings are validated client-side; typos throw immediately.
- Auto-reconnects on network drops with exponential backoff; the last seen
  `seq` is passed as `since=` so the replay ring fills the gap.
- On `replay_lapsed` the widget gets a host toast ("Stream replay lapsed")
  AND the callback fires so the widget can refetch baseline state.
- On server shutdown the stream closes quietly (no reconnect).

**`spindrel.stream` vs `spindrel.bus`** — `bus` is `BroadcastChannel`,
widget↔widget only, same browser, cross-window only. `stream` is server
SSE — cross-client, includes the bot's own activity, survives page reloads
via replay. Use `bus` for presentation-layer pubsub between pinned copies;
use `stream` for "react to what the agent is doing."

**Reference widget** — `app/tools/local/widgets/context_tracker/index.html`
pins a live context-window gauge driven entirely by
`spindrel.stream([context_budget, turn_started, turn_ended, turn_stream_tool_start], ...)`.

### What's NOT in Phase A

- `spindrel.db` — server SQLite per bundle. Phase B.

## Common Mistakes

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
| `file(create, path="data/widgets/foo/index.html")` + `emit_html_widget(path="data/widgets/foo/index.html")` | Use the same absolute `/workspace/channels/<channel_id>/data/widgets/foo/index.html` for **both** tools | `file`'s relative paths root at the bot workspace; `emit_html_widget`'s relative paths root at the channel workspace. Pass the absolute form to both and the ambiguity goes away. |
| Shipping a widget without updating `memory/MEMORY.md` | Add index entry + `memory/reference/<slug>.md` same turn | Future turns lose the bundle. You'll rebuild or debug blind. |
| Dumping loose `.html` at the workspace root | Put each widget in its own bundle folder | Bundles move/rename/delete atomically; the root stays legible |
| Blind-overwriting `state.json` | Read-merge-write; use `spindrel.state.load` + `state.save` when the bundle's shape might change over time | Two open copies stay coherent; schema_version + migrations make shape changes safe across deploys |
| Skipping `display_label` | Always supply one | Blank headers on the dashboard are ugly + fail the pinned-widget context hint |
| Asking the user to "broaden your admin key" so your widget works | Ask them to broaden YOUR BOT's scopes via admin UI | The widget uses your bot's key, not the user's session. |
| Hand-rolling a form with `<input>` / state tracking / validation / submit-disable | `window.spindrel.form(el, {fields, onSubmit, ...})` | Declarative — validation + error surfaces + submitting state + sd-* styling for free. |
| Hand-rolling a `<table>` + empty-state + loading skeleton | `window.spindrel.ui.status(el, "loading")` + `ui.table(rows, cols)` + `ui.status(el, "empty")` | One-liners that stay on-brand and dark-mode-safe. |
| Inlining Chart.js or hand-writing SVG for a small sparkline | `window.spindrel.ui.chart(el, values, { type: "area", min: 0, max: 1 })` | Native `spindrel.theme.accent`, crisp strokes at any width, no 60 KB JS. See [[#ui.chart — sparkline / line / bar / area]]. |
| Swallowing errors with `try { ... } catch {}` | `catch (e) { window.spindrel.notify("error", e.message); }` | Toasts surface through host chrome above the widget; user sees what failed. |
| `console.log("debug:", x)` | `window.spindrel.log.info("debug:", x)` | Ring-buffered, forwarded to Widgets → Dev → Recent → "Widget log" with per-pin attribution; visible without opening browser devtools. |
| `setInterval(() => fetchShared(), 5000)` in every widget that shares data | One widget fetches + `window.spindrel.bus.publish("X_changed", data)`; peers subscribe | One fetch instead of N; widgets stay in sync without polling races. |
| `setInterval(() => refetchChannelState(), 2000)` to see new messages / turns | `window.spindrel.stream("new_message", cb)` | SSE over the channel event bus — zero poll latency, no wasted round-trips, auto-replays missed events on reconnect. |
| Using `spindrel.bus` to hear what the bot is doing | `spindrel.stream(["turn_started","turn_ended","tool_activity"], cb)` | `bus` is `BroadcastChannel` — widget↔widget only. The agent doesn't post there. `stream` is the backend bus. |

## When NOT to Use This

- Simple text / Markdown reply → just reply normally.
- Entity detail the existing `tool_widgets:` templates already cover → component widget is nicer.
- A link or file the user wants to open → `send_file` or a plain URL.
- Reusable parameterized widget across many channels → defer to the user; the non-channel `/workspace/widgets/<slug>/` root is queued (DX-5b) and not yet resolvable, so the current answer is "emit it per-channel for now".

## Workflow — Build an Evolving Dashboard

When the user says "build me a dashboard for X":

1. **Discover** — `list_api_endpoints(scope="...")` to see what your bot can read/write. Build from what you have, not what you wish you had.
2. **Pick a root** — channel-scoped `data/widgets/<slug>/` (the default, works today). Non-channel roots arrive with DX-5b.
3. **Pick an archetype** — status (RMW `state.json`), feed (poll API), control panel (dispatch tools), KB reader (workspace files + markdown). Most real dashboards mix two.
4. **One-shot the bundle** — `file(create, path="/workspace/channels/<CHANNEL_ID>/data/widgets/<slug>/index.html", content=<full doc>)` plus any `state.json` defaults. Use `sd-*` classes; use `window.spindrel.api()` for every GET; use `spindrel.callTool` for triggering work.
5. **Emit** — `emit_html_widget(path="/workspace/channels/<CHANNEL_ID>/data/widgets/<slug>/index.html", display_label="<Slug>")`. Same absolute path you used to write. User pins it to the dashboard.
6. **Iterate** — tweaks via `file(edit, path="/workspace/channels/<CHANNEL_ID>/data/widgets/<slug>/index.html", find=..., replace=...)`. The pinned widget refreshes within ~3 s. No re-emit needed.
7. **Record it** — leave breadcrumbs in your memory (see "Remember what you built" below) so future-you knows the widget exists and where to find it.

This is the highest-leverage pattern: path mode + a bundle folder + the `file` tool turns "build me a widget" into a live, iteratively-editable surface.

---

## DX Roadmap — What's Coming

These helpers **don't exist yet**. The skill examples above deliberately avoid them so you don't ship widgets that reference APIs that aren't there. Each item below is a scoped proposal that could land in a follow-up session.

### ~~DX-1 — `window.spindrel.renderMarkdown`~~ — shipped

Now live. See the **Markdown Rendering** section above.

### ~~DX-2 — `window.spindrel.callTool`~~ — shipped

Now live. See the **Tool Dispatch** section above. Passes extras through `opts.extra`.

### ~~DX-3 — `window.spindrel.data`~~ — shipped

Now live. See the **`state.json` Pattern** section above. Arrays replaced, not concatenated; first-run safe; throws on invalid JSON. Will be the entry point for DX-5 relative-path resolution when that lands.

### ~~DX-4 — event subscription wrappers~~ — shipped

Now live. See the **Reacting to live updates** section above. `onConfig` debounces on actual config change so it's cheap to call from layout-sensitive code.

### DX-5 — Relative paths + bundled assets + non-channel-scoped root

Shipping in slices.

**~~DX-5a — Relative-path resolution in helpers~~ — shipped**

`window.spindrel.widgetPath` is set to the widget's `source_path` (null for inline). `readWorkspaceFile`, `writeWorkspaceFile`, and `data.*` accept `./foo` and `../foo` and resolve against `dirname(widgetPath)`. `/workspace/...` absolute paths are reserved for DX-5b and currently throw with a clear error. See the **Relative paths** section above.

**DX-5b — Non-channel workspace root** — queued. Adds `{ws_root}/widgets/<slug>/` as a sibling of `channels/`, bot-scoped but channel-agnostic. Extends `emit_html_widget(path=...)` to accept `"/workspace/widgets/<slug>/index.html"` and `"/workspace/channels/<id>/..."` forms. Needs: backend path resolver (`app/services/workspace.py` + `app/tools/local/emit_html_widget.py`), a non-channel-scoped workspace-file endpoint, and extending the `resolvePath` grammar in the iframe bootstrap to accept the absolute forms.

**~~DX-5c — bundled asset loading via `loadAsset`~~ — shipped**

Now live. `window.spindrel.loadAsset(path)` fetches a workspace file with the bot's bearer, blobs it, and returns a `blob:` object URL safe to drop into any `src` attribute. Paired with `revokeAsset(url)` for explicit cleanup. See the **Bundled assets** section above. No CSP changes — object URLs are same-origin by construction.

**DX-5c-full — `<base href>` native asset loading** — queued. The full "just drop `<img src="assets/logo.svg" />` in your HTML and have it work" shape needs either a signed-URL token pattern (bearer in query string), a service worker to inject `Authorization` headers on browser-native loads, or a public no-auth asset endpoint — all three need a security design call. `loadAsset` shipped instead as the pragmatic unlock that doesn't commit us to a security stance.

---

### `widget.yaml` — manifest for backend-capable widgets

A bundle can declare a sibling `widget.yaml` to opt into backend capabilities (server-side SQLite, Python handlers, cron, event subscriptions). For Phase B.0 the manifest is parsed and surfaced in the widget catalog; execution hooks land in later slices.

**Minimal manifest (no backend needed):**

```yaml
name: My Widget
version: 1.0.0
description: What this widget does
```

**Full schema:**

```yaml
name: Project Status          # required; overrides HTML frontmatter name
version: 1.2.0
description: Live phase tracker
permissions:
  tools: [fetch_url]          # tools ctx.tool() may call; enforced at dispatch (B.2+)
  events: [new_message]       # ChannelEventKind values @on_event may subscribe to
cron:
  - name: hourly_refresh
    schedule: "0 * * * *"     # 5-field classic cron only
    handler: hourly_refresh   # function name in widget.py
events:
  - kind: new_message
    handler: on_new_message
db:
  schema_version: 2           # integer >= 1; source of truth
  migrations:
    - from: 1
      to: 2                   # must be from+1; steps must be contiguous starting at 1
      sql: |
        alter table items add column priority integer default 0;
```

**Validation rules enforced at parse time:**
- `name` — required non-empty string
- `permissions.events` — each value must be a valid `ChannelEventKind`
- `cron[].schedule` — must pass `validate_cron()` (5-field, no seconds)
- `db.schema_version` — integer ≥ 1; `migrations` must be contiguous `{from: N, to: N+1}` starting at 1 and ending at `schema_version`
- Tool names in `permissions.tools` are accepted as strings; unknown names surface as 403 at `ctx.tool()` call time (B.2+)

**Catalog badge:** bundles with a valid `widget.yaml` show a "manifest" badge in the HTML Widgets section of the dev panel Library tab.

---

### `window.spindrel.db` — server-side SQLite per bundle

Available only for **path-mode pinned widgets** (those with a `source_path` in their envelope — i.e. pinned from a channel bundle directory, not inline `<p>…</p>` widgets). `dashboardPinId` must be set in the bootstrap; inline widgets throw.

The DB file lives at `<bundle_dir>/data.sqlite` inside the channel workspace. Built-in bundles (under `app/tools/local/widgets/`) redirect to `{workspace_base}/widget_db/builtin/<slug>/data.sqlite` so the Docker read-only layer is never written to. WAL mode is enabled automatically; concurrent writes from different browser tabs are serialised server-side by an asyncio lock keyed on the DB path.

#### API

```js
// Read rows — params optional, returns array of row objects
const rows = await window.spindrel.db.query(sql, params?);

// Write — returns { lastInsertRowid, rowsAffected }
const result = await window.spindrel.db.exec(sql, params?);

// Logical transaction helper — callback receives { query, exec }
const out = await window.spindrel.db.tx(async (tx) => {
  await tx.exec("INSERT INTO items(text) VALUES (?)", ["hello"]);
  return tx.query("SELECT * FROM items");
});
```

All three methods POST to `/api/v1/widget-actions` with `dispatch: "db_query"` / `"db_exec"` using the bot bearer. Errors throw `Error` with the server message.

#### Schema migrations

Declare migrations in `widget.yaml` under `db.migrations`. On first open the server runs any pending steps in order using `PRAGMA user_version` as the authoritative version counter. Downgrades are refused; gaps raise an error at open time (not at widget load), so schema errors surface immediately in the dev panel.

```yaml
db:
  schema_version: 2
  migrations:
    - from: 0
      to: 1
      sql: |
        CREATE TABLE items (
          id    INTEGER PRIMARY KEY AUTOINCREMENT,
          text  TEXT NOT NULL,
          done  INTEGER NOT NULL DEFAULT 0
        );
    - from: 1
      to: 2
      sql: |
        ALTER TABLE items ADD COLUMN priority INTEGER DEFAULT 0;
```

Steps must be contiguous `{from: N, to: N+1}` starting at 0 → 1 and ending at `schema_version`. If no `widget.yaml` exists the DB is opened without migration.

#### Unpin and data cleanup

When a user unpins a widget that has a non-empty `data.sqlite`, the Unpin drawer presents a two-step confirmation: first click reveals a warning banner; second click deletes both the pin row and the DB file (`?delete_bundle_data=true`).

---

### `widget.py` — server-side Python handlers

A bundle can declare a sibling `widget.py` that exposes JS-callable handlers running in the server process under the pin's bot scope.

```python
# <bundle>/widget.py
from spindrel.widget import on_action, ctx

@on_action("save_item")
async def save(args):
    await ctx.db.execute(
        "insert into items(text, created_at) values (?, datetime('now'))",
        [args["text"]],
    )
    return {"ok": True}

@on_action("search")
async def search(args):
    env = await ctx.tool("web_search", query=args["q"])
    return env.get("results", [])[:5]
```

Call from iframe JS via `window.spindrel.callHandler`:

```js
const result = await window.spindrel.callHandler("save_item", { text: "hello" });
```

**Identity and scope.** Each handler invocation resolves the pin's `source_bot_id` and sets `current_bot_id` / `current_channel_id` ContextVars for the duration. `ctx.tool(name, **kwargs)` dispatches through the exact same policy gate as LLM-driven tool calls (`_check_tool_policy`); a bot missing a tool's scope gets a `scope_denied` error surfaced as `{ok: false, error: "scope_denied: ..."}` in the JS response. Handlers cannot elevate beyond the bot's own ceiling.

**Manifest allowlist.** If `widget.yaml` declares `permissions.tools: [...]`, `ctx.tool(name, ...)` refuses any name not in that list — fail-loud, before the policy evaluator even runs. Leave `permissions.tools` empty to allow any tool the bot can already call.

**Timeouts.** Each handler runs under `asyncio.wait_for(..., timeout=30)` by default. Override per-handler with `@on_action("slow", timeout=120)`. Long-running work should schedule a task via `ctx.tool("schedule_task", ...)` instead of blocking.

**Hot reload.** Editing `widget.py` bumps its mtime; the next call re-imports the module — no server restart needed during development.

**`ctx` surface (Phase B.2).**

| Attribute | Purpose |
|---|---|
| `ctx.db.query(sql, params?)` | Returns list of row dicts. Migrations from `widget.yaml` auto-apply on first access. |
| `ctx.db.execute(sql, params?)` | Returns `{lastInsertRowid, rowsAffected}`. Takes the per-path write lock. |
| `await ctx.tool(name, **kwargs)` | Policy-checked tool dispatch under the pin's bot. Result is the parsed JSON envelope. |
| `ctx.bot_id` / `ctx.channel_id` / `ctx.pin` | Read-only accessors for the current invocation. |

#### `@on_cron` — scheduled handlers (Phase B.3)

Declare a schedule in `widget.yaml` and the handler with the matching name in `widget.py`; the server's task scheduler fires the handler under the pin's `source_bot_id` each time `next_fire_at` falls due.

```python
# <bundle>/widget.py
from spindrel.widget import on_cron, ctx

@on_cron("hourly_roll")
async def hourly_roll():
    env = await ctx.tool("fetch_url", url="https://example.com/status")
    await ctx.db.execute("update state set last = ? where id = 1", [env["body"]])
```

```yaml
# <bundle>/widget.yaml
cron:
  - name: hourly_roll
    schedule: "0 * * * *"
    handler: hourly_roll
```

Per-handler timeout defaults to 5 minutes — override with `@on_cron("name", timeout=N)`. The scheduler advances `next_fire_at` BEFORE invoking, so a crashed handler cannot cause a re-fire storm. An invalid cron schedule disables its row (`enabled=False`) without failing the pin write.

#### `@on_event` — channel event subscriptions (Phase B.4)

Subscribe a handler to a channel-event stream. One live `asyncio.Task` per `(pin, kind, handler)` row subscribes to `channel_events.subscribe(pin.source_channel_id)` and fires the handler with the event's serialised payload dict.

```python
# <bundle>/widget.py
from spindrel.widget import on_event, ctx

@on_event("new_message")
async def on_msg(payload):
    await ctx.db.execute(
        "insert into log(ts, body) values (datetime('now'), ?)",
        [payload.get("message", {}).get("content", "")],
    )
```

```yaml
# <bundle>/widget.yaml
permissions:
  events: [new_message]              # ChannelEventKind allowlist — required
events:
  - kind: new_message
    handler: on_msg
```

Key behaviour:

- **Allowlist is fail-loud.** A handler declared for a `kind` not in `permissions.events` persists as `enabled=False` (visible in the DB, no task spawned). Missing from the allowlist ≠ oversight — widgets must declare what they listen to.
- **No replay.** Subscribers use `since=None`; handlers see only events that happen *after* pin creation / lifespan-startup registration. Events published before the server booted are not delivered.
- **Per-handler timeout** defaults to 30 s — override with `@on_event("kind", timeout=N)`. One slow or raising handler cannot stall the subscriber loop; exceptions are logged and the loop keeps listening.
- **Survives restarts.** On server boot, `app/main.py` lifespan iterates every pinned bundle with a manifest and re-registers its event subscribers. Shutdown cancels them cleanly.
- **Envelope update rebinds.** Swapping `source_path` (or the manifest behind it) cancels old subscriber tasks and respawns against the new manifest — no pin delete/recreate needed.

Valid `kind` values are everything in `app.domain.channel_events.ChannelEventKind` (common ones: `new_message`, `turn_started`, `turn_ended`, `tool_activity`, `heartbeat_tick`, `approval_requested`, `message_updated`). The manifest validator rejects unknown kinds at load time.

#### `ctx.notify_reload()` + `spindrel.autoReload` — the reload loop (Phase B.5)

Handlers mutate bundle state (`ctx.db`, `ctx.state`) but the iframe doesn't know it changed. `ctx.notify_reload()` closes the loop: the pin's iframe re-runs whatever render function the widget registered, without a full unmount.

The **preferred DX is `spindrel.autoReload`** — one function that doubles as "initial render" and "reload handler", so mount and reload share one code path:

```html
<!-- <bundle>/index.html -->
<div id="list">Loading…</div>
<script>
  spindrel.autoReload(async () => {
    const rows = await spindrel.db.query("select ts, body from log order by ts desc limit 50");
    document.getElementById("list").innerHTML =
      rows.map(r => `<div>${r.ts} — ${r.body}</div>`).join("");
  });
</script>
```

```python
# <bundle>/widget.py
from spindrel.widget import on_event, ctx

@on_event("new_message")
async def on_msg(payload):
    await ctx.db.execute(
        "insert into log(ts, body) values (datetime('now'), ?)",
        [payload.get("message", {}).get("content", "")],
    )
    await ctx.notify_reload()
```

That's it. Every `new_message` → row inserted → iframe re-queries → DOM updates. No polling, no manual subscription.

If you need more control (e.g. conditionally skip reloads), use the lower-level `spindrel.onReload(cb)` — registers a callback only; you're responsible for the initial render. Returns an `unsubscribe()`.

Key behaviour:

- **Scope is per-pin.** `ctx.notify_reload()` publishes a `widget_reload` event carrying the pin's id; the iframe filters by `pin_id === self.dashboardPinId`. Peer pins of the same bundle on the same channel don't react to each other automatically — use `spindrel.bus.publish()` if you want cross-pin sync.
- **Fire-and-forget.** `ctx.notify_reload()` returns as soon as the event is on the bus. Safe to call from any handler flavor (`@on_action` / `@on_cron` / `@on_event`). Safe to call multiple times — each fires; if you're in a tight loop, debounce manually.
- **Rides existing SSE plumbing.** Widget iframes subscribe to `widget_reload` through the same `spindrel.stream` multiplexer the bus already exposes, so reconnect + replay-on-lapse are free.
- **Inline widgets (no `dashboardPinId`) are a no-op.** `autoReload` still runs once at mount; the subscription is just skipped.
- **Call `notify_reload` AFTER committing your DB work**, not before — otherwise the iframe's re-query races and sees stale data.

Quick-reference placement: `spindrel.onReload` and `spindrel.autoReload` live on `window.spindrel` alongside `stream` / `bus`. `ctx.notify_reload()` lives on the Python `ctx` alongside `ctx.db` / `ctx.tool`.

### Suites — sharing a DB across multiple bundles (Phase B.6)

A **suite** is a group of widget bundles that share a dashboard-scoped SQLite DB. Pin multiple member widgets onto the same dashboard, they see the same data. Pin them on a different dashboard, they see a different (isolated) DB.

When to reach for a suite: two or three widgets that naturally complement each other and want to read/write the same table — Timeline + Kanban + Tasks (the shipped `mission-control` suite), or a Frigate camera wall + an alert feed + an event log. If you've got one widget, use a per-bundle `widget.yaml` `db.schema_version` and keep writing to the bundle-local `data.sqlite`.

**File layout**

```
app/tools/local/widgets/suites/mission-control/
├── suite.yaml                  # suite manifest — name + members + migrations
├── migrations/
│   └── 001_items.sql
└── assets/                     # optional shared assets
    └── tokens.css

app/tools/local/widgets/mc_timeline/
├── widget.yaml                 # db.shared: mission-control
├── widget.py                   # writes to the shared DB via ctx.db
└── index.html                  # reads via spindrel.db
```

**`suite.yaml` shape**

```yaml
name: Mission Control
description: Timeline + Kanban + Tasks sharing one board.
members:
  - mc_timeline
  - mc_kanban
  - mc_tasks
db:
  schema_version: 1
  migrations:
    - from: 0
      to: 1
      sql_file: migrations/001_items.sql   # or inline `sql: "..."` for one-liners
```

**Member `widget.yaml` shape**

```yaml
name: MC Timeline
version: 1.0.0
description: Chronological feed of Mission Control events.
db:
  shared: mission-control    # <-- opts into the suite's DB; schema_version + migrations disallowed here
```

The member's `widget.py` keeps using `ctx.db` — nothing changes at the handler level. Behind the scenes, `resolve_db_path` notices `db.shared` and routes reads/writes to `{workspace}/widget_db/suites/<safe_dashboard_slug>/<suite_id>/data.sqlite`.

**Scope is the dashboard.** Path-safe-slug of the pin's `dashboard_key` is the partition key:

- Pin on a channel dashboard (`channel:<uuid>`) → `widget_db/suites/channel_<uuid>/mission-control/data.sqlite`. Every member pinned on that same channel dashboard shares one DB; every channel gets its own.
- Pin on a global dashboard (e.g. `default`, or any user-created slug) → `widget_db/suites/default/mission-control/data.sqlite`. Global dashboards are visible to everyone with access; the suite inherits the dashboard's permissions.

No bot indirection, no user id plumbing. Two different bots can co-pin members of the same suite on the same dashboard and still collaborate through the shared DB — bot identity shapes *who emits* the widget, not *where the data lives*.

**Pinning a suite atomically**

From a bot, two tools do the job:

```python
# list what's installed
list_suites()
# -> {"suites": [{"suite_id": "mission-control", "name": "Mission Control",
#                 "members": ["mc_timeline", "mc_kanban", "mc_tasks"], ...}]}

# pin every member onto the current channel's dashboard
pin_suite(suite_id="mission-control")

# ...or pin onto a specific dashboard slug
pin_suite(suite_id="mission-control", dashboard_key="default")

# ...or narrow to a subset
pin_suite(suite_id="mission-control", members=["mc_kanban", "mc_tasks"])
```

From the dashboard UI: the Add-widget sheet gains a "Suites" tab (shipping with the Phase B.6 UI slice) that previews the member list and pins them all with one click.

Both paths hit the same endpoint (`POST /api/v1/widgets/dashboard/pins/suite`) which wraps the member `create_pin` calls so a single failure rolls everything back — you never end up with a half-pinned suite.

**Cross-widget interop pattern**

Members that want to react to each other's writes follow the existing reload contract:

1. Handler writes to the shared DB (e.g. `ctx.db.execute("UPDATE items SET column_id = ? WHERE id = ?", ...)`).
2. Handler calls `ctx.notify_reload()` — its own pin re-renders.
3. If another member's widget needs to react, it subscribes to `spindrel.bus` (peer pub/sub on the same channel) and calls its own re-render when the relevant topic fires.

Or more commonly, **write through once and let peers self-serve**: every member's `spindrel.autoReload(loadAndRender)` is already running; if a member's render pulls fresh data on each call, it picks up sibling writes on its next reload. The MC bundle demonstrates this — Kanban's `move_card` handler inserts a `timeline_event` row as a side effect; the Timeline widget's next autoReload pulls it naturally.

**Invariants**

- `db.shared` and `db.migrations` on a bundle are mutually exclusive (the suite owns migrations; mixing races). Manifest validator rejects the combo.
- Suite slugs match `^[a-z0-9][a-z0-9-]{0,47}$`. Same as dashboard slugs, same as most Spindrel identifiers.
- `suite.yaml` migrations are contiguous from version 0 → target `schema_version`. First run of any member on a fresh dashboard runs every pending step; subsequent opens are a no-op (SQLite `PRAGMA user_version`).
- Each member's `source_path` still points at `widgets/<member>/index.html` relative to the workspace — the bundle source tree is unchanged. Suites are a DB-sharing primitive, not a bundling format.

---

*If one of these ships, this skill is updated the same session. Until then: build with the primitives above.*

## See also

- [Widget Dashboards](widget_dashboards.md) — the `describe_dashboard` / `pin_widget` / `move_pins` / `unpin_widget` / `promote_panel` / `demote_panel` tool suite for reading, proposing, and modifying dashboard layouts. `emit_html_widget` shows a widget in chat; `pin_widget` places a library widget on the dashboard.
