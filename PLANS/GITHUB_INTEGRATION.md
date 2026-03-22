---
status: active
last_updated: 2026-03-22
owner: mtoth
summary: >
  Direct trusted webhook integration with GitHub. Receives CI/workflow events,
  validates HMAC signature, and notifies the agent in Slack. No ingestion pipeline —
  private repo events are trusted. GitHub is the first direct (non-isolated) integration.
---

# GitHub Integration Plan

## Core Principle
GitHub webhooks from our private repo are **trusted** — no 4-layer ingestion pipeline needed.
Events are ephemeral and fire-and-forget. No SQLite, no quarantine.

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
  handlers.py      # workflow_run/check_run failed → notify agent via Slack
  config.py        # GithubConfig(BaseSettings): GITHUB_WEBHOOK_SECRET, GITHUB_TOKEN
```

## Webhook Events (Phase 1)
- `workflow_run` — completed + conclusion=failure → Slack notification
- `check_run` — completed + conclusion=failure → Slack notification

## Env Vars
- `GITHUB_WEBHOOK_SECRET` — for HMAC validation
- `GITHUB_TOKEN` — for posting PR comments (Phase 2)

## Implementation Steps (for Claude Code)
1. Create all files under `integrations/github/`
2. Register router in `app/main.py` under `/integrations/github/webhook`
3. Wire Slack notification via existing Slack tool/client
4. Add `GITHUB_WEBHOOK_SECRET` to env docs
5. Configure webhook in GitHub repo settings (manual step)
6. Write tests under `integrations/github/tests/`

## Out of Scope (Phase 1)
- Public issue ingestion
- Ingestion pipeline routing
- Auto re-run CI
