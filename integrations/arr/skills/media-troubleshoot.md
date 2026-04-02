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

### Determine diagnosis
Based on findings, classify as one of:
- **NOT_TRACKED** — not in Sonarr/Radarr at all
- **DOWNLOADING** — actively downloading with progress, just needs time
- **STALLED** — torrent is stuck (stalledDL, no peers, ETA infinity)
- **QUEUED** — grabbed but download hasn't started
- **NOT_GRABBED** — tracked but no release grabbed yet
- **IMPORT_ISSUE** — downloaded/completed but not in Jellyfin library

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

## Step 4: Report

Write a conversational summary for the user:
- What you found (available, downloading, was stuck, wasn't tracked, etc.)
- What you did about it (re-searched, grabbed new release, requested it, etc.)
- Expected timeline ("should be there in a few hours", "downloading now, ~45 min left", etc.)
- Any follow-up needed ("if it's still not there tomorrow, check the indexer")

Example tone: "Checked it out — The Pitt S02E13 was downloaded but the import to Jellyfin got stuck. Triggered a library scan, should show up within the hour."
