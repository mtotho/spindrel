# Creating an Integration

This guide explains how to create a new integration — a self-contained module that
connects an external service (GitHub, Gmail, webhooks, etc.) to the agent server without
touching core code.

> **Architecture decisions and design philosophy** → see [DESIGN.md](DESIGN.md)

---

## External Integrations (INTEGRATION_DIRS)

Integrations don't have to live inside the agent-server repo. Set `INTEGRATION_DIRS` in
`.env` to point to one or more directories containing integration folders:

```bash
# .env
INTEGRATION_DIRS=/home/you/my-integrations
```

Each directory is scanned the same way as `integrations/` — any subfolder with a
`router.py`, `dispatcher.py`, `tools/*.py`, `skills/*.md`, or `process.py` is discovered
automatically.

**Docker deployment:** mount your external integrations directory into the container and
set `INTEGRATION_DIRS` to the mount point:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - /home/you/my-integrations:/app/ext-integrations:ro
    environment:
      - INTEGRATION_DIRS=/app/ext-integrations
```

**Self-contained structure:** each external integration should include its own `config.py`
for settings and use `integrations/_register.py` (or a local copy of the stub) for tool
registration. See the "Creating an External Integration" section in [example.md](example.md).

---

## Folder Structure

Each integration lives under `integrations/<name>/`. The auto-discovery system scans
this directory at startup. All files are optional except your integration must have at
least one of `router.py`, `dispatcher.py`, or `tools/*.py` to do anything useful.

```
integrations/
├── __init__.py          # auto-discovery (don't edit)
├── _register.py         # tool registration shim (don't edit)
├── utils.py             # helpers: ingest_document, inject_message, etc.
└── mygithub/            # your integration folder
    ├── __init__.py      # optional: id, name, version metadata
    ├── config.py        # integration-specific settings (Pydantic BaseSettings)
    ├── router.py        # HTTP endpoints → registered at /integrations/mygithub/
    ├── dispatcher.py    # task result delivery → called by the task worker
    ├── hooks.py         # integration metadata + lifecycle hooks
    ├── process.py       # background process → auto-started by dev-server.sh
    └── tools/
        ├── __init__.py
        └── my_tool.py   # agent tools — auto-discovered by the loader
```

### What each file does

| File | Auto-loaded? | Purpose |
|---|---|---|
| `router.py` | Yes — registered at `/integrations/<name>/` | Receive webhooks, expose config endpoints |
| `dispatcher.py` | Yes — imported to trigger `register()` | Deliver completed task results to your service |
| `hooks.py` | Yes — imported to trigger `register_integration()` / `register_hook()` | Integration metadata + lifecycle hooks |
| `process.py` | Via `dev-server.sh` | Declare a background process (e.g. a Bolt app) |
| `__init__.py` | Yes (as package) | Optional metadata: `id`, `name`, `version` |
| `config.py` | No (imported by your tools) | Integration-specific env var settings |
| `tools/*.py` | Yes — auto-discovered | Agent tools (underscore-prefixed files skipped) |
| `skills/*.md` | Yes — synced at startup | Skill documents ingested into the skill system |

---

## Agent Tools

Integration tools live in `integrations/<name>/tools/*.py`. The loader auto-discovers
them at startup — any `*.py` file (except underscore-prefixed) is imported and its
`@register`-decorated functions become available as agent tools.

### Registration

Import `register` from the shim at `integrations/_register.py`:

```python
from integrations._register import register

@register({
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Does something useful.",
        "parameters": {"type": "object", "properties": {}},
    },
})
async def my_tool() -> str:
    return '{"result": "ok"}'
```

When running inside the agent server, this resolves to the real registry. When
developing an integration **outside** the server (standalone repo, tests, etc.),
it falls back to a stub that attaches the schema to the function — no server
dependency needed.

**If you're building an external integration**, you only need this stub:

```python
# Minimal drop-in replacement for integrations/_register.py
def register(schema, *, source_dir=None):
    def decorator(func):
        func._tool_schema = schema
        return func
    return decorator
```

To deploy: drop your integration folder into `integrations/` and add your tool
directory to `TOOL_DIRS` (or rely on the `integrations/*/tools/` auto-discovery).

### Config

Integration-specific settings go in your own `config.py` — **not** in `app/config.py`:

```python
# integrations/mygithub/config.py
from pydantic_settings import BaseSettings

class MyConfig(BaseSettings):
    MYGITHUB_TOKEN: str = ""
    MYGITHUB_WEBHOOK_SECRET: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = MyConfig()
