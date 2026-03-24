# Heartbeat Quiet Hours — Per-Channel Overnight Suppression

## Summary

Allow per-channel-heartbeat configuration of a daily time window during which the heartbeat is suppressed entirely. Replaces the current global `HEARTBEAT_QUIET_HOURS` env var with database-driven per-heartbeat settings.

## Design Decisions

### 1. Storage — ChannelHeartbeat (not Bot)

**Decision**: Add fields to `ChannelHeartbeat`, not `Bot`.

**Rationale**: Heartbeat scheduling is channel-scoped — `interval_minutes`, `enabled`, `next_run_at` all live on `ChannelHeartbeat`. Quiet hours are a scheduling concern, so they belong alongside the other scheduling fields. This also allows different channels of the same bot to have different quiet windows (e.g., a Slack channel in EST vs a Discord channel in PST).

**New nullable columns on `channel_heartbeats`:**
- `quiet_start` — `TIME` (e.g. 22:00). NULL = no quiet hours.
- `quiet_end` — `TIME` (e.g. 07:00). NULL = no quiet hours.
- `timezone` — `TEXT` (e.g. "America/New_York"). NULL = use global `settings.TIMEZONE`.

Both `quiet_start` and `quiet_end` must be set together (both null or both non-null). Midnight-wrapping ranges supported (e.g. 22:00–07:00).

### 2. Enforcement

Checked in two places (same as current global logic):
- **`fetch_due_heartbeats()`** — After fetching due heartbeats, filter out any whose current local time falls within their quiet window. This prevents task creation entirely.
- **`get_effective_interval()`** — Falls back to per-heartbeat quiet hours. If in quiet window, returns 0 (skip). The global `HEARTBEAT_QUIET_HOURS` still acts as a server-wide override when set.

**Priority**: Per-heartbeat quiet hours take precedence. Global quiet hours apply as a fallback/override for heartbeats without their own config.

### 3. UI

New fields in the Heartbeat tab of channel settings (`ui/app/(app)/channels/[channelId]/settings.tsx`):
- Two `TextInput` fields for quiet start/end (HH:MM format)
- One `SelectInput` dropdown for timezone (common timezones list)
- Grouped in a "Quiet Hours" subsection below the existing heartbeat controls
- Show descriptive text: "During quiet hours, heartbeats are paused entirely."

### 4. Timezone

No per-bot timezone field exists. Rather than adding one to Bot, we add `timezone` directly to `ChannelHeartbeat` — this is the only place it's needed. Falls back to global `settings.TIMEZONE` when null.

### 5. Behavior During Quiet Hours

**Skip entirely** — no task is created. This is the simplest and most predictable behavior. The global `HEARTBEAT_QUIET_INTERVAL_MINUTES` setting continues to work as a server-wide fallback for heartbeats without per-heartbeat config.

### 6. Resume Behavior

When quiet hours end, the heartbeat fires on its next normal poll cycle (within 30 seconds of the worker loop). No immediate catch-up fire — it waits for the next `next_run_at` that falls after the quiet window.

## Implementation

### Migration (059)
```sql
ALTER TABLE channel_heartbeats ADD COLUMN quiet_start TIME;
ALTER TABLE channel_heartbeats ADD COLUMN quiet_end TIME;
ALTER TABLE channel_heartbeats ADD COLUMN timezone TEXT;
```

### Files Changed
1. `migrations/versions/059_heartbeat_quiet_hours.py` — New migration
2. `app/db/models.py` — Add `quiet_start`, `quiet_end`, `timezone` to `ChannelHeartbeat`
3. `app/services/heartbeat.py` — Update `fetch_due_heartbeats` and `get_effective_interval` to use per-heartbeat quiet hours
4. `app/routers/api_v1_admin/channels.py` — Add fields to `HeartbeatUpdate`, `HeartbeatConfigOut` schemas; save in update handler
5. `ui/app/(app)/channels/[channelId]/settings.tsx` — Add quiet hours inputs to HeartbeatTab
6. `tests/unit/test_heartbeat.py` — Add tests for per-heartbeat quiet hours

### Complexity Assessment

**Straightforward** — No complex design tradeoffs. The quiet hours logic already exists (parsing, midnight wrapping, is_quiet_hours check). This is a matter of moving the source of truth from env vars to DB columns and wiring up the UI. Proceeding directly to implementation.
