---
name: Download Monitoring
description: Heartbeat-driven download monitoring, stuck download detection, AI-assisted torrent selection, workspace tracking
---
# SKILL: Download Monitoring (ARR Stack)

## Heartbeat Monitoring Protocol

When running as a periodic heartbeat, follow this sequence:

### 1. Check Download Queues
```
sonarr_queue()     → active TV downloads
radarr_queue()     → active movie downloads
qbit_torrents(filter="downloading") → all active torrents
```

Report: total items downloading, overall progress, any issues.

### 2. Detect Stuck Downloads
```
qbit_torrents(filter="stalled") → torrents with no peers/progress
```

A torrent is "stuck" if:
- State is `stalledDL` (stalled downloading)
- Progress hasn't changed in consecutive checks
- ETA is `8640000` (qBit's "infinity" value)

### 3. Fix Stuck Downloads
For each stuck torrent:
1. `qbit_manage(hashes=["..."], action="delete")` — remove the bad torrent
2. Identify the source: check `sonarr_queue` / `radarr_queue` for matching items
3. `sonarr_releases(action="search", series_id=X)` or `radarr_releases(action="search", movie_id=X)` — browse alternatives
4. Evaluate releases (see selection criteria below)
5. `*_releases(action="grab", guid="...", indexer_id=N)` — grab the best one

### 4. Check Wanted Items
```
sonarr_wanted(limit=10)              → missing TV episodes
radarr_movies(filter="wanted")       → missing movies
```

If items have been wanted for a long time, consider triggering a manual search.

### 5. Update Workspace (if enabled)
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

### Red Flags
- Size = 0 MB → fake release
- Size << expected → likely low quality or wrong content
- All releases rejected → quality profile may need adjustment, inform user

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
