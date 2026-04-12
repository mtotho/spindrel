# Excalidraw

Hand-drawn-style diagram generation — from Excalidraw JSON or Mermaid syntax.

Built on [Excalidraw](https://excalidraw.com) (MIT) and [Puppeteer](https://pptr.dev) (Apache-2.0).

## Requirements

**On the server host** (where the Spindrel process runs):

1. **Node.js / npm** — for export scripts (same as slides/Marp)
2. **Chromium or Google Chrome** — for headless rendering
   - Debian/Ubuntu: `apt install chromium`
   - The path is auto-detected from common locations (`/usr/bin/chromium`, `/usr/bin/google-chrome`, etc.)
   - Or set `EXCALIDRAW_CHROME_PATH` in the integration settings below

Click **Install Dependencies** to install the npm packages. They install locally inside this integration's `scripts/` directory.

## What's included

| Asset | Purpose |
|-------|---------|
| `create_excalidraw` | Tool — render Excalidraw element JSON to SVG/PNG |
| `mermaid_to_excalidraw` | Tool — convert Mermaid syntax to hand-drawn Excalidraw image |
| `excalidraw` skill | Element reference, color palette, and diagram patterns for bots |
