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

## Removing this example

Delete `integrations/example/` and restart the server. No other changes needed.
