---
name: Media Management
description: ARR media stack tools — Sonarr, Radarr, Prowlarr, qBittorrent, Jellyfin, Jellyseerr, Bazarr
---
# SKILL: Media Management (ARR Stack)

## Overview
Full control over the home media stack: TV shows (Sonarr), movies (Radarr), indexers (Prowlarr), downloads (qBittorrent), streaming (Jellyfin), media requests (Jellyseerr), and subtitles (Bazarr). All tools make direct API calls — no cached data.

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
- `sonarr_quality_profiles(profile_id=None)` — list all quality profiles or view one in detail (allowed qualities, cutoff, upgrade settings)
- `sonarr_quality_profile_update(profile_id, upgrade_allowed=None, cutoff_quality=None, enable_qualities=None, disable_qualities=None)` — modify quality profile: enable/disable qualities by name, change cutoff target, toggle upgrades

### Radarr (Movies)
- `radarr_movies(search=None, filter=None)` — list library (newest first) or search TMDB; filter: "missing" (no file), "wanted" (missing + monitored)
- `radarr_command(action, movie_ids=None)` — trigger searches: MoviesSearch (needs movie_ids), MissingMoviesSearch (no params)
- `radarr_queue()` — items in download queue with progress, quality, ETA, queue_id, tracked_status, and error messages
- `radarr_releases(action, movie_id=None, guid=None, indexer_id=None)` — same as sonarr_releases but for movies
- `radarr_history(movie_id, limit=30)` — grab/import/failure events with error messages
- `radarr_queue_manage(queue_ids, blocklist=False, remove_from_client=True)` — remove items from Radarr queue (same as sonarr_queue_manage)
- `radarr_quality_profiles(profile_id=None)` — list all quality profiles or view one in detail
- `radarr_quality_profile_update(profile_id, upgrade_allowed=None, cutoff_quality=None, enable_qualities=None, disable_qualities=None)` — modify quality profile

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

### Prowlarr (Indexers)
- `prowlarr_indexers(action="list", indexer_id=None)` — list all indexers with health/failure info; action="test" + indexer_id to test one; action="test_all" to test all
- `prowlarr_indexer_schemas(search=None)` — browse available indexer types to add (filter by name)
- `prowlarr_indexer_manage(action, indexer_id=None, definition_name=None, app_profile_id=1, tags=None, field_values=None)` — add/update/delete indexers. `app_profile_id` is **required** for add (default 1 = standard). `tags` for linking to FlareSolverr proxy. `field_values` for config like API keys.
- `prowlarr_tags()` — list tags (find FlareSolverr tag ID for Cloudflare-protected indexers like 1337x)
- `prowlarr_search(query, type="search", limit=20, indexer_ids=None)` — search across ALL indexers; shows which indexers found results. type: "search" (general), "tvsearch" (TV), "movie"
- `prowlarr_apps()` — list connected apps (Sonarr/Radarr) and sync status
- `prowlarr_health()` — system health check: indexer issues, sync problems, warnings

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
1. Get internal IDs: `sonarr_series()` → find series `id` (NOT tvdb_id)
2. Get episode ID: `sonarr_episodes(series_id=X, season=N)` → find episode `id`
3. Browse: `sonarr_releases(action="search", episode_id=EP_ID)` or `radarr_releases(action="search", movie_id=MOVIE_ID)`
4. Evaluate: quality (1080p preferred), seeders ≥10, size 1-4 GB for TV, rejection status
5. Grab: `sonarr_releases(action="grab", guid="...", indexer_id=N)` or `radarr_releases(action="grab", ...)`

### Add new indexers
1. `prowlarr_indexer_schemas(search="eztv")` — find the indexer definition
2. `prowlarr_indexer_manage(action="add", definition_name="eztv", app_profile_id=1)` — add it (public indexers usually need no extra config)
3. `prowlarr_indexers(action="test", indexer_id=N)` — verify it works
4. Prowlarr auto-syncs to Sonarr/Radarr via app profiles

### Troubleshoot indexers
1. `prowlarr_health()` — check for system-level warnings
2. `prowlarr_indexers()` — see which are enabled/disabled/failing
3. `prowlarr_search(query="Show S01E05")` — test search across all indexers
4. `prowlarr_indexers(action="test", indexer_id=X)` — test specific indexer connectivity

### Manage quality profiles
1. `sonarr_quality_profiles()` / `radarr_quality_profiles()` — list all profiles with allowed qualities and cutoff
2. To enable 4K: `sonarr_quality_profile_update(profile_id=1, enable_qualities=["Bluray-2160p", "WEBDL-2160p"], cutoff_quality="Bluray-2160p")`
3. To disable SD: `sonarr_quality_profile_update(profile_id=1, disable_qualities=["SDTV", "DVD"])`
4. To allow upgrades: `sonarr_quality_profile_update(profile_id=1, upgrade_allowed=True)`
5. Quality names must match exactly — use `*_quality_profiles(profile_id=X)` to see valid names

### Find something to watch
1. `jellyfin_library(action="recent")` — see latest additions
2. `jellyfin_library(action="search", search="comedy")` — search by genre/title
3. `jellyfin_now_playing()` — see what others are watching

### Check subtitle status
1. `bazarr_subtitles(action="wanted")` — see missing subtitles
2. `bazarr_subtitles(action="search")` — trigger search for all wanted

## Common Patterns
- **ID lookups**: Use `sonarr_series()` (no search) to get internal series `id` (NOT tvdb_id). Use `radarr_movies()` (no search) for internal movie `id` (NOT tmdb_id). Search mode returns `id` only if the item is already in your library.
- **Torrent hashes**: Get from `qbit_torrents` results, pass to `qbit_manage`
- **TMDB IDs**: Get from `jellyseerr_search`, pass to `jellyseerr_manage(action="request")`
- **Release GUIDs**: Get from `*_releases(action="search")`, pass to `*_releases(action="grab")`
- **Unconfigured services**: Tools return clear "X_URL not configured" errors — skip those services
- **Quality preference**: Default 1080p — Bluray > WEB-DL > HDTV; avoid 720p unless nothing else available
