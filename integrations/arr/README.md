# ARR Media Stack Integration

Controls Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, and Bazarr via their APIs. Provides 16 agent tools for browsing, searching, and managing your media stack.

## Setup

Add the env vars for the services you use to `.env`. Unconfigured services are fine — their tools return a clear "not configured" error.

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

# Bazarr (Subtitles)
BAZARR_URL=http://192.168.1.x:6767
BAZARR_API_KEY=your-bazarr-api-key
```

**Finding API keys:**
- Sonarr/Radarr: Settings → General → API Key
- Jellyfin: Dashboard → API Keys → create one
- Jellyseerr: Settings → General → API Key
- Bazarr: Settings → General → API Key
- qBittorrent: uses username/password (Settings → Web UI)

## Bot Configuration

Add the tools you want to the bot's `local_tools` list in `bots/*.yaml`:

```yaml
local_tools:
  # Sonarr
  - sonarr_calendar
  - sonarr_series
  - sonarr_wanted
  - sonarr_queue
  - sonarr_command
  # Radarr
  - radarr_movies
  - radarr_command
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

skills:
  - integrations/arr/media_management
```

Or let tool retrieval pick them up automatically — the skill doc gives the agent enough context to know when to use each tool.

## Tools

| Service | Tool | Read/Write | Description |
|---------|------|-----------|-------------|
| Sonarr | `sonarr_calendar` | Read | Upcoming episodes + download status |
| Sonarr | `sonarr_series` | Read | List monitored series or search TVDB |
| Sonarr | `sonarr_wanted` | Read | Missing episodes |
| Sonarr | `sonarr_queue` | Read | Download queue |
| Sonarr | `sonarr_command` | Write | Trigger SeriesSearch, EpisodeSearch, MissingEpisodeSearch |
| Radarr | `radarr_movies` | Read | List movies or search TMDB; filter missing/wanted |
| Radarr | `radarr_command` | Write | Trigger MoviesSearch, MissingMoviesSearch |
| qBit | `qbit_torrents` | Read | List torrents + global speeds |
| qBit | `qbit_manage` | Write | Pause/resume/delete torrents |
| Jellyfin | `jellyfin_now_playing` | Read | Active streams |
| Jellyfin | `jellyfin_library` | Read | Recent items, search, stats |
| Jellyfin | `jellyfin_users` | Write | List/create/delete users |
| Jellyseerr | `jellyseerr_requests` | Read | List media requests by status |
| Jellyseerr | `jellyseerr_search` | Read | Search TMDB |
| Jellyseerr | `jellyseerr_manage` | Write | Approve/decline/create requests |
| Bazarr | `bazarr_subtitles` | Both | View wanted subs, trigger search, check status |
