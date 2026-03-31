---
name: "Media Operations"
description: "Workspace schema for media stack management — download monitoring, request tracking, library health."
category: workspace_schema
tags:
  - media
  - arr
  - sonarr
  - radarr
  - downloads
---

## Workspace File Organization — Media Operations

Organize channel workspace files to track your media stack's ongoing state. Files are living documents — update them on each heartbeat or interaction, not append-only logs.

- **MEDIA.md** — Current download and request status (the main dashboard)
  - Active downloads with progress
  - Stuck/problem items needing attention
  - Recent media requests and their status
  - Resolved items (clean up after ~7 days)

- **library.md** — Library health and statistics
  - Per-service availability status (which services are configured and healthy)
  - Disk space and library size trends
  - Quality profile notes and preferences
  - Indexer health and performance notes

- **notes.md** — Operational log and decisions
  - Date-stamp entries: `## YYYY-MM-DD`
  - Record manual interventions (deleted torrents, grabbed specific releases, etc.)
  - Configuration changes and their rationale
  - Recurring problems and solutions found

Create files as needed — start with just MEDIA.md and expand as the channel matures. Archive old notes to `archive/` when they're no longer relevant.

### MEDIA.md — Status Dashboard Format

This is the primary file, updated on every heartbeat or check-in. Keep it current, not historical.

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
- Keep the file concise — it's injected into context every request

### library.md — Library Health Format

```markdown
## Service Status

| Service | Status | Last Checked |
|---------|--------|-------------|
| Sonarr | Healthy | 2026-03-28 |
| Radarr | Healthy | 2026-03-28 |
| qBittorrent | Healthy | 2026-03-28 |
| Jellyfin | Healthy | 2026-03-28 |
| Jellyseerr | Healthy | 2026-03-28 |
| Bazarr | Not configured | — |

## Library Stats
- **TV Series**: 142 monitored, 12,450 episodes (98.2% complete)
- **Movies**: 385 in library, 12 wanted
- **Missing subtitles**: 23 episodes, 5 movies

## Quality Notes
- TV default: 1080p HDTV/WEB-DL, prefer WEB-DL
- Movie default: 1080p Bluray, allow 4K for specific titles
- Size alerts: TV episode > 5 GB, Movie > 20 GB (likely remux, may want to skip)

## Known Issues
- Indexer X has been flaky since March — consider removing if it continues
```

### notes.md — Operational Log Format

```markdown
## 2026-03-28

- Deleted 3 stalled torrents for Show S01 — all from same indexer with 0 seeders
- Grabbed alternatives with 30+ seeders, completing normally now
- Approved 2 pending Jellyseerr requests (Movie A, Show B S02)

## 2026-03-25

- Radarr quality profile updated: added 4K as acceptable for specific movies
- Noticed Indexer Y returning mostly rejected results — quality format mismatch
```
