# Excalidraw

Hand-drawn-style diagram generation for Spindrel bots.

Built on [Excalidraw](https://excalidraw.com) (MIT) and [excalidraw_export](https://github.com/Timmmm/excalidraw_export) (MIT).

## Requirements

- Node.js / npx (auto-installs CLI tools on first use)

If `canvas` prebuilt binaries fail on your platform:
```bash
apt-get install libcairo2-dev libjpeg-dev libpango1.0-dev libgif-dev build-essential
```

## What's included

- `tools/excalidraw.py` — `create_excalidraw` and `mermaid_to_excalidraw` tools
- `scripts/mermaid_convert.mjs` — Mermaid → Excalidraw JSON converter
- `skills/excalidraw.md` — element reference and patterns for bots
