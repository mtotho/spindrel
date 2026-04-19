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

- **Allowed**: inline `<script>` / `<style>`, `fetch("/api/v1/...")` (carries session cookie), `data:` / `blob:` images.
- **Blocked**: cross-origin network (`fetch("https://example.com/...")` will fail), popups, form submissions that navigate, top-level navigation.

If you need external data, have a prior tool call fetch it and inline the JSON into the widget.

## The `window.spindrel` Helper

Every widget gets a small helper injected automatically. No imports, no setup:

```js
window.spindrel.channelId                  // current channel UUID, or null
window.spindrel.api(path, options?)        // fetch any /api/v1/... endpoint, returns parsed body
window.spindrel.readWorkspaceFile(path)    // returns file content as a string
window.spindrel.writeWorkspaceFile(path, content)   // PUT
window.spindrel.listWorkspaceFiles({include_archive?, include_data?, data_prefix?})
```

`api(path, options)` is a thin `fetch` wrapper — it sets `Content-Type: application/json` by default, parses JSON responses, and throws on non-2xx so you can `try/catch`.

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

```js
async function refresh() {
  const cid = window.spindrel.channelId;
  const data = await window.spindrel.api("/api/v1/channels/" + cid + "/messages?limit=20");
  const ul = document.getElementById("messages");
  ul.innerHTML = data.messages
    .map(m => `<li><b>${m.bot_id || "user"}:</b> ${m.content}</li>`)
    .join("");
}
setInterval(refresh, 5000);
refresh();
```

### List tasks + their latest status

```js
async function loadTasks() {
  const tasks = await window.spindrel.api("/api/v1/tasks");
  const rows = tasks.map(t => `
    <tr>
      <td>${t.title}</td>
      <td>${t.status}</td>
      <td>${t.next_run_at ?? "—"}</td>
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
| `GET /api/v1/channels/{id}/messages` | Recent messages |
| `GET /api/v1/channels/{id}/workspace/files` | Workspace file tree |
| `GET /api/v1/channels/{id}/workspace/files/content?path=...` | Read a workspace file |
| `PUT /api/v1/channels/{id}/workspace/files/content?path=...` | Write a workspace file |
| `GET /api/v1/tasks` | Tasks + runs |
| `GET /api/v1/admin/tool-calls/recent` | Recent tool-call envelopes |
| `GET /api/v1/bots/me` | Bot's own config |

Writes (POST/PUT/PATCH/DELETE) work the same way. Think of it as "a browser tab logged in as the user."

## Layout & Sizing

- The iframe auto-resizes to content height (up to 800px). Taller content scrolls inside the iframe.
- Cards fill available width on the dashboard grid. Let the user resize from the dashboard; don't set fixed widths.
- Base stylesheet is minimal (system font, 13px, padded body). Override via `<style>` / `css=`.

## Display Label

Always set `display_label` — it appears on the dashboard card header, in the "Updated Xm ago" chip, and in the pinned-widget context block you get on future turns. Without it the card shows generic text.

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| Returning HTML as Markdown or a code fence | `emit_html_widget(html=...)` | Only this tool gets you interactivity + pin-to-dashboard |
| `fetch("https://api.example.com/...")` from widget JS | Prior tool call fetches it; inline the data | CSP blocks cross-origin; iframe can only hit same-origin |
| `html=...` + `path=...` together | Exactly one | Tool errors — pick inline OR path |
| Path mode pointing at a non-existent file | Create the file first with `file(create, ...)` | Tool refuses if the path doesn't resolve |
| `emit_html_widget(html="<script>...</script>")` with no HTML body | Put JS in `js=...`, not inside `html=...` | Cleaner; the tool stitches them correctly |
| Bare style tags in `html` | Use `css=...` | Same — cleaner separation, avoids duplicates |
| Skipping `display_label` | Always supply one | Blank headers on the dashboard are ugly + fail the pinned-widget context hint |

## When NOT to Use This

- Simple text / Markdown reply → just reply normally.
- Entity detail the existing `tool_widgets:` templates already cover → component widget is nicer.
- A link or file the user wants to open → `send_file` or a plain URL.
- Reusable parameterized widget across many channels → defer to the user, no library path for HTML templates yet (v1 is ephemeral output).

## Workflow — Build an Evolving Dashboard

When the user says "build me a dashboard for X":

1. Plan what panels / what data sources you need.
2. `file(create, path="dashboards/<slug>.html", content=<full HTML doc>)` — one-shot the first cut.
3. `emit_html_widget(path="dashboards/<slug>.html", display_label="<Slug>")` — renders; user pins it to the dashboard.
4. User asks for tweaks → `file(edit, path="dashboards/<slug>.html", find=..., replace=...)` — the pinned widget updates within a few seconds.
5. Keep iterating on the file. No need to re-emit the widget.

This is the highest-leverage pattern: path mode + the `file` tool turns "build me a widget" into a live, iteratively-editable surface for the user.
