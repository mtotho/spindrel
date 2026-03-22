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
- `app/routers/admin_channels.py` — admin UI for Slack channel config display
- `app/config.py` — `SLACK_BOT_TOKEN`/`SLACK_DEFAULT_BOT` env var config (used by admin)

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
All its HTTP calls go through `integrations/slack/client.py` (for messages) and
`integrations/slack/uploads.py` (for files).

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

## `integrations/slack/client.py` and `integrations/slack/uploads.py`

All Slack HTTP calls live in `integrations/slack/`:

- **`client.py`** — `post_message()` and `bot_attribution()`: single source of truth for
  `chat.postMessage`. Used by `SlackDispatcher.deliver()`, `SlackDispatcher.post_message()`,
  and indirectly by `_fanout()` and `delegation.post_child_response()` via the dispatcher registry.
- **`uploads.py`** — file upload flow (files.getUploadURLExternal → upload →
  completeUploadExternal). Called by `SlackDispatcher.deliver()`.

**Known bug that was fixed**: `files.getUploadURLExternal` requires form-encoded body
(`data=`), NOT JSON (`json=`). Using `json=` silently fails with `missing_filename`.

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

**What does NOT belong in `dispatch_config`** (resolved):

- Delegation bookkeeping (`notify_parent`, `parent_session_id`, `parent_bot_id`,
  `parent_client_id`) — moved to `Task.callback_config` JSONB (migrations 039+040).

- Harness execution config (`harness_name`, `working_directory`, `sandbox_instance_id`) —
  moved to `Task.callback_config` JSONB.

---

## Channel Config — Single Source of Truth

**Use `Channel` (`channels` table, migration 043).** `IntegrationChannelConfig` is a legacy
table kept for backwards compatibility but no longer read by core code.

| Column | Purpose |
|---|---|
| `id` | UUID primary key (derived from `client_id` via `derive_channel_id()`) |
| `client_id` | Format: `"slack:C123456"` |
| `integration` | `"slack"` (allows future: `"teams"`, `"discord"`) |
| `bot_id` | Which bot handles this channel |
| `require_mention` | Whether bot needs `@mention` to respond |
| `passive_memory` | Whether bot silently reads all messages for memory |
| `dispatch_config` | JSONB delivery target (channel_id, token, thread_ts) |

The Slack integration reads channel config via `/api/slack/config` (60s TTL cache),
served by `app/routers/admin_channels.py`. It does NOT query the DB directly.

---

## Known Debt

For detailed explanation of each item (current behavior, problem, fix, implementation steps)
see [`DEBT.md`](DEBT.md).

### Remaining issues

_(None — all known integration boundary violations have been resolved.)_

### Completed

- [x] `slack-integration/` folder deleted — `integrations/slack/` is canonical
- [x] Dispatcher registry is now pluggable — `app/agent/dispatchers.py` + `integrations/slack/dispatcher.py`
- [x] `SlackDispatcher` moved out of `tasks.py` into `integrations/slack/dispatcher.py`
- [x] `Bot.slack_display_name/icon_emoji/icon_url` → `display_name`, `avatar_url`, `integration_config`
  (migration 033 + 034)
- [x] `SlackChannelConfig` table dropped (migration 033)
- [x] `integrations/slack/uploads.py` — canonical file upload (moved from `app/services/slack_uploads.py`)
- [x] Integration process discovery — `process.py` convention, `dev-server.sh` auto-starts
- [x] Knowledge session scoping + per-row similarity thresholds (migrations 035–038)
- [x] `_post_to_slack()` consolidated — `integrations/slack/client.py` is single source of truth
- [x] `_fanout()` driven through dispatcher registry — `post_message()` on Dispatcher protocol
- [x] `Task.callback_config` JSONB added (migrations 039+040) — orchestration separated from delivery
- [x] Delegation `_post_to_slack()` removed — uses dispatcher registry via `post_child_response()`
- [x] `store_slack_echo_as_passive` renamed to `store_dispatch_echo` — integration-agnostic
- [x] Hardcoded `dispatch_type == "slack"` checks replaced with `channel.integration or "none"`
- [x] `_INTEGRATION_PREFIXES` deduplicated — exported from `channels.py`

---

## Things That Are Fine — Don't Touch

- Agent loop (`app/agent/loop.py`) — clean, no integration coupling
- RAG system — clean
- Tool registry + discovery — clean
- Delegation framework (`app/services/delegation.py`) — clean, routes through dispatcher registry
- Provider abstraction — clean
- `/api/v1/` public API — reasonable
- `app/agent/dispatchers.py` — clean registry pattern
