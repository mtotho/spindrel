---
tags: [spindrel, track, integrations]
status: active
created: 2026-04-09
---
# Track — Declarative Integrations (integration.yaml)

**Goal:** Define integrations with a single YAML file instead of Python setup.py boilerplate. Bundle MCP servers, carapaces, skills, and config in one declarative manifest.

**Motivation:** Flynn Thoughts deployment needs a YAML-only integration that bundles a Google Workspace MCP server. The current setup.py pattern requires Python code even for config-only integrations.

## Completed (April 9, 2026)

### Phase 1: Foundation
- [x] `IntegrationManifest` DB model (id, name, manifest JSONB, yaml_content, source, content_hash)
- [x] Alembic migration 182
- [x] `app/services/integration_manifests.py` — parse, seed, load, update, check_file_drift
- [x] Startup hook: `seed_manifests()` + `load_manifests()` in main.py

### Phase 2: Dual Discovery
- [x] `_get_setup()` helper in `integrations/__init__.py` — checks manifest cache first, falls back to setup.py
- [x] `_manifest_to_setup()` converts YAML manifest to SETUP-compatible dict
- [x] All 8 `discover_*` functions refactored to use `_get_setup()` instead of inline setup.py loading
- [x] `setup_dict_to_manifest()` converts legacy SETUP dicts for auto-seeding

### Phase 3: MCP Server Registration
- [x] `seed_from_integrations()` in `app/services/mcp_servers.py` — seeds MCP servers from manifests with `source="integration:{id}"`
- [x] Supports both `url:` (external) and `image:` (container, future) declarations
- [x] Wired into startup: manifests seeded → MCP servers seeded → MCP servers loaded

### Phase 4: Per-Channel MCP Scoping
- [x] `channel_overrides.py` — activated integrations inject their MCP servers into effective tools
- [x] `context_assembly.py` — same injection in context assembly path
- [x] Respects `mcp_servers_disabled` channel override

### Phase 5: Admin UI
- [x] API: `GET/PUT /integrations/{id}/yaml` — YAML content for editor
- [x] API: `GET /integrations/{id}/manifest` — enriched manifest with MCP server status + file drift
- [x] API hooks: `useIntegrationManifest`, `useIntegrationYaml`, `useUpdateIntegrationYaml`
- [x] `ManifestEditor.tsx` — Home Assistant-style Visual/YAML toggle
- [x] `MCPServerCard` — status dot, test button, docker run instructions for container servers
- [x] Round-trip editing: YAML edits → parse → DB → Visual tab reflects changes

### Phase 6: Setup Instructions
- [x] Container-based MCP servers show amber "Setup Required" banner
- [x] Docker run command with copy button
- [x] Image/port info stored in MCP server config JSONB

## Example integration.yaml

### Tools-only integration (Excalidraw)
```yaml
id: excalidraw
name: Excalidraw
icon: PenTool
description: Hand-drawn-style diagrams
version: "1.0"

settings:
  - key: EXCALIDRAW_CHROME_PATH
    type: string
    label: "Path to Chrome/Chromium binary"
    required: false

dependencies:
  npm:
    - package: "puppeteer-core + @excalidraw/utils + mermaid"
      check_path: scripts/node_modules      # local path checked for installed status
      local_install_dir: scripts             # npm install runs here, not global

provides:
  - tools
  - skills
```

### Full integration with MCP + binding (Flynn Design)
```yaml
name: Flynn Design
id: flynndesign
icon: Palette
description: Interior design business assistant
version: "1.0"
includes:
  - google_workspace

mcp_servers:
  - id: google-workspace
    display_name: Google Workspace
    image: taylorwilsdon/google_workspace_mcp:latest
    port: 3000
    env:
      - key: GOOGLE_CLIENT_ID
        required: true
      - key: GOOGLE_CLIENT_SECRET
        required: true
        secret: true

settings:
  - key: DEFAULT_TIMEZONE
    type: string
    label: Timezone
    default: America/New_York

activation:
  carapaces:
    - flynn-design
  config_fields:
    - key: client_name
      type: string
      label: Client Name
```

### npm dependency fields
| Field | Purpose | Default |
|---|---|---|
| `package` | Display name shown in admin UI | required |
| `binary_name` | Binary to `which` check for installed status | `package` value |
| `check_path` | Local path to check instead of `which` (relative to integration dir) | none |
| `local_install_dir` | Directory with `package.json` for local `npm install` | none (global) |

### Phase 7: Local npm dependencies + integration settings (2026-04-12)
- [x] `check_path` field on `npm_dependencies` — checks a local path (e.g. `scripts/node_modules`) instead of `which(binary_name)` for installed status
- [x] `local_install_dir` field — `install-npm-deps` endpoint runs `npm install` in a specified directory instead of global install
- [x] Both are generic features in `integrations/__init__.py` and `app/routers/api_v1_admin/integrations.py`
- [x] First consumer: Excalidraw integration (installs puppeteer-core + @excalidraw/utils + mermaid locally in `scripts/`)

## Deferred to v2

- [ ] Container lifecycle management (auto docker run/stop from image: declarations)
- [ ] Port management, health checks, cleanup for hosted MCP containers
- [ ] File diff viewer when source file drifts from DB copy

## Key Files

| File | Role |
|---|---|
| `app/db/models.py` | IntegrationManifest model |
| `app/services/integration_manifests.py` | Parser, seeder, cache |
| `app/services/mcp_servers.py` | Integration-aware MCP seeding |
| `integrations/__init__.py` | `_get_setup()` + `_manifest_to_setup()` helpers |
| `app/routers/api_v1_admin/integrations.py` | YAML/manifest API endpoints |
| `app/agent/channel_overrides.py` | Per-channel MCP injection |
| `app/agent/context_assembly.py` | Per-channel MCP injection (context path) |
| `ui/.../ManifestEditor.tsx` | Visual/YAML editor component |
| `integrations/example_yaml/` | Example YAML-only integration |
