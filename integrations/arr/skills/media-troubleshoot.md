---
id: integrations/arr/media-troubleshoot
title: Media Troubleshooting Procedure
description: Step-by-step diagnostic for "why isn't X on Jellyfin?" — checks availability, download chain, auto-remediates, reports back
tags: [media, troubleshooting, arr]
---

# Media Troubleshooting Procedure

Follow this procedure step by step when a user asks why something isn't available on Jellyfin. Call tools inline and share findings as you go.

## Title Matching (important)

Titles differ across platforms — "Paradise" might be "Paradise (2025)" in Sonarr, just "Paradise" in Jellyfin. Always:
- Search with the shortest unambiguous form first
- If multiple results, pick the most likely match based on context
- Try without year, then with year if ambiguous
- Track the canonical title each service uses as you go

## Step 1: Check Jellyfin

Search Jellyfin: `jellyfin_library(action="search", search="TITLE")`

If no results, try shorter/simpler variations of the title.

- **If FOUND**: Tell the user it's already available — include quality, when added, full title. You're done.
- **If NOT FOUND**: Continue to Step 2.

## Step 2: Check the Download Chain

### 2a. Is it tracked?
- TV: `sonarr_series()` (no search param) — lists library series with internal `id`. Find the title by scanning results.
- Movie: `radarr_movies()` (no search param) — lists library movies with internal `id`. Find the title by scanning results.
- If media type is unclear, check both
- **Save the internal `id` field** — this is the series_id/movie_id needed for ALL subsequent tool calls. Do NOT use tvdb_id or tmdb_id.

### 2b. Download queue (if tracked)
- `sonarr_queue()` / `radarr_queue()` — is it grabbed/downloading?
- `qbit_torrents(filter="downloading")` — active download progress?
- `qbit_torrents(filter="stalled")` — is anything stuck?

### 2c. Recent imports (if downloaded)
- `jellyfin_library(action="recent", limit=20)` — did it import recently?

### 2d. Inspect episodes (if import issue suspected)
- `sonarr_episodes(series_id=X, season=N)` — check `has_file`, `episode_file_id`, `file_size_mb`
- `sonarr_history(series_id=X, episode_id=Y)` — see grab/import/failure events with error messages

### 2e. Read queue errors carefully
When `sonarr_queue()` / `radarr_queue()` returns items, check these fields:
- `tracked_status: "warning"` → import problem, read `errors[]` for the reason
- `errors[]` contains the actual failure messages — parse them for these common patterns:

| Error pattern | What it means |
|---|---|
| "has been blocked by your anti virus" / `.exe` / `.scr` / `.bat` extension | Sketchy release — malware/fake, blocklist and re-search |
| "Not a Custom Format upgrade" / "quality cutoff" | Quality profile rejected it — Sonarr grabbed it but won't import. Blocklist + re-search |
| "No files found are eligible for import" | Download contains wrong content or unparseable filenames |
| "Sample" in error or tiny file size | Grabbed a sample, not the full episode |
| "Unable to parse file" / "Invalid media file" | Corrupt or incompatible file format |
| "Not enough disk space" | Disk full — need cleanup before anything will import |
| "Path does not exist" | Root folder misconfigured or mount issue |

### Determine diagnosis
Based on findings, classify as one of:
- **NOT_TRACKED** — not in Sonarr/Radarr at all
- **DOWNLOADING** — actively downloading with progress, just needs time
- **STALLED** — torrent is stuck. Check qBit state:
  - `stalledDL` = no peers, download can't progress
  - `metaDL` for >10 min = magnet link can't resolve, tracker down or torrent dead
  - `missingFiles` = files deleted from disk but torrent still active
  - `error` = hash check failed or disk I/O error
  - ETA = 8640000 (infinity) with 0 speed = dead torrent
- **QUEUED** — grabbed but download hasn't started
- **NOT_GRABBED** — tracked but no release grabbed yet
- **BAD_GRAB** — Sonarr/Radarr auto-grabbed a release that will never import cleanly:
  - Queue shows `tracked_status: "warning"` with error about quality/format/extension
  - Release has sketchy file extension (`.exe`, `.scr`, `.bat`, `.com`)
  - Size is way off (e.g. 50 MB for a "1080p episode" = fake, or 20 GB for a single episode = bloated/wrong)
  - Release title doesn't match what was expected (wrong show/episode entirely)
