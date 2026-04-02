# Example Integration

The `integrations/example/` scaffold demonstrates the minimal integration structure.

## Files

```
integrations/example/
├── __init__.py    # metadata: id, name, version
└── router.py      # FastAPI router registered at /integrations/example/
```

## Endpoints (once server starts)

- `GET /integrations/example/ping` — health check, returns `{"status": "ok", "integration": "example"}`
- `POST /integrations/example/ingest` — ingest a document into the integration_documents store

## Optional files you can add

| File | Purpose |
|---|---|
| `dispatcher.py` | Deliver task results to your service — calls `register("example", ...)` |
| `process.py` | Declare a background process auto-started by `dev-server.sh` |

See [Creating an Integration](index.md) for full documentation on each file.

## Removing this example

Delete `integrations/example/` and restart the server. No other changes needed.

---

## Creating an External Integration

You can develop integrations **outside** the agent-server repo and load them via `INTEGRATION_DIRS`.

### 1. Create a directory

```bash
mkdir -p ~/my-integrations/mygithub
```

### 2. Add the `_register.py` shim

Copy this into your integration's root (or import from the agent-server's `integrations/_register.py`):

```python
# ~/my-integrations/mygithub/_register.py
def register(schema, *, source_dir=None):
    def decorator(func):
        func._tool_schema = schema
        return func
    return decorator
```

### 3. Create your tools

```python
# ~/my-integrations/mygithub/tools/my_tool.py
from integrations._register import register

@register({
    "type": "function",
    "function": {
        "name": "github_search",
        "description": "Search GitHub issues.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
})
async def github_search(query: str) -> str:
    return '{"results": []}'
```

### 4. Add config, router, skills as needed

Follow the same structure as in-repo integrations. See [Creating an Integration](index.md).

### 5. Wire it up

```bash
# .env
INTEGRATION_DIRS=~/my-integrations
```

For Docker, add a volume mount:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - ~/my-integrations:/app/ext-integrations:ro
    environment:
      - INTEGRATION_DIRS=/app/ext-integrations
```

Restart the server. Your integration's tools, skills, routers, and dispatchers are discovered automatically.
