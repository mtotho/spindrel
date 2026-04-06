# Activation & Workspace Templates

This guide explains how integrations interact with channel workspaces — capability injection and optional templates.

---

## The Layering Model

When an integration is **activated** on a channel:

1. **Capability injection** (automatic): Tools, skills, and a system prompt fragment are injected into every agent call. The bot gains new capabilities without any manual configuration. The capability's `system_prompt_fragment` also teaches the bot how to organize workspace files for this integration.

2. **Workspace templates** (optional, power-user): Pre-defined file organization schemas available in advanced channel settings. Not required — integration capabilities teach file organization directly.

**Key principle:** Integration capabilities are self-contained. They provide tools, skills, behavioral instructions, AND workspace file organization guidance in their `system_prompt_fragment`. Templates exist as an optional override mechanism for power users who want a specific structure.

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

## Worked Example — Mission Control

### 1. Activation manifest (`integrations/mission_control/setup.py`)

```python
SETUP = {
    "version": "1.0",
    "activation": {
        "carapaces": ["mission-control"],
        "requires_workspace": True,
    },
}
```

### 2. Capability

`integrations/mission_control/carapaces/mission-control.yaml` declares tools (`create_task_card`, `move_task_card`, etc.), skills, and a system prompt fragment that teaches the bot both the MC protocol AND workspace file organization (which files to create, their format, which are tool-managed vs manually edited).

### 3. User flow

1. User activates Mission Control on a channel
2. Capability injection adds MC tools, skills, AND file organization guidance automatically
3. Bot knows how to create task boards, manage plans, and organize workspace files — no template selection needed
4. Power users can optionally link a template in advanced settings to override the default file organization

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
- **Declared in:** `SETUP["version"]` in `setup.py`
- **Exposed via:** Available integrations API (`version` field) and admin UI
- **Convention:** `"MAJOR.MINOR"` — no semver enforcement, no runtime compatibility checks
- **Used for:** UI display, documentation, debugging

---

## For Integration Developers

When building an integration that needs workspace file organization:

1. **Put file org guidance in your carapace's `system_prompt_fragment`** — describe which files the bot should create, their format, which are tool-managed (read-only) vs manually edited
2. **Don't create a separate template** unless the file structure is complex enough to warrant a full schema document
3. The `system_prompt_fragment` is injected into every conversation where your integration is activated — it's the right place for "how to organize files" instructions
