---
hide:
  - navigation
---

# Spindrel

**Self-hosted AI agent server** with persistent channels, composable expertise, workspace-driven memory, multi-step task pipelines, interactive widget dashboards, and a pluggable integration framework.

Built on FastAPI + PostgreSQL (pgvector). Bring your own API keys — use any LLM provider.

!!! warning "Early Access"
    Spindrel is under active development and in daily use by the maintainer. Core features are stable, but APIs, configuration formats, and database schemas may change between releases. Bug reports, feature requests, and contributions are welcome.

---

## Features

### Any LLM Provider

OpenAI, Anthropic, Gemini, Ollama, OpenRouter, vLLM — or any OpenAI-compatible endpoint. A dedicated **ChatGPT Subscription** provider type signs in via OAuth device code and bills against your existing Plus/Pro plan ($0 per call). Mix providers across bots. Automatic retry with fallback models. Cost tracking via LiteLLM pricing data.

### Auto-Discovery (Capabilities, Tools, Skills)

Bots need only `model` + `system_prompt` — everything else is discovered at runtime. Composable **capabilities** (tools + skills + behavioral instructions, `carapaces:` in config) activate from the conversation via hybrid RAG. Tool and skill retrieval use the same pipeline, with a semantic `search_tools` fallback when the initial retrieval misses. Capability gating filters by declared requirements so unavailable tools never leak into the model's context.

### Widget Dashboards + Interactive HTML Widgets

Tool results become **live, interactive control surfaces**. Pin them to a **channel dashboard** (lazy-created per channel, surfaces in the OmniPanel rail) or to a **user dashboard** (Home Assistant-style grid, drag + resize). Bots can author their own HTML widgets via `emit_html_widget` — full-iframe dashboards with `window.spindrel.*` helpers for tool dispatch, workspace file read/write, and deep-merge RMW over JSON state. Widgets authenticate as the emitting bot via short-lived JWTs, not the viewer.

### Task Pipelines + Sub-Sessions

Reusable multi-step automations defined as `Task` rows: `exec`, `tool`, `agent`, `user_prompt`, and `foreach` steps with conditions, parameters, approval gates, and cross-bot delegation. Pipeline runs render as a **chat-native sub-session** — a modal or docked transcript showing every step's LLM thinking, tool widgets, and output. Bind pipelines to a channel with per-channel cron schedules. Five built-in bot audit pipelines (`analyze_discovery`, `analyze_skill_quality`, `analyze_memory_quality`, `analyze_tool_usage`, `analyze_costs`) let bots self-tune.

### Workspace Memory + Conversation Continuity

Bots maintain `MEMORY.md`, daily logs, and reference docs — all on disk, all indexed for RAG. Conversations are automatically archived into searchable sections that persist across fresh starts. **Chat state rehydrates** on reconnect via a snapshot endpoint, so in-flight approvals and streaming turns survive page reloads, mobile tab wakes, and network drops. Per-channel file stores with schema templates keep project context structured.

### Heartbeats + Task Scheduling

Periodic autonomous check-ins with quiet hours and repetition detection. Schedule one-off or recurring tasks with cron-like flexibility. Bots can self-schedule via `schedule_task` or trigger pipelines from a heartbeat. Results dispatch to Slack, webhooks, push notifications, or the UI.

### Integration Activation + Templates

Activate an integration on a channel and it instantly gets the right tools, skills, and behavioral instructions — no manual configuration. Pick a compatible workspace template and the bot knows exactly how to organize files. One click to go from blank channel to structured project.

### Self-Improving Agents

Bots create their own skills at runtime via `manage_bot_skill`. Three learning nudges (correction detection, repeated-lookup detection, mid-conversation reflection) teach bots *when* to learn. Skills enter the RAG pipeline and auto-surface in future sessions. A split dreaming job (Maintenance + Skill Review) prunes stale skills, merges duplicates, and rewrites weak triggers from real ranker signal. A dedicated Learning tab shows surfacing analytics and health badges per skill.

### Integration Framework

Pluggable integrations with auto-discovery. Shipped: Slack (with App Home, modals, ephemeral messages, reaction intents), GitHub, Discord, Gmail, Frigate (cameras + event timeline), Home Assistant (device control), Excalidraw (collaborative whiteboard), OpenWeather, Web Search, Wyoming (STT/TTS), Mission Control, Arr, Claude Code, BlueBubbles, Google Workspace, Firecrawl, VS Code, Ingestion. Each provides routers, dispatchers, tools, lifecycle hooks, and in-chat HUD widgets. Extend with your own via `INTEGRATION_DIRS`.

### Sub-Agents

Five built-in presets (`research`, `quality`, `summarize`, `code`, `plan`) and parallel execution. Depth and rate limits keep runaway delegation safe. Unit + E2E coverage.

### PWA + Push Notifications

Install Spindrel as a Progressive Web App. Browser push notifications are triggered explicitly by bots via the `send_push_notification` tool or the `POST /api/v1/push/send` endpoint — notifications are intentional, not a firehose.

### Usage Tracking + Budgeting

Per-bot token usage and cost tracking. Budget limits with configurable enforcement. Usage forecasting and breakdown by model. Powered by LiteLLM pricing data when available; plan-billing providers (ChatGPT Subscription) report $0 per call. *Cost data is best-effort — always verify against your provider's billing dashboard.*

### Web Search

Built-in web search via SearXNG (self-hosted) or DuckDuckGo (zero-config). Switch backends at runtime from the admin UI. No external API keys required.

### Command Execution

