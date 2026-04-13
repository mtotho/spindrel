# Excalidraw

Hand-drawn-style diagram generation — from Excalidraw JSON or Mermaid syntax.

Built on [Excalidraw](https://excalidraw.com) (MIT) and [Puppeteer](https://pptr.dev) (Apache-2.0).

## Requirements

These tools run in the **server process** (not the agent workspace). All dependencies must be on the server host.

**On the server host** (bare metal or inside the server Docker container):

1. **Node.js / npm** — for export scripts
2. **Chromium or Google Chrome** — for headless rendering via Puppeteer
   - Debian/Ubuntu: `apt install chromium`
   - Auto-detected from: `/usr/bin/chromium`, `/usr/bin/google-chrome-stable`, `/usr/bin/google-chrome`
   - Or configure `EXCALIDRAW_CHROME_PATH` in the settings below
   - Or set the `CHROME_PATH` environment variable on the server process

**Docker users**: add `chromium` to your server Dockerfile:
```dockerfile
RUN apt-get update && apt-get install -y chromium
```

## Install

Click **Install Dependencies** above to install the npm packages. They install locally inside `integrations/excalidraw/scripts/node_modules/` — no global packages.

First diagram render takes ~3-5s (Puppeteer cold start). Subsequent renders are faster (~1-2s).

## What's included

| Asset | Purpose |
|-------|---------|
| `create_excalidraw` | Tool — render Excalidraw element JSON to SVG/PNG |
| `mermaid_to_excalidraw` | Tool — convert Mermaid syntax to hand-drawn Excalidraw image |
| `excalidraw` skill | Element reference, color palette, and diagram patterns for bots |

## How it works

1. Bot calls `create_excalidraw` or `mermaid_to_excalidraw`
2. Python tool writes JSON/Mermaid to a temp file
3. Shells out to Node.js export script → launches headless Chrome → loads `@excalidraw/utils` UMD bundle in the browser page → renders to SVG/PNG
4. Output bytes → `create_attachment(type="image")` → image appears inline in chat
5. For Slack/Discord: `client_action: upload_file` triggers native file upload
