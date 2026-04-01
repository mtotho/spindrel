---
name: "Arr Stack Channel Workspace Template"
description: "Download monitoring, request tracking, and library health for Sonarr/Radarr/qBit/Jellyfin. Spindrel Mission Control compatible."
category: workspace_schema
tags:
  - media
  - arr
  - sonarr
  - radarr
  - downloads
  - mission-control
---

## Workspace File Organization — Media Stack

Organize channel workspace files to track your media stack's ongoing state. Root files are living documents injected into every context — keep them concise. Use `data/` for structured persistence and `archive/` for historical records.

This schema is Mission Control compatible. Task tracking, status reporting, and activity logging follow the MC protocol.

### Root Files (auto-injected)

- **MEDIA.md** — Current download and request status (the main dashboard)
  - Active downloads with progress
  - Stuck/problem items needing attention
  - Recent media requests and their status
  - Resolved items (clean up after ~7 days)

- **status.md** — System health and library overview (Mission Control compatible)
  - Phase/health/owner header block
  - Per-service availability status
  - Library stats, disk usage, quality profiles
  - Current focus and blockers

- **tasks.md** — Kanban board for persistent issues and manual work (Mission Control compatible)
  - Promoted issues that survive >24h or >2 failed auto-remediations
  - Manual tasks (quality profile changes, indexer maintenance, bulk operations)
  - Use `create_task_card` and `move_task_card` tools

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: heartbeat actions, downloads completed, issues detected/resolved, requests processed, schedule changes
  - Manual entries via `append_timeline_event`: configuration changes, manual interventions, release sign-offs
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

Create files as needed — start with just MEDIA.md and expand as the channel matures.

### Data Files (`data/`)

Bulk structured data that doesn't need to be in every context. Read on demand during heartbeats and when investigating specific media.

- **data/tracked-shows.json** — Persistent show registry. Every show ever requested or mentioned gets an entry here. This is the canonical "we care about this" list and the primary input for heartbeat cycles.

- **data/tracked-movies.json** — Same as above for movies.

- **data/history.json** — Long-term completion log. When tracked media is fully resolved (series ended + all episodes available, or movie in library), move a summary record here and optionally remove from the tracked file.

### Archive (`archive/`)

Searchable historical records, organized by month:

```
archive/
  2026-03/
    timeline.md       # rotated timeline entries
    resolved.json     # issues resolved that month
    completed.json    # media that became available
  2026-04/
    ...
```

Rotate `timeline.md` entries older than ~30 days into archive. Move resolved issue detail here when cleaning up MEDIA.md.

---

## File Formats

### MEDIA.md — Status Dashboard

Updated on every heartbeat or check-in. Keep it current, not historical.

```markdown
## Active Downloads

| Item | Type | Quality | Progress | Speed | ETA | Notes |
|------|------|---------|----------|-------|-----|-------|
| Show Name S02E05 | TV | 1080p | 67% | 4.2 MB/s | ~12m | |
| Movie Title (2025) | Movie | 4K | 23% | 1.1 MB/s | ~2h | |

## Issues

### Stalled: Show Name S01E03
- **detected**: 2026-03-28
- **action**: Deleted torrent (0 seeders), grabbed alternative from Indexer (45 seeders, 2.1 GB)
- **status**: Downloading normally now — remove this entry once complete

### Low seeders: Movie Title (2024)
- **detected**: 2026-03-29
- **action**: Best available release has 3 seeders — monitoring, will re-search in a few days
- **status**: Slow but progressing
- **promoted**: mc-m3n4o5 (>24h unresolved)

## Requests

| Title | Type | TMDB ID | Status | Requested | Notes |
|-------|------|---------|--------|-----------|-------|
| New Show S01 | TV | 98765 | Processing | 2026-03-28 | Sonarr monitoring |
| Movie Name | Movie | 54321 | Pending approval | 2026-03-29 | |

## Recently Resolved
- 2026-03-27: Show Name S01E02 — was stalled, replaced torrent, now in Jellyfin
- 2026-03-25: Movie Title (2023) — requested and downloaded successfully

*Clean up resolved entries older than 7 days.*
```

**Maintenance rules:**
- Update progress numbers on each heartbeat check
- Move items to "Recently Resolved" when confirmed available in Jellyfin
- Remove resolved entries after ~7 days
- Issues section: add when detected, update with actions taken, remove when resolved
- Issues surviving >24h or >2 failed auto-remediations → promote to `tasks.md` card, add `promoted: mc-XXXXXX` reference
- Keep the file concise — it's injected into context every request

### status.md — System Health (Mission Control Format)

