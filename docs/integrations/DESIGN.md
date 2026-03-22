# Integration System Design

This document captures the architectural decisions, design philosophy, known issues, and
remaining debt for the integration layer. It exists so future Claude sessions and contributors
don't re-litigate these decisions or re-introduce the same slop.

---

## Core Boundary

**`/app` is core. `/integrations` (root-level) is extending code.**

| Belongs in `/app` | Belongs in `/integrations` |
|---|---|
| Agent loop, RAG, tool system | Slack Bolt app, channel config logic |
| Task worker, scheduler | Slack-specific message formatting |
| Dispatcher registry + core dispatchers | Integration-specific dispatchers |
| DB models (generic) | Integration-specific config tables |
| `/api/v1/` public REST API | `/integrations/<name>/` routers |

**Rule**: `/app` must not import from `/integrations`. `/app` must not contain integration
brand names (like "slack") in business logic. The word "slack" is allowed only in:
- `app/services/slack_uploads.py` — Slack HTTP calls
- `app/routers/admin_slack.py` — admin UI for Slack channel config
- `app/routers/api_v1_sessions.py` — `_fanout()` fallback

---

## Dispatcher Registry

Dispatchers answer one question: **"Given a completed task result, where and how do I send it?"**

### How it works

`app/agent/dispatchers.py` is the registry:

```python
from app.agent.dispatchers import register, get

# Register a dispatcher for a dispatch_type
register("mytype", MyDispatcher())

# Look up a dispatcher (falls back to "none" if unknown)
dispatcher = get(task.dispatch_type)
await dispatcher.deliver(task, result_text, client_actions=...)
```

`tasks.py` uses `dispatchers.get()` — it has no knowledge of individual dispatchers.

### Core dispatchers (always available)

Registered in `app/agent/dispatchers.py` at import time:

| `dispatch_type` | Class | Behavior |
|---|---|---|
| `"none"` | `_NoneDispatcher` | Result stays in DB only; caller polls `get_task` |
| `"webhook"` | `_WebhookDispatcher` | HTTP POST `{task_id, result}` to `dispatch_config.url` |
| `"internal"` | `_InternalDispatcher` | Injects result into a parent session as a user message |

### Integration dispatchers (pluggable)

An integration registers its dispatcher by placing `dispatcher.py` in its folder.
`integrations/__init__.py` auto-imports it during `discover_integrations()`.

```
integrations/
└── slack/
    └── dispatcher.py   ← calls register("slack", SlackDispatcher()) at import time
```

The `SlackDispatcher` handles `chat.postMessage` + file uploads for the task path.
It is allowed to know about Slack — it's explicitly scoped to `dispatch_type="slack"`.
All its HTTP calls go through `app/services/slack_uploads.py` (for files) and direct
httpx (for messages). The goal is eventually to consolidate into `app/services/slack_client.py`.

---

## Integration Process Discovery

Integrations that need a background process (e.g. Slack Bolt runs as a separate Python
process in socket mode) declare it in `process.py`:

```python
# integrations/slack/process.py
DESCRIPTION = "Slack Bolt bot (socket mode)"
CMD = ["python", "integrations/slack/slack_bot.py"]
REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
```

`integrations/__init__.py` exposes `discover_processes()` which returns only processes
whose `REQUIRED_ENV` vars are all set. `scripts/dev-server.sh` calls
`scripts/list_integration_processes.py` to auto-start all declared processes:

```bash
# In dev-server.sh — no hardcoded integration names
while IFS= read -r cmd; do
    [[ "$cmd" == \#* ]] && continue
    eval "$cmd" &
    PIDS+=($!)
done < <(python scripts/list_integration_processes.py)
```

---

## `app/services/slack_uploads.py`

Canonical place for Slack file upload HTTP calls (files.getUploadURLExternal → upload →
completeUploadExternal). Called by `integrations/slack/dispatcher.py` for the task path.

**Known bug that was fixed**: `files.getUploadURLExternal` requires form-encoded body
(`data=`), NOT JSON (`json=`). Using `json=` silently fails with `missing_filename`.

**TODO**: There is still a `_post_to_slack()` duplicated in multiple places:
- `app/services/delegation.py`
- `app/routers/admin_slack.py`
- `app/routers/api_v1_sessions.py` (`_fanout()`)

These should be consolidated into `app/services/slack_client.py`.

---

## Bot Display Config

