---
category: workspace_schema
description: Media library management — request tracking, quality profiles, download monitoring, and library organization.
compatible_integrations: arr
tags: media, sonarr, radarr, jellyfin
---
## Workspace File Organization — Media Management

Organize channel workspace files as follows:

- **requests.md** — Active media requests: what's been asked for, search status, availability
- **library.md** — Library overview: collection stats, quality profile preferences, storage notes
- **issues.md** — Current problems: failed downloads, missing subtitles, quality upgrades needed
- **notes.md** — General notes, user preferences, watch recommendations

### Guidelines
- When a user requests media, search first (Sonarr for TV, Radarr for movies, Jellyseerr for requests)
- Track requests in requests.md so you remember what's pending
- Log recurring issues (subtitle failures, quality mismatches) in issues.md for pattern detection
- Archive resolved requests and fixed issues to the archive/ folder
