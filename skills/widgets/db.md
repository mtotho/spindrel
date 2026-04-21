---
name: spindrel.db — server-side SQLite per bundle
description: Per-bundle server-side SQLite DB accessible from iframe JS (`window.spindrel.db`) and Python handlers (`ctx.db`). Covers the JS API (query/exec/tx), migration contract driven by `widget.yaml`, WAL + per-path write lock, and the unpin data-cleanup flow. Path-mode pinned widgets only.
triggers: spindrel.db, widget SQLite, widget db.query, widget db.exec, widget db.tx, db migration, PRAGMA user_version, widget database, widget data.sqlite, server-side storage
category: core
---

# `window.spindrel.db` — server-side SQLite per bundle

Available only for **path-mode pinned widgets** (those with a `source_path` in their envelope — i.e. pinned from a channel bundle directory, not inline `<p>…</p>` widgets). `dashboardPinId` must be set in the bootstrap; inline widgets throw.

The DB file lives at `<bundle_dir>/data.sqlite` inside the channel workspace. Built-in bundles (under `app/tools/local/widgets/`) redirect to `{workspace_base}/widget_db/builtin/<slug>/data.sqlite` so the Docker read-only layer is never written to. WAL mode is enabled automatically; concurrent writes from different browser tabs are serialised server-side by an asyncio lock keyed on the DB path.

For widgets that share a DB with other bundles, see `widgets/suites.md` (suite-scoped shared DB keyed by dashboard slug).

## API

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

## Schema migrations

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

For lengthier migrations, put the SQL in a separate file and reference it from the manifest:

```yaml
db:
  schema_version: 1
  migrations:
    - from: 0
      to: 1
      sql_file: migrations/001_schema.sql
```

`sql_file:` paths are resolved relative to the bundle root and refuse to traverse outside it.

## Unpin and data cleanup

When a user unpins a widget that has a non-empty `data.sqlite`, the Unpin drawer presents a two-step confirmation: first click reveals a warning banner; second click deletes both the pin row and the DB file (`?delete_bundle_data=true`).

## Concurrency + locking

- **WAL mode** is enabled on every bundle DB — concurrent readers coexist, a single writer takes the per-path lock.
- **Server-side asyncio lock** is keyed on the absolute DB path, so two iframes and a Python handler all serialise through one queue. Deadlock-impossible because the lock is per-path and held only for the life of one `query` / `exec` / `tx` call.
- **Transactions are logical.** `db.tx(fn)` acquires the lock once, runs the callback, then releases. You can't hold a DB handle across multiple `await`s outside `tx` — each `query` / `exec` starts fresh.

## See also

- `widgets/manifest.md` — the `widget.yaml` fields that drive this
- `widgets/handlers.md` — `ctx.db` (Python-side of the same DB)
- `widgets/suites.md` — shared DB across multiple bundles
- `widgets/sdk.md#spindreldata---rmw-json-state` — the JSON-file alternative when SQL is overkill
