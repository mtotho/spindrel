# Integration Status

This page is the honest status snapshot for Spindrel's integrations.

It is **not** a marketing matrix. If something is rough, partial, untested, or likely to change, this page should say so plainly.

**Snapshot date:** 2026-04-21

## Status meanings

| Status | Meaning |
|---|---|
| `working` | Actively usable now; core flow is expected to work |
| `working (beta)` | Usable, but still new or carrying meaningful caveats |
| `partial` | Important pieces work, but known gaps or direction changes remain |
| `untested` | Code exists, but current manual validation is missing or incomplete |
| `experimental` | In tree, but not yet something to promise to users |

## Current matrix

| Integration | Status | What it currently does | Notes |
|---|---|---|---|
| Slack | `working` | Mature chat integration with mentions, threads, reactions, App Home, shortcuts, modals, ephemeral messages, scheduled/pin/bookmark tools | Slack depth pilot shipped 2026-04-17 and is the current reference-grade integration |
| Discord | `untested` | Gateway-based chat integration with slash commands and channel bindings | Present in tree, but the roadmap explicitly says Discord audit is next; treat as not yet validated end-to-end |
| BlueBubbles | `partial` | iMessage bridge via BlueBubbles with webhook delivery and bindings | Usable in parts, but not yet at the same confidence level as Slack; roadmap puts BlueBubbles depth after Discord |
| Browser Live | `untested` | Real logged-in browser control via paired Chrome extension: goto, act, eval, screenshot, status | v0.1 shipped 2026-04-19; powerful and promising, but not yet something to claim as validated |
| Home Assistant | `working` | MCP-backed HA control with entity targeting and rich widgets (toggle, brightness slider, live state polling) | The MCP + skills + widgets path is working |
| Excalidraw | `working` | Hand-drawn diagram rendering from Mermaid or Excalidraw JSON | Tested and working |
| Google Workspace | `partial` | Google OAuth, Drive/Gmail/Calendar/Docs/etc. access through the GWS CLI | Slightly tested; some pieces work, but it is still not a fully trusted path |
| ARR | `working` | Sonarr/Radarr/qBittorrent/Jellyfin/Jellyseerr/Bazarr control and browsing | Large surface area, but mostly tested and working |
| Claude Code | `partial` | Runs the `claude` CLI inside the workspace Docker environment | Useful, but depends heavily on container/image setup and workspace model; not something to call polished yet |
| Frigate | `working` | Camera/event tools, MQTT push alerts, snapshots/clips, and widget surface | Tested and working |
| GitHub | `working` | GitHub webhook ingestion plus issue/PR comment dispatch | Working, though the events side is still rough in places |
| Web Search | `working` | SearXNG/DuckDuckGo search, fetch, and widget rendering | Tested and working |
| OpenWeather | `working` | Weather tools with current conditions / forecast widget output | Actively used in the widget stack; expected to work |
| Wyoming | `working` | Voice-assistant flow via Wyoming satellites / ESPHome devices | Tested working, roughly; still an advanced hardware/audio setup |
| Firecrawl | `working` | Firecrawl-backed crawling/extraction integration | Tested and working |
| VS Code | `experimental` | In tree | Not documented as a polished user-facing integration yet |
| Ingestion | `experimental` | Shared ingestion/security framework for feed-style integrations | More of a platform/framework integration than a polished end-user binding |

## Omitted on purpose

- **Gmail** is intentionally omitted from this table because it is on the way out.

## Notes

- This table is intentionally conservative. If an integration sits between two labels, it should usually get the less flattering one.
- "Working" does not mean "every edge case is closed." It means the core path is expected to work for real use.
- Integrations with external dependencies inherit the reliability of those dependencies: OAuth setup, webhooks, Docker services, browsers, hardware, third-party APIs, and local network conditions all matter.

## See also

- [Creating Integrations](../integrations/index.md)
- [Slack Integration](slack.md)
- [Browser Live](browser-live.md)
- [Home Assistant](homeassistant.md)
- [Excalidraw](excalidraw.md)
