-- Mission Control suite schema — v1
-- Three member bundles (mc_timeline, mc_kanban, mc_tasks) share this DB.
-- All write through the unified items table with a kind discriminator.

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,  -- 'timeline_event' | 'kanban_card' | 'task'
    title TEXT NOT NULL,
    body TEXT,
    column_id TEXT,  -- NULL unless kind='kanban_card'
    position INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,  -- meaningful for kind='task'
    due_at TEXT,
    tags TEXT,  -- JSON array string
    source_kind TEXT,  -- provenance hint, e.g. 'tasks→kanban', 'kanban→timeline'
    source_id TEXT,  -- the id of the item that spawned this one, if any
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_items_kind ON items (kind);
CREATE INDEX IF NOT EXISTS ix_items_column ON items (column_id, position);
CREATE INDEX IF NOT EXISTS ix_items_created_at ON items (created_at DESC);

CREATE TABLE IF NOT EXISTS kanban_columns (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_kanban_columns_position ON kanban_columns (position);
