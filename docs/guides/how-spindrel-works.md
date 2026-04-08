# How Spindrel Works

This guide explains the mental model — how the pieces fit together, not API details.

---

## The Core Idea

A **channel** is a conversation with a bot. What makes that bot useful depends on what's plugged into it: tools, skills, behavioral instructions, and workspace files. Spindrel's job is composing those pieces so the right capabilities show up at the right time, without manual configuration for every channel.

The composition chain:

```
Channel → Template + Integration Activation → Capabilities → Skills + Tools + Behavior
```

---

## Channels

A channel is where a user talks to a bot. Each channel has:

- A **bot** assignment (which LLM, which personality)
- A **workspace** (a directory of `.md` files the bot reads and writes)
- Zero or more **integration bindings** (Slack, GitHub, Mission Control, etc.)
- Optional **overrides** (extra tools, disabled capabilities, custom prompt)

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

1. The integration's **capability** is automatically injected
2. The capability brings in **tools** (function calls the bot can make), **skills** (domain knowledge), and **behavioral instructions** (how to use them)
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

## Capabilities

Capabilities are composable expertise bundles that give bots domain knowledge. They're the mechanism behind integration activation — but they're useful beyond integrations too.

A capability bundles:

- **Tools** — Functions the bot can call (e.g., `create_task_card`, `sonarr_search`)
- **Skills** — Markdown knowledge documents with domain expertise (e.g., how to run a code review, how to manage a sourdough starter)
- **System prompt fragment** — Behavioral instructions injected into the system prompt ("when the user asks about X, fetch skill Y and use tool Z")
- **Includes** — Other capabilities to compose with (e.g., `qa` includes `code-review`)

### Auto-Discovery

Bots automatically discover available capabilities at runtime. On every request, the bot sees a compact index of capabilities it doesn't already have loaded. When a user's request matches one, the bot calls `activate_capability()` to load it for the session — no manual configuration needed.

You can also **pin** capabilities to a bot (`carapaces: [qa, code-review]` in bot config — `carapaces` is the config key for capabilities) so they're always active, or **disable** specific ones per-channel.

### How the Bot Finds Skills

Skills use the same semantic search as tools and capabilities. On each message, the system retrieves the most relevant skills from the bot's enrolled set and presents a compact index. The bot calls `get_skill()` to load the full content of any skill it needs, or `get_skill_list()` to browse all available skills when the index doesn't show what it's looking for.

Skills aren't all loaded at once (that would blow the context window). Only the most relevant skills appear in the index each turn, and the bot fetches full content on demand. This means a bot can have access to thousands of pages of domain knowledge without any of it consuming context until it's actually needed.

Capabilities can also route to skills via their system prompt fragment — e.g., "when the user asks about task management, fetch `get_skill('mission_control')`" — providing an explicit routing layer on top of the semantic search.

### How Capabilities Activate

- **Auto-discovered** — Bot sees the capability index and activates what it needs per-conversation.
- **Pinned** — Declared in bot config: `carapaces: [qa, code-review]` (`carapaces` is the config key for capabilities). Always active.
- **Integration-injected** — Automatically loaded when an integration is activated on a channel. Can be disabled per-channel.

### Composition

Capabilities can include other capabilities. The `orchestrator` capability includes `mission-control`. The `qa` capability includes `code-review`. Resolution is depth-first with cycle detection, max 5 levels deep.

---

## The Full Picture

Here's how it all comes together when you set up a channel:

### 1. Create a channel, assign a bot

The bot brings its base personality, model, and any pinned capabilities from its config.

### 2. Activate integrations

Each activated integration injects its capability. The bot gains tools and skills without any manual configuration.

### 3. Pick a compatible template

The template tells the bot how to organize workspace files. Compatible templates are designed to match the activated integration's tools — e.g., the Media Management template's `requests.md` aligns with how `sonarr_search` and `radarr_search` report results.

### 4. Start chatting

On every message, Spindrel's context assembly pipeline runs:

1. **Capability resolution** — Collects all capabilities (pinned + activated + auto-discovered), resolves includes, merges tools and skills
2. **Template injection** — The workspace schema is injected so the bot knows the file structure
3. **Workspace files** — Active `.md` files in the workspace root are injected into context (the bot "sees" project state)
4. **Tool retrieval** — Relevant tools are selected via semantic search (vector + BM25 hybrid, not all tools are sent every time)
5. **Skill retrieval** — Relevant on-demand skills are selected via semantic search and presented as a compact index; the bot loads full content via `get_skill()`

The result: the bot has exactly the right tools, knowledge, and context for this channel's purpose — assembled fresh on every request.

---

## Key Concepts Summary

| Concept | What it is | Where it lives |
|---------|-----------|---------------|
| **Channel** | A conversation with a bot | UI sidebar, database |
| **Template** | Workspace file organization guide | `prompts/*.md` or Admin > Templates |
| **Integration** | Connection to an external service | `integrations/*/` directory |
| **Activation** | Enabling an integration's full capabilities on a channel | Channel > Integrations tab |
| **Capability** | Bundle of tools + skills + behavior | `carapaces/*.yaml` (directory name) or Admin > Capabilities |
| **Skill** | Markdown knowledge document | `skills/*.md` or capability subdirectory |
| **Workspace** | Per-channel file store | `~/.spindrel-workspaces/` on disk |

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
1. Create channel → The bot auto-discovers `code-review` (or pin it: `carapaces: [code-review]` — `carapaces` is the config key for capabilities)
2. No activation needed — code review is a standalone capability, not integration-bound

### "I want to add my own tools and capabilities"
1. Drop a `.py` file in `tools/` with a `@register` decorator → tool is available on next restart
2. Or keep a personal extensions repo and load it via `INTEGRATION_DIRS` — see the [Custom Tools & Extensions guide](custom-tools.md)