Subprocess-based `exec_tool` runs workspace commands against the server's host filesystem. Long-lived Docker sandboxes are available for isolated code execution with configurable images, mount points, and resource limits.

---

## Quick Start

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh          # interactive wizard: deployment, LLM provider, auth
docker compose up -d
```

The setup wizard configures `.env`, starts services, and creates a default bot. The Orchestrator bot guides you through the rest conversationally.

[Full setup guide &rarr;](setup.md)

## Guides

| Guide | Description |
|-------|-------------|
| [How Spindrel Works](guides/how-spindrel-works.md) | The mental model — channels, templates, activation, capabilities, and how they compose. |
| [Setup Guide](setup.md) | Installation, providers, workspaces, integrations, troubleshooting. |
| [LLM Providers](guides/providers.md) | All seven provider types, feature matrix, ChatGPT Subscription OAuth walkthrough. |
| [Templates & Activation](guides/templates-and-activation.md) | Activate integrations on channels, pick workspace templates, instant project setup. |
| [Slack Integration](guides/slack.md) | Connect Spindrel to Slack via Socket Mode. |
| [Discord Integration](guides/discord.md) | Connect Spindrel to Discord. |
| [BlueBubbles (iMessage)](guides/bluebubbles.md) | iMessage integration via BlueBubbles with connection HUD and diagnostics. |
| [Gmail Integration](guides/gmail.md) | Gmail integration for email-driven workflows. |
| [Home Assistant](guides/homeassistant.md) | Device control via MCP — toggle + brightness widgets, live state polling, targeting grammar. |
| [Excalidraw](guides/excalidraw.md) | Hand-drawn-style diagrams from Excalidraw JSON or Mermaid. |
| [Delegation](guides/delegation.md) | Bot-to-bot delegation — immediate and deferred. |
| [Secrets & Redaction](guides/secrets.md) | Secret vault, automatic redaction, and user input detection. |
| [Content Ingestion](guides/ingestion.md) | Security pipeline for content feeds with sidebar dashboard and feed health HUD. |
| [Usage & Billing](guides/usage-and-billing.md) | Cost tracking, budget limits, spend forecasting, and provider pricing. |
| [Pipelines](guides/pipelines.md) | Multi-step task automation — exec, tool, agent, user_prompt, and foreach steps with conditions, params, and approval gates. |
| [Task Sub-Sessions](guides/task-sub-sessions.md) | Pipeline-run-as-chat — anchor cards, run-view modal, `sub_session_bus` routing, ephemeral skill scope. |
| [Sub-Agents](guides/subagents.md) | Five presets, parallel execution, depth and rate limits. |
| [Heartbeats](guides/heartbeats.md) | Periodic autonomous check-ins with quiet hours, dispatch modes, repetition detection, and pipeline triggers. |
| [MCP Servers](guides/mcp-servers.md) | Connect external tool servers (Home Assistant, databases, APIs). Pair with capabilities for domain expertise. |
| [Self-Improving Agents](guides/bot-skills.md) | Bot-authored skills, the RAG pipeline, skill hygiene, and admin visibility. |
| [Custom Tools & Extensions](guides/custom-tools.md) | Create custom tools, manage a personal extensions repo, load external capabilities and skills. |
| [Widget Dashboards](guides/widget-dashboards.md) | Named dashboards, channel dashboards, and the OmniPanel rail. How component widgets and HTML widgets live side-by-side. |
| [HTML Widgets](guides/html-widgets.md) | Bot-authored live dashboards. How the bot-scoped iframe auth works and how to provision bots that can build them. |
| [Widget Templates](widget-templates.md) | YAML widget templates that render tool results as live, interactive UI. Component templates, HTML templates, and the `state_poll` field. |
| [Developer Panel](guides/dev-panel.md) | `/widgets/dev` — browse the catalog, author templates with live preview, call tools in a sandbox, inspect recent results. |
| [Creating Integrations](integrations/index.md) | Build custom integrations with routers, dispatchers, hooks, and HUD widgets. |
| [Chat History](guides/chat-history.md) | Conversation archival, searchable sections, and continuity across fresh starts. |
| [Chat State Rehydration](guides/chat-state-rehydration.md) | Snapshot endpoint, `useChannelState` + `rehydrateTurn`, reconnect / tab-wake / replay-lapsed recovery. |
| [PWA & Push Notifications](guides/pwa-push.md) | Install the PWA, subscribe a device, `send_push_notification` tool, scoped `/api/v1/push/send` endpoint. |
| [Developer API](guides/api.md) | Authentication, scoped keys, streaming, SSE events. |
| [Lifecycle Webhooks](guides/webhooks.md) | Outgoing events for monitoring, cost analytics, and audit. |
| [Command Execution](guides/command-execution.md) | Docker workspaces, host execution, client-side shell, deferred tasks — when to use each and how they differ. |
| [Agent Client](guides/clients.md) | Remote voice assistant + local tool executor. |
| [E2E Testing](guides/e2e-testing.md) | YAML scenario framework, ad-hoc agent testing, assertion reference, and LLM provider config. |
| [Backup & Restore](backup.md) | Automated Postgres + config backups to S3. |
| [Docker Deployment](docker-deployment.md) | Production setup with the sibling container pattern. |

## Reference

| Reference | Description |
|-----------|-------------|
| [Architecture](reference/architecture.md) | System overview, request flow, and key components. |
| [RAG Pipeline](reference/rag-pipeline.md) | Indexing, retrieval, hybrid search, reranking, halfvec acceleration, contextual retrieval, and LLM retry infrastructure. |
