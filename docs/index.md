---
hide:
  - navigation
---

# Spindrel

**Self-hosted AI agent server** with persistent channels, composable expertise, workspace-driven memory, multi-step workflows, and a pluggable integration framework.

Built on FastAPI + PostgreSQL (pgvector). Bring your own API keys — use any LLM provider.

!!! warning "Early Access"
    Spindrel is under active development and in daily use by the maintainer. Core features are stable, but APIs, configuration formats, and database schemas may change between releases. Bug reports, feature requests, and contributions are welcome.

---

## Features

### Any LLM Provider

OpenAI, Anthropic, Gemini, Ollama, OpenRouter, vLLM — or any OpenAI-compatible endpoint. Mix providers across bots. Automatic retry with fallback models. Cost tracking via LiteLLM pricing data.

### Capabilities (Auto-Discovered Expertise)

Composable bundles of tools, skills, and behavioral instructions. Bots discover and activate relevant capabilities at runtime — or pin specific ones like `carapaces: [qa, code-review]` (`carapaces` is the config key for capabilities) to always include. Capabilities compose via `includes` for layered expertise.

### Workspace Memory + Conversation Continuity

Bots maintain `MEMORY.md`, daily logs, and reference docs — all on disk, all indexed for RAG. Conversations are automatically archived into searchable sections that persist across fresh starts. Per-channel file stores with schema templates keep project context structured.

### Workflows

Reusable multi-step automations defined in YAML. Conditions, approval gates, parallel branches, cross-bot delegation, and scoped secrets. Trigger via API, bot tool, or heartbeat. Manage and monitor from the admin UI.

### Heartbeats + Task Scheduling

Periodic autonomous check-ins with quiet hours and repetition detection. Schedule one-off or recurring tasks with cron-like flexibility. Bots can self-schedule via `schedule_task`. Results dispatch to Slack, webhooks, or the UI.

### Integration Activation + Templates

Activate an integration on a channel and it instantly gets the right tools, skills, and behavioral instructions — no manual configuration. Pick a compatible workspace template and the bot knows exactly how to organize files. One click to go from blank channel to structured project.

### Self-Improving Agents

Bots create their own skills at runtime via `manage_bot_skill`. Three learning nudges (correction detection, repeated-lookup detection, mid-conversation reflection) teach bots *when* to learn. Skills enter the RAG pipeline and auto-surface in future sessions. Scheduled review heartbeats prune stale skills, merge duplicates, and rewrite weak triggers autonomously. A dedicated Learning tab shows surfacing analytics and health badges per skill.

### Integration Framework

Pluggable integrations with auto-discovery. Shipped: Slack, GitHub, Discord, Gmail, Frigate, Mission Control, Arr, Claude Code, BlueBubbles, Ingestion. Each provides routers, dispatchers, tools, lifecycle hooks, and in-chat HUD widgets. Extend with your own via `INTEGRATION_DIRS`.

### Usage Tracking + Budgeting

Per-bot token usage and cost tracking. Budget limits with configurable enforcement. Usage forecasting and breakdown by model. Powered by LiteLLM pricing data when available. *Cost data is best-effort — always verify against your provider's billing dashboard.*

### Web Search

Built-in web search via SearXNG (self-hosted) or DuckDuckGo (zero-config). Switch backends at runtime from the admin UI. No external API keys required.

### Docker Sandboxes

Long-lived containers for isolated code execution. Per-bot sandbox profiles with configurable images, mount points, and resource limits. Scope modes: session, client, agent, or shared.

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
| [Templates & Activation](guides/templates-and-activation.md) | Activate integrations on channels, pick workspace templates, instant project setup. |
| [Slack Integration](guides/slack.md) | Connect Spindrel to Slack via Socket Mode. |
| [Discord Integration](guides/discord.md) | Connect Spindrel to Discord. |
| [BlueBubbles (iMessage)](guides/bluebubbles.md) | iMessage integration via BlueBubbles with connection HUD and diagnostics. |
| [Gmail Integration](guides/gmail.md) | Gmail integration for email-driven workflows. |
| [Delegation](guides/delegation.md) | Bot-to-bot delegation — immediate and deferred. |
| [Secrets & Redaction](guides/secrets.md) | Secret vault, automatic redaction, and user input detection. |
| [Content Ingestion](guides/ingestion.md) | Security pipeline for content feeds with sidebar dashboard and feed health HUD. |
| [Usage & Billing](guides/usage-and-billing.md) | Cost tracking, budget limits, spend forecasting, and provider pricing. |
| [Pipelines](guides/pipelines.md) | Multi-step task automation — exec, tool, agent, user_prompt, and foreach steps with conditions, params, and approval gates. |
| [Workflows](guides/workflows.md) | **Deprecated** — superseded by pipelines. Kept for reference. |
| [Heartbeats](guides/heartbeats.md) | Periodic autonomous check-ins with quiet hours, dispatch modes, repetition detection, and workflow triggers. |
| [MCP Servers](guides/mcp-servers.md) | Connect external tool servers (Home Assistant, databases, APIs). Pair with capabilities for domain expertise. |
| [Self-Improving Agents](guides/bot-skills.md) | Bot-authored skills, the RAG pipeline, skill hygiene, and admin visibility. |
| [Custom Tools & Extensions](guides/custom-tools.md) | Create custom tools, manage a personal extensions repo, load external capabilities and skills. |
| [Widget Dashboards](guides/widget-dashboards.md) | Named dashboards, channel dashboards, and the OmniPanel rail. How component widgets and HTML widgets live side-by-side. |
| [HTML Widgets](guides/html-widgets.md) | Bot-authored live dashboards. How the bot-scoped iframe auth works and how to provision bots that can build them. |
| [Creating Integrations](integrations/index.md) | Build custom integrations with routers, dispatchers, hooks, and HUD widgets. |
| [Chat History](guides/chat-history.md) | Conversation archival, searchable sections, and continuity across fresh starts. |
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