```markdown
- **phase**: Monitoring — Steady State
- **health**: green
- **updated**: 2026-03-28
- **owner**: Media Bot

## Current Focus
- Monitoring 3 active downloads
- Awaiting The Bear S04E01 air date (2026-04-03)

## Blockers
- None currently

## Service Status

| Service | Status | Last Checked |
|---------|--------|-------------|
| Sonarr | Healthy | 2026-03-28 14:00 |
| Radarr | Healthy | 2026-03-28 14:00 |
| qBittorrent | Healthy | 2026-03-28 14:00 |
| Jellyfin | Healthy | 2026-03-28 14:00 |
| Jellyseerr | Healthy | 2026-03-28 14:00 |

## Library Stats
- **TV Series**: 142 monitored, 12,450 episodes (98.2% complete)
- **Movies**: 385 in library, 12 wanted
- **Storage**: 4.2 TB used / 8 TB total (52%)

## Quality Profiles
- TV default: 1080p HDTV/WEB-DL, prefer WEB-DL
- Movie default: 1080p Bluray, allow 4K for specific titles
- Size alerts: TV episode > 5 GB, Movie > 20 GB (likely remux, may want to skip)

## Recent Milestones
- 2026-03-27: Andor S02 fully available in Jellyfin
- 2026-03-20: Migrated to new indexer, search performance improved
```

**Health values:**
- `green` — all services healthy, no stuck downloads, requests processing normally
- `yellow` — degraded service, stalled downloads, or issues in auto-remediation
- `red` — service down, multiple stuck items, or data loss risk (disk >90%)

### tasks.md — Kanban (Mission Control Format)

Only for persistent issues and manual work. Short-lived auto-resolved items stay in MEDIA.md Issues.

```markdown
## Backlog

### Investigate Indexer X reliability
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: indexer, maintenance
- **due**: 2026-04-15

### Upgrade quality profile for Marvel movies to 4K
- **id**: mc-p6q7r8
- **priority**: low
- **tags**: quality, configuration

## In Progress

### Resolve: Movie Title (2024) — no viable release
- **id**: mc-m3n4o5
- **priority**: high
- **tags**: stuck, auto-promoted
- **started**: 2026-03-30

## Done

### Reconfigure Sonarr series path mapping
- **id**: mc-j0k1l2
- **priority**: high
- **completed**: 2026-03-20
```

**Promotion criteria** (MEDIA.md issue → tasks.md card):
- Issue unresolved for >24 hours
- Auto-remediation failed 2+ times for the same item
- Issue requires manual intervention (config change, quality profile tweak, manual grab)

Use `create_task_card` and `move_task_card` tools. Do not manually edit card format.

### timeline.md — Activity Log (Mission Control Format)

Reverse-chronological event stream. New entries go at the top of the current day's section.

```markdown
## 2026-03-28

- 16:30 — Heartbeat: 3 active downloads healthy, 1 issue auto-resolved (Show S01E02 stall → re-grabbed)
- 14:00 — Download complete: Severance S02E07 — confirmed in Jellyfin
- 13:45 — Card mc-m3n4o5 created (auto-promoted) — "Movie Title (2024) no viable release, >24h unresolved"
- 11:00 — Request processed: New Show S01 — added to Sonarr, monitoring
- 10:30 — Schedule update: The Bear S04 premiere confirmed 2026-04-03 (web_search)
- 09:00 — Heartbeat: all services healthy, 2 active downloads, no issues

## 2026-03-27

- 17:00 — Andor S02 fully available — moved to history, tracking complete
- 15:30 — Card mc-j0k1l2 moved to **Done** (was: In Progress) — "Reconfigure Sonarr path mapping"
- 14:00 — Issue detected: Show S01E03 stalled, 0 seeders — auto-deleted, re-searching
- 10:00 — Status health changed: green → yellow (stalled download detected)
```

**Auto-logged events** (by heartbeat and bot actions):
- Heartbeat summaries (active count, issues found/resolved)
- Downloads completed + Jellyfin availability confirmed
- Issues detected and auto-remediation actions
- Requests received and processed
- Schedule updates from web searches
- Task card promotions, moves, completions
- Status health changes
- Service outages detected/resolved

**Manually logged events** (via `append_timeline_event`):
- Configuration changes and rationale
- Manual interventions (force-grabbed a release, deleted problem media)
- Quality profile changes
- Indexer additions/removals

### plans.md — Structured Execution Plans

You can create structured plans for complex goals. Use `draft_plan` when proposing multi-step work — the user reviews and approves in Mission Control before execution begins. Pull the planning skill for the full protocol.

---

## Data File Formats

### data/tracked-shows.json

