---
status: active
last_updated: 2026-03-22
owner: mtoth
summary: >
  Direct trusted webhook integration with GitHub. Receives CI/workflow events,
  validates HMAC signature, and notifies the agent via session message injection.
  No ingestion pipeline — private repo events are trusted.
  GitHub is the first direct (non-isolated) integration.
---

# GitHub Integration Plan

## Core Principle
GitHub webhooks from our private repo are **trusted** — no 4-layer ingestion pipeline needed.
Events are ephemeral and fire-and-forget. No SQLite, no quarantine.

## Notification Mechanism
GitHub events are injected into the agent via `POST /api/v1/sessions/{id}/messages` — the standard API boundary. No direct Slack API calls in the integration. The agent receives the event as a message and dispatches to Slack naturally through its normal flow.

> **Open question:** How does the integration know which session/channel to post back to? Options: hardcoded env var (AGENT_SESSION_ID), looked up from a config table, or passed in via webhook metadata. Needs decision before implementation.

## Scope (Phase 1)
- CI/workflow failure notifications → post to Slack with context + link
- PR opened/merged → optional, low priority

## Structure
```
integrations/github/
  __init__.py
  router.py        # FastAPI router, POST /integrations/github/webhook
  validator.py     # HMAC-SHA256 signature validation (X-Hub-Signature-256)
  dispatcher.py    # Routes event types to handlers
  handlers.py      # workflow_run/check_run failed → notify agent via POST /api/v1/sessions/{id}/messages
  config.py        # GithubConfig(BaseSettings): GITHUB_WEBHOOK_SECRET, GITHUB_TOKEN, AGENT_SESSION_ID
  tests/
    __init__.py
    test_validator.py
    test_dispatcher.py
```

## Webhook Events (Phase 1)
- `workflow_run` — completed + conclusion=failure → Slack notification
- `check_run` — completed + conclusion=failure → Slack notification

## Env Vars
- `GITHUB_WEBHOOK_SECRET` — for HMAC validation
- `GITHUB_TOKEN` — for posting PR comments (Phase 2)
- `AGENT_SESSION_ID` — target session for injected messages

## Implementation Steps (for Claude Code)
1. Create all files under `integrations/github/`
2. Register router in `app/main.py` under `/integrations/github/webhook`
3. Wire notification via POST /api/v1/sessions/{id}/messages — no direct Slack calls
4. Add `GITHUB_WEBHOOK_SECRET` to env docs
5. Configure webhook in GitHub repo settings (manual step)
6. Write tests under `integrations/github/tests/`

## Out of Scope (Phase 1)
- Public issue ingestion
- Ingestion pipeline routing
- Auto re-run CI