- **IMPORT_ISSUE** — downloaded/completed but not in Jellyfin library. Usually:
  - Jellyfin library scan hasn't run yet
  - File landed in wrong directory
  - Permissions issue on import path
- **PHANTOM_FILE** — Sonarr thinks it has the file (hasFile=true, queue completed) but the file is bad/missing/corrupt. Common with `.scr` releases or failed imports.

**History chain analysis:** If you see `grabbed` in history but no `downloadFolderImported` or `downloadFailed` after it, the download is stuck somewhere between qBit and Sonarr — check qBit state.

If **DOWNLOADING**: tell the user the current progress and ETA. No fix needed — just patience. Skip to Step 4.

## Step 3: Fix

Take corrective action based on diagnosis. Use the canonical title/IDs from Step 2 — don't re-search.

### NOT_TRACKED — Search and request it
1. `jellyseerr_search(query="TITLE")` — find the TMDB match
2. Check the `status` field — if already `pending`/`processing`, it's in the pipeline already
3. If not requested: `jellyseerr_manage(action="request", media_id=TMDB_ID, media_type="movie"|"tv")`
4. Also try direct lookup: `sonarr_series(search="TITLE")` / `radarr_movies(search="TITLE")`

### STALLED — Remove bad torrent and find alternatives
1. **Remove from arr queue first** (not just qBit): `sonarr_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)`
   - This removes the queue entry + torrent + blocklists the dead release
   - If it's just a qBit issue (not in arr queue), then: `qbit_manage(hashes=[...], action="delete")`
2. Get the episode ID: `sonarr_episodes(series_id=X, season=N)` → find the target episode's `id` field
3. Browse releases: `sonarr_releases(action="search", episode_id=EP_ID)` or `radarr_releases(action="search", movie_id=X)`
4. Pick the best release: 1080p preferred, seeders >= 10, reasonable size, not rejected
5. Grab it: `*_releases(action="grab", guid="...", indexer_id=N)`

### BAD_GRAB — Remove bad release and find a good one
Sonarr/Radarr auto-grabbed something that won't import (wrong quality, sketchy file, size mismatch).
1. **Blocklist the bad release**: `sonarr_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)` — prevents re-grabbing
2. **Browse releases manually**: `sonarr_episodes(series_id=X, season=N)` → get episode `id` → `sonarr_releases(action="search", episode_id=EP_ID)`
3. **Evaluate carefully** — the auto-grab already failed, so be picky:
   - Skip releases with `.scr`, `.exe`, `.bat`, `.com` in title
   - Skip releases with suspicious size (< 200 MB or > 10 GB for TV episode)
   - Prefer releases with high seeders (≥ 10) and age > 1 day (proven availability)
   - Match episode title roughly to release title
4. **Grab the best one**: `*_releases(action="grab", guid="...", indexer_id=N)`

### NOT_GRABBED / QUEUED — Force a search
- TV: `sonarr_command(action="SeriesSearch", series_id=X)` or `sonarr_command(action="EpisodeSearch", episode_ids=[...])`
- Movie: `radarr_command(action="MoviesSearch", movie_ids=[X])`
- If search returns no results, browse releases manually and grab the best one
- **If no releases found at all**, escalate to indexer diagnostics (see below)

### NO_RELEASES — Indexer diagnostics
When `sonarr_releases` or `radarr_releases` returns 0 results, or all results are rejected, the problem is likely at the indexer level.

**Step-by-step diagnosis:**
1. **Search Prowlarr directly**: `prowlarr_search(query="Show S01E05")` — this searches ALL indexers. If Prowlarr finds results but Sonarr doesn't, the indexer isn't synced to Sonarr properly.
2. **Check indexer health**: `prowlarr_health()` — look for warnings about unavailable indexers.
3. **List indexers**: `prowlarr_indexers()` — check for:
   - `enabled: false` → indexer is disabled, may need re-enabling
   - `disabled_till` set → temporarily disabled due to failures (will auto-recover)
   - `escalation_level` > 0 → indexer has been failing repeatedly