```

Then import from your tools: `from integrations.mygithub.config import settings`.

### Shared helpers

Use underscore-prefixed files for shared code within your integration (the loader
skips them): `integrations/<name>/tools/_helpers.py`.

---

## Quickstart

### 1. Create the folder

```bash
mkdir integrations/mygithub
touch integrations/mygithub/__init__.py
```

### 2. Add optional metadata (`__init__.py`)

```python
id = "mygithub"
name = "GitHub Integration"
version = "0.1.0"
```

### 3. Add a router (`router.py`)

The router is a standard FastAPI `APIRouter`. It's registered at `/integrations/<name>/`
automatically — no changes to `app/main.py` needed.

```python
from fastapi import APIRouter, Request
from integrations import utils

router = APIRouter()

@router.post("/webhook")
async def github_webhook(request: Request):
    data = await request.json()
    event = request.headers.get("X-GitHub-Event")

    if event == "pull_request":
        pr = data["pull_request"]

        # 1. Get or create a session for this repo
        from app.db.engine import async_session
        async with async_session() as db:
            session_id = await utils.get_or_create_session(
                client_id=f"github:{data['repository']['full_name']}",
                bot_id="code_review_bot",
                db=db,
            )

            # 2. Inject a message — agent runs and result is dispatched
            result = await utils.inject_message(
                session_id=session_id,
                content=f"PR #{pr['number']} opened: {pr['title']}\n{pr['html_url']}",
                source="github",
                run_agent=True,
                notify=True,
                db=db,
            )

    return {"ok": True}
```

### 4. Add a dispatcher (`dispatcher.py`)

A dispatcher is called by the task worker after an agent run completes. It delivers
the result to your service. Add one only if your integration has its own delivery channel
(e.g. posting to a different chat platform, calling a specific API).

```python
import logging
from app.agent.dispatchers import register

logger = logging.getLogger(__name__)


class MyDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None) -> None:
        cfg = task.dispatch_config or {}
        target_url = cfg.get("webhook_url")
        if not target_url:
            return
        # ... post result to your service ...


# Register at import time — this is what makes it pluggable
register("mygithub", MyDispatcher())
```

The dispatcher is called when a task has `dispatch_type="mygithub"`. To create such a
task, set `dispatch_type` and `dispatch_config` when calling `utils.inject_message()`.

### 5. Add hooks (`hooks.py`)

Hooks let your integration register metadata (client ID prefix, user attribution,
display name resolution) and subscribe to agent lifecycle events — without touching
core code.

**Integration metadata** — register at import time:

```python
from app.agent.hooks import IntegrationMeta, register_integration

def _user_attribution(user) -> dict:
    """Return payload fields for user identity (username, icon)."""
    attrs = {}
    if user.display_name:
        attrs["username"] = user.display_name
    cfg = (user.integration_config or {}).get("mygithub", {})
    if cfg.get("avatar_url"):
        attrs["icon_url"] = cfg["avatar_url"]
    return attrs

register_integration(IntegrationMeta(
    integration_type="mygithub",
    client_id_prefix="mygithub:",
    user_attribution=_user_attribution,
))
```

This registers your integration's client ID prefix (used by `is_integration_client_id()`),
user attribution (used when mirroring messages), and optionally a `resolve_display_names`
callback for the admin UI channel list.

**Lifecycle hooks** — subscribe to agent events:

```python
from app.agent.hooks import HookContext, register_hook

async def _on_after_tool_call(ctx: HookContext, **kwargs) -> None:
    tool = ctx.extra.get("tool_name", "")
    ms = ctx.extra.get("duration_ms", 0)
    print(f"Tool {tool} took {ms}ms for bot {ctx.bot_id}")

register_hook("after_tool_call", _on_after_tool_call)
```

Available lifecycle events:

| Event | Fired when | `ctx.extra` keys |
|-------|-----------|-----------------|
| `after_tool_call` | After each tool execution | `tool_name`, `tool_args`, `duration_ms` |
| `after_response` | After agent returns final response | `response_length`, `tool_calls_made` |
| `before_context_assembly` | Before context is built for an LLM call | `user_message` |

All lifecycle hooks are fire-and-forget — errors are logged but never propagate.
Both sync and async callbacks are supported. Hooks receive a `HookContext` with
`bot_id`, `session_id`, `channel_id`, `client_id`, `correlation_id`, and `extra`.

See `integrations/slack/hooks.py` for a real example: Slack uses `after_tool_call`
to add emoji reactions as tool indicators and log tool calls to an audit channel.

### 6. Add a background process (`process.py`)

If your integration needs a long-running process (e.g. a bot framework using socket mode),
declare it here. `dev-server.sh` will auto-start it when all required env vars are set.

```python
DESCRIPTION = "GitHub webhook listener"
CMD = ["python", "integrations/mygithub/listener.py"]
REQUIRED_ENV = ["GITHUB_WEBHOOK_SECRET", "GITHUB_TOKEN"]
```

`CMD` is a list of strings (passed to `shlex.join` for the shell). The process is
only started if every var in `REQUIRED_ENV` is set in the environment.

---

## APIs Available to Integrations

### Option A: Python helpers (`integrations/utils.py`)

Use these inside router handlers (they take an open `AsyncSession`):

```python
from integrations import utils
from app.db.engine import async_session

