# Per-Channel Attachment Retention Configuration

## Overview

Add per-channel controls for attachment retention (auto-purge of `file_data` bytes), max file size, and attachment type filtering. Global defaults in `app/config.py`; channel-level overrides on the `Channel` model. Admin UI section on the channel detail page.

---

## 1. Schema Changes — Channel Model

Add nullable columns to `channels` (NULL = inherit global default):

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `attachment_retention_days` | `Integer`, nullable | NULL (keep forever) | Days to retain `file_data` bytes. After expiry, `file_data` is set to NULL; row + description kept. |
| `attachment_max_size_bytes` | `Integer`, nullable | NULL (no limit) | Reject storing `file_data` for files exceeding this size. Metadata row still created, `file_data` left NULL. |
| `attachment_types_allowed` | `JSONB`, nullable | NULL (all types) | List of types to store bytes for, e.g. `["image", "file"]`. Types not listed get metadata only (no `file_data`). Valid values: `image`, `file`, `text`, `audio`, `video`. |

### Global Defaults (app/config.py)

```python
ATTACHMENT_RETENTION_DAYS: int | None = None          # None = keep forever
ATTACHMENT_MAX_SIZE_BYTES: int | None = None           # None = no limit
ATTACHMENT_TYPES_ALLOWED: list[str] | None = None      # None = all types
ATTACHMENT_RETENTION_SWEEP_INTERVAL_S: int = 3600      # 1 hour between sweeps
```

### Resolution Order

```
channel.attachment_retention_days  ??  settings.ATTACHMENT_RETENTION_DAYS  ??  None (keep forever)
channel.attachment_max_size_bytes  ??  settings.ATTACHMENT_MAX_SIZE_BYTES  ??  None (no limit)
channel.attachment_types_allowed   ??  settings.ATTACHMENT_TYPES_ALLOWED   ??  None (all)
```

Helper in `app/services/attachments.py`:

```python
def get_effective_retention(channel: Channel, settings: Settings) -> dict:
    return {
        "retention_days": channel.attachment_retention_days ?? settings.ATTACHMENT_RETENTION_DAYS,
        "max_size_bytes": channel.attachment_max_size_bytes ?? settings.ATTACHMENT_MAX_SIZE_BYTES,
        "types_allowed": channel.attachment_types_allowed ?? settings.ATTACHMENT_TYPES_ALLOWED,
    }
```

---

## 2. Retention Enforcement Strategy

**Recommendation: Option A — Scheduled sweep only.**

### Rationale

- **Simplicity**: One code path for purging. No hidden latency on reads.
- **Predictability**: Admins know purging happens on a schedule, not randomly on access.
- **Efficiency**: Bulk `UPDATE ... SET file_data = NULL` is far cheaper than per-row checks on every read.
- **No edge cases**: Lazy expiry (Option B) would require modifying every read path (API, tools, agent context assembly) and adds complexity for minimal benefit. The sweep interval (default 1 hour) is frequent enough that "edge cases" are just attachments that survive at most one extra sweep cycle.

### Sweep Implementation

New background worker: `attachment_retention_worker` in `app/services/attachment_retention.py`.

```
Started in app/main.py lifespan alongside heartbeat_worker and task_worker.
Polls every ATTACHMENT_RETENTION_SWEEP_INTERVAL_S (default 3600s).
```

**Sweep query (per cycle):**

```sql
UPDATE attachments a
SET file_data = NULL
FROM channels c
WHERE a.channel_id = c.id
  AND a.file_data IS NOT NULL
  AND (
    -- Channel-level retention
    (c.attachment_retention_days IS NOT NULL
     AND a.created_at < now() - (c.attachment_retention_days || ' days')::interval)
    OR
    -- Global retention (channels with no override)
    (c.attachment_retention_days IS NULL
     AND :global_retention_days IS NOT NULL
     AND a.created_at < now() - (:global_retention_days || ' days')::interval)
  )
```

**What survives purging:**
- The `attachments` row itself (id, filename, mime_type, size_bytes, etc.)
- `description` and `described_at` (cheap text, still useful for agent context)
- `url` (if present — external link still valid)

**What gets purged:**
- `file_data` only — set to NULL

**Logging:** Each sweep logs count of purged attachments per channel for observability.

### Index Addition

Add an index to support efficient sweep queries:

```sql
CREATE INDEX ix_attachments_retention
ON attachments (channel_id, created_at)
WHERE file_data IS NOT NULL;
```

### Max Size Enforcement

Enforced at **write time** in `create_attachment()`:

```python
effective = get_effective_retention(channel, settings)
if effective["max_size_bytes"] and len(file_bytes) > effective["max_size_bytes"]:
    # Still create the attachment row for metadata, but skip storing bytes
    file_data = None
```

### Type Filtering Enforcement

Also at **write time** in `create_attachment()`:

```python
if effective["types_allowed"] and attachment_type not in effective["types_allowed"]:
    file_data = None  # Store metadata only
```

---

## 3. Admin UI Changes

### New Section: "Attachment Settings"

Add as a new collapsible section on the channel detail page, after the existing "Compaction Settings" section. Template: `app/templates/admin/channel_attachments_section.html`.

