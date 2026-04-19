---
name: HTML Widgets
description: How to build interactive HTML widgets with emit_html_widget — inline vs workspace-backed, same-origin API access, when to pick this over component widgets
triggers: emit_html_widget, html widget, interactive widget, custom widget, build a widget, chart widget, mini dashboard, render html, iframe widget, workspace html, live dashboard, bespoke ui
category: core
---

# HTML Widgets — `emit_html_widget` Tool Guide

When the user asks for something you can't render with the standard component widgets — a chart, a custom layout, a mini-dashboard, a scraped page distilled into a card, an interactive control — emit an HTML widget. You write the HTML (and optionally JavaScript + CSS); it renders inside a sandboxed iframe in the chat bubble. The user can pin the result to their dashboard.

Unlike any string you might return as Markdown, an HTML widget can:

- Run JavaScript (fetch app data, handle clicks, update itself)
- Call the app's own API at `/api/v1/...` (same-origin — auth comes along for free)
- Re-render automatically when a workspace file changes (path mode)

## When to Use Which Widget

| Situation | Use |
|---|---|
| Entity detail, toggle, or status card that fits the component grammar | Component widgets (YAML template) |
| Chart, table, free-form layout, or anything not in the grammar | `emit_html_widget` |
| User says "make me a custom widget for X" | `emit_html_widget` |
| User says "show me X live / as a dashboard" | `emit_html_widget` (usually path mode) |
| One-off inline result | Normal text/Markdown reply (no widget needed) |

Default to component widgets when a template exists; reach for HTML when the component grammar doesn't cover it.

## The Two Modes

| Mode | Signature | When | Auto-updates |
|---|---|---|---|
| **Inline** | `emit_html_widget(html=..., js?, css?, display_label?)` | One-off snapshot. You assemble the widget from data you already have. | No — static snapshot |
| **Path** | `emit_html_widget(path="dashboards/foo.html", display_label?)` | You wrote (or will iterate on) a workspace file. The widget re-renders when the file changes. | Yes — polls the file every 3 s |

Exactly one of `html` / `path` is required.

### Inline Example

```
emit_html_widget(
  html='''
  <h3 style="margin:0 0 8px">Channels</h3>
  <ul id="list"><li>loading…</li></ul>
  <button id="refresh">Refresh</button>
  ''',
  js='''
  async function load() {
    const r = await fetch("/api/v1/channels");
    const data = await r.json();
    const ul = document.getElementById("list");
    ul.innerHTML = data.map(c => `<li>${c.name}</li>`).join("");
  }
  document.getElementById("refresh").addEventListener("click", load);
  load();
  ''',
  display_label="Channels"
)
```

### Path Example (recommended for dashboards the user will tweak)

```
1. file(create, path="dashboards/server-stats.html", content="<html>… full doc …</html>")
2. emit_html_widget(path="dashboards/server-stats.html", display_label="Server stats")
```

After pinning, further edits to `dashboards/server-stats.html` make the pinned widget refresh within ~3 seconds. Iterate on the file; no need to re-emit.

## What the Sandbox Allows

The widget runs in an iframe with `sandbox="allow-scripts allow-same-origin"` and a tight CSP:

- **Allowed**: inline `<script>` / `<style>`, same-origin `fetch("/api/v1/...")`, `data:` / `blob:` images.
- **Blocked**: cross-origin network (`fetch("https://example.com/...")` will fail), popups, form submissions that navigate, top-level navigation.

If you need external data, have a prior tool call fetch it and inline the JSON into the widget.

## Auth — widgets run as YOU (the bot), not as the viewer

When you emit a widget, the envelope captures your bot id. At render time the host mints a **short-lived (15 min) bearer token scoped to your bot's API key** and injects it into `window.spindrel.api()`. Consequences:

- **Use `window.spindrel.api(path)`**, not raw `fetch(path)`. Only `api()` attaches the bearer — a bare `fetch` will come back 422 (missing Authorization header) or 401.
- **Your bot's scopes are the ceiling.** If your bot's API key doesn't have `channels:read`, your widget can't call channel endpoints. Ask the user to broaden scopes via the admin UI; don't try to work around it.
- **You inherit nothing from the viewing user.** An admin looking at your widget does NOT lend you their admin scopes. Designed that way — this is how bot-authored JS is prevented from issuing privileged calls in someone else's session.
- **The widget chrome shows `@your-bot-name`** in the bottom-left of the rendered card. That's the user's cue that your widget is acting with your credentials.

If your bot has no API key configured, the widget renders but `api()` calls will surface a clear "Widget auth failed" banner — the user needs to provision a key before the widget works.

## The `window.spindrel` Helper

Every widget gets a small helper injected automatically. No imports, no setup:

```js
window.spindrel.channelId                  // emitting channel UUID, or null
window.spindrel.botId                      // your bot id (the one running this)
window.spindrel.botName                    // display name, e.g. "crumb"
window.spindrel.api(path, options?)        // authed fetch → parsed body (JSON/text), throws on !ok
window.spindrel.apiFetch(path, options?)   // authed fetch → raw Response (for blobs, streams, binary)
window.spindrel.toolResult                 // only set for declarative html_template widgets
window.spindrel.readWorkspaceFile(path)    // returns file content as a string
window.spindrel.writeWorkspaceFile(path, content)   // PUT
window.spindrel.listWorkspaceFiles({include_archive?, include_data?, data_prefix?})
```