async with async_session() as db:
    # Ingest + embed a document (searchable by agents via RAG)
    doc_id = await utils.ingest_document(
        integration_id="mygithub",
        title="PR #42: Add dark mode",
        content="...",
        session_id=None,           # optional: scope to a session
        metadata={"pr_number": 42},
        db=db,
    )

    # Semantic search across ingested documents
    docs = await utils.search_documents(
        q="dark mode css changes",
        integration_id="mygithub",
        limit=5,
        db=db,
    )

    # Get or create a persistent session for a user/channel/resource
    session_id = await utils.get_or_create_session(
        client_id="github:owner/repo",   # unique identifier for this integration entity
        bot_id="my_bot",
        dispatch_config={               # optional: where to deliver results
            "type": "slack",
            "channel_id": "C12345",
            "token": "xoxb-...",
        },
        db=db,
    )

    # Inject a message into a session
    result = await utils.inject_message(
        session_id=session_id,
        content="New PR from alice: Add dark mode",
        source="github",
        run_agent=True,    # True → runs agent, creates a task, returns task_id
        notify=True,       # True → fans out result to dispatch_config target
        db=db,
    )
    # result = {"message_id": "uuid", "session_id": "uuid", "task_id": "uuid-or-null"}
```

### Option B: Public REST API (`/api/v1/`)

Use this from external processes (your integration's background process, tests, etc.).
All endpoints require `Authorization: Bearer <API_KEY>`.

#### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents` | Ingest + embed a document |
| `GET` | `/api/v1/documents/search?q=...` | Semantic search |
| `GET` | `/api/v1/documents/{id}` | Fetch a document |
| `DELETE` | `/api/v1/documents/{id}` | Delete a document |

```json
// POST /api/v1/documents
{
  "title": "PR #42: Add dark mode",
  "content": "...",
  "integration_id": "mygithub",
  "session_id": null,
  "metadata": {"pr_number": 42}
}
```

```
// GET /api/v1/documents/search
?q=dark+mode&integration_id=mygithub&limit=5
```

#### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/sessions` | Create or get a session |
| `POST` | `/api/v1/sessions/{id}/messages` | Inject a message |
| `GET` | `/api/v1/sessions/{id}/messages` | List messages |

```json
// POST /api/v1/sessions
{
  "bot_id": "my_bot",
  "client_id": "github:owner/repo",
  "dispatch_config": {
    "type": "slack",
    "channel_id": "C12345",
    "token": "xoxb-..."
  }
}
// → {"session_id": "uuid"}
```

```json
// POST /api/v1/sessions/{id}/messages
{
  "content": "New PR from alice: Add dark mode",
  "source": "github",
  "run_agent": true,
  "notify": true
}
// → {"message_id": "uuid", "session_id": "uuid", "task_id": "uuid-or-null"}
```

#### Tasks

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/tasks/{id}` | Poll a task's status and result |

Poll this after `run_agent=true` returns a `task_id`. Status: `pending`, `running`, `complete`, `failed`.

---

## Dispatch Config

When a task completes, the task worker looks up the dispatcher for `task.dispatch_type`
and calls `dispatcher.deliver(task, result)`. The dispatcher reads `task.dispatch_config`
for its delivery parameters.

Standard shapes:

```json
// dispatch_type = "slack"
{"channel_id": "C123", "token": "xoxb-...", "thread_ts": "1234.56", "reply_in_thread": true}

// dispatch_type = "webhook"
{"url": "https://myservice.example.com/hook"}

// dispatch_type = "internal"  (injects result back into a session as a user message)
{"session_id": "uuid"}

// dispatch_type = "none"  (result stays in DB; caller polls /api/v1/tasks/{id})
{}
```

For a custom dispatch type, add a `dispatcher.py` (see step 4 above).

---

## Example

See [example.md](example.md) for the minimal `integrations/example/` scaffold.

---

## What Integration Code Must Not Do

- Import from `app/` directly — use `integrations/_register.py` for tool registration, `integrations/utils.py` for helpers, and keep config in your own `config.py`
  - Exception: dispatchers may import `app/agent/dispatchers` for `register()` and `app/agent/bots` for `get_bot()`
- Put integration-specific config in `app/config.py` — create your own `integrations/<name>/config.py`
- Duplicate Slack API call logic — use `integrations/slack/client.py` for messages and `integrations/slack/uploads.py` for file uploads
- Add new columns to core models (`Bot`, `Task`, `Session`) for integration-specific data — use `dispatch_config`, `integration_config` JSONB fields, or add your own table
- Edit `app/main.py`, `app/agent/tasks.py`, or `app/agent/dispatchers.py` (unless adding a core delivery mechanism)