Bots have a **generic** display identity usable by any integration:

| Column | Purpose |
|---|---|
| `display_name` | How the bot signs its messages ("Aria", "DevBot") |
| `avatar_url` | URL to the bot's profile image (any integration can use this) |

**Slack emoji shortcodes** (`:robot_face:`) are Slack-specific. They live in
`Bot.integration_config JSONB` under `{"slack": {"icon_emoji": ":robot_face:"}}`.

The admin UI's bot edit page has a Slack subsection under Display for `icon_emoji`.

---

## `dispatch_config` JSONB

`dispatch_config` on `Task` holds the **delivery target** only — where to send the result:

```json
// Slack
{"channel_id": "C123", "token": "xoxb-...", "thread_ts": "1234.56", "reply_in_thread": true}

// Webhook
{"url": "https://example.com/hook"}

// Internal
{"session_id": "uuid"}
```

**What does NOT belong in `dispatch_config`** (known debt):

- Delegation bookkeeping (`_notify_parent`, `_parent_session_id`, `_parent_bot_id`,
  `_parent_client_id`) — these are internal task orchestration state. **TODO**: move
  to a `Task.callback_config` JSONB column.

- Harness execution config (`harness_name`, `working_directory`, `sandbox_instance_id`) —
  these are execution parameters, not delivery targets. **TODO**: move to `Task.metadata` JSONB.

---

## Channel Config — Single Source of Truth

**Use `IntegrationChannelConfig` (`integration_channel_configs` table). Full stop.**

| Column | Purpose |
|---|---|
| `client_id` | Primary key. Format: `"slack:C123456"` |
| `integration` | `"slack"` (allows future: `"teams"`, `"discord"`) |
| `bot_id` | Which bot handles this channel |
| `require_mention` | Whether bot needs `@mention` to respond |
| `passive_memory` | Whether bot silently reads all messages for memory |

`SlackChannelConfig` (`slack_channel_configs`) was dead code and has been dropped
(migration 033).

The Slack integration reads channel config via `/api/slack/config` (60s TTL cache),
served by `app/routers/admin_slack.py`. It does NOT query the DB directly.

---

## Known Debt

For detailed explanation of each item (current behavior, problem, fix, implementation steps)
see [`DEBT.md`](DEBT.md).

### Remaining issues

- [ ] `_post_to_slack()` still duplicated in `app/services/delegation.py` and
  `app/routers/api_v1_sessions.py` and `integrations/slack/dispatcher.py`
  **Fix**: consolidate into `app/services/slack_client.py`

- [ ] `dispatch_config` polluted with delegation bookkeeping (`_notify_parent`, `_parent_*`)
  and harness execution params (`harness_name`, `working_directory`, etc.)
  **Fix**: add `Task.callback_config` JSONB column (migration 039); move those keys there

- [ ] `Task.trigger_rag_loop` boolean column is Slack-specific on a generic model
  **Fix**: move to `callback_config`; drop the column (migration 040)

- [ ] `_fanout()` in `api_v1_sessions.py` has hardcoded `startswith("slack:")` check
  **Fix**: drive fan-out through dispatcher registry (depends on `slack_client.py` being done)

### Completed

- [x] `slack-integration/` folder deleted — `integrations/slack/` is canonical
- [x] Dispatcher registry is now pluggable — `app/agent/dispatchers.py` + `integrations/slack/dispatcher.py`
- [x] `SlackDispatcher` moved out of `tasks.py` into `integrations/slack/dispatcher.py`
- [x] `Bot.slack_display_name/icon_emoji/icon_url` → `display_name`, `avatar_url`, `integration_config`
  (migration 033 + 034)
- [x] `SlackChannelConfig` table dropped (migration 033)
- [x] `app/services/slack_uploads.py` created — canonical file upload, form-encoding bug fixed
- [x] Integration process discovery — `process.py` convention, `dev-server.sh` auto-starts
- [x] Knowledge session scoping + per-row similarity thresholds (migrations 035–038)

---

## Things That Are Fine — Don't Touch

- Agent loop (`app/agent/loop.py`) — clean, no integration coupling
- RAG system — clean
- Tool registry + discovery — clean
- Delegation framework (`app/services/delegation.py`) — good design, just uses bad delivery mechanism
- Provider abstraction — clean
- `/api/v1/` public API — reasonable
- `app/agent/dispatchers.py` — clean registry pattern
