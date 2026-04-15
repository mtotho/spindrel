---
name: "Arr Stack - Heartbeat"
description: "Periodic maintenance cycle for the media stack bot — checks downloads, resolves issues, updates schedules, and keeps workspace files current."
category: heartbeat
tags:
  - media
  - arr
  - heartbeat
  - maintenance
  - mission-control
---

Execute all 9 phases in order. Skip any phase whose required service is down. Log all notable actions via `append_timeline_event`.

## Phase 1: Service Health Check
Ping Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr. Update `status.md` service table. If a service is down, log it, add to MEDIA.md Issues, skip dependent phases. If recovered, log recovery.

## Phase 2: Download Check (requires qBittorrent)
Query active torrents. Classify each: healthy (progressing) → update MEDIA.md downloads; stalled (0 seeds, >1hr) or errored → auto-remediate (delete torrent, re-search in Sonarr/Radarr, log). Check completed items for import failures.

## Phase 3: Arr Stack Sync (requires Sonarr/Radarr)
**Sonarr**: Check queue, wanted/missing for tracked shows in `data/tracked-shows.json`. Update episode states, log completions, check calendar for upcoming episodes.
**Radarr**: Check queue, update tracked movies in `data/tracked-movies.json`. Log completions, update timestamps.

## Phase 4: Jellyfin Verification (requires Jellyfin)
For media that became "available" in Phase 3: confirm it exists and is playable in Jellyfin. Update tracked data IDs, move to MEDIA.md Recently Resolved. Flag mismatches (imported but not in library).

## Phase 5: Jellyseerr Sync (requires Jellyseerr)
Check pending/processing requests. New requests → add to MEDIA.md + tracked data. Fulfilled → move to Recently Resolved. Flag any approved but not in Sonarr/Radarr.

## Phase 6: Schedule Updates (max 5 web searches)
For tracked shows where `schedule.next_lookup <= now`: web search for next episode dates, cancellations, renewals. Update `schedule` block and `next_lookup`. Same for tracked movies awaiting release.

## Phase 7: Issue Promotion
Review open MEDIA.md issues. Promote to Mission Control task card if: open >24h, or auto-remediation failed 2+ times, or needs manual intervention. Close promoted cards for resolved issues.

## Phase 8: Workspace File Sync
Rebuild MEDIA.md (downloads, issues, requests, recently resolved). Update `status.md` health (green/yellow/red) and stats. Update tracked data timestamps. Archive timeline entries >30 days, move completed media to `data/history.json`.

## Phase 9: Summary
Post to channel if: new issues, auto-resolutions, service changes, schedule changes, media now available, or episodes in next 48h. Stay silent if everything is healthy with no changes — just log `"Heartbeat: {N} active downloads, all healthy"`.
