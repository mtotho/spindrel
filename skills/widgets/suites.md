---
name: suite.yaml — multi-widget bundles sharing a DB
description: A suite groups widget bundles that share a dashboard-scoped SQLite DB. Covers `suite.yaml`, the `db.shared` member opt-in, dashboard-slug scoping, atomic pinning via `list_suites` / `pin_suite`, and the cross-widget interop pattern.
triggers: suite.yaml, widget suite, shared DB widget, mission-control suite, multi-widget bundle, pin_suite, list_suites, db.shared, dashboard-scoped DB, cross-widget interop
category: core
---

# Suites — sharing a DB across multiple bundles

A **suite** is a group of widget bundles that share a dashboard-scoped SQLite DB. Pin multiple member widgets onto the same dashboard, they see the same data. Pin them on a different dashboard, they see a different (isolated) DB.

When to reach for a suite: two or three widgets that naturally complement each other and want to read/write the same table — Timeline + Kanban + Tasks (the shipped `mission-control` suite), or a Frigate camera wall + an alert feed + an event log. If you've got one widget, use a per-bundle `widget.yaml` `db.schema_version` and keep writing to the bundle-local `data.sqlite` — see `widgets/db.md`.

## File layout

```
app/tools/local/widgets/mission-control/
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

A suite lives **alongside** its member widgets under `app/tools/local/widgets/` (or `integrations/<name>/widgets/`). The `suite.yaml` file identifies a folder as a suite; member widgets stay in their own folders and opt in via `widget.yaml` `db.shared`.

## `suite.yaml` shape

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

## Member `widget.yaml` shape

```yaml
name: MC Timeline
version: 1.0.0
description: Chronological feed of Mission Control events.
db:
  shared: mission-control    # <-- opts into the suite's DB; schema_version + migrations disallowed here
```

The member's `widget.py` keeps using `ctx.db` — nothing changes at the handler level. Behind the scenes, `resolve_db_path` notices `db.shared` and routes reads/writes to `{workspace}/widget_db/suites/<safe_dashboard_slug>/<suite_id>/data.sqlite`.

## Scope is the dashboard

Path-safe-slug of the pin's `dashboard_key` is the partition key:

- Pin on a channel dashboard (`channel:<uuid>`) → `widget_db/suites/channel_<uuid>/mission-control/data.sqlite`. Every member pinned on that same channel dashboard shares one DB; every channel gets its own.
- Pin on a global dashboard (e.g. `default`, or any user-created slug) → `widget_db/suites/default/mission-control/data.sqlite`. Global dashboards are visible to everyone with access; the suite inherits the dashboard's permissions.

**No bot indirection, no user id plumbing.** Two different bots can co-pin members of the same suite on the same dashboard and still collaborate through the shared DB — bot identity shapes *who emits* the widget, not *where the data lives*.

## Pinning a suite atomically

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

From the dashboard UI: the Add-widget sheet's "Suites" tab previews the member list and pins them all with one click.

Both paths hit the same endpoint (`POST /api/v1/widgets/dashboard/pins/suite`) which wraps the member `create_pin` calls so a single failure rolls everything back — you never end up with a half-pinned suite.

## Cross-widget interop pattern

Members that want to react to each other's writes follow the existing reload contract:

1. Handler writes to the shared DB (e.g. `ctx.db.execute("UPDATE items SET column_id = ? WHERE id = ?", ...)`).
2. Handler calls `ctx.notify_reload()` — its own pin re-renders.
3. If another member's widget needs to react, it subscribes to `spindrel.bus` (peer pub/sub on the same channel) and calls its own re-render when the relevant topic fires.

Or more commonly, **write through once and let peers self-serve**: every member's `spindrel.autoReload(loadAndRender)` is already running; if a member's render pulls fresh data on each call, it picks up sibling writes on its next reload. The MC bundle demonstrates this — Kanban's `move_card` handler inserts a `timeline_event` row as a side effect; the Timeline widget's next autoReload pulls it naturally.

## Invariants

- `db.shared` and `db.migrations` on a bundle are mutually exclusive (the suite owns migrations; mixing races). Manifest validator rejects the combo.
- Suite slugs match `^[a-z0-9][a-z0-9-]{0,47}$`. Same as dashboard slugs, same as most Spindrel identifiers.
- `suite.yaml` migrations are contiguous from version 0 → target `schema_version`. First run of any member on a fresh dashboard runs every pending step; subsequent opens are a no-op (SQLite `PRAGMA user_version`).
- Each member's `source_path` still points at `widgets/<member>/index.html` relative to the workspace — the bundle source tree is unchanged. Suites are a DB-sharing primitive, not a bundling format.

## See also

- `widgets/manifest.md` — bundle-level `widget.yaml` with `db.shared`
- `widgets/db.md` — single-bundle SQLite (the non-suite alternative)
- `widgets/handlers.md` — `ctx.db` + `ctx.notify_reload`
- `widgets/sdk.md` — `spindrel.bus` (peer pubsub), `spindrel.autoReload`