`api(path, options)` is a thin `fetch` wrapper — attaches `Authorization: Bearer <short-lived bot token>`, sets `Content-Type: application/json`, parses JSON responses, and throws on non-2xx so you can `try/catch`. **Always use this or `apiFetch` instead of raw `fetch()`**; raw fetch won't be authenticated.

`apiFetch(path, options)` is the same auth but returns the raw `Response` object. Reach for it when you need a blob (images, video, downloads), headers, or streaming — anywhere `api()`'s auto-parsing gets in the way:

```js
const r = await window.spindrel.apiFetch("/api/v1/attachments/" + id,
  { headers: { Accept: "image/*" } });
if (!r.ok) throw new Error("HTTP " + r.status);
img.src = URL.createObjectURL(await r.blob());
```

## Discovering what endpoints your widget can hit

Don't guess URLs or copy examples blindly — **call `list_api_endpoints` BEFORE writing the widget** and use the result as your ground truth. It returns only the endpoints your bot's scoped API key can hit, so you never paste in a call that will 403 inside the iframe.

```
list_api_endpoints(scope="channels")   # → all channel endpoints in your scope
list_api_endpoints(scope="admin")       # → admin endpoints (if you have them)
list_api_endpoints()                    # → everything your bot can touch
```

Then inside the widget, use those exact paths with `window.spindrel.api()`:

```js
// list_api_endpoints told you about GET /api/v1/channels/{channel_id}/state
const state = await window.spindrel.api(
  "/api/v1/channels/" + window.spindrel.channelId + "/state"
);
```

The symmetry is intentional: `call_api` (server-side) and `window.spindrel.api` (widget-side) both use the same bot-scoped API key. If `call_api` works from your tool, `spindrel.api` works from the widget — same scopes, same endpoints, same responses.

## JavaScript Cookbook

Concrete patterns that work in the sandbox. Use these directly.

### Read + display a workspace file

```js
async function loadNotes() {
  try {
    const text = await window.spindrel.readWorkspaceFile("notes/today.md");
    document.getElementById("notes").textContent = text;
  } catch (e) {
    document.getElementById("notes").textContent = "Couldn't load: " + e.message;
  }
}
loadNotes();
```

### Write workspace file from a form submit

```js
document.getElementById("save").addEventListener("click", async () => {
  const content = document.getElementById("editor").value;
  await window.spindrel.writeWorkspaceFile("notes/today.md", content);
  document.getElementById("status").textContent = "Saved " + new Date().toLocaleTimeString();
});
```

### Poll recent messages

There is no `GET /channels/{id}/messages`. Use the search endpoint with no
query — it returns the most recent rows in the channel ordered by date:

```js
async function refresh() {
  const cid = window.spindrel.channelId;
  const messages = await window.spindrel.api(
    "/api/v1/channels/" + cid + "/messages/search?limit=20"
  );
  const ul = document.getElementById("messages");
  ul.innerHTML = messages
    .map(m => `<li><b>${m.role}:</b> ${m.content}</li>`)
    .join("");
}
setInterval(refresh, 5000);
refresh();
```

### List tasks + their latest status

The tasks list lives under `/admin/tasks`. Filter by `channel_id` to scope
to the current chat:

```js
async function loadTasks() {
  const cid = window.spindrel.channelId;
  const data = await window.spindrel.api(
    "/api/v1/admin/tasks?channel_id=" + cid + "&limit=20"
  );
  const rows = (data.tasks || []).map(t => `
    <tr>
      <td>${t.prompt?.slice(0, 60) ?? t.id}</td>
      <td>${t.status}</td>
      <td>${t.scheduled_at ?? "—"}</td>
    </tr>
  `).join("");
  document.getElementById("tasks").innerHTML = rows;
}
loadTasks();
```

### Render a chart from a tool result

For charts, inline a library like Chart.js by having a prior `file(create, ...)` write the full page (including a CDN script tag won't work — CSP blocks cross-origin — but you can write the library's source into the workspace and path-mode the widget, OR ship a tiny bespoke SVG renderer in your JS). The simpler path is SVG:

```js
async function drawBar() {
  const data = await window.spindrel.api("/api/v1/admin/tool-calls/recent?limit=20");
  const counts = {};
  for (const tc of data) counts[tc.tool_name] = (counts[tc.tool_name] ?? 0) + 1;
  const max = Math.max(...Object.values(counts), 1);
  const bars = Object.entries(counts).map(([name, n], i) => `
    <rect x="${i*40}" y="${100 - (n/max)*100}" width="30" height="${(n/max)*100}" fill="#58a6ff" />
    <text x="${i*40 + 15}" y="115" text-anchor="middle" font-size="9">${name.slice(0,6)}</text>
  `).join("");
  document.getElementById("chart").innerHTML = `<svg viewBox="0 0 ${Object.keys(counts).length*40} 120" width="100%">${bars}</svg>`;
}
drawBar();
```

