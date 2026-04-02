# Templates & Integration Activation

When you create a channel in Spindrel, it starts as a blank conversation. Templates and integration activation turn it into a structured workspace with the right tools, skills, and file organization for a specific kind of work.

---

## How It Works

Two layers combine to configure a channel:

1. **Integration activation** — Enables an integration on a channel, automatically injecting its tools, skills, and behavioral instructions (via carapaces). One click, no manual tool configuration.

2. **Workspace template** — Defines the file structure for the channel's workspace (which `.md` files to create, their headings, their purpose). Templates are independent of activation — you can use a template without activating anything, or activate without a template.

**Together:** Activate Mission Control on a channel and pick the "Software Development" template. The bot immediately gains project management tools (task boards, plans, timelines) AND knows how to organize workspace files (tasks.md with kanban columns, status.md with phase tracking, etc.).

---

## Activating an Integration

### From the Channel Settings

1. Open a channel and go to the **Integrations** tab
2. You'll see available integrations with activation status
3. Click **Activate** on the integration you want
4. The integration's carapace is injected — tools, skills, and system prompt guidance are now active

### What Activation Does

When you activate an integration, its **activation manifest** kicks in:

- **Carapaces injected** — The integration's carapace(s) are added to the bot's context for this channel. This brings in tools, skills, and a system prompt fragment that teaches the bot how to use them.
- **No manual tool config** — You don't need to add individual tools to the bot's config. The carapace bundles everything.
- **Per-channel** — Activation is scoped to the channel. Other channels using the same bot are unaffected.

### Deactivating

Click **Deactivate** in the Integrations tab. The carapace is removed and the bot loses those capabilities on this channel. Workspace files are not deleted.

---

## Workspace Templates

Templates define the file structure for a channel's workspace. When a bot has `workspace.enabled: true`, the channel workspace is a directory of `.md` files that the bot reads and writes during conversations.

### Picking a Template

1. Open a channel and go to the **Workspace** tab
2. The **Schema** section shows available templates
3. If an integration is activated, **compatible templates** are highlighted with a green badge and shown first under "Suggested templates"
4. Click a template to apply it — the bot will use this structure when creating workspace files

### Built-in Templates

Spindrel ships templates for common workflows:

| Template | Best for | Compatible with | Key files |
|----------|----------|----------------|-----------|
| Software Development | Code projects with task tracking | Mission Control | tasks.md, architecture.md, decisions.md |
| Research / Analysis | Investigation and analysis | — | findings.md, sources.md, questions.md |
| Creative Project | Writing, design, content | — | brief.md, concepts.md, feedback.md |
| General Project | Lightweight catch-all | — | overview.md, notes.md, tasks.md |
| Project Management Hub | Project coordination | Mission Control | status.md, projects.md, reports.md |
| Mission Control | Structured task tracking | Mission Control | tasks.md, status.md, decisions.md |
| Software Testing / QA | Test planning and execution | — | test-plan.md, bugs.md, coverage.md |
| Media Management | Media library and requests | Arr | requests.md, library.md, issues.md |
| Email Digest | Email ingestion and action tracking | Gmail | feeds.md, digest.md, actions.md |
| Home Automation | Device inventory and events | Frigate | devices.md, automations.md, events.md |
| DevOps | Repository and deployment tracking | GitHub | repos.md, prs.md, deployments.md |

### Template Compatibility

Templates can declare compatibility with specific integrations. A "Software Development" template tagged as Mission Control-compatible means its file structure matches what MC tools expect (e.g., `tasks.md` has the kanban column format that `create_task_card` writes to).

**What happens with an incompatible template:** The integration's tools still work, but the bot may create files in unexpected formats or locations. The UI shows an orange warning if your linked template isn't compatible with an active integration.

### Custom Templates

Create templates in two ways:

**From a file** — Add a `.md` file to `prompts/` (or `integrations/*/prompts/`):

```yaml
---
name: "My Custom Schema"
description: "Workspace schema for game development"
category: workspace_schema
compatible_integrations:
  - mission_control
tags:
  - gamedev
---

## Workspace File Organization

### tasks.md
Kanban board with columns: Backlog, In Progress, Testing, Done
...
```

Restart the server — the template is auto-synced.

**From the UI** — In Admin > Templates, create a new template and set compatibility tags.

---

## Recommended Workflow

### Setting Up a New Project Channel

1. **Create a channel** — Give it a name and assign a bot
2. **Enable the workspace** — In the Workspace tab, toggle workspace on (if not enabled by default)
3. **Activate integrations** — In the Integrations tab, activate Mission Control (or other integrations relevant to your work)
4. **Pick a compatible template** — In the Workspace tab, select a suggested template. The green badge means it's designed for your active integration.
5. **Start chatting** — The bot now has the right tools and knows how to organize files. Ask it to create a task board, write a status report, or plan a feature — it knows the formats.

### What You Get

After activation + template selection:

- **Tools** — The bot can create task cards, move items between columns, update status, manage plans (whatever the integration provides)
- **Skills** — The bot has domain knowledge about the integration's workflows (e.g., how to run a standup, how to triage bugs)
- **File structure** — The workspace has a defined schema so files are consistently organized
- **Context injection** — Active `.md` files in the workspace root are automatically injected into every conversation, keeping the bot aware of project state

### Checking What's Active

In the **Integrations** tab, you can see:
- Which integrations are activated
- What tools, skills, and system prompt fragments are injected
- Links to the carapace detail pages for full inspection

---

## For Integration Developers

If you're building an integration and want it to support activation and template compatibility, see [Activation & Template Compatibility](../integrations/activation-and-templates.md) for the developer guide covering:

- The `activation` block in `setup.py`
- Carapace injection mechanics
- Declaring `compatible_templates` tags
- Creating compatible workspace schema templates