4. **Test failing indexers**: `prowlarr_indexers(action="test", indexer_id=X)` — confirms whether the indexer is actually reachable.
5. **Check app sync**: `prowlarr_apps()` — verify Sonarr/Radarr are connected with `sync_level: "fullSync"`.

**Common causes and fixes:**
- **Indexer temporarily disabled** (rate limiting) — check `disabled_till`, it'll auto-recover. If urgent, re-enable: `prowlarr_indexer_manage(action="update", indexer_id=X, enabled=true)`
- **Indexer API key expired** — test will fail. Update credentials: `prowlarr_indexer_manage(action="update", indexer_id=X, field_values={"apiKey": "new-key"})`
- **Indexer down/unreachable** — test fails with connection error. Wait, or try alternative indexers.
- **Prowlarr→Sonarr sync broken** — `prowlarr_apps()` shows the connection status. If `sync_level` isn't "fullSync", indexers won't propagate.
- **Not enough indexers** — if only 1-2 indexers are configured, content coverage is limited. Browse available indexers: `prowlarr_indexer_schemas(search="torrent")` and add more: `prowlarr_indexer_manage(action="add", definition_name="...", field_values={...})`
- **Content simply not available** — `prowlarr_search()` returns 0 results from all indexers. Tell user to wait (content may not be released/indexed yet) or try different search terms.

**Adding new indexers** (when current ones don't have the content):
1. `prowlarr_indexer_schemas(search="...")` — browse available indexer types by name
2. Review which ones are public (no account needed) vs private (requires registration)
3. For public indexers: `prowlarr_indexer_manage(action="add", definition_name="thepiratebay")` — most work with defaults
4. For private indexers: user will need to provide API key or credentials
5. After adding: `prowlarr_indexers(action="test", indexer_id=N)` to verify it works
6. Prowlarr auto-syncs new indexers to Sonarr/Radarr if app sync is configured

### IMPORT_ISSUE — Diagnose why import failed, then fix
First check `sonarr_queue()` / `radarr_queue()` — read the `errors[]` field carefully:

- **If errors mention quality/format rejection**: Sonarr downloaded it but won't import. Blocklist + re-search (same as BAD_GRAB).
- **If errors mention disk space**: Tell user to free disk space.
- **If errors mention path/permission**: Infrastructure issue, tell user.
- **If no errors but not in Jellyfin**: `jellyfin_library(action="scan")` to force a library scan, then check again.
- **If queue is empty but history shows `grabbed` with no `downloadFolderImported`**: Download vanished — likely qBit dropped it. Re-search.

### PHANTOM_FILE — Clear bad state and re-search
This is the trickiest case. The download completed but the file is bad/missing, and Sonarr's internal state is confused.

**Step-by-step fix:**
1. **Remove from Sonarr queue**: `sonarr_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)` — this clears the queue entry AND removes the bad torrent from qBittorrent AND blocklists the bad release
2. **Trigger SeriesSearch**: `sonarr_command(action="SeriesSearch", series_id=X)` — this re-evaluates ALL episodes for the series and searches for new releases
3. **Monitor**: Check `sonarr_queue()` after a minute to see if a new release was grabbed

**Important:** Do NOT use `EpisodeSearch` or `rescan_series` on episodes with phantom file references — they fail with "Sequence contains no matching element." Always use `SeriesSearch` as the workaround.

**Why not just delete from qBittorrent?** Deleting from qBit does NOT clear Sonarr's phantom file reference. The queue item persists in Sonarr and blocks new downloads. You MUST remove via `sonarr_queue_manage` to properly clean up.

**Batch operations:** Process queue removals one at a time — passing multiple IDs is fine with `sonarr_queue_manage`, but if qBit batch delete is needed separately, delete one torrent at a time (known qBit API bug with multiple hashes).

## Step 4: Report

Write a conversational summary for the user:
- What you found (available, downloading, was stuck, wasn't tracked, etc.)
- What you did about it (re-searched, grabbed new release, requested it, etc.)
- Expected timeline ("should be there in a few hours", "downloading now, ~45 min left", etc.)
- Any follow-up needed ("if it's still not there tomorrow, check the indexer")

Example tone: "Checked it out — The Pitt S02E13 was downloaded but the import to Jellyfin got stuck. Triggered a library scan, should show up within the hour."
