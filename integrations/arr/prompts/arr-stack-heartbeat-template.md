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

## Heartbeat — Media Stack

This defines the maintenance cycle the bot runs on each heartbeat trigger. After this runs, MEDIA.md and status.md reflect ground truth, tracked items have current schedule data, and problems are either auto-resolved, promoted to task cards, or surfaced in the channel.

All notable actions are logged to `timeline.md` via `append_timeline_event`.

### Execution Order

Run phases in order. Each phase can short-circuit (skip) if there's nothing to process.

---

### Phase 1: Service Health Check

**Purpose:** Confirm all services are reachable before doing real work.

1. Ping each service endpoint: Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr
2. Update `status.md` Service Status table with current state + timestamp
3. If any service is unreachable:
   - `append_timeline_event`: `"Service {name} unreachable — skipping dependent phases"`
   - If service was previously healthy → change `status.md` health to `yellow` or `red`
   - Add to MEDIA.md Issues if not already there
   - Skip phases that depend on the downed service, continue with healthy services
4. If a service recovers from a previous outage:
   - `append_timeline_event`: `"Service {name} recovered"`
   - Re-evaluate `status.md` health

---

### Phase 2: Download Check (qBittorrent)

**Purpose:** Detect stuck, stalled, or errored downloads and attempt auto-remediation.

**Requires:** qBittorrent healthy

1. Query qBittorrent for all active torrents
2. For each torrent, classify state:
   - **Healthy**: downloading with seeds, progressing → update MEDIA.md Active Downloads table
   - **Stalled** (0 seeds, no progress >1 hour): flag as issue
   - **Errored** (tracker error, missing files): flag as issue
   - **Completed**: verify import by Sonarr/Radarr (check if still in queue)
3. For stalled/errored items — auto-remediate:
   - Look up media in `data/tracked-shows.json` or `data/tracked-movies.json` using torrent name/hash
   - Delete the stalled torrent in qBittorrent
   - Trigger re-search in Sonarr/Radarr for that item
   - Increment remediation attempt count on the issue
   - `append_timeline_event`: `"Auto-remediation: {title} — deleted stalled torrent, triggered re-search"`
   - Add/update issue in MEDIA.md
4. For completed items not yet imported:
   - Check Sonarr/Radarr import queue for errors (wrong format, sample file, etc.)
   - Log import failures as issues

---

### Phase 3: Arr Stack Check (Sonarr + Radarr)

**Purpose:** Sync tracked media state with what Sonarr/Radarr actually report.

**Requires:** Sonarr and/or Radarr healthy (run whichever is available)

1. **Sonarr — shows:**
   - Query queue for in-progress items → update MEDIA.md Active Downloads
   - Query wanted/missing episodes for all monitored series → cross-reference with `data/tracked-shows.json`
   - For each tracked show with `tracking.status: active`:
     - Update `episodes_of_interest` with current state (grabbed, downloading, imported, missing)
     - If episode was missing and is now imported → mark `available`, update `last_checked`
     - `append_timeline_event`: `"Download complete: {title} {episode}"`
   - Check calendar for upcoming episodes → update `schedule.next_episode` in tracked data

2. **Radarr — movies:**
   - Query queue for in-progress items → update MEDIA.md
   - For each tracked movie with `tracking.status: active`:
     - Check availability state (searched, downloading, available, missing)
     - If newly available → mark in tracked data
     - `append_timeline_event`: `"Download complete: {title}"`
   - Update `last_checked` timestamps

---

### Phase 4: Jellyfin Availability Verification

**Purpose:** Confirm that imported media is actually playable.

**Requires:** Jellyfin healthy

1. For any media that transitioned to "available" in Phase 3:
   - Query Jellyfin library by title/year or stored Jellyfin ID
   - Confirm it exists and is playable (not metadata-only)
   - If present:
     - Update tracked data `ids.jellyfin`
     - Move to MEDIA.md Recently Resolved
     - `append_timeline_event`: `"{title} confirmed available in Jellyfin"`
   - If missing despite Sonarr/Radarr saying imported:
     - Flag as issue (library scan needed, path mismatch, etc.)
     - `append_timeline_event`: `"Jellyfin mismatch: {title} imported but not in library"`
2. Optionally trigger Jellyfin library scan if new content was imported this cycle

---

### Phase 5: Jellyseerr Request Sync

**Purpose:** Keep the Requests table current and auto-track new requests.

**Requires:** Jellyseerr healthy

1. Query Jellyseerr for all pending/processing requests
2. Cross-reference with MEDIA.md Requests table:
   - New requests not in table → add them
   - For each new request: create entry in `data/tracked-shows.json` or `data/tracked-movies.json` if not already tracked
   - `append_timeline_event`: `"Request processed: {title} — added to {Sonarr/Radarr}, monitoring"`
   - Fulfilled requests → move to Recently Resolved
   - Approved but not in Sonarr/Radarr → flag sync issue
3. Update `ids.jellyseerr` in tracked data for newly linked items

---

### Phase 6: Schedule & Air Date Updates

**Purpose:** Keep upcoming episode/release info current using web search.

**Requires:** web_search tool available. Rate limit: max 5 lookups per heartbeat cycle.

