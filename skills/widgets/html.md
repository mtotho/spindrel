---
name: emit_html_widget — modes, bundles, sandbox, auth
description: Core reference for the `emit_html_widget` tool — inline vs path modes, channel-scoped bundle layout, YAML frontmatter for catalog discoverability, CSP sandbox and `extra_csp`, auth model (widgets run as the emitting bot). Read this first when you have the target shape picked.
triggers: emit_html_widget, preview_widget, inline html widget, path html widget, widget bundle, workspace widget, extra_csp, widget sandbox, widget frontmatter, display_mode panel, widget path grammar, widget dry run
category: core
---

# `emit_html_widget` — modes, bundles, sandbox, auth

## Widget bundles — where to put your files

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
- **Relative paths work inside the bundle** — `./state.json`, `../shared/config.json`, `./assets/logo.svg` resolve against the widget's `index.html` directory inside the iframe. See `widgets/sdk.md#relative-paths`.
- **One folder per widget.** Keep the tree legible; a bundle can then be renamed/moved/deleted atomically.

Discover the current channel id at runtime:

```js
window.spindrel.channelId   // the emitting channel's UUID, or null if unbound
```

If you're building inside an ephemeral widget-dashboard session: you inherit the parent channel's workspace and channel context, so use the parent channel's ID in `/workspace/channels/<parent_channel_id>/data/widgets/<slug>/` with the `file` tool. (Non-channel roots arrive with DX-5b.)

## The two modes

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

## Dry-run first: `preview_widget`

Before you emit a widget to chat (or pin a newly-authored library widget), call **`preview_widget`** with the same arguments you'd pass to `emit_html_widget`. It runs the full resolution + validation path without rendering anything in the conversation — so you see manifest, CSP, path, and library-ref errors in the same turn, without waiting for the user to pin a broken widget and paste back the error.

```
preview_widget(library_ref="bot/my_widget")
→ {"ok": true, "envelope": {...}, "errors": []}

preview_widget(html="<p>x</p>", extra_csp={"script_src": ["'self'"]})
→ {"ok": false, "envelope": null,
   "errors": [{"phase": "csp", "message": "...", "severity": "error"}]}
```

Input shape is identical to `emit_html_widget` (`library_ref` / `html` / `path` plus the same optional `js` / `css` / `display_label` / `display_mode` / `extra_csp`). Output shape is `{ok, envelope?, errors: [{phase, message, severity}]}`:

- `phase` names which layer rejected the input — `input` (mutually-exclusive modes, bad enum), `library_ref` (scope/name resolution), `manifest` (the bundle's `widget.yaml` failed `parse_manifest`), `csp` (an `extra_csp` directive was rejected), or `path` (workspace file not found / non-channel absolute path).
- `envelope` is the exact envelope `emit_html_widget` would have produced — safe to inspect (e.g. to verify `source_library_ref` resolved to the scope you expected) before actually emitting.

Use it proactively when you just authored or edited a bundle via the `file` tool. A two-call loop — `preview_widget` → fix → `emit_html_widget` — costs no user round-trips and catches the common authoring errors (missing `name` in `widget.yaml`, keyword in `extra_csp`, path that escapes the channel workspace) as structured tool output instead of invisible pin failures.

## What the sandbox allows

The widget runs in an iframe with `sandbox="allow-scripts allow-same-origin"` and a tight CSP:

- **Allowed**: inline `<script>` / `<style>`, same-origin `fetch("/api/v1/...")`, `data:` / `blob:` images.
- **Blocked**: cross-origin network (`fetch("https://example.com/...")` will fail), popups, form submissions that navigate, top-level navigation.

If you need external data, have a prior tool call fetch it and inline the JSON into the widget — or trigger `fetch_url` from the widget via the tool dispatcher (see `widgets/tool-dispatch.md`).

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

## Display Label

Always set `display_label` — it appears on the dashboard card header, in the "Updated Xm ago" chip, and in the pinned-widget context block you get on future turns. Without it the card shows generic text.

## Layout & sizing

- The iframe auto-resizes to content height (up to 800px). Taller content scrolls inside the iframe.
- Cards fill available width on the dashboard grid. Let the user resize from the dashboard; don't set fixed widths.
- The theme stylesheet handles reset (box-sizing, margin/padding), scrollbar styling, table borders, code blocks, links. You rarely need a `<style>` block — reach for `sd-*` classes and `var(--sd-*)` first. See `widgets/styling.md`.

## Scroll behavior

The iframe auto-sizes to content height, capped at 800px. Taller content scrolls **inside** the iframe (native browser scrollbar). You don't need to wrap anything in your own scroll container. Dynamic content (async fetches, intervals) triggers a re-measure automatically.

## See also

- `widgets/sdk.md` — the `window.spindrel` API surface (auth, workspace files, tool dispatch, streams, UI helpers)
- `widgets/tool-dispatch.md` — `/api/v1/widget-actions` envelope + `callTool` pattern
- `widgets/dashboards.md` — archetypes, `state.json` pattern, memory convention
- `widgets/styling.md` — `sd-*` vocabulary + theme + dark mode
- `widgets/manifest.md` — `widget.yaml` for backend-capable widgets
- `widgets/errors.md` — widget-not-rendering / 422 / CSP-blocked lookup
