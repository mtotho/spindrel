# Media Server Integration — Phase 1

Lightweight cron scripts that fetch data from media APIs and write JSON to `data/media/`. Agent tools read these files to surface summaries.

## Scripts

| Script | Source | Output |
|--------|--------|--------|
| `scripts/media/sonarr_today.sh` | Sonarr `/api/v3/calendar` (today) | `data/media/sonarr_today.json` |
| `scripts/media/sonarr_upcoming.sh` | Sonarr `/api/v3/calendar` (7 days) | `data/media/sonarr_upcoming.json` |
| `scripts/media/radarr_recent.sh` | Radarr `/api/v3/movie` (recent) | `data/media/radarr_recent.json` |
| `scripts/media/qbit_status.sh` | qBittorrent `/api/v2/torrents/info` | `data/media/qbit_status.json` |
| `scripts/media/jellyseerr_pending.sh` | Jellyseerr `/api/v1/request?filter=pending` | `data/media/jellyseerr_pending.json` |

Each script writes atomically (`.tmp` then `mv`) and wraps output as `{"fetched_at": "...", "data": [...]}`.

## Cron Setup

```cron
# Media data collection — adjust paths to your repo root
*/30 * * * * /opt/thoth/agent-server/scripts/media/sonarr_today.sh
0 */6 * * *  /opt/thoth/agent-server/scripts/media/sonarr_upcoming.sh
0 */6 * * *  /opt/thoth/agent-server/scripts/media/radarr_recent.sh
*/15 * * * * /opt/thoth/agent-server/scripts/media/qbit_status.sh
0 * * * *    /opt/thoth/agent-server/scripts/media/jellyseerr_pending.sh
```

## Environment Variables

Set these in `.env` at the repo root:

```bash
SONARR_URL=http://arr-docker-host:8989
SONARR_API_KEY=your-sonarr-api-key
RADARR_URL=http://arr-docker-host:7878
RADARR_API_KEY=your-radarr-api-key
QBIT_URL=http://arr-docker-host:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=your-qbit-password
JELLYSEERR_URL=http://jellyseerr-lxc:5055
JELLYSEERR_API_KEY=your-jellyseerr-api-key
```

## Agent Tools

Tools are registered in `app/tools/local/media.py` and auto-discovered at startup:

| Tool | Description |
|------|-------------|
| `media_today` | Today's expected episodes + download status |
| `media_upcoming` | Episodes airing next 7 days |
| `media_downloads` | Active/stuck torrents |
| `media_requests` | Pending Jellyseerr requests |
| `media_status` | Combined summary of all the above |

To wire into a bot, add the tool names to the bot's `local_tools` list in the admin UI.

Tools warn if data is older than 2 hours and handle missing files gracefully. Free-text fields from external APIs are sanitized against prompt injection patterns.
