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

See [README.md](README.md) for full documentation on each file.

## Removing this example

Delete `integrations/example/` and restart the server. No other changes needed.
