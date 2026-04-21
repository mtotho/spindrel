---
name: Widget dashboard patterns — state.json + archetypes + memory
description: How to build real dashboards that remember — the `state.json` pattern, four archetypes (live status, activity feed, tool control panel, KB reader), and the memory/MEMORY.md convention for leaving breadcrumbs so future turns can find widgets you shipped.
triggers: state.json, widget dashboard, pinned widget, dashboard archetype, live status board, RMW state, widget memory, widget breadcrumbs, dashboard pattern, project status dashboard, control panel widget, activity feed widget
category: core
---

# Widget dashboards — `state.json` pattern + archetypes + memory

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

**Why RMW matters**: if two copies of the widget are open, naive `save(patch)` loses concurrent edits. `patch` reads fresh each time, so two copies stay coherent. This is the same pattern `web_search.html` uses for its `starred[]` list (hand-rolled, pre-`data` helper).

**First-run safety**: the file doesn't have to exist. `load` returns defaults on miss; `patch` creates it.

See `widgets/sdk.md#spindreldata---rmw-json-state` for the full `data` API and `spindrel.state` (versioned variant with schema migrations).

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

Use when: *"what's been going on in this channel"*, *"show me recent X"*, *"live feed of Y"*. Prefer a 5–10 s poll interval; anything faster hammers the bot's rate limits. For zero-poll live updates, use `window.spindrel.stream(...)` instead (see `widgets/sdk.md#spindrelstreamkinds-filter-cb---live-channel-events`).

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

Use when: *"give me one-click access to X"*, *"I want buttons for my common Y"*. Pair with optimistic-update patterns (disable → "…" → show result). See `widgets/tool-dispatch.md` for the full `callTool` contract.

### D. Embedded Knowledge-Base Reader

Read markdown files from the workspace and render them via the bundled renderer:

```js
async function loadNote(path) {
  const md = await window.spindrel.readWorkspaceFile(path);
  document.getElementById("doc").innerHTML = window.spindrel.renderMarkdown(md);
}
```

Pair with a file picker (`listWorkspaceFiles` + a `<select>`) to browse a whole `notes/` folder. Use when: *"let me browse project notes"*, *"show me the README as a dashboard"*, *"embed this doc alongside the live data"*.

## Workflow — Build an Evolving Dashboard

When the user says "build me a dashboard for X":

1. **Discover** — `list_api_endpoints(scope="...")` to see what your bot can read/write. Build from what you have, not what you wish you had.
2. **Pick a root** — channel-scoped `data/widgets/<slug>/` (the default, works today). Non-channel roots arrive with DX-5b.
3. **Pick an archetype** — status (RMW `state.json`), feed (poll API), control panel (dispatch tools), KB reader (workspace files + markdown). Most real dashboards mix two.
4. **One-shot the bundle** — `file(create, path="/workspace/channels/<CHANNEL_ID>/data/widgets/<slug>/index.html", content=<full doc>)` plus any `state.json` defaults. Use `sd-*` classes; use `window.spindrel.api()` for every GET; use `spindrel.callTool` for triggering work.
5. **Emit** — `emit_html_widget(path="/workspace/channels/<CHANNEL_ID>/data/widgets/<slug>/index.html", display_label="<Slug>")`. Same absolute path you used to write. User pins it to the dashboard.
6. **Iterate** — tweaks via `file(edit, path=..., find=..., replace=...)`. The pinned widget refreshes within ~3 s. No re-emit needed.
7. **Record it** — leave breadcrumbs in your memory (see "Remember what you built" below) so future-you knows the widget exists and where to find it.

This is the highest-leverage pattern: path mode + a bundle folder + the `file` tool turns "build me a widget" into a live, iteratively-editable surface.

## Remember what you built

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

## See also

- `widgets/html.md` — bundle layout, `emit_html_widget` path grammar, sandbox
- `widgets/sdk.md` — `spindrel.data`, `spindrel.state`, `spindrel.api`, `spindrel.stream`
- `widgets/tool-dispatch.md` — `callTool` for the control-panel archetype
- `widgets/db.md` — server-side SQLite when JSON isn't enough