1. Scan `data/tracked-shows.json` for entries where `schedule.next_lookup <= now`
2. Prioritize by `next_episode.air_date` proximity (soonest first), cap at 5
3. For each due show:
   - `web_search`: `"{show title}" next episode air date {year}`
   - Parse results for: next episode date, season finale, series end, cancellation/renewal
   - Update `schedule` block: `next_episode`, `season_finale`, `series_end`, `show_status`
   - Set `next_lookup`:
     - **Airing weekly**: day after next episode air date
     - **Between seasons/hiatus**: 2 weeks out
     - **Ended**: null
   - If show cancelled or ended → update `schedule.show_status`, check all episodes available
   - `append_timeline_event`: `"Schedule update: {title} — {change summary}"`
4. Scan `data/tracked-movies.json` for entries where `release.next_lookup <= now`
   - `web_search` for digital/physical release dates if still `searching`
   - Update `release` block, bump `next_lookup`

---

### Phase 7: Issue Promotion Check

**Purpose:** Escalate persistent issues from MEDIA.md to Mission Control task cards.

1. Review all open issues in MEDIA.md
2. For each issue, check promotion criteria:
   - **Time threshold**: issue open >24 hours
   - **Remediation threshold**: auto-remediation failed 2+ times
   - **Manual intervention needed**: issue requires config change, quality profile tweak, or manual grab
3. If criteria met and no existing `task_ref`:
   - Use `create_task_card` to add card to `tasks.md` Backlog:
     - Title: `"Resolve: {media title} — {issue summary}"`
     - Priority: `high` (or `critical` if download is for actively airing show)
     - Tags: `stuck, auto-promoted`
   - Add `promoted: mc-XXXXXX` reference to MEDIA.md issue
   - Add `task_ref: mc-XXXXXX` to tracked data entry
   - `append_timeline_event`: `"Card {mc-id} created (auto-promoted) — {issue summary}"`
4. For existing promoted issues that are now resolved:
   - Use `move_task_card` to move card to Done
   - Remove `promoted` reference from MEDIA.md
   - Clear `task_ref` in tracked data

---

### Phase 8: Workspace File Sync

**Purpose:** Reconcile all workspace files with data gathered above.

1. **MEDIA.md**: Rebuild from current state
   - Active Downloads: from qBit + Sonarr/Radarr queue data
   - Issues: carry forward unresolved, add new, remove resolved
   - Requests: from Jellyseerr sync
   - Recently Resolved: add newly completed, remove entries >7 days old

2. **status.md**: Update MC header block
   - Refresh service status table
   - Update library stats if data available (total series/movies, disk usage)
   - Set `health` based on current state:
     - `green`: all services up, no stuck downloads, no unresolved issues >24h
     - `yellow`: degraded service, active issues in remediation, or disk >80%
     - `red`: service down, multiple stuck items, or disk >90%
   - Update `Current Focus` with upcoming items (next air dates, active investigations)
   - Update `Recent Milestones` with completions from this cycle
   - If health changed → `append_timeline_event`: `"Status health changed: {old} → {new}"`

3. **data/tracked-*.json**: Ensure `last_checked` timestamps are current (already updated in phases above)

4. **Archival**:
   - `timeline.md` entries >30 days → rotate to `archive/{YYYY-MM}/timeline.md`
   - Completed + ended tracked media → move to `data/history.json`, remove from tracked files

---

### Phase 9: Heartbeat Summary

**Purpose:** Decide whether to post to channel and compose summary.

1. Compile heartbeat results:
   - Services checked: N healthy, N degraded, N down
   - Active downloads: N (list any completing soon)
   - Issues: N new, N auto-resolved, N promoted to tasks
   - Requests: N new, N fulfilled
   - Schedule changes: list any (cancellations, date shifts, new seasons)
   - Upcoming in next 48h: list episodes/releases

2. **Post to channel if any of:**
   - New issues detected
   - Issues auto-resolved (brief confirmation)
   - Service went down or recovered
   - Schedule change discovered (cancellation, date shift)
   - Media confirmed available in Jellyfin (user-facing good news)
   - Upcoming episodes in next 48h (heads-up)

3. **Silent heartbeat if:**
   - All services healthy, downloads progressing normally, no changes
   - Only action was updating progress numbers and timestamps
   - Log a minimal timeline entry: `"Heartbeat: {N} active downloads, all healthy"`

---

### Timing Guidelines

| Interval | Phases | Notes |
|----------|--------|-------|
| 15–30 min | 1–4, 8–9 | Download/service health — fast API calls only |
| 1–2 hours | 5 | Jellyseerr sync — request check-in |
| 6–12 hours | 6 | Schedule web searches — avoid excessive lookups |
| Every heartbeat | 7, 8, 9 | Issue promotion, file sync, and summary always run |

A single heartbeat invocation can run all phases, or split into separate schedules with different intervals. Phase 7–9 should always run regardless of interval.

---

### Error Handling

- **Phase isolation**: If a phase fails mid-execution, log the error via `append_timeline_event` and continue to the next phase. A Sonarr timeout shouldn't prevent qBit cleanup.
- **Service escalation**: If the same service fails 3+ consecutive heartbeats, post a message to the channel tagging the user. Set `status.md` health to `red`.
- **Remediation cooldown**: If auto-remediation fails for an item, don't retry for 24 hours. Log the failed attempt and let Phase 7 promote it to a task card.
- **Web search rate limit**: Max 5 schedule lookups per cycle. If more are due, prioritize by air date proximity (soonest first), defer the rest to next cycle.
- **File write safety**: If workspace file write fails, retry once. If still failing, log error and post to channel — don't silently lose state.