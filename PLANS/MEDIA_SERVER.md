---
status: planned
last_updated: 2026-03-22
owner: mtoth
summary: >
  Dedicated media bot integrating Michael's *arr stack (Sonarr, Radarr, Prowlarr,
  Jellyfin, Jellyseerr, qBittorrent, Bazarr) via REST APIs. Own Slack channel,
  heartbeat-driven monitoring, phased rollout from read-only queries to proactive alerts.
---

# Media Server Integration

## Goals

1. **Single-channel media bot** — dedicated Slack channel with its own bot config and heartbeat
2. **Query the *arr stack** — today's episodes, download status, pending requests, stuck torrents
3. **Take actions** — request media, trigger searches, manage torrents, manage Jellyfin users
4. **Proactive monitoring** — alert on missing downloads, stuck torrents, failed grabs, disk pressure
5. **VM maintenance** — SSH-based health checks on the media server Proxmox node

---

## Architecture

### Infrastructure Layout

```
┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
│  Proxmox Node A (Thoth VM)           │     │  Proxmox Node B (Media Server VM)    │
│                                      │     │                                      │
│  thoth.service (agent-server)        │────▶│  Sonarr       :8989  (TV)            │
│    └─ media bot (media_bot.yaml)     │ API │  Radarr       :7878  (Movies)        │
│       └─ integrations/sonarr/        │     │  Prowlarr     :9696  (Indexers)      │
│       └─ integrations/radarr/        │     │  Jellyfin     :8096  (Streaming)     │
│       └─ integrations/jellyfin/      │     │  Jellyseerr   :5055  (Requests)      │
│       └─ integrations/qbittorrent/   │     │  qBittorrent  :8080  (Downloads)     │
│       └─ integrations/bazarr/        │     │  Bazarr       :6767  (Subtitles)     │
│       └─ integrations/jellyseerr/    │     │                                      │
│       └─ integrations/prowlarr/      │     │  SSH :22 (VM maintenance)            │
└──────────────────────────────────────┘     └──────────────────────────────────────┘
```

### Bot Config

```yaml
# bots/media_bot.yaml
id: media_bot
name: "Media Bot"
model: gemini/gemini-2.5-flash
system_prompt: |
  You are the media server assistant. You help Michael manage his home media stack:
  Sonarr (TV), Radarr (movies), Jellyfin (streaming), Jellyseerr (requests),
  qBittorrent (downloads), Bazarr (subtitles), and Prowlarr (indexers).

  When reporting download status, be concise — use tables or bullet lists.
  When something is wrong (stuck torrent, failed grab, missing episode), lead with the problem.
local_tools:
  - sonarr_today
  - sonarr_upcoming
  - sonarr_search_missing
  - radarr_recent
  - radarr_search_missing
  - qbittorrent_list
  - qbittorrent_manage
  - jellyseerr_pending
  - jellyseerr_request
  - jellyfin_manage_user
  - bazarr_status
  - media_health_check
  - media_disk_usage
pinned_tools:
  - sonarr_today
  - qbittorrent_list
tool_retrieval: true
context_compaction: true
compaction_interval: 10
memory:
  enabled: true
  cross_channel: false
```

### Heartbeat Cadence

| Schedule | What | Why |
|----------|------|-----|
| Every 30 min | Service health pings (HTTP status of each service) | Catch downtime fast |
| 8:00 PM daily | Evening check — today's expected episodes vs. actually downloaded | Alert on missing shows before bedtime |
| Sunday 10:00 AM | Weekly summary — downloads, failures, pending requests, disk usage | Big picture review |

### Slack Channel

- `#media` — dedicated channel, only the media bot posts here
- Heartbeat messages go here; ad-hoc queries also happen here
- Thread replies for details (e.g., "3 episodes missing" → thread lists which ones)

### API Key Storage

All stored in `.env`, loaded via `app/config.py`:

```bash
# Media Server — *arr stack
SONARR_URL=http://media-server:8989
SONARR_API_KEY=...
RADARR_URL=http://media-server:7878
RADARR_API_KEY=...
PROWLARR_URL=http://media-server:9696
PROWLARR_API_KEY=...
JELLYFIN_URL=http://media-server:8096
JELLYFIN_API_KEY=...
JELLYSEERR_URL=http://media-server:5055
JELLYSEERR_API_KEY=...
QBITTORRENT_URL=http://media-server:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=...
BAZARR_URL=http://media-server:6767
BAZARR_API_KEY=...
MEDIA_SERVER_SSH_HOST=media-server
MEDIA_SERVER_SSH_USER=thoth
MEDIA_SERVER_SSH_KEY_PATH=/opt/thoth/.ssh/media_server_ed25519
```

### Integration Folder Structure

```
integrations/
├── sonarr/
│   ├── __init__.py
│   ├── client.py          # SonarrClient — thin wrapper around REST API
│   └── tools.py           # @register'd tools: sonarr_today, sonarr_upcoming, sonarr_search_missing
├── radarr/
│   ├── __init__.py
│   ├── client.py           # RadarrClient
│   └── tools.py            # radarr_recent, radarr_search_missing
├── qbittorrent/
│   ├── __init__.py
│   ├── client.py           # QBittorrentClient (handles cookie auth)
│   └── tools.py            # qbittorrent_list, qbittorrent_manage
├── jellyfin/
│   ├── __init__.py
│   ├── client.py           # JellyfinClient
│   └── tools.py            # jellyfin_manage_user
├── jellyseerr/
│   ├── __init__.py
│   ├── client.py           # JellyseerrClient
│   └── tools.py            # jellyseerr_pending, jellyseerr_request
├── bazarr/
│   ├── __init__.py
│   ├── client.py           # BazarrClient
│   └── tools.py            # bazarr_status
├── prowlarr/
│   ├── __init__.py
│   ├── client.py           # ProwlarrClient
│   └── tools.py            # (Phase 3 — indexer health)
└── media_common/
    ├── __init__.py
    └── health.py           # media_health_check, media_disk_usage (SSH-based)
```

Each `client.py` follows the same pattern — an async class using `httpx.AsyncClient` with base URL and API key from config. Each `tools.py` registers tools via `@register(openai_schema)` that call the client.

---

## Phase 1 — Core Query Tools

*Highest value, lowest effort. Read-only API calls, no side effects.*

**Effort: ~2-3 days**

### Sonarr

#### `sonarr_today`
Returns today's expected episodes and whether they've downloaded.

```python
# GET /api/v3/calendar?start={today}&end={tomorrow}
# Returns list of episodes with: seriesTitle, seasonNumber, episodeNumber, title, hasFile, airDateUtc
```

**Output format:**
```
Today's Episodes (March 22):
✓ Severance — S02E10 "Cold Harbor" — downloaded
✗ The Last of Us — S02E04 "Grounded" — missing (airs 9:00 PM)
✓ Reacher — S03E06 — downloaded
```

#### `sonarr_upcoming`
Episodes airing this week (next 7 days).

```python
# GET /api/v3/calendar?start={today}&end={today+7}
```

### Radarr

#### `radarr_recent`
Recently added movies and their download status.

```python
# GET /api/v3/movie?sortKey=dateAdded&sortDirection=descending
# Filter to last 14 days, check hasFile and movieFile status
```

#### `radarr_download_status`
Currently downloading/queued movies.

```python
# GET /api/v3/queue?includeMovie=true
```

### qBittorrent

#### `qbittorrent_list`
List active and stuck torrents. Flag anything with state `stalledDL` or older than 24h without progress.

```python
# POST /api/v2/auth/login (cookie auth — see API Reference)
# GET /api/v2/torrents/info?filter=active
# GET /api/v2/torrents/info?filter=stalled
```

**Output format:**
```
Active Torrents (3):
  Severance.S02E10 — 78% — 12.3 MB/s — ETA 4min
  The.Last.of.Us.S02E04 — queued

⚠ Stuck Torrents (1):
  Old.Movie.2024 — stalledDL — 0 B/s for 26 hours
```

### Jellyseerr

#### `jellyseerr_pending`
Pending media requests awaiting approval or processing.

```python
# GET /api/v1/request?take=20&filter=pending&sort=added
```

### Bazarr

#### `bazarr_status`
Subtitle status — wanted vs. available, any failed downloads.

```python
# GET /api/episodes?wanted=true   (missing subtitles for TV)
# GET /api/movies?wanted=true     (missing subtitles for movies)
```

### Phase 1 Deliverables

- [ ] `integrations/sonarr/client.py` + `tools.py`
- [ ] `integrations/radarr/client.py` + `tools.py`
- [ ] `integrations/qbittorrent/client.py` + `tools.py`
- [ ] `integrations/jellyseerr/client.py` + `tools.py`
- [ ] `integrations/bazarr/client.py` + `tools.py`
- [ ] `bots/media_bot.yaml`
- [ ] `.env` additions documented
- [ ] Basic smoke tests for each client

---

## Phase 2 — Action Tools

*Write operations. Require more care — confirm destructive actions with the user.*

**Effort: ~2-3 days**

### Jellyseerr

#### `jellyseerr_request`
Request a show or movie by name. Searches Jellyseerr, confirms the match with the user, then submits the request.

```python
# GET /api/v1/search?query={name}&page=1&language=en
# POST /api/v1/request  { mediaType, mediaId, seasons (for TV) }
```

### Jellyfin

#### `jellyfin_manage_user`
Create user, delete user, reset password.

```python
# POST /Users/New         — create user
# DELETE /Users/{userId}  — delete user
# POST /Users/{userId}/Password — reset password
```

### Sonarr

#### `sonarr_search_missing`
Trigger an automatic search for a specific missing episode or all missing episodes for a series.

```python
# POST /api/v3/command  { name: "EpisodeSearch", episodeIds: [...] }
# POST /api/v3/command  { name: "MissingEpisodeSearch" }
```

### Radarr

#### `radarr_search_missing`
Trigger search for a specific missing movie.

```python
# POST /api/v3/command  { name: "MoviesSearch", movieIds: [...] }
```

### qBittorrent

#### `qbittorrent_manage`
Pause, resume, or delete a torrent by hash.

```python
# POST /api/v2/torrents/pause    { hashes: "..." }
# POST /api/v2/torrents/resume   { hashes: "..." }
# POST /api/v2/torrents/delete   { hashes: "...", deleteFiles: true/false }
```

**Safety:** The bot should confirm before deleting with `deleteFiles: true`. Present the torrent name and size first.

### Phase 2 Deliverables

- [ ] `jellyseerr_request` tool with search + confirm flow
- [ ] `jellyfin_manage_user` tool (create/delete/reset)
- [ ] `sonarr_search_missing` tool
- [ ] `radarr_search_missing` tool
- [ ] `qbittorrent_manage` tool (pause/resume/delete)
- [ ] Confirmation UX for destructive actions

---

## Phase 3 — Proactive Heartbeat Monitoring

*The bot checks things on a schedule and alerts in `#media` when something needs attention.*

**Effort: ~2-3 days**

### Alert Conditions

| Condition | Check | Severity |
|-----------|-------|----------|
| Today's expected shows haven't downloaded by 8 PM | Sonarr calendar + `hasFile` check | High |
| Torrent stuck >24h (stalledDL, no progress) | qBittorrent torrent list + `last_activity` | Medium |
| Sonarr/Radarr failed grab | Sonarr/Radarr `/api/v3/history?eventType=grabbed` with `data.downloadClient` failures | High |
| Disk usage >90% on media drives | SSH `df -h` or Sonarr `/api/v3/diskspace` | High |
| Service unreachable | HTTP health check on each service URL | Critical |
| Prowlarr indexer down | Prowlarr `/api/v1/indexerstatus` | Medium |

### Evening Check (8:00 PM)

```
🎬 Evening Media Check — March 22

TV:
  ✓ Severance S02E10 — downloaded, subtitles ready
  ✗ The Last of Us S02E04 — NOT DOWNLOADED (aired 3h ago)
    → Triggered search via Sonarr

Movies:
  ✓ No pending downloads

Torrents:
  2 active, 0 stuck

Disk: /media — 62% used (1.8 TB free)
```

### Weekly Summary (Sunday 10:00 AM)

```
📊 Weekly Media Summary — March 16-22

Downloaded this week:
  TV: 12 episodes across 5 shows
  Movies: 2 (Dune: Part Three, The Brutalist)
  Subtitles: 14 fetched, 1 still missing

Failed/Retried:
  1 failed grab (Reacher S03E05 — retried successfully)

Pending Requests:
  2 movie requests awaiting processing

Storage:
  /media — 62% (1.8 TB free), +48 GB this week
  Estimated weeks until 90%: ~11
```

### Implementation Notes

- Heartbeat checks use the existing `heartbeat_worker` infrastructure in `app/services/heartbeat.py`
- The media bot's heartbeat config in its YAML defines the schedule
- Each check is a tool call the heartbeat invokes on schedule
- Alerts post to `#media` with appropriate severity formatting

### Phase 3 Deliverables

- [ ] Heartbeat schedule config in `media_bot.yaml`
- [ ] Evening check routine (8 PM)
- [ ] Weekly summary routine (Sunday 10 AM)
- [ ] Alert formatting (severity levels, thread details)
- [ ] `integrations/prowlarr/` client + indexer health tool

---

## Phase 4 — VM Maintenance

*SSH-based checks on the media server host. Secondary priority — nice to have for the weekly summary.*

**Effort: ~1-2 days**

### Tools

#### `media_health_check`
SSH to the media server and check:

- All Docker containers running (`docker ps --format`)
- System load average
- Uptime
- Memory usage

```python
# SSH command: docker ps --format '{{.Names}}\t{{.Status}}' && cat /proc/loadavg && uptime && free -h
```

#### `media_disk_usage`
Check disk usage on all relevant mount points.

```python
# SSH command: df -h /media /downloads /config
```

#### `media_apt_updates`
Check for pending apt updates on the media server.

```python
# SSH command: apt list --upgradable 2>/dev/null | tail -n +2 | wc -l
```

### SSH Setup

- Dedicated SSH key pair for the Thoth agent
- Key stored at `MEDIA_SERVER_SSH_KEY_PATH` (default: `/opt/thoth/.ssh/media_server_ed25519`)
- Media server `authorized_keys` entry restricted: `command="/usr/local/bin/thoth-ssh-gate"` for safety (optional)
- Use `asyncssh` library for non-blocking SSH execution

### Phase 4 Deliverables

- [ ] `integrations/media_common/health.py` — SSH-based health tools
- [ ] SSH key setup documentation
- [ ] `media_health_check` tool
- [ ] `media_disk_usage` tool
- [ ] `media_apt_updates` tool

---

## API Reference

### Shared *arr API Pattern (Sonarr, Radarr, Prowlarr)

All *arr applications use the same API framework (v3). Auth and request patterns are identical:

```python
import httpx

class ArrClient:
    """Base client for *arr APIs (Sonarr, Radarr, Prowlarr)."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Api-Key": self.api_key},
            timeout=30.0,
        )

    async def get(self, path: str, **params) -> dict | list:
        resp = await self.client.get(f"/api/v3{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: dict = None) -> dict:
        resp = await self.client.post(f"/api/v3{path}", json=json)
        resp.raise_for_status()
        return resp.json()
```

**Common endpoints across *arr apps:**

| Endpoint | What |
|----------|------|
| `GET /api/v3/system/status` | Health check — version, uptime, OS |
| `GET /api/v3/calendar` | Upcoming media (episodes/movies) |
| `GET /api/v3/queue` | Download queue |
| `GET /api/v3/history` | Event history (grabs, downloads, failures) |
| `GET /api/v3/diskspace` | Disk usage for configured root folders |
| `POST /api/v3/command` | Trigger actions (search, rename, backup) |

### Per-Service Details

| Service | Base URL Pattern | Auth Method | API Version |
|---------|-----------------|-------------|-------------|
| Sonarr | `http://host:8989` | `X-Api-Key` header | v3 |
| Radarr | `http://host:7878` | `X-Api-Key` header | v3 |
| Prowlarr | `http://host:9696` | `X-Api-Key` header | v1 (not v3) |
| Jellyfin | `http://host:8096` | `Authorization: MediaBrowser Token="..."` | REST (no versioned path) |
| Jellyseerr | `http://host:5055` | `X-Api-Key` header | v1 (`/api/v1/`) |
| Bazarr | `http://host:6767` | `X-Api-Key` header (or `apikey` query param) | `/api/` (no version prefix) |
| qBittorrent | `http://host:8080` | Cookie-based (see below) | v2 (`/api/v2/`) |

### qBittorrent Cookie Auth Quirk

qBittorrent does **not** use API keys. It uses session cookies obtained via a login endpoint. The cookie (`SID`) must be stored and sent with every subsequent request. It expires after inactivity (default: 3600s).

```python
class QBittorrentClient:
    """Client for qBittorrent Web API. Handles cookie-based auth."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        # httpx.AsyncClient automatically stores and resends cookies
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        self._authenticated = False

    async def _ensure_auth(self):
        if self._authenticated:
            return
        resp = await self.client.post("/api/v2/auth/login", data={
            "username": self.username,
            "password": self.password,
        })
        if resp.text == "Ok.":
            self._authenticated = True
        else:
            raise RuntimeError(f"qBittorrent auth failed: {resp.text}")

    async def get(self, path: str, **params):
        await self._ensure_auth()
        resp = await self.client.get(f"/api/v2{path}", params=params)
        if resp.status_code == 403:
            # Session expired — re-auth and retry
            self._authenticated = False
            await self._ensure_auth()
            resp = await self.client.get(f"/api/v2{path}", params=params)
        resp.raise_for_status()
        return resp.json()
```

**Key gotcha:** If the qBittorrent web UI has "bypass auth for clients on localhost" enabled, and the agent is on a different host, auth is still required. The `SID` cookie can expire silently — always handle 403 with a re-login.

### Jellyfin Auth

Jellyfin uses a custom `Authorization` header format:

```
Authorization: MediaBrowser Token="<api_key>", Client="Thoth", Device="AgentServer", DeviceId="thoth-1", Version="1.0.0"
```

API keys are created in Jellyfin Dashboard → API Keys. No versioned path prefix — endpoints are at the root (e.g., `GET /Users`, `POST /Users/New`).

### Prowlarr Note

Prowlarr uses API v1, not v3 like Sonarr/Radarr. The `ArrClient` base class should accept a configurable API version prefix.

---

## Implementation Order & Effort Estimates

### Recommended Order

```
Phase 1a: Foundation + Sonarr + qBittorrent          ~1 day
  ├─ media_common/ base client
  ├─ integrations/sonarr/ (client + tools)
  ├─ integrations/qbittorrent/ (client + tools)
  └─ bots/media_bot.yaml (minimal)

Phase 1b: Radarr + Jellyseerr + Bazarr               ~1 day
  ├─ integrations/radarr/ (client + tools)
  ├─ integrations/jellyseerr/ (client + tools)
  └─ integrations/bazarr/ (client + tools)

Phase 2a: Action tools (Sonarr/Radarr search)        ~1 day
  ├─ sonarr_search_missing
  ├─ radarr_search_missing
  └─ qbittorrent_manage (pause/resume/delete)

Phase 2b: Jellyseerr requests + Jellyfin users        ~1 day
  ├─ jellyseerr_request (search + confirm + submit)
  └─ jellyfin_manage_user (create/delete/reset)

Phase 3: Heartbeat + proactive alerts                 ~2-3 days
  ├─ Heartbeat schedule wiring
  ├─ Evening check routine
  ├─ Weekly summary routine
  ├─ Alert formatting
  └─ integrations/prowlarr/ (indexer health)

Phase 4: VM maintenance (SSH)                         ~1-2 days
  ├─ SSH client setup (asyncssh)
  ├─ media_health_check
  ├─ media_disk_usage
  └─ media_apt_updates
```

**Total estimate: ~7-10 days**

### Start With

**Phase 1a (Sonarr + qBittorrent)** — these two alone answer the most common question: "Did my shows download?" Getting `sonarr_today` and `qbittorrent_list` working first gives immediate daily value.

### Open Questions

1. **Prowlarr scope** — Is Prowlarr integration needed beyond indexer health checks? It mainly manages indexers for Sonarr/Radarr, which already work independently.
2. **Jellyfin playback stats** — Should the bot report "most watched" or playback history? Jellyfin has plugins (Playback Reporting) for this but it adds complexity.
3. **Multi-user Jellyseerr** — Are there multiple Jellyseerr users whose requests need managing, or just Michael's?
4. **qBittorrent categories** — Does the setup use categories (e.g., `tv-sonarr`, `radarr`) to separate TV vs. movie torrents? This affects how we filter and report.
5. **VPN kill switch** — Does qBittorrent run behind a VPN? If so, should the bot monitor VPN status as part of health checks?
6. **Notification overlap** — Sonarr/Radarr may already send notifications (Discord, email). Should the bot replace those or supplement them?

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Media server unreachable (network/VPN) | All tools fail | Health check pings first; degrade gracefully with "media server unreachable" message |
| qBittorrent cookie expiry mid-session | Silent auth failure | Auto re-login on 403 (implemented in client) |
| API breaking changes on *arr updates | Tools return errors | Pin expected API versions; version check on startup |
| Sonarr/Radarr API rate limiting | Throttled during heavy queries | Single shared client with connection pooling; avoid polling loops |
| SSH key compromise | Unauthorized host access | Dedicated key with restricted `command=` in `authorized_keys`; no root access |
| Large queue/history responses | Slow/OOM on massive libraries | Paginate all list endpoints; cap results (e.g., top 50 torrents) |