Persistent registry of all tracked shows. Entry is created when a show is first mentioned in any request. The `schedule` block drives heartbeat lookups.

```json
{
  "severance": {
    "title": "Severance",
    "type": "show",
    "year": 2022,
    "ids": {
      "tmdb": 95396,
      "tvdb": 371980,
      "sonarr": 142,
      "jellyfin": "abc123...",
      "jellyseerr": 87
    },
    "tracking": {
      "status": "active",
      "seasons_monitored": [1, 2],
      "quality_profile": "HD-1080p",
      "added": "2026-01-15"
    },
    "schedule": {
      "show_status": "airing",
      "network": "Apple TV+",
      "air_day": "Friday",
      "next_episode": {
        "id": "S02E08",
        "air_date": "2026-04-04"
      },
      "season_finale": "2026-04-18",
      "series_end": null,
      "next_lookup": "2026-04-04"
    },
    "episodes_of_interest": {
      "S02E07": { "state": "available", "resolved": "2026-03-28" },
      "S02E08": { "state": "awaiting", "air_date": "2026-04-04" }
    },
    "last_checked": "2026-04-01T14:00Z",
    "notes": []
  },
  "breaking-bad": {
    "title": "Breaking Bad",
    "type": "show",
    "year": 2008,
    "ids": {
      "tmdb": 1396,
      "tvdb": 81189,
      "sonarr": 88,
      "jellyfin": "def456...",
      "jellyseerr": null
    },
    "tracking": {
      "status": "active",
      "seasons_monitored": [1, 2, 3, 4, 5],
      "quality_profile": "HD-1080p",
      "added": "2026-03-20"
    },
    "schedule": {
      "show_status": "ended",
      "network": "AMC",
      "air_day": null,
      "next_episode": null,
      "season_finale": null,
      "series_end": "2013-09-29",
      "next_lookup": null
    },
    "episodes_of_interest": {
      "S03E05": { "state": "stalled", "task_ref": "mc-m3n4o5" }
    },
    "last_checked": "2026-04-01T14:00Z",
    "notes": ["S03E05 promoted to task card after 2 failed re-searches"]
  }
}
```

**Key fields:**
- `tracking.status`: `active` | `complete` | `paused` | `ended` — whether we're actively managing this
- `schedule.show_status`: `airing` | `hiatus` | `ended` | `upcoming` — the show's actual broadcast status
- `schedule.next_lookup`: ISO date. Heartbeat checks items where `next_lookup <= now`. Null means no scheduled check (ended shows, completed downloads).
- `episodes_of_interest`: Only episodes the bot is actively managing or that were recently relevant. Not a full series index — Sonarr owns that.
- `ids`: Cross-service mapping so the bot can jump between Sonarr → qBit → Jellyfin without rediscovering entities each time.
- `task_ref`: Link to `tasks.md` card ID if an issue was promoted to MC kanban.

**Lifecycle:**
1. User mentions a show → bot creates entry with `tracking.status: active`, populates IDs by querying services
2. Bot runs web_search to populate `schedule` block (air dates, network, season end)
3. Heartbeat cycles keep `schedule`, `episodes_of_interest`, and `last_checked` current
4. When show is fully available + ended → move summary to `data/history.json`, set `tracking.status: ended`

### data/tracked-movies.json

Same structure, simplified (no episodes/schedule complexity):

```json
{
  "dune-2021": {
    "title": "Dune",
    "type": "movie",
    "year": 2021,
    "ids": {
      "tmdb": 438631,
      "radarr": 55,
      "jellyfin": null,
      "jellyseerr": 92
    },
    "tracking": {
      "status": "active",
      "quality_profile": "HD-1080p",
      "added": "2026-03-29"
    },
    "release": {
      "theatrical": "2021-10-22",
      "digital": "2022-01-12",
      "physical": "2022-01-11",
      "next_lookup": "2026-04-03"
    },
    "task_ref": null,
    "last_checked": "2026-04-01T14:00Z",
    "notes": ["No viable release found yet, Radarr monitoring indexers"]
  }
}
```

### data/history.json

Long-term record of completed media. Append-only:

```json
{
  "completed": [
    {
      "key": "andor",
      "title": "Andor S01-S02",
      "type": "show",
      "completed": "2026-03-31",
      "added": "2025-11-01",
      "notes": "All episodes available in Jellyfin"
    },
    {
      "key": "oppenheimer-2023",
      "title": "Oppenheimer (2023)",
      "type": "movie",
      "completed": "2026-03-15",
      "added": "2026-03-10",
      "notes": "4K Bluray grabbed on first search"
    }
  ]
}
```