# Integrations

Integrations connect external services (Gmail, GitHub, webhooks, etc.) to the agent server without touching core code. Each integration lives in its own folder under `integrations/` and is auto-discovered at startup.

## Architecture

```
integrations/
├── __init__.py          # auto-discovery (scans */router.py)
├── base.py              # optional IntegrationBase class
├── utils.py             # helpers: ingest_document, inject_message, etc.
└── gmail/               # your integration
    ├── __init__.py      # id, name, version metadata
    └── router.py        # FastAPI APIRouter — registered at /integrations/gmail/
```

Integrations interact with the agent server through two surfaces:

1. **Public REST API** (`/api/v1/`) — call from anywhere with a Bearer token
2. **Python helpers** (`integrations/utils.py`) — use inside router handlers (have a DB session)

## Creating an Integration

### 1. Create the folder

```bash
mkdir integrations/mygmail
touch integrations/mygmail/__init__.py integrations/mygmail/router.py
```

### 2. Add metadata (`__init__.py`)

```python
id = "gmail"
name = "Gmail Integration"
version = "0.1.0"
```

### 3. Add the router (`router.py`)

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth
from integrations import utils

router = APIRouter()

@router.post("/webhook")
async def gmail_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive Gmail push notifications."""
    data = await request.json()

    # 1. Ingest the email as a searchable document
    doc_id = await utils.ingest_document(
        integration_id="gmail",
        title=data["subject"],
        content=data["body"],
        metadata={"from": data["from"], "thread_id": data["threadId"]},
        db=db,
    )

    # 2. Inject a message into a session (fans out to Slack if that session is a Slack channel)
    result = await utils.inject_message(
        session_id=...,      # your integration's session UUID
        content=f"New email from {data['from']}: {data['subject']}",
        source="gmail",
        run_agent=True,      # have the agent process and respond
        notify=True,         # fan-out to Slack / dispatch_config
        db=db,
    )

    return {"ok": True, "doc_id": str(doc_id), "task_id": result["task_id"]}
```

The router is registered at `/integrations/gmail/` automatically. No changes to `app/main.py` needed.

## Session Fan-out

When `notify=True` is passed to `inject_message()`, the agent server fans out to the session's dispatch targets:

- **Slack** — if the session's `client_id` starts with `slack:{channel_id}`, a message is posted to that channel using the configured `SLACK_BOT_TOKEN`. Alternatively, a full `dispatch_config` (with token, channel_id, thread_ts) can be stored on the session.
- **Future** — additional fan-out targets can be added by extending `_fanout()` in `app/routers/api_v1_sessions.py`.

### Storing dispatch_config on a session

When creating a session for an integration that should fan-out to Slack (or another target):

```python
session_id = await utils.get_or_create_session(
    client_id="gmail:user@example.com",
    bot_id="my_bot",
    dispatch_config={
        "type": "slack",
        "channel_id": "C12345678",
        "thread_ts": None,          # None = channel root
        "token": "xoxb-...",        # optional — falls back to SLACK_BOT_TOKEN
    },
    db=db,
)
```

## Public REST API (`/api/v1/`)

All endpoints require `Authorization: Bearer <API_KEY>`.

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/tasks/{id}` | Poll a task's status and result |

Use this to poll after `run_agent=true` on message injection returns a `task_id`. Status values: `pending`, `running`, `complete`, `failed`.

### Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents` | Ingest + embed a document |
| `GET` | `/api/v1/documents/search?q=...` | Semantic search |
| `GET` | `/api/v1/documents/{id}` | Fetch by ID |
| `DELETE` | `/api/v1/documents/{id}` | Delete |

**POST /api/v1/documents**
```json
{
  "title": "Email: Q1 Review",
  "content": "...",
  "integration_id": "gmail",
  "session_id": "uuid-or-null",
  "metadata": {"thread_id": "..."}
}
```

**GET /api/v1/documents/search**
```
?q=quarterly+review&integration_id=gmail&session_id=uuid&limit=10
```

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sessions` | Create/get a session |
| `POST` | `/api/v1/sessions/{id}/messages` | Inject a message |
| `GET` | `/api/v1/sessions/{id}/messages` | List messages |

**POST /api/v1/sessions**
```json
{
  "bot_id": "default",
  "client_id": "gmail:user@example.com",
  "dispatch_config": {"type": "slack", "channel_id": "C123", "token": "xoxb-..."}
}
```

**POST /api/v1/sessions/{id}/messages**
```json
{
  "content": "New email from alice@example.com: meeting at 3pm",
  "source": "gmail",
  "run_agent": true,
  "notify": true
}
```

Returns:
```json
{"message_id": "uuid", "session_id": "uuid", "task_id": "uuid-or-null"}
```

## Available Helpers (`integrations/utils.py`)

```python
# Embed and store a document
await utils.ingest_document(integration_id, title, content, *, session_id=None, metadata=None, db)

# Semantic search
await utils.search_documents(q, *, integration_id=None, session_id=None, limit=10, db)

# Get or create a session (locked=True, for integrations)
await utils.get_or_create_session(client_id, bot_id, *, dispatch_config=None, db)

# Inject a message (store + optional fan-out + optional agent run)
await utils.inject_message(session_id, content, source, *, run_agent=False, notify=True, db)
```

## Examples

- [Example integration scaffold](example.md)
