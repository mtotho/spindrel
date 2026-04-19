---
name: HTML Widgets
description: How to build interactive HTML widgets and bot-authored dashboards with emit_html_widget — inline vs workspace-backed, bundle layout, state.json pattern, tool dispatch via /widget-actions, sd-* design vocabulary, when to pick this over component widgets
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
| Blind-overwriting `state.json` | Read-merge-write | Two open copies stay coherent; no silent data loss |
| Skipping `display_label` | Always supply one | Blank headers on the dashboard are ugly + fail the pinned-widget context hint |
| Asking the user to "broaden your admin key" so your widget works | Ask them to broaden YOUR BOT's scopes via admin UI | The widget uses your bot's key, not the user's session. |

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

*If one of these ships, this skill is updated the same session. Until then: build with the primitives above.*
