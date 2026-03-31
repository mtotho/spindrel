# Spindrel

A self-hosted LLM agent server built on FastAPI and PostgreSQL. All LLM calls route through a LiteLLM proxy — bring your own API keys, use any model provider.

## What It Does

- **Multi-bot agent system** with tool use, delegation, and harness execution
- **Workspace isolation** — Docker-based environments with per-bot file access and skills
- **Channel-based conversations** with persistent history, compaction, and workspace file storage
- **Integration framework** — Slack, GitHub, Frigate, and custom integrations via a plugin system
- **Scheduled automation** — heartbeats, recurring tasks, and quiet hours
- **RAG pipeline** — skills, workspace files, and tool schemas indexed with pgvector

## Quick Start

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh
```

The setup wizard walks you through `.env` configuration, database setup, and first bot creation. See the [full setup guide](setup.md) for details.

## Architecture at a Glance

```
Client (UI / Slack / API)
    ↓
FastAPI server → Agent Loop → LiteLLM Proxy → LLM Provider
    ↓                ↓
PostgreSQL      Tool Dispatch (local, MCP, client)
(pgvector)           ↓
                Workspace (Docker containers, file storage)
```

## Next Steps

- [Setup Guide](setup.md) — install and configure
- [Docker Deployment](docker-deployment.md) — run in production
- [Slack Integration](guides/slack.md) — connect to Slack
- [Creating an Integration](integrations/index.md) — build your own
