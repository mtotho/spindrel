# Activation & Template Compatibility

This guide explains how integrations interact with channel workspace templates — the layering model, compatibility declarations, and how to create compatible templates for existing or new integrations.

---

## The Layering Model

When an integration is **activated** on a channel, two independent layers engage:

1. **Carapace injection** (automatic): Tools, skills, and a system prompt fragment are injected into every agent call. The bot gains new capabilities without any manual configuration.

2. **Workspace template** (user-selected): Defines the `.md` file structure for the channel workspace. This is NOT auto-selected — the user picks a template (or writes a custom schema).

**Key principle:** Templates do NOT repeat integration behavioral instructions. The carapace provides "how to behave" (tools, skills, prompts); the template provides "what files to work with" (file layout, column formats, section headings).

What happens without a compatible template: the integration's tools still work, but the bot lacks structural guidance and may create files in unexpected formats.

---

## What "Compatible" Means

A template is **compatible** with an integration when its file structure supports the integration's tools.

**Example — Mission Control:**
- `create_task_card` writes to `tasks.md` expecting kanban columns (Backlog, In Progress, Done)
- A compatible template defines `tasks.md` with those exact headings
- An incompatible template might not have `tasks.md` at all, or use a different format

Compatibility is not strictly binary — a general template may partially work but miss some file structures the integration expects.

---

## Declaring Compatibility — Template Side

### File-managed templates (prompts/*.md, integrations/*/prompts/*.md)

Add `compatible_integrations` to the YAML frontmatter:

```yaml
---
name: "My Custom Schema"
description: "A workspace schema for game development projects"
category: workspace_schema
compatible_integrations:
  - mission_control
tags:
  - gamedev
  - software
  - mission-control
---

## Workspace File Organization
...
```

During file sync, `compatible_integrations: [mission_control]` is automatically expanded into `integration:mission_control` tags. The existing `mission-control` tag is preserved for backward compatibility.

### Manual templates (created via UI)

In the template detail page, use the **Integration Compatibility** section to add compatibility. This adds `integration:<id>` tags to the template.

### Tag convention

- **Canonical:** `integration:<integration_id>` (e.g., `integration:mission_control`)
- **Legacy:** `mission-control` (still recognized by MC's activation manifest)
- Both work through the same UI highlighting path

---

## Declaring Compatibility — Integration Side

In `setup.py`, integrations declare which template tags they consider compatible:

```python
SETUP = {
    "version": "1.0",
    # ... other fields ...
    "activation": {
        "carapaces": ["mission-control"],
        "requires_workspace": True,
        "description": "Project management with task boards, plans, and timelines",
        "compatible_templates": ["mission-control"],  # tag(s) to match
    },
}
```

The `compatible_templates` list contains tag values. The UI uses `compatible_templates[0]` as the highlight tag to identify and recommend matching templates.

The `version` field is a human-readable string declared at the SETUP top level, automatically embedded into the activation manifest for API consumers.

---

## Worked Example — Mission Control

### 1. Activation manifest (`integrations/mission_control/setup.py`)

```python
SETUP = {
    "version": "1.0",
    "activation": {
        "carapaces": ["mission-control"],
        "requires_workspace": True,
        "compatible_templates": ["mission-control"],
    },
}
```

### 2. Carapace (`integrations/mission_control/carapaces/mission-control/carapace.yaml`)

Declares 6 tools (`create_task_card`, `move_task_card`, etc.), 5 skills, and a system prompt fragment that teaches the bot the MC protocol.

### 3. Templates (`integrations/mission_control/prompts/*.md`)

Nine workspace schemas, each defining file structures like `tasks.md` (kanban format), `timeline.md`, `status.md`, `plans.md`. All tagged with `mission-control` and `compatible_integrations: [mission_control]`.

### 4. User flow

1. User activates Mission Control on a channel
2. UI detects active integration with `compatible_template_tag: "mission-control"`
3. Workspace Schema section shows recommended templates with green compatibility badges
4. User picks "Software Development" template
5. Bot now has MC tools (from carapace) AND structured file layout (from template)

### 5. Wrong template selected

If the user picks an incompatible template:
- UI shows an orange warning: "Not marked as compatible with Mission Control"
- Tools still work but may create files in unexpected formats
- User can switch to a compatible template at any time

---

## Creating a Custom MC-Compatible Template

1. Create `prompts/my-game-dev.md` (or in any scanned prompts directory)

2. Add frontmatter:
   ```yaml
   ---
   name: "Game Development"
   description: "Workspace schema for game projects with MC task tracking"
   category: workspace_schema
   compatible_integrations:
     - mission_control
   tags:
     - gamedev
     - software
   ---
   ```

3. Define required MC file structures:
   - `tasks.md` — Kanban board (Backlog / In Progress / Done columns)
   - `timeline.md` — Reverse-chronological activity log
   - `status.md` — Phase/health/owner header block
   - `plans.md` — Structured plans with milestones

4. Add domain-specific files:
   - `DESIGN.md` — Game design document
   - `BUILDS.md` — Build status and release notes

5. Restart server — template is auto-synced and shows as MC-compatible in UI

---

## Creating a New Integration with Template Compatibility

For a hypothetical "QA Testing" integration:

### 1. Declare in `setup.py`

```python
SETUP = {
    "version": "1.0",
    "activation": {
        "carapaces": ["qa-testing"],
        "requires_workspace": True,
        "description": "Test planning and execution tracking",
        "compatible_templates": ["qa-testing"],
    },
}
```

### 2. Create a carapace

`integrations/qa_testing/carapaces/qa-testing/carapace.yaml` with tools for test case management, skills for test planning, and a system prompt fragment.

### 3. Create workspace schema templates

`integrations/qa_testing/prompts/qa-workspace.md`:
```yaml
---
name: "QA Test Tracking"
category: workspace_schema
compatible_integrations:
  - qa_testing
tags:
  - testing
  - qa-testing
---
```

### 4. UI behavior

The UI automatically:
- Detects that QA Testing has `compatible_template_tag: "qa-testing"`
- Highlights templates with the `qa-testing` tag
- Shows compatibility badges and section headers
- Warns if an incompatible template is linked

No UI code changes needed — the system is fully generic.

---

## Integration Versioning

- **Purpose:** Human-readable identifier for integration revisions
- **Declared in:** `SETUP["version"]` in `setup.py`
- **Exposed via:** Available integrations API (`version` field) and admin UI
- **Convention:** `"MAJOR.MINOR"` — no semver enforcement, no runtime compatibility checks
- **Used for:** UI display, template compatibility documentation, debugging
