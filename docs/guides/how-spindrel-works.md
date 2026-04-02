# How Spindrel Works

This guide explains the mental model — how the pieces fit together, not API details.

---

## The Core Idea

A **channel** is a conversation with a bot. What makes that bot useful depends on what's plugged into it: tools, skills, behavioral instructions, and workspace files. Spindrel's job is composing those pieces so the right capabilities show up at the right time, without manual configuration for every channel.

The composition chain:

```
Channel → Template + Integration Activation → Carapace → Skills + Tools + Behavior
```

---

## Channels

A channel is where a user talks to a bot. Each channel has:

- A **bot** assignment (which LLM, which personality)
- A **workspace** (a directory of `.md` files the bot reads and writes)
- Zero or more **integration bindings** (Slack, GitHub, Mission Control, etc.)
- Optional **overrides** (extra tools, disabled carapaces, custom prompt)

Channels are lightweight. Create one per project, topic, or workflow. The bot's base configuration comes from its YAML definition, but the channel can layer on top.

---

## Templates

A template defines **how the workspace should be organized** — which files to create, what each file is for, and how they relate.

For example, the **Software Development** template says:

> Create `project.md` for goals and scope, `architecture.md` for design, `tasks.md` for tracking, `decisions.md` for ADRs.

The **Media Management** template says:

> Create `requests.md` for pending media requests, `library.md` for collection overview, `issues.md` for download problems.

Templates are suggestions, not constraints. The bot follows the structure when creating files but adapts if the conversation goes in a different direction.

**Picking a template** happens in the channel's Workspace tab. If an integration is activated, compatible templates are highlighted — pick the green one for the best experience.

---

## Integration Activation

Integrations connect Spindrel to external services (Slack, GitHub, Gmail, your media stack). **Binding** an integration to a channel means messages can flow in and out. **Activating** it means the bot gains the integration's full capabilities.

When you activate an integration on a channel:

1. The integration's **carapace** is automatically injected
2. The carapace brings in **tools** (function calls the bot can make), **skills** (domain knowledge), and **behavioral instructions** (how to use them)
3. No manual tool configuration needed

**Example:** Activate the Arr integration on a channel, and the bot instantly knows how to search Sonarr for TV shows, add movies to Radarr, check download status in qBittorrent, and browse your Jellyfin library. Pair it with the **Media Management** template and the bot also knows to track requests in `requests.md` and log issues in `issues.md`.

### Current Integrations with Activation

| Integration | What it provides | Compatible template |
|-------------|-----------------|-------------------|
| **Mission Control** | Task boards, plans, timelines, project management | Mission Control, Software Dev, PM Hub |
| **Arr (Media Stack)** | Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, Bazarr | Media Management |
| **Gmail** | Email ingestion, digest management, feed rules | Email Digest |

Other integrations (Slack, GitHub, Discord, Frigate) provide channel binding and tools but don't yet have activation manifests. Their tools are available when configured on the bot directly.

---

## Carapaces (Expertise Bundles)

Carapaces are the mechanism that makes activation work — but they're useful beyond integrations too.

A carapace bundles:

- **Tools** — Functions the bot can call (e.g., `create_task_card`, `sonarr_search`)
- **Skills** — Markdown knowledge documents with domain expertise (e.g., how to run a code review, how to manage a sourdough starter)
- **System prompt fragment** — Behavioral instructions injected into every message ("when the user asks about X, fetch skill Y and use tool Z")
- **Includes** — Other carapaces to compose with (e.g., `qa` includes `code-review`)

### How the Bot Finds Skills

Carapaces use a **fragment-as-index** pattern. The system prompt fragment acts as a routing table:

> "When the user asks about task management or project status, fetch `get_skill('mission_control')` for the full reference."

Skills aren't all loaded at once (that would blow the context window). Instead, the system prompt tells the bot *when* to load each skill, and the bot fetches them on demand via `get_skill()`. This means a bot can have access to thousands of pages of domain knowledge without any of it consuming context until it's actually needed.

### Static vs Dynamic Carapaces

- **Static** — Declared in the bot's YAML: `carapaces: [qa, code-review]`. Always active.
- **Dynamic** — Injected via integration activation. Only active on channels where the integration is activated. Can be disabled per-channel.

### Composition

Carapaces can include other carapaces. The `orchestrator` carapace includes `mission-control`. The `qa` carapace includes `code-review`. Resolution is depth-first with cycle detection, max 5 levels deep.

---

## The Full Picture

Here's how it all comes together when you set up a channel:

### 1. Create a channel, assign a bot

The bot brings its base personality, model, and any static carapaces from its YAML config.

### 2. Activate integrations

Each activated integration injects its carapace(s). The bot gains tools and skills without any manual configuration.

### 3. Pick a compatible template

The template tells the bot how to organize workspace files. Compatible templates are designed to match the activated integration's tools — e.g., the Media Management template's `requests.md` aligns with how `sonarr_search` and `radarr_search` report results.

### 4. Start chatting

On every message, Spindrel's context assembly pipeline runs:

1. **Carapace resolution** — Collects all carapaces (static + activated), resolves includes, merges tools and skills
2. **Template injection** — The workspace schema is injected so the bot knows the file structure
3. **Workspace files** — Active `.md` files in the workspace root are injected into context (the bot "sees" project state)
4. **Tool retrieval** — Relevant tools are selected via embedding similarity (not all tools are sent every time)
5. **Skill routing** — The system prompt fragments tell the bot when to load on-demand skills

The result: the bot has exactly the right tools, knowledge, and context for this channel's purpose — assembled fresh on every request.

---

## Key Concepts Summary

| Concept | What it is | Where it lives |
|---------|-----------|---------------|
| **Channel** | A conversation with a bot | UI sidebar, database |
| **Template** | Workspace file organization guide | `prompts/*.md` or Admin > Templates |
| **Integration** | Connection to an external service | `integrations/*/` directory |
| **Activation** | Enabling an integration's full capabilities on a channel | Channel > Integrations tab |
| **Carapace** | Bundle of tools + skills + behavior | `carapaces/*/carapace.yaml` |
| **Skill** | Markdown knowledge document | `skills/*.md` or carapace subdirectory |
| **Workspace** | Per-channel file store | `~/.agent-workspaces/` on disk |

---

## Common Patterns

### "I want a project management channel"
1. Create channel → Activate Mission Control → Pick "Software Dev" or "Mission Control" template
2. Bot can now create task boards, draft plans, track timelines, and organize files

### "I want a media request channel"
1. Create channel → Activate Arr → Pick "Media Management" template
2. Bot can search and add media, monitor downloads, track requests

### "I want an email digest channel"
1. Create channel → Bind Gmail → Activate Gmail → Pick "Email Digest" template
2. Bot processes incoming emails, builds digests, tracks action items

### "I want a code review channel"
1. Create channel → Give the bot `carapaces: [code-review]` (or `qa` for full QA)
2. No activation needed — code review is a static carapace, not integration-bound
