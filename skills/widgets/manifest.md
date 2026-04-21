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
```

Even a minimal manifest gets you the "manifest" catalog badge and overrides the HTML frontmatter name/description — worth adding whenever a widget is at-home-on-disk enough to deserve a stable identity.

## Full schema

```yaml
name: Project Status          # required; overrides HTML frontmatter name
version: 1.2.0
description: Live phase tracker
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
    - from: 1
      to: 2                   # must be from+1; steps must be contiguous starting at 1
      sql: |
        alter table items add column priority integer default 0;
```

## Validation rules enforced at parse time

- `name` — required non-empty string
- `permissions.events` — each value must be a valid `ChannelEventKind` (see `app/domain/channel_events.py`)
- `cron[].schedule` — must pass `validate_cron()` (5-field, no seconds)
- `db.schema_version` — integer ≥ 1; `migrations` must be contiguous `{from: N, to: N+1}` starting at 1 and ending at `schema_version`
- Tool names in `permissions.tools` are accepted as strings; unknown names surface as 403 at `ctx.tool()` call time
- `db.shared` and `db.migrations` / `db.schema_version` are **mutually exclusive** at the bundle level — a member of a suite inherits schema from `suite.yaml` and must not redeclare it

A manifest that fails validation refuses to load — the bundle either reverts to "no manifest" (for catalog purposes) or surfaces an error at pin-write time, whichever is safer.

## Catalog badge

Bundles with a valid `widget.yaml` show a "manifest" badge in the HTML Widgets section of the dev panel Library tab. That's your signal at a glance that a bundle has backend-capable behaviour attached.

## Where the manifest lives

```
data/widgets/<slug>/
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
