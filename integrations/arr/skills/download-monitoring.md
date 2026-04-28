---
name: Download Monitoring
description: Heartbeat-driven download monitoring, stuck download detection, AI-assisted torrent selection, workspace tracking
---
# SKILL: Download Monitoring (ARR Stack)

## Heartbeat Monitoring Protocol

When running as a periodic heartbeat, follow this sequence:

### 1. Take One Aggregate Snapshot
```
arr_heartbeat_snapshot()
```

Use the snapshot to determine which services are configured, unavailable, or healthy. Do not fan out into individual read tools unless the snapshot shows an issue, missing detail, or a remediation target.

### 2. Check Download Queues
```
sonarr_queue()     → active TV downloads
radarr_queue()     → active movie downloads
qbit_torrents(filter="downloading") → all active torrents
```

Report: total items downloading, overall progress, any issues.

### 3. Detect Stuck Downloads
```
qbit_torrents(filter="stalled") → torrents with no peers/progress
sonarr_queue()                  → check for tracked_status: "warning" (import failures)
radarr_queue()                  → same for movies
```

**qBit states that indicate problems:**

| State | Meaning | Severity |
|-------|---------|----------|
| `stalledDL` | No peers, download can't progress | High — dead torrent, replace it |
| `metaDL` (>10 min) | Magnet link can't resolve metadata | High — tracker down or torrent dead |
| `missingFiles` | Files deleted from disk but torrent active | Critical — need to remove + re-search |
| `error` | Hash check failed or disk I/O error | Critical — corrupt data |
| `stalledUP` | 100% complete but no peers to upload to | Low — may still import fine, check arr queue |
| ETA = `8640000` + speed = 0 | qBit's "infinity" value, zero progress | High — dead torrent |

**Arr queue states that indicate problems:**

| Queue state | Meaning | Action |
|-------------|---------|--------|
| `tracked_status: "warning"` | Import failed — read `errors[]` | Diagnose error, likely blocklist + re-search |
| `status: "completed"` + still in queue | Downloaded but can't import | Read `errors[]` — common: quality rejection, bad format, disk full |
| `status: "delay"` | Waiting for delay profile | Usually fine, just needs time |

**Common import failure patterns in `errors[]`:**
- File extension `.exe`, `.scr`, `.bat`, `.com` → malware/fake release, blocklist immediately
- "Not a Custom Format upgrade" → quality profile rejected, blocklist + search for better match
- "No files found are eligible for import" → wrong content, corrupt, or unparseable
- "Sample" or tiny size (< 100 MB) → grabbed a sample, not the full file
- "Not enough disk space" → disk full, tell user

### 4. Fix Stuck Downloads
For each stuck torrent:
1. **Remove from Sonarr/Radarr queue first** (this is critical):
   - `sonarr_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)` — removes queue entry + torrent + blocklists bad release
   - OR `radarr_queue_manage(...)` for movies
2. **Trigger re-search**: `sonarr_command(action="SeriesSearch", series_id=X)` or `radarr_command(action="MoviesSearch", movie_ids=[X])`
3. Monitor `sonarr_queue()` / `radarr_queue()` for new grab

**Important:** Do NOT just delete from qBittorrent — this leaves a phantom entry in Sonarr/Radarr's queue that blocks new downloads. Always remove via `*_queue_manage` first.

**If the queue is empty but episode is still missing**, use `sonarr_episodes(series_id=X)` to inspect file state, then `sonarr_history(series_id=X)` to see what happened.

**For bad auto-grabs** (import warning, sketchy file, wrong quality):
1. Blocklist via `*_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)`
2. Browse releases manually: `sonarr_episodes(series_id=X, season=N)` → get episode `id` → `sonarr_releases(action="search", episode_id=EP_ID)`
3. Select a release that passes all checks (see AI-Assisted Torrent Selection below)
4. Grab: `*_releases(action="grab", guid="...", indexer_id=N)`

### 5. Check Indexer Health
```
prowlarr_health()       → system warnings (disabled indexers, sync issues)
prowlarr_indexers()     → all indexers with enabled/disabled status and failure info
```