```
+----------------------------------------------------------+
| Attachment Settings                                       |
+----------------------------------------------------------+
|                                                           |
|  Retention Period                                         |
|  [  30  ] days   [ ] Keep forever                         |
|  (Global default: keep forever)                           |
|                                                           |
|  Max File Size                                            |
|  [  10  ] MB     [ ] No limit                             |
|  (Global default: no limit)                               |
|                                                           |
|  Allowed Attachment Types                                 |
|  [x] Image  [x] File  [x] Text  [ ] Audio  [ ] Video    |
|  (Unchecked types: metadata stored, bytes skipped)        |
|                                                           |
|  ---- Storage Usage ----                                  |
|  Total attachments: 247                                   |
|  With file data:    183                                   |
|  Total stored:      48.2 MB                               |
|  Oldest attachment: 2025-11-03                            |
|                                                           |
|  [Save]                                                   |
+----------------------------------------------------------+
```

### UI Behavior

- "Keep forever" checkbox: when checked, clears the days input and sends `null` for `attachment_retention_days`.
- "No limit" checkbox: when checked, clears the MB input and sends `null` for `attachment_max_size_bytes`.
- Type checkboxes: all checked = sends `null` (no filtering). Partial selection sends the list.
- Storage usage section is read-only, loaded via HTMX from the stats endpoint.
- HTMX POST to `/admin/channels/{channel_id}/attachment-settings` for form submission.
- Show "(Global default: X)" hint text below each field so admins know what they're overriding.

### Admin Route

New route in `app/routers/admin_channels.py`:

```python
@router.post("/channels/{channel_id}/attachment-settings")
async def update_attachment_settings(channel_id: UUID, ...):
    # Parse form, update channel, return updated section partial
```

---

## 4. API Changes

### Update ChannelUpdate Schema

Add to `ChannelUpdate` in `app/schemas/channels.py` (or wherever it lives):

```python
attachment_retention_days: int | None = UNSET
attachment_max_size_bytes: int | None = UNSET
attachment_types_allowed: list[str] | None = UNSET
```

The existing `PUT /api/v1/channels/{channel_id}` endpoint picks these up automatically.

### New Endpoint: Attachment Stats

```
GET /api/v1/channels/{channel_id}/attachment-stats
```

Response:

```json
{
  "channel_id": "uuid",
  "total_count": 247,
  "with_file_data_count": 183,
  "total_size_bytes": 50529280,
  "oldest_created_at": "2025-11-03T14:22:00Z",
  "effective_config": {
    "retention_days": 30,
    "max_size_bytes": 10485760,
    "types_allowed": ["image", "file", "text"]
  }
}
```

**Query:**

```sql
SELECT
  count(*) AS total_count,
  count(*) FILTER (WHERE file_data IS NOT NULL) AS with_file_data_count,
  coalesce(sum(size_bytes) FILTER (WHERE file_data IS NOT NULL), 0) AS total_size_bytes,
  min(created_at) AS oldest_created_at
FROM attachments
WHERE channel_id = :channel_id
```

---

## 5. Migration

**Migration 054: `add_channel_attachment_retention.py`**

```python
def upgrade():
    op.add_column('channels', sa.Column('attachment_retention_days', sa.Integer(), nullable=True))
    op.add_column('channels', sa.Column('attachment_max_size_bytes', sa.Integer(), nullable=True))
    op.add_column('channels', sa.Column('attachment_types_allowed', JSONB(), nullable=True))

    # Partial index for efficient retention sweeps
    op.create_index(
        'ix_attachments_retention',
        'attachments',
        ['channel_id', 'created_at'],
        postgresql_where=text('file_data IS NOT NULL')
    )

def downgrade():
    op.drop_index('ix_attachments_retention')
    op.drop_column('channels', 'attachment_types_allowed')
    op.drop_column('channels', 'attachment_max_size_bytes')
    op.drop_column('channels', 'attachment_retention_days')
```

---

## 6. Files to Create/Modify

| File | Action | What |
|------|--------|------|
| `migrations/versions/054_channel_attachment_retention.py` | Create | Migration adding 3 columns + index |
| `app/db/models.py` | Modify | Add 3 columns to Channel model |
| `app/config.py` | Modify | Add 4 global defaults |
| `app/services/attachment_retention.py` | Create | Sweep worker + `get_effective_retention()` |
| `app/services/attachments.py` | Modify | Enforce max_size and type filtering at write time |
| `app/main.py` | Modify | Start `attachment_retention_worker` in lifespan |
| `app/schemas/channels.py` | Modify | Add fields to ChannelUpdate |
| `app/routers/api_v1_channels.py` | Modify | Add attachment-stats endpoint |
| `app/routers/admin_channels.py` | Modify | Add attachment settings POST route |
| `app/templates/admin/channel_attachments_section.html` | Create | Admin UI section template |
| `app/templates/admin/channel_detail.html` | Modify | Include new section |
| `tests/unit/test_attachment_retention.py` | Create | Tests for sweep logic + config resolution |

---

## 7. Open Questions for Michael

1. **Default retention**: Should we ship with a sensible global default (e.g., 90 days) or default to keep-forever and let admins opt in?

2. **Retroactive purging**: When a channel's retention is first set (e.g., 30 days), should the next sweep immediately purge all attachments older than 30 days, or only start the clock from when the setting was configured? (Plan assumes immediate retroactive purge.)

3. **Orphaned attachments**: Attachments where `channel_id IS NULL` (channel was deleted) — should the sweep also clean these up after some grace period?

4. **Notification on purge**: Should the sweep log a message to the channel (or admin) when it purges attachments, or should it be silent?

5. **Bulk purge safety**: Should we add a "Purge all attachment data now" button to the admin UI, or is the scheduled sweep sufficient?

6. **Bot-level overrides**: The bot model already has attachment config (summarization). Should retention config also be settable per-bot (with resolution: channel -> bot -> global), or is channel-level enough?
