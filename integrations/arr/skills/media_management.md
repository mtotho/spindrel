---
name: Media Management
description: ARR media stack tools — Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, Bazarr
---
# SKILL: Media Management (ARR Stack)

## Overview
Full control over the home media stack: TV shows (Sonarr), movies (Radarr), downloads (qBittorrent), streaming (Jellyfin), media requests (Jellyseerr), and subtitles (Bazarr). All tools make direct API calls — no cached data.

## Tools by Service

### Sonarr (TV Shows)
- `sonarr_calendar` — upcoming episodes for next N days, with download status
- `sonarr_series` — list monitored series or search TVDB for new ones
- `sonarr_wanted` — missing episodes that need downloading
- `sonarr_queue` — items currently being downloaded
- `sonarr_command` — trigger searches: SeriesSearch, EpisodeSearch, MissingEpisodeSearch
- `sonarr_releases` — browse available releases for a series/episode, or grab a specific release

### Radarr (Movies)
- `radarr_movies` — list library or search TMDB; filter by "missing"/"wanted"
- `radarr_command` — trigger searches: MoviesSearch, MissingMoviesSearch
- `radarr_queue` — items currently being downloaded
- `radarr_releases` — browse available releases for a movie, or grab a specific release

### qBittorrent (Downloads)
- `qbit_torrents` — list torrents with speeds; filters: downloading, seeding, completed, paused, active, stalled
- `qbit_manage` — pause/resume/delete/delete_with_files torrents by hash

### Jellyfin (Streaming)
- `jellyfin_now_playing` — active streams with user, media, progress
- `jellyfin_library` — recent additions, search library, or get item counts (stats)
- `jellyfin_users` — list/create/delete Jellyfin users

### Jellyseerr (Requests)
- `jellyseerr_requests` — list media requests; filter: pending, approved, declined, processing, available
- `jellyseerr_search` — search TMDB for movies/shows (returns IDs for requesting)
- `jellyseerr_manage` — approve/decline existing requests, or create new requests by TMDB ID

### Bazarr (Subtitles)
- `bazarr_subtitles` — view wanted subtitles, trigger subtitle search, check system status

## Key Workflows

### Ensure all shows are downloaded
1. `sonarr_wanted` — see what's missing
2. `sonarr_command(action="MissingEpisodeSearch")` — trigger search for all missing
3. `sonarr_queue` or `qbit_torrents` — monitor download progress

### Find something to watch
1. `jellyfin_library(action="recent")` — see latest additions
2. `jellyfin_library(action="search", search="comedy")` — search by genre/title
3. `jellyfin_now_playing` — see what others are watching

### Handle media requests
1. `jellyseerr_requests(filter="pending")` — see pending requests
2. `jellyseerr_manage(action="approve", request_id=123)` — approve a request
3. Monitor: `sonarr_queue` or `radarr_movies(filter="wanted")` — track fulfillment

### Request new media
1. `jellyseerr_search(query="The Bear")` — find TMDB ID
2. `jellyseerr_manage(action="request", media_id=12345, media_type="tv", seasons=[1,2])` — request it

### Create a Jellyfin user
1. `jellyfin_users(action="create", username="john", password="temp123")`

### Fix stuck downloads
1. `qbit_torrents(filter="stalled")` — find stuck torrents
2. `qbit_manage(hashes=["abc123"], action="delete")` — remove stuck ones
3. `sonarr_releases(action="search", series_id=123)` — browse available releases
4. Evaluate: prefer high seeders (>10), reasonable size, not rejected
5. `sonarr_releases(action="grab", guid="...", indexer_id=1)` — grab best release

### Browse and grab specific releases
1. `sonarr_releases(action="search", series_id=123)` or `radarr_releases(action="search", movie_id=456)` — browse
2. Evaluate results: seeders, size, quality, rejection status
3. `sonarr_releases(action="grab", guid="...", indexer_id=1)` or `radarr_releases(action="grab", ...)` — grab

### Check subtitle status
1. `bazarr_subtitles(action="wanted")` — see missing subtitles
2. `bazarr_subtitles(action="search")` — trigger search for all wanted

## Common Patterns
- **ID lookups**: Use `sonarr_series` to get series IDs, `radarr_movies` for movie IDs
- **Torrent hashes**: Get from `qbit_torrents` results, pass to `qbit_manage`
- **TMDB IDs**: Get from `jellyseerr_search`, pass to `jellyseerr_manage(action="request")`
- **Release GUIDs**: Get from `*_releases(action="search")`, pass to `*_releases(action="grab")`
- **Unconfigured services**: Tools return clear "X_URL not configured" errors — just skip those services