Watch for:
- Indexers with `disabled_till` set — temporarily disabled, will auto-recover
- Indexers with `escalation_level > 3` — failing repeatedly, may need attention
- `enabled: false` — disabled indexer, may be intentional or may need re-enabling
- Health warnings about unavailable indexers or app sync issues

If many indexers are disabled/failing, this explains why searches return no results.

### 6. Check Wanted Items
```
sonarr_wanted(limit=10)              → missing TV episodes
radarr_movies(filter="wanted")       → missing movies
```

If items have been wanted for a long time, consider triggering a manual search.
If manual search also returns nothing, check indexer health (Step 4) and consider adding more indexers:
- `prowlarr_indexer_schemas(search="...")` to browse available types
- `prowlarr_indexer_manage(action="add", definition_name="eztv", app_profile_id=1)` to add
- `prowlarr_indexers(action="test", indexer_id=N)` to verify

### 7. Update Workspace (if enabled)
Update MEDIA.md with current state (see workspace tracking below).

## AI-Assisted Torrent Selection

When evaluating releases from `*_releases(action="search")`:

### Selection Criteria (Priority Order)
1. **Not rejected** — skip releases where `rejected: true` (quality profile mismatch, custom format issues)
2. **Seeders > 10** — ensures download will actually complete
3. **Reasonable size** — matches quality profile expectations:
   - TV episode (1080p): 1-4 GB typical
   - TV episode (720p): 0.5-2 GB typical
   - Movie (1080p): 5-15 GB typical
   - Movie (4K): 15-60 GB typical
4. **Quality match** — matches the quality profile configured in Sonarr/Radarr
5. **Age** — newer releases tend to have more active seeders
6. **Trusted indexer** — prefer known indexers if available

### When to Grab vs Skip
- **Grab**: Seeders ≥ 10, not rejected, reasonable size
- **Skip**: Seeders < 5, rejected, suspiciously small (likely fake), suspiciously large
- **Ask user**: Borderline cases, only rejected releases available, all releases have low seeders

### Red Flags — Release Problems
- Size = 0 MB → fake release
- Size << expected (e.g. 50 MB "1080p episode") → fake, sample, or wrong content
- Size >> expected (e.g. 20 GB single TV episode) → wrong content or bloated encode
- `.scr`, `.exe`, `.bat`, `.com` in release title → malware/fake, never grab these
- All releases rejected → quality profile may need adjustment, inform user
- Release title doesn't match expected show/episode → wrong content entirely
- Seeders = 0 → dead torrent, will never download
- `tracked_status: "warning"` in queue → import problem, check `errors` field

### Red Flags — After Grabbing
- qBit shows `stalledDL` immediately after grab → dead torrent, blocklist + try next
- qBit shows `metaDL` for >10 min → magnet can't resolve, tracker issue
- qBit shows `missingFiles` → files vanished, re-search needed
- Queue `errors[]` mentions file extension → sketchy release, blocklist + re-search
- Download completes but queue shows warning → import rejected, read error message

## Workspace Tracking

When channel workspace is enabled, maintain a `MEDIA.md` file at the workspace root:

### Structure
```markdown
# Media Stack Status

## Active Downloads
| Item | Type | Progress | Status |
|------|------|----------|--------|
| Show S01E05 | TV | 45% | Downloading |
| Movie Name | Movie | 0% | Stalled → replaced |

## Stuck/Issues
- [date] Show S01E05 was stalled, deleted torrent, grabbed alternative (32 seeders)
- [date] Movie Name — only low-seeder releases available, waiting

## Recent Requests
| Title | Type | Status | Requested |
|-------|------|--------|-----------|
| The Bear S03 | TV | Processing | 2024-01-15 |

## Resolved (remove after 7 days)
- [date] Show S01E04 — now available in Jellyfin
```

### Maintenance Rules
- Add entries when issues are found or requests are made
- Update progress on each heartbeat
- Move to "Resolved" when items appear in Jellyfin (`jellyfin_library(action="search")`)
- Remove resolved entries after ~7 days
- Keep the file concise — it's injected into context every request
