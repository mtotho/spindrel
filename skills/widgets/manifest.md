---
name: widget.yaml manifest — permissions, cron, events, db
description: The `widget.yaml` sibling file that opts a bundle into backend capabilities (server-side SQLite, Python handlers, cron schedules, event subscriptions). Covers the schema, validation rules, and the catalog "manifest" badge.
triggers: widget.yaml, widget manifest, permissions tools, permissions events, cron widget, events allowlist, widget schema_version, widget migrations, manifest badge
category: core
---

# `widget.yaml` — manifest for backend-capable widgets

A bundle can declare a sibling `widget.yaml` to opt into backend capabilities (server-side SQLite, Python handlers, cron, event subscriptions). The manifest is parsed on load, validated, and surfaced in the widget catalog. The execution hooks live in sibling files:

- `widgets/db.md` — `spindrel.db` server-side SQLite
- `widgets/handlers.md` — `widget.py` handlers (`@on_action` / `@on_cron` / `@on_event`)
- `widgets/suites.md` — shared DB across bundles via `db.shared`

## Minimal manifest (no backend needed)

```yaml
name: My Widget
version: 1.0.0
description: What this widget does
panel_title: Home command center
show_panel_title: true
package: home-ops
```

Even a minimal manifest gets you the "manifest" catalog badge and overrides the HTML frontmatter name/description — worth adding whenever a widget is at-home-on-disk enough to deserve a stable identity.

`panel_title` and `show_panel_title` are optional host-chrome metadata. When set, panel surfaces render the title outside the widget body so it stays visible while the widget content scrolls.

Use them when the bundle is intended to read as a named panel across hosts. Skip them when the only title belongs inside the widget body or when `display_label` already handles the generic tile/library label.

## Full schema

```yaml
name: Project Status          # required; overrides HTML frontmatter name
version: 1.2.0
description: Live phase tracker
panel_title: Home command center
show_panel_title: true
suite: project-ops               # optional grouping; use exactly one of suite/package
permissions:
  tools: [fetch_url]          # tools ctx.tool() may call; enforced at dispatch
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
    - from: 0
      to: 1                   # first step always goes from 0 → 1 (fresh DB)
      sql: |
        create table items (id integer primary key, text text);
    - from: 1
      to: 2                   # must be from+1; steps must be contiguous
      sql: |
        alter table items add column priority integer default 0;
layout_hints:
  preferred_zone: grid        # chip | rail | dock | grid (advisory only)
  min_cells: {w: 3, h: 3}
  max_cells: {w: 8, h: 12}
handlers:
  - name: add_item            # must match an @on_action in widget.py
    description: Append a new item.
    triggers: [add item, remember to]
    args:
      text: {type: string, description: Item text., required: true}
    returns:
      type: object
      properties:
        id: {type: string}
    bot_callable: true        # opt-in: surfaces as `widget__<slug>__add_item`
    safety_tier: mutating     # readonly | mutating | exec_capable
```

## Validation rules enforced at parse time

- `name` — required non-empty string
- `permissions.events` — each value must be a valid `ChannelEventKind` (see `app/domain/channel_events.py`)
- `cron[].schedule` — must pass `validate_cron()` (5-field, no seconds)
- `db.schema_version` — integer ≥ 1; `migrations` must be contiguous `{from: N, to: N+1}` starting at 0 (fresh DB) and ending at `schema_version`
- `handlers[].name` — lowercase snake_case, must match an `@on_action` name in `widget.py`
- `handlers[].bot_callable` — defaults to false; when true, the handler must have a non-empty `description`
- `handlers[].safety_tier` — `readonly` / `mutating` / `exec_capable` (default `mutating`)
- `layout_hints.preferred_zone` — one of `chip` / `rail` / `dock` / `grid` (advisory — the dashboard editor never refuses a drop based on this)
- `suite` / `package` — optional slug strings used for library grouping; set at most one of them
- Tool names in `permissions.tools` are accepted as strings; unknown names surface as 403 at `ctx.tool()` call time
- `db.shared` and `db.migrations` / `db.schema_version` are **mutually exclusive** at the bundle level — a member of a suite inherits schema from `suite.yaml` and must not redeclare it

A manifest that fails validation refuses to load — the bundle either reverts to "no manifest" (for catalog purposes) or surfaces an error at pin-write time, whichever is safer.

## Catalog badge

Bundles with a valid `widget.yaml` show a "manifest" badge in the HTML Widgets section of the dev panel Library tab. That's your signal at a glance that a bundle has backend-capable behaviour attached.

## Where the manifest lives

```
widget://bot/<name>/          (or widget://workspace/<name>/, widget://core/<name>/)
├── index.html       # HTML frontmatter (display-only metadata)
├── widget.yaml      # manifest (backend capabilities) — sibling of index.html
├── widget.py        # handlers (if declared in manifest)
├── data.sqlite      # runtime DB file (auto-created on first `spindrel.db` call)
└── migrations/      # optional SQL files referenced via `sql_file:` in manifest
```

The manifest is discovered via the same scanner that walks `.html` bundles — no registration needed. Editing `widget.yaml` bumps its mtime; the next scan picks up the change. Handler re-imports happen per-call (see `widgets/handlers.md#hot-reload`).

## See also

- `widgets/db.md` — how `db.schema_version` + `db.migrations` drive the per-bundle SQLite DB
- `widgets/handlers.md` — how `permissions.tools` + `permissions.events` gate what `widget.py` can do
- `widgets/suites.md` — how `db.shared` opts a bundle into a suite's shared DB
- `widgets/bot-callable-handlers.md` — making `@on_action` handlers invokable from a bot's turn via the `handlers:` block
