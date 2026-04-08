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
- TV: `sonarr_series()` — search results for the title (partial match)
- Movie: `radarr_movies()` — search results for the title (partial match)
- If media type is unclear, check both
- Note the series_id/movie_id and canonical title for later steps

### 2b. Download queue (if tracked)
- `sonarr_queue()` / `radarr_queue()` — is it grabbed/downloading?
- `qbit_torrents(filter="downloading")` — active download progress?
- `qbit_torrents(filter="stalled")` — is anything stuck?

### 2c. Recent imports (if downloaded)
- `jellyfin_library(action="recent", limit=20)` — did it import recently?

### 2d. Inspect episodes (if import issue suspected)
- `sonarr_episodes(series_id=X, season=N)` — check `has_file`, `episode_file_id`, `file_size_mb`
- `sonarr_history(series_id=X, episode_id=Y)` — see grab/import/failure events with error messages

**Phantom file indicators:**
- Queue shows `status: "completed"` + `tracked_status: "warning"` but episode isn't in Jellyfin
- `sonarr_episodes` shows `has_file: true` but file is actually bad/missing
- History shows `downloadFailed` events or no `downloadFolderImported` event after a `grabbed` event
- `.scr` suffix in release title = screener/corrupt file

### Determine diagnosis
Based on findings, classify as one of:
- **NOT_TRACKED** — not in Sonarr/Radarr at all
- **DOWNLOADING** — actively downloading with progress, just needs time
- **STALLED** — torrent is stuck (stalledDL, no peers, ETA infinity)
- **QUEUED** — grabbed but download hasn't started
- **NOT_GRABBED** — tracked but no release grabbed yet
- **IMPORT_ISSUE** — downloaded/completed but not in Jellyfin library
- **PHANTOM_FILE** — Sonarr thinks it has the file (hasFile=true, queue completed) but the file is bad/missing/corrupt. Common with `.scr` releases or failed imports.

If **DOWNLOADING**: tell the user the current progress and ETA. No fix needed — just patience. Skip to Step 4.

## Step 3: Fix

Take corrective action based on diagnosis. Use the canonical title/IDs from Step 2 — don't re-search.

### NOT_TRACKED — Search and request it
1. `jellyseerr_search(query="TITLE")` — find the TMDB match
2. Check the `status` field — if already `pending`/`processing`, it's in the pipeline already
3. If not requested: `jellyseerr_manage(action="request", media_id=TMDB_ID, media_type="movie"|"tv")`
4. Also try direct lookup: `sonarr_series(search="TITLE")` / `radarr_movies(search="TITLE")`

### STALLED — Remove bad torrent and find alternatives
1. `qbit_manage(hashes=[...], action="delete")` — remove stuck torrent
2. Browse releases: `sonarr_releases(action="search", series_id=X)` or `radarr_releases(action="search", movie_id=X)`
3. Pick the best release: 1080p preferred, seeders >= 10, reasonable size, not rejected
4. Grab it: `*_releases(action="grab", guid="...", indexer_id=N)`

### NOT_GRABBED / QUEUED — Force a search
- TV: `sonarr_command(action="SeriesSearch", series_id=X)` or `sonarr_command(action="EpisodeSearch", episode_ids=[...])`
- Movie: `radarr_command(action="MoviesSearch", movie_ids=[X])`
- If search returns no results, browse releases manually and grab the best one

### IMPORT_ISSUE — Trigger library refresh
- `jellyfin_library(action="scan")` to force a library scan
- Check if the content appears after scan

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
