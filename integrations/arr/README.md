# ARR Media Stack Integration

Controls Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, Prowlarr, Bazarr, and FlareSolverr via their APIs. Provides agent tools for browsing, searching, monitoring, and managing your media stack.

## Setup

Add the env vars for the services you use to `.env` (or configure via the admin integrations page). Unconfigured services are fine — their tools return a clear "not configured" error.

```env
# Sonarr (TV shows)
SONARR_URL=http://192.168.1.x:8989
SONARR_API_KEY=your-sonarr-api-key

# Radarr (Movies)
RADARR_URL=http://192.168.1.x:7878
RADARR_API_KEY=your-radarr-api-key

# qBittorrent (Downloads)
QBIT_URL=http://192.168.1.x:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=your-password

# Jellyfin (Streaming)
JELLYFIN_URL=http://192.168.1.x:8096
JELLYFIN_API_KEY=your-jellyfin-api-key

# Jellyseerr (Requests)
JELLYSEERR_URL=http://192.168.1.x:5055
JELLYSEERR_API_KEY=your-jellyseerr-api-key

# Prowlarr (Indexers)
PROWLARR_URL=http://192.168.1.x:9696
PROWLARR_API_KEY=your-prowlarr-api-key

# Bazarr (Subtitles)
BAZARR_URL=http://192.168.1.x:6767
BAZARR_API_KEY=your-bazarr-api-key

# FlareSolverr (Cloudflare bypass for indexers — no auth)
FLARESOLVERR_URL=http://192.168.1.x:8191
```

**Finding API keys:**
- Sonarr/Radarr: Settings → General → API Key
- Jellyfin: Dashboard → API Keys → create one
- Jellyseerr: Settings → General → API Key
- Bazarr: Settings → General → API Key
- qBittorrent: uses username/password (Settings → Web UI)

## Bot Configuration

Enroll the ARR tools you want on the bot for full media stack support:

```yaml
local_tools:
  # Aggregate heartbeat/status snapshot
  - arr_heartbeat_snapshot
  # Sonarr
  - sonarr_calendar
  - sonarr_series
  - sonarr_wanted
  - sonarr_queue
  - sonarr_command
  - sonarr_releases
  # Radarr
  - radarr_movies
  - radarr_command
  - radarr_queue
  - radarr_releases
  # qBittorrent
  - qbit_torrents
  - qbit_manage
  # Jellyfin
  - jellyfin_now_playing
  - jellyfin_library
  - jellyfin_users
  # Jellyseerr
  - jellyseerr_requests
  - jellyseerr_search
  - jellyseerr_manage
  # Bazarr
  - bazarr_subtitles
```

## Tools

| Service | Tool | Read/Write | Description |
|---------|------|-----------|-------------|
| ARR Stack | `arr_heartbeat_snapshot` | Read | One read-only heartbeat snapshot across configured services; reports not_configured/unavailable per service |
| Sonarr | `sonarr_calendar` | Read | Upcoming episodes + download status |
| Sonarr | `sonarr_series` | Read | List monitored series or search TVDB |
| Sonarr | `sonarr_wanted` | Read | Missing episodes |
| Sonarr | `sonarr_queue` | Read | Download queue |
| Sonarr | `sonarr_command` | Write | Trigger SeriesSearch, EpisodeSearch, MissingEpisodeSearch |
| Sonarr | `sonarr_releases` | Both | Browse available releases or grab a specific one |
| Radarr | `radarr_movies` | Read | List movies or search TMDB; filter missing/wanted |
| Radarr | `radarr_command` | Write | Trigger MoviesSearch, MissingMoviesSearch |
| Radarr | `radarr_queue` | Read | Download queue |
| Radarr | `radarr_releases` | Both | Browse available releases or grab a specific one |
| qBit | `qbit_torrents` | Read | List torrents + global speeds |
| qBit | `qbit_manage` | Write | Pause/resume/delete torrents |
| Jellyfin | `jellyfin_now_playing` | Read | Active streams |
| Jellyfin | `jellyfin_library` | Read | Recent items, search, stats |
| Jellyfin | `jellyfin_users` | Write | List/create/delete users |
| Jellyseerr | `jellyseerr_requests` | Read | List media requests by status |
| Jellyseerr | `jellyseerr_search` | Read | Search TMDB |
| Jellyseerr | `jellyseerr_manage` | Write | Approve/decline/create requests |
| Bazarr | `bazarr_subtitles` | Both | View wanted subs, trigger search, check status |
| FlareSolverr | `flaresolverr_health` | Read | Reachability + version + active session count — first thing to check when CF indexers fail |
| FlareSolverr | `flaresolverr_sessions` | Both | List, create, or destroy browser sessions |
| FlareSolverr | `flaresolverr_test_fetch` | Read | Fetch a Cloudflare URL through FS to verify challenge solving works end-to-end |
| FlareSolverr | `flaresolverr_destroy_all_sessions` | Write | Reset all FS sessions (canonical fix for wedged FS) |

## Key Workflows

### Check availability → Request
1. `jellyfin_library(action="search", search="The Bear")` — check if already available
2. If not: `jellyseerr_search(query="The Bear")` — find TMDB ID
3. `jellyseerr_manage(action="request", media_id=12345, media_type="tv", seasons=[3])` — request it

### Fix stuck downloads
1. `qbit_torrents(filter="stalled")` — find stuck torrents
2. `qbit_manage(hashes=["abc123"], action="delete")` — remove bad torrent
3. `sonarr_releases(action="search", series_id=123)` — browse alternatives
4. `sonarr_releases(action="grab", guid="...", indexer_id=1)` — grab best release

### Heartbeat monitoring
Configure a channel heartbeat to call `arr_heartbeat_snapshot()` first, then use detailed service tools only for anomalies or remediation. The snapshot gracefully handles users who configured only one or a few services. See the `download-monitoring` skill for the full protocol.
