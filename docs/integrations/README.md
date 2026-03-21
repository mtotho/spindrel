# Creating an Integration

This guide explains how to create a new integration — a self-contained module that
connects an external service (GitHub, Gmail, webhooks, etc.) to the agent server without
touching core code.

> **Architecture decisions, design philosophy, and known debt** → see [DESIGN.md](DESIGN.md)

---

## Folder Structure

Each integration lives under `integrations/<name>/`. The auto-discovery system scans
this directory at startup. All files are optional except your integration must have at
least one of `router.py` or `dispatcher.py` to do anything useful.

```
integrations/
├── __init__.py          # auto-discovery (don't edit)
├── utils.py             # helpers: ingest_document, inject_message, etc.
└── mygithub/            # your integration folder
    ├── __init__.py      # optional: id, name, version metadata
    ├── router.py        # HTTP endpoints → registered at /integrations/mygithub/
    ├── dispatcher.py    # task result delivery → called by the task worker
    └── process.py       # background process → auto-started by dev-server.sh
```

### What each file does

| File | Auto-loaded? | Purpose |
|---|---|---|
| `router.py` | Yes — registered at `/integrations/<name>/` | Receive webhooks, expose config endpoints |
| `dispatcher.py` | Yes — imported to trigger `register()` | Deliver completed task results to your service |
| `process.py` | Via `dev-server.sh` | Declare a background process (e.g. a Bolt app) |
| `__init__.py` | Yes (as package) | Optional metadata: `id`, `name`, `version` |

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

### 5. Add a background process (`process.py`)

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

- Import from `app/agent/`, `app/services/`, or `app/tools/` directly (except `app/agent/dispatchers` for `register()` and `app/agent/bots` for `get_bot()` in dispatchers)
- Duplicate Slack API call logic — use `app/services/slack_uploads.py` for file uploads
- Add new columns to core models (`Bot`, `Task`, `Session`) for integration-specific data — use `dispatch_config`, `integration_config` JSONB fields, or add your own table
- Edit `app/main.py`, `app/agent/tasks.py`, or `app/agent/dispatchers.py` (unless adding a core delivery mechanism)
