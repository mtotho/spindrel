# Activation & Workspace Templates

This guide explains how integrations interact with channel workspaces — integration-provided tools and optional templates.

---

## The Layering Model

When an integration is **activated** on a channel:

1. **Tool activation** (automatic): The integration's declared tools become available on that channel.
2. **Workspace templates** (optional): Pre-defined file organization schemas remain available in advanced channel settings.

**Key principle:** there is no separate capability bundle. Integrations expose tools through activation metadata, and any related knowledge lives in normal skills or prompt templates.

---

## Templates

Templates are workspace schema definitions that define file structures for different project types. They are optional — most users don't need to select one.

### File-managed templates

Templates are synced from `prompts/*.md` and `integrations/*/prompts/*.md`:

```yaml
---
name: "My Custom Schema"
description: "A workspace schema for game development projects"
category: workspace_schema
tags:
  - gamedev
  - software
---

## Workspace File Organization
...
```

### Manual templates

Created via the admin UI template editor.

---

## Worked Example — GitHub

### 1. Activation manifest (`integrations/github/integration.yaml`)

```yaml
id: github
name: GitHub
version: "1.0"

activation:
  requires_workspace: false
  description: "GitHub repository management — PR reviews, issue tracking, code push events, and release monitoring"

provides:
  - target
  - renderer
  - router
  - tools
  - skills
```

`provides` lists what the integration ships. Tools listed under `provides: [tools]` are auto-discovered from `integrations/github/tools/`; skills come from `integrations/github/skills/`. There is no separate capability bundle — declared tools are exposed when the channel activates the integration, and skills enter the normal skill RAG pool.

### 2. Integration assets

GitHub ships its tools directly (PR ops, issue ops, release ops), plus normal skill packs that teach the bot the GitHub conventions. Skills are retrieved on demand via RAG, not pinned per channel.

### 3. User flow

1. User activates GitHub on a channel
2. The integration's declared tools become available on that channel
3. The skill pack surfaces in RAG when the bot is reasoning about repos or PRs
4. Power users can optionally link a workspace schema template (e.g. DevOps) in advanced settings to override the default file organization

---

## Creating a Custom Template

1. Create `prompts/my-template.md` (or in any scanned prompts directory)

2. Add frontmatter:
   ```yaml
   ---
   name: "Game Development"
   description: "Workspace schema for game projects with task tracking"
   category: workspace_schema
   tags:
     - gamedev
     - software
   ---
   ```

3. Define file structures relevant to your project type

4. Restart server — template is auto-synced and appears in the advanced template picker

---

## Integration Versioning

- **Purpose:** Human-readable identifier for integration revisions
- **Declared in:** top-level `version:` field in `integration.yaml`
- **Exposed via:** Available integrations API (`version` field) and admin UI
- **Convention:** `"MAJOR.MINOR"` — no semver enforcement, no runtime compatibility checks
- **Used for:** UI display, documentation, debugging

---

## For Integration Developers

When building an integration that needs workspace file organization:

1. Put the file-organization guidance in shipped skills or prompt templates.
2. Don't create a separate template unless the file structure is complex enough to warrant a full schema document.
3. Activation should expose tools; documentation and file conventions should live in the normal skills/prompts surfaces.
