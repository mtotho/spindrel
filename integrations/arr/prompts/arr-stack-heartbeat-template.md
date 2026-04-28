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
Call `arr_heartbeat_snapshot()` first. Use its per-service statuses to update `status.md`. If a service is unavailable, log it, add to MEDIA.md Issues, skip dependent phases. If recovered, log recovery. Do not replace this with serial Sonarr/Radarr/qBit/Jellyfin/Jellyseerr health checks unless the snapshot itself needs focused diagnosis.

## Phase 2: Download Check (requires qBittorrent)
Use the qBittorrent section from `arr_heartbeat_snapshot` as the baseline. Query active torrents only if the snapshot shows an issue or does not include enough rows. Classify each: healthy (progressing) → update MEDIA.md downloads; stalled (0 seeds, >1hr) or errored → auto-remediate (delete torrent, re-search in Sonarr/Radarr, log). Check completed items for import failures.

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

**Rules for this phase — read these literally, they prevent data loss:**

- **Never rebuild `data/tracked-shows.json` or `data/tracked-movies.json` from scratch.** If you construct a fresh JSON containing only the entries you touched this cycle and write it over the file, every show you didn't mention disappears. Use `file(operation="json_patch", path="data/tracked-shows.json", patch=[...])` to touch only the keys you intend to change. Same for `tracked-movies.json`.
- Updating a show's `last_checked` or `schedule.next_lookup`: `[{"op": "replace", "path": "/<show-slug>/last_checked", "value": "<ISO timestamp>"}]`.
- Adding a new show: `[{"op": "add", "path": "/<new-slug>", "value": {...}}]`.
- Removing a show (rare — only when the user explicitly resolves/drops it): `[{"op": "remove", "path": "/<slug>"}]`.
- If the JSON itself is malformed (a prior run left literal `\n` escape sequences in the file, say), fix it with `file(operation="overwrite", ...)` AFTER reading the current contents — the read-before-overwrite precondition prevents a shrunken replacement.

**For MEDIA.md and status.md (narrative markdown):**
- Prefer `file(operation="edit", path="MEDIA.md", find="<exact old section>", replace="<new section>")` to update sections in place.
- Only use `file(operation="overwrite", path="MEDIA.md", content=...)` for a deliberate full regeneration, and only after you've just called `file(operation="read", path="MEDIA.md")` — the tool will refuse the overwrite otherwise.

**History:** archive timeline entries >30 days and move completed media to `data/history.json` via `json_patch` add + remove pairs. Do not rewrite `history.json` wholesale.

## Phase 9: Summary
Post to channel if: new issues, auto-resolutions, service changes, schedule changes, media now available, or episodes in next 48h. Stay silent if everything is healthy with no changes — just log `"Heartbeat: {N} active downloads, all healthy"`.
