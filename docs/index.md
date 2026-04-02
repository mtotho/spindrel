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

<div class="grid cards" markdown>

-   :material-swap-horizontal:{ .lg .middle } **Any LLM Provider**

    ---

    OpenAI, Anthropic, Gemini, Ollama, OpenRouter, vLLM — or any OpenAI-compatible endpoint. Mix providers across bots. Automatic retry with fallback models. Cost tracking via LiteLLM pricing data.

-   :material-puzzle-outline:{ .lg .middle } **Composable Expertise (Carapaces)**

    ---

    Snap-on skillsets that bundle tools, knowledge, and behavioral instructions. Give a bot `carapaces: [qa, code-review]` and it instantly knows how to test and review code. Carapaces compose via `includes` for layered expertise.

-   :material-file-document-outline:{ .lg .middle } **Workspace Memory + Channel Workspaces**

    ---

    Bots maintain `MEMORY.md`, daily logs, and reference docs — all on disk, all indexed for RAG. Per-channel file stores with 7 built-in schema templates keep project context structured and searchable.

-   :material-sitemap:{ .lg .middle } **Workflows**

    ---

    Reusable multi-step automations defined in YAML. Conditions, approval gates, parallel branches, cross-bot delegation, and scoped secrets. Trigger via API, bot tool, or heartbeat. Manage and monitor from the admin UI.

-   :material-heart-pulse:{ .lg .middle } **Heartbeats + Task Scheduling**

    ---

    Periodic autonomous check-ins with quiet hours and repetition detection. Schedule one-off or recurring tasks with cron-like flexibility. Bots can self-schedule via `schedule_task`. Results dispatch to Slack, webhooks, or the UI.

-   :material-lightning-bolt:{ .lg .middle } **Integration Activation + Templates**

    ---

    Activate an integration on a channel and it instantly gets the right tools, skills, and behavioral instructions — no manual configuration. Pick a compatible workspace template and the bot knows exactly how to organize files. One click to go from blank channel to structured project.

-   :material-plug:{ .lg .middle } **Integration Framework**

    ---

    Pluggable integrations with auto-discovery. Shipped: Slack, GitHub, Discord, Gmail, Frigate, Mission Control, Arr, Claude Code, BlueBubbles, Ingestion. Each provides routers, dispatchers, tools, and lifecycle hooks. Extend with your own via `INTEGRATION_DIRS`.

-   :material-chart-line:{ .lg .middle } **Usage Tracking + Budgeting**

    ---

    Per-bot token usage and cost tracking. Budget limits with configurable enforcement. Usage forecasting and breakdown by model. Powered by LiteLLM pricing data when available.

-   :material-magnify:{ .lg .middle } **Web Search**

    ---

    Built-in web search via SearXNG (self-hosted) or DuckDuckGo (zero-config). Switch backends at runtime from the admin UI. No external API keys required.

-   :material-docker:{ .lg .middle } **Docker Sandboxes**

    ---

    Long-lived containers for isolated code execution. Per-bot sandbox profiles with configurable images, mount points, and resource limits. Scope modes: session, client, agent, or shared.

</div>

---

## Quick Start

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh          # interactive wizard: deployment, LLM provider, auth
docker compose up -d
```

The setup wizard configures `.env`, starts services, and creates a default bot. The Orchestrator bot guides you through the rest conversationally.

[:octicons-arrow-right-24: Full setup guide](setup.md)

## Guides

<div class="grid cards" markdown>

-   [:material-setup: **Setup Guide**](setup.md)

    Installation, providers, workspaces, integrations, troubleshooting.

-   [:material-lightning-bolt: **Templates & Activation**](guides/templates-and-activation.md)

    Activate integrations on channels, pick workspace templates, instant project setup.

-   [:material-slack: **Slack Integration**](guides/slack.md)

    Connect Spindrel to Slack via Socket Mode.

-   [:fontawesome-brands-discord: **Discord Integration**](guides/discord.md)

    Connect Spindrel to Discord.

-   [:material-gmail: **Gmail Integration**](guides/gmail.md)

    Gmail integration for email-driven workflows.

-   [:material-directions-fork: **Delegation**](guides/delegation.md)

    Bot-to-bot delegation — immediate and deferred.

-   [:material-console: **Harnesses**](guides/harnesses.md)

    External CLI tools (Claude Code, Cursor) as agent subprocesses.

-   [:material-shield-lock-outline: **Secrets & Redaction**](guides/secrets.md)

    Secret vault, automatic redaction, and user input detection.

-   [:material-file-import-outline: **Content Ingestion**](guides/ingestion.md)

    Document ingestion pipeline for PDFs, web pages, and more.

-   [:material-chart-line: **Usage & Billing**](guides/usage-and-billing.md)

    Cost tracking, budget limits, spend forecasting, and provider pricing.

-   [:material-puzzle-edit-outline: **Creating Integrations**](integrations/index.md)

    Build custom integrations with routers, dispatchers, and hooks.

-   [:material-cellphone-link: **Agent Client**](guides/clients.md)

    Remote voice assistant + local tool executor.

-   [:material-backup-restore: **Backup & Restore**](backup.md)

    Automated Postgres + config backups to S3.

-   [:material-docker: **Docker Deployment**](docker-deployment.md)

    Production setup with the sibling container pattern.

</div>
