# Workspace Templates & Integration Activation

Two optional layers can shape a channel beyond the bot + chat default:

1. **Integration activation** — Enables an integration on a channel and exposes its declared tools to the bot there.
2. **Workspace schema template** — Defines the file structure (`.md` files, headings, intent) the bot scaffolds when it writes to the channel workspace.

Neither is required. Most channels work fine with no template and no activated integration — just the bot, its enrolled skills, and whatever workspace files it builds up over time.

There is **no separate capability bundle**. The old "carapace / capability" composition layer was removed; integrations expose tools through their activation manifest, and any related domain knowledge lives as normal skills or prompt templates that the regular skill RAG pulls in on demand.

---

## Activating an Integration

### From Channel Settings

1. Open a channel → **Integrations** tab
2. Available integrations are listed with activation status
3. Click **Activate**

### What Activation Does

Activation flips `ChannelIntegration.activated = true` for that channel and integration. From then on:

- **Declared tools become available** on that channel — every tool the integration registers via its activation manifest is added to the bot's tool surface.
- **Integration skills stay in the regular RAG pool** — they're discovered and pulled in by the same skill system that loads `skills/*.md`. Nothing is force-injected per channel.
- **No manual tool config** — you don't add individual tools to the bot's YAML. The integration declares what it provides.
- **Per-channel scope** — activation only affects this channel. Other channels using the same bot are unaffected.

### Deactivating

Click **Deactivate** in the Integrations tab. The integration's tools are removed from this channel; workspace files are not touched.

---

## Workspace Schema Templates

Workspace templates define the file structure for a channel's workspace. When a bot has `workspace.enabled: true`, the channel workspace is a directory of `.md` files the bot reads and writes during conversations.

### Do I need a template?

**Usually no.** Templates give a predictable starting shape, but they're optional. The file-backed workspace is the core feature; the template is just a starting scaffold.

Templates are useful when:
- You want a **specific file structure** for a recurring project type (research, devops, gamedev)
- You want **consistency** across multiple channels doing similar work
- You want to **override** the default file organization the bot would otherwise pick

### Picking a Template

1. Open a channel → **Workspace** tab
2. Expand **Advanced Workspace Settings**
3. In **Organization Template**, link a template
4. The bot uses this structure when creating workspace files

### Built-in Templates

Spindrel ships templates for common project shapes:

| Template | Best for | Key files |
|----------|----------|-----------|
| Software Development | Code projects with task tracking | `tasks.md`, `architecture.md`, `decisions.md` |
| Research / Analysis | Investigation and analysis | `findings.md`, `sources.md`, `questions.md` |
| Creative Project | Writing, design, content | `brief.md`, `concepts.md`, `feedback.md` |
| General Project | Lightweight catch-all | `overview.md`, `notes.md`, `tasks.md` |
| Project Management Hub | Project coordination | `status.md`, `projects.md`, `reports.md` |
| Software Testing / QA | Test planning and execution | `test-plan.md`, `bugs.md`, `coverage.md` |
| Media Management | Media library and requests | `requests.md`, `library.md`, `issues.md` |
| Home Automation | Device inventory and events | `devices.md`, `automations.md`, `events.md` |
| DevOps | Repository and deployment tracking | `repos.md`, `prs.md`, `deployments.md` |

### Custom Templates

Two ways to add your own:

**From a file** — Add a `.md` to `prompts/` (or `integrations/*/prompts/`):

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

**From the UI** — Admin → Templates → New, with a name, description, and tags.

---

## Recommended Setup Flow

1. **Create a channel** — Give it a name and assign a bot
2. **Enable the workspace** if not already on (channel → Workspace tab)
3. **Optionally activate an integration** — only if this channel really needs one
4. **Optionally pick a workspace template** — only if you want a specific starting structure
5. **Start chatting** — the bot will scaffold workspace files as it goes, using the template if one is set and the integration's tools if one is activated

Both template selection and activation are optional.

---

## What You Get After Activation

- **Tools** — Whatever the integration registers (create cards, control devices, run searches, …)
- **Skills via RAG** — The regular skill system picks up integration-shipped skill packs and pulls them in when relevant; you don't have to enroll them manually per channel
- **Context injection** — Active `.md` files in the workspace root are automatically injected into every conversation, keeping the bot aware of project state

### Checking What's Active

In the **Integrations** tab you can see:
- Which integrations are activated on this channel
- What tools each one exposes
- Links into the integration detail page for full inspection

---

## For Integration Developers

If you're building an integration and want it to support activation, see [Activation & Workspace Templates](../integrations/activation-and-templates.md) for the developer guide covering:

- The `activation:` block in `integration.yaml`
- How declared tools become channel-scoped
- Creating workspace schema templates that complement the integration
