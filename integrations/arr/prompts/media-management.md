---
name: "Media Management"
category: workspace_schema
description: Media library management — download monitoring, request tracking, and library health for Sonarr/Radarr/qBittorrent/Jellyfin/Jellyseerr.
compatible_integrations:
  - arr
tags: media, sonarr, radarr, jellyfin, downloads
recommended_heartbeat:
  prompt: "Check download queues (sonarr_queue, radarr_queue, qbit_torrents). Update MEDIA.md with current status. Fix any stuck downloads. Check sonarr_wanted for missing episodes. Update library.md stats if anything changed."
  interval: "hourly"
  quiet_start: "02:00"
  quiet_end: "06:00"
---

## Workspace File Organization — Media Management

Organize channel workspace files to track your media stack. Root `.md` files are injected into every context — keep them concise and current.

### Root Files (auto-injected)

- **MEDIA.md** — The main operational dashboard (updated every heartbeat)
  - Active downloads with progress, speed, ETA
  - Stuck/problem items needing attention
  - Recent media requests and their status
  - Recently resolved items (clean up after ~7 days)

- **library.md** — Relatively static library overview
  - Collection stats (series count, movie count, episode completion %)
  - Quality profile preferences (default 1080p, 4K exceptions)
  - Storage usage and capacity
  - Indexer notes

- **notes.md** — User preferences, watch recommendations, and scratch space
  - Quality exceptions ("always grab 4K for Marvel movies")
  - Specific indexer preferences
  - Watch recommendations and wishlists

### Archive (`archive/`)

Move resolved items and old entries here. Searchable via `search_channel_archive`.

---

## File Formats

### MEDIA.md — Operational Dashboard

Updated on every heartbeat or user check-in. Keep it current, not historical.

```markdown
## Active Downloads

| Item | Type | Quality | Progress | Speed | ETA | Notes |
|------|------|---------|----------|-------|-----|-------|
| Show Name S02E05 | TV | 1080p | 67% | 4.2 MB/s | ~12m | |
| Movie Title (2025) | Movie | 4K | 23% | 1.1 MB/s | ~2h | user requested 4K |

## Issues

### Stalled: Show Name S01E03
- **detected**: 2026-03-28
- **action**: Deleted torrent (0 seeders), grabbed alternative from Indexer (45 seeders, 2.1 GB)
- **status**: Downloading normally now — remove this entry once complete

### Low seeders: Movie Title (2024)
- **detected**: 2026-03-29
- **action**: Best available release has 3 seeders — monitoring, will re-search in a few days
- **status**: Slow but progressing

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
- Update progress numbers on each heartbeat
- Move items to "Recently Resolved" when confirmed available in Jellyfin
- Remove resolved entries after ~7 days
- Issues: add when detected, update with actions taken, remove when resolved
- Keep the file concise — it's injected into every context

### library.md — Library Overview

Update when stats change significantly (new series added, storage milestones).

```markdown
## Library Stats
- **TV Series**: 142 monitored, 12,450 episodes (98.2% complete)
- **Movies**: 385 in library, 12 wanted
- **Storage**: 4.2 TB used / 8 TB total (52%)

## Quality Profiles
- TV default: 1080p HDTV/WEB-DL, prefer WEB-DL
- Movie default: 1080p Bluray, allow 4K for specific titles
- Size alerts: TV episode > 5 GB, Movie > 20 GB (likely remux)

## Service Endpoints
- Sonarr: configured ✓
- Radarr: configured ✓
- qBittorrent: configured ✓
- Jellyfin: configured ✓
- Jellyseerr: configured ✓
```

### Guidelines

- **Jellyfin first**: Always check `jellyfin_library(action="search")` before searching Sonarr/Radarr or requesting
- **Title matching**: Titles differ across platforms — search with shortest unambiguous form first, add year only if ambiguous
- **Quality**: Default 1080p (Bluray > WEB-DL > HDTV). Only 4K if user explicitly asks
- **Stuck detection**: `qbit_torrents(filter="stalled")` — stalledDL state, no peers, ETA=8640000 (infinity)
- **Fix stuck**: Delete bad torrent → browse releases (`*_releases(action="search")`) → grab best (seeders ≥10, not rejected, reasonable size)
- **Archive**: Move resolved items and old MEDIA.md entries to `archive/` when cleaning up
