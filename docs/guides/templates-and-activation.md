# Templates & Integration Activation

When you create a channel in Spindrel, it starts as a blank conversation. Templates and integration activation turn it into a structured workspace with the right tools, skills, and file organization for a specific kind of work.

---

## How It Works

Two layers combine to configure a channel:

1. **Integration activation** — Enables an integration on a channel, automatically injecting its tools, skills, and behavioral instructions (via capabilities). One click, no manual tool configuration.

2. **Workspace template** — Defines the file structure for the channel's workspace (which `.md` files to create, their headings, their purpose). Templates are independent of activation — you can use a template without activating anything, or activate without a template.

**Together:** Activate Mission Control on a channel and pick the "Software Development" template. The bot immediately gains project management tools (task boards, plans, timelines) AND knows how to organize workspace files (tasks.md with kanban columns, status.md with phase tracking, etc.).

---

## Activating an Integration

### From the Channel Settings

1. Open a channel and go to the **Integrations** tab
2. You'll see available integrations with activation status
3. Click **Activate** on the integration you want
4. The integration's capability is injected — tools, skills, and system prompt guidance are now active

### What Activation Does

When you activate an integration, its **activation manifest** kicks in:

- **Capabilities injected** — The integration's capability bundle(s) are added to the bot's context for this channel. This brings in tools, skills, and a system prompt fragment that teaches the bot how to use them.
- **No manual tool config** — You don't need to add individual tools to the bot's config. The capability bundles everything.
- **Per-channel** — Activation is scoped to the channel. Other channels using the same bot are unaffected.

### Deactivating

Click **Deactivate** in the Integrations tab. The capability is removed and the bot loses those capabilities on this channel. Workspace files are not deleted.

---

## Workspace Templates

Templates define the file structure for a channel's workspace. When a bot has `workspace.enabled: true`, the channel workspace is a directory of `.md` files that the bot reads and writes during conversations.

### Do I need a template?

**Usually no.** If you've activated an integration (like Mission Control), it already teaches the bot how to organize workspace files through its capability. The bot will create the right files with the right format automatically.

Templates are useful when:
- You want a **specific file structure** for a non-integration workflow (e.g., a research project)
- You want to **override** the integration's built-in file organization
- You want **consistency** across multiple channels doing similar work

### Picking a Template (optional)

1. Open a channel and go to the **Workspace** tab
2. Expand **Advanced Workspace Settings**
3. In the **Organization Template** section, link a template
4. The bot will use this structure when creating workspace files

### Built-in Templates

Spindrel ships templates for common workflows:

| Template | Best for | Key files |
|----------|----------|-----------|
| Software Development | Code projects with task tracking | tasks.md, architecture.md, decisions.md |
| Research / Analysis | Investigation and analysis | findings.md, sources.md, questions.md |
| Creative Project | Writing, design, content | brief.md, concepts.md, feedback.md |
| General Project | Lightweight catch-all | overview.md, notes.md, tasks.md |
| Project Management Hub | Project coordination | status.md, projects.md, reports.md |
| Mission Control | Structured task tracking | tasks.md, status.md, decisions.md |
| Software Testing / QA | Test planning and execution | test-plan.md, bugs.md, coverage.md |
| Media Management | Media library and requests | requests.md, library.md, issues.md |
| Email Digest | Email ingestion and action tracking | feeds.md, digest.md, actions.md |
| Home Automation | Device inventory and events | devices.md, automations.md, events.md |
| DevOps | Repository and deployment tracking | repos.md, prs.md, deployments.md |

### Custom Templates

Create templates in two ways:

**From a file** — Add a `.md` file to `prompts/` (or `integrations/*/prompts/`):

```yaml
---
name: "My Custom Schema"
description: "Workspace schema for game development"
category: workspace_schema
tags:
  - gamedev
---

## Workspace File Organization

### tasks.md
Kanban board with columns: Backlog, In Progress, Testing, Done
...
```

Restart the server — the template is auto-synced.

**From the UI** — In Admin > Templates, create a new template with a name, description, and tags.

---

## Recommended Workflow

### Setting Up a New Project Channel

1. **Create a channel** — Give it a name and assign a bot
2. **Enable the workspace** — In the Workspace tab, toggle workspace on (if not enabled by default)
3. **Activate integrations** — In the Integrations tab, activate Mission Control (or other integrations relevant to your work)
4. **Start chatting** — The bot now has the right tools and knows how to organize files. Ask it to create a task board, write a status report, or plan a feature — it knows the formats from the integration's capability.

That's it. No template selection needed. The integration's capability teaches the bot both the tools AND the file organization.

### What You Get

After activation:

- **Tools** — The bot can create task cards, move items between columns, update status, manage plans (whatever the integration provides)
- **Skills** — The bot has domain knowledge about the integration's workflows (e.g., how to run a standup, how to triage bugs)
- **File organization** — The capability teaches the bot how to structure workspace files for this integration
- **Context injection** — Active `.md` files in the workspace root are automatically injected into every conversation, keeping the bot aware of project state

### Checking What's Active

In the **Integrations** tab, you can see:
- Which integrations are activated
- What tools, skills, and system prompt fragments are injected
- Links to the capability detail pages for full inspection

---

## For Integration Developers

If you're building an integration and want it to support activation, see [Activation & Workspace Templates](../integrations/activation-and-templates.md) for the developer guide covering:

- The `activation` block in `setup.py`
- Capability injection mechanics
- Creating workspace schema templates