### Optimistic update pattern

```js
async function togglePin(id, btn) {
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "…";
  try {
    await window.spindrel.api("/api/v1/widget-pins/" + id, {
      method: "PATCH",
      body: JSON.stringify({ pinned: true }),
    });
    btn.textContent = "Pinned";
  } catch (e) {
    btn.textContent = original;
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}
```

### Handling errors

`api()` throws on non-2xx. Don't swallow — show the error to the user so they know something's wrong:

```js
try {
  const data = await window.spindrel.api("/api/v1/whatever");
  // …
} catch (e) {
  document.getElementById("error").textContent = e.message;
}
```

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

Writes (POST/PUT/PATCH/DELETE) work the same way. Think of it as **your own scoped API key running in a browser tab** — because that's exactly what it is.

For the exhaustive filtered-by-your-scopes list, call `list_api_endpoints()`. That's always more authoritative than this table.

## Styling — Use the `sd-*` Vocabulary

Every widget iframe auto-inherits the app's design language: colors, spacing, typography, and a small set of component classes. **Use these instead of inline hex colors or bespoke CSS.** Widgets that lean on the vocabulary look like part of the app, stay correct in both light and dark mode, and survive future theme changes.

### CSS variables

Every token from the host theme is available as a CSS variable. Reach for these any time you need a color:

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

Prefer these over hand-rolled CSS — they compose the same way Tailwind does and stay consistent across widgets:

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

Toggle buttons work via `aria-pressed="true"` — the base `.sd-btn` handles the pressed styling. Example:

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

When you're drawing programmatically — SVG chart fills, canvas strokes, animated gradients — use `window.spindrel.theme` instead of hard-coded hex:

```js
const accent = window.spindrel.theme.accent;   // resolved hex for the current mode
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

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| Returning HTML as Markdown or a code fence | `emit_html_widget(html=...)` | Only this tool gets you interactivity + pin-to-dashboard |
| `fetch("/api/v1/...")` inside the widget | `window.spindrel.api("/api/v1/...")` | Only `spindrel.api` attaches the bearer. Raw `fetch` → 422 (missing Authorization). |
| `fetch("https://api.example.com/...")` from widget JS | Prior tool call fetches it; inline the data | CSP blocks cross-origin; iframe can only hit same-origin |
| Guessing API paths | `list_api_endpoints()` first, copy the exact path | You only see endpoints your scopes cover. Saves a roundtrip of 403s. |
| Inline hex colors (`#fff`, `#1f2937`, `rgb(59,130,246)`) | `var(--sd-*)` variables or `sd-*` classes | Hex drifts from the theme and breaks dark mode. |
| Hand-rolled `.card { border: 1px solid #e5e7eb; ... }` | `class="sd-card"` | The vocabulary already covers this — on-brand, consistent, dark-mode correct. |
| `html=...` + `path=...` together | Exactly one | Tool errors — pick inline OR path |
| Path mode pointing at a non-existent file | Create the file first with `file(create, ...)` | Tool refuses if the path doesn't resolve |
| `emit_html_widget(html="<script>...</script>")` with no HTML body | Put JS in `js=...`, not inside `html=...` | Cleaner; the tool stitches them correctly |
| Bare style tags in `html` | Use `css=...` | Same — cleaner separation, avoids duplicates |
| Skipping `display_label` | Always supply one | Blank headers on the dashboard are ugly + fail the pinned-widget context hint |
| Asking the user to "broaden your admin key" so your widget works | Ask them to broaden YOUR BOT's scopes via admin UI | The widget uses your bot's key, not the user's session. Scope the bot, not the user. |

## When NOT to Use This

- Simple text / Markdown reply → just reply normally.
- Entity detail the existing `tool_widgets:` templates already cover → component widget is nicer.
- A link or file the user wants to open → `send_file` or a plain URL.
- Reusable parameterized widget across many channels → defer to the user, no library path for HTML templates yet (v1 is ephemeral output).

## Workflow — Build an Evolving Dashboard

When the user says "build me a dashboard for X":

1. **Discover**: `list_api_endpoints(scope="...")` to see what your bot can read/write. Build from what you have, not what you wish you had.
2. **Plan** what panels / what data sources you need. If a data source you want isn't in the endpoint list, ask the user to broaden your bot's scopes (admin UI → Bots → this bot → API permissions) — don't work around it.
3. `file(create, path="dashboards/<slug>.html", content=<full HTML doc>)` — one-shot the first cut. Use `window.spindrel.api()` for every call; hard-code the literal endpoint paths you discovered in step 1.
4. `emit_html_widget(path="dashboards/<slug>.html", display_label="<Slug>")` — renders; user pins it to the dashboard.
5. User asks for tweaks → `file(edit, path="dashboards/<slug>.html", find=..., replace=...)` — the pinned widget updates within a few seconds.
6. Keep iterating on the file. No need to re-emit the widget.

This is the highest-leverage pattern: path mode + the `file` tool turns "build me a widget" into a live, iteratively-editable surface for the user.
