---
name: Media Management
description: ARR media stack tools — Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, Bazarr
---
# SKILL: Media Management (ARR Stack)

## Overview
Full control over the home media stack: TV shows (Sonarr), movies (Radarr), downloads (qBittorrent), streaming (Jellyfin), media requests (Jellyseerr), and subtitles (Bazarr). All tools make direct API calls — no cached data.

## Tools by Service

### Sonarr (TV Shows)
- `sonarr_calendar(days_ahead=7)` — upcoming episodes for next N days, with download status
- `sonarr_series(search=None, limit=50)` — list monitored series (newest first) or search TVDB
- `sonarr_wanted(limit=20)` — missing episodes (paged, newest airdate first)
- `sonarr_queue()` — items in download queue with progress, quality, ETA, queue_id, tracked_status, and error messages
- `sonarr_command(action, series_id=None, episode_ids=None)` — trigger searches: SeriesSearch (needs series_id), EpisodeSearch (needs episode_ids), MissingEpisodeSearch (no params)
- `sonarr_releases(action, episode_id=None, guid=None, indexer_id=None)` — action="search" to browse releases (sorted by seeders, top 15); action="grab" to download (needs guid + indexer_id). Release search uses 60s timeout.
- `sonarr_episodes(series_id, season=None)` — episode details: hasFile, episodeFileId, monitored, file path/quality/size. Essential for diagnosing phantom file references.
- `sonarr_history(series_id, episode_id=None, limit=30)` — grab/import/failure events with error messages. Use to see why imports failed.
- `sonarr_queue_manage(queue_ids, blocklist=False, remove_from_client=True)` — remove items from Sonarr queue. Optionally blocklist bad release and/or remove torrent from qBittorrent.

### Radarr (Movies)
- `radarr_movies(search=None, filter=None)` — list library (newest first) or search TMDB; filter: "missing" (no file), "wanted" (missing + monitored)
- `radarr_command(action, movie_ids=None)` — trigger searches: MoviesSearch (needs movie_ids), MissingMoviesSearch (no params)
- `radarr_queue()` — items in download queue with progress, quality, ETA, queue_id, tracked_status, and error messages
- `radarr_releases(action, movie_id=None, guid=None, indexer_id=None)` — same as sonarr_releases but for movies
- `radarr_history(movie_id, limit=30)` — grab/import/failure events with error messages
- `radarr_queue_manage(queue_ids, blocklist=False, remove_from_client=True)` — remove items from Radarr queue (same as sonarr_queue_manage)

### qBittorrent (Downloads)
- `qbit_torrents(filter="all", limit=50)` — list torrents with speeds; filters: all, downloading, seeding, completed, paused, active, stalled
- `qbit_manage(hashes, action)` — actions: pause, resume, delete, delete_with_files

### Jellyfin (Streaming)
- `jellyfin_now_playing()` — active streams with user, media, progress
- `jellyfin_library(action="recent", search=None, media_type=None, limit=20)` — actions: recent (latest), search (find media), stats (item counts)
- `jellyfin_users(action="list", username=None, password=None, user_id=None)` — actions: list, create, delete

### Jellyseerr (Requests)
- `jellyseerr_requests(filter="all", limit=20, skip=0, sort="added")` — list requests; filters: all, pending, approved, processing, available, unavailable, failed; sort: added (newest first) or modified (recently updated)
- `jellyseerr_search(query, page=1)` — search TMDB (20 results/page); results include `status` if already requested/available
- `jellyseerr_manage(action, request_id=None, media_id=None, media_type=None, seasons=None)` — actions: approve (needs request_id), decline (needs request_id), request (needs media_id + media_type; optional seasons for TV)

### Bazarr (Subtitles)
- `bazarr_subtitles(action="wanted", media_type="episodes", limit=20)` — actions: wanted (missing subs), search (trigger search), status (system health)

## Pagination

- `jellyseerr_requests(skip=20, limit=20)` — page 2; check `page.has_more`
- `jellyseerr_search(query="...", page=2)` — page 2; check `page.total_pages`
- `sonarr_series(limit=100)` / `radarr_movies(limit=100)` — larger pages

## Key Workflows

### Request new media
1. Check Jellyfin first: `jellyfin_library(action="search", search="The Bear")`
2. If not found, search TMDB: `jellyseerr_search(query="The Bear")`
3. Check `status` on results — skip if already `available`/`pending`/`processing`
4. Confirm the match (title + year) with the user
5. Request: `jellyseerr_manage(action="request", media_id=12345, media_type="tv", seasons=[1,2,3])`

### Handle pending requests
1. `jellyseerr_requests(filter="pending")` — see what needs approval
2. `jellyseerr_manage(action="approve", request_id=123)` — approve
3. Monitor: `sonarr_queue()` or `radarr_queue()` — track download progress

### Ensure all shows are downloaded
1. `sonarr_wanted()` — see what's missing
2. `sonarr_command(action="MissingEpisodeSearch")` — trigger search for all missing
3. `sonarr_queue()` or `qbit_torrents(filter="downloading")` — monitor progress

### Fix stuck downloads
1. `sonarr_queue()` / `radarr_queue()` — find items with `tracked_status: "warning"` or `status: "completed"` still in queue
2. `sonarr_queue_manage(queue_ids=[ID], remove_from_client=true, blocklist=true)` — remove from queue + qBit + blocklist bad release
3. `sonarr_command(action="SeriesSearch", series_id=X)` — trigger re-search for clean release
4. If auto-search doesn't grab: `sonarr_releases(action="search", episode_id=Y)` — browse alternatives manually
5. Evaluate: 1080p preferred, seeders ≥10, reasonable size, not rejected, no `.scr` suffix
6. `sonarr_releases(action="grab", guid="...", indexer_id=1)` — grab best release

### Diagnose import failures
1. `sonarr_episodes(series_id=X, season=N)` — check `has_file` and `file_size_mb` for suspicious state
2. `sonarr_history(series_id=X, episode_id=Y)` — see grab/import/failure events
3. Look for: `downloadFailed` events, missing `downloadFolderImported` after `grabbed`, phantom file references

### Browse and grab specific releases
1. `sonarr_releases(action="search", series_id=123)` or `radarr_releases(action="search", movie_id=456)`
2. Evaluate: quality (1080p preferred), seeders, size, rejection status
3. `sonarr_releases(action="grab", guid="...", indexer_id=1)` or `radarr_releases(action="grab", ...)`

### Find something to watch
1. `jellyfin_library(action="recent")` — see latest additions
2. `jellyfin_library(action="search", search="comedy")` — search by genre/title
3. `jellyfin_now_playing()` — see what others are watching

### Check subtitle status
1. `bazarr_subtitles(action="wanted")` — see missing subtitles
2. `bazarr_subtitles(action="search")` — trigger search for all wanted

## Common Patterns
- **ID lookups**: Use `sonarr_series` to get series IDs, `radarr_movies` for movie IDs
- **Torrent hashes**: Get from `qbit_torrents` results, pass to `qbit_manage`
- **TMDB IDs**: Get from `jellyseerr_search`, pass to `jellyseerr_manage(action="request")`
- **Release GUIDs**: Get from `*_releases(action="search")`, pass to `*_releases(action="grab")`
- **Unconfigured services**: Tools return clear "X_URL not configured" errors — skip those services
- **Quality preference**: Default 1080p — Bluray > WEB-DL > HDTV; avoid 720p unless nothing else available
