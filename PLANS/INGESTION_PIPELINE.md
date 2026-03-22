---
status: active
last_updated: 2026-03-22
owner: mtoth
summary: |
  4-layer security pipeline for ingesting external content (email, webhooks, etc.)
  into the agent. Integrations are isolated SQLite-backed plugins that cross into
  the agent only via HTTP to /api/v1/. Gmail is the first integration.
---

# Ingestion Pipeline Plan

## Core Architectural Principle

Integrations are **isolated plugins**. A third-party developer should be able to
copy `integrations/gmail/`, set a few env vars, and have it running with zero
knowledge of agent-server internals.

Rules:
- **SQLite only** — each integration owns `store.db` for quarantine, audit, processed IDs
- **No `/app` imports** — cross the boundary only via HTTP calls to `/api/v1/`
- **No Alembic migrations** — integrations manage their own SQLite schema on startup
- **Pydantic models** throughout (not dataclasses)

---

## Integration HTTP Boundary

| Action | Endpoint |
|--------|----------|
| Inject clean message | `POST /api/v1/sessions/{id}/messages` |
| Store document for RAG | `POST /api/v1/documents` |
| Search documents | `GET /api/v1/documents/search` |
| Get embeddings (optional) | `POST /api/v1/embed` *(see recommendation below)* |

---

## Embedding Endpoint Recommendation

**Recommend: implement `POST /api/v1/embed`**

- Accepts: `{"text": "...", "model": "optional-override"}`
- Returns: `{"embedding": [...], "model": "text-embedding-3-small", "dimensions": 1536}`
- Uses server's existing LiteLLM infrastructure
- Integration only needs `AGENT_API_KEY` + `AGENT_BASE_URL` — no separate provider keys
- Optional — integrations that don't need local semantic search can skip it

---

## 4-Layer Security Pipeline

### Layer 1 — Structural Extraction (deterministic)
- HTML stripping (`html.parser` stdlib, no extra deps)
- MIME decoding (`email` stdlib)
- UTF-8 normalization
- Size truncation (configurable max bytes)
- Output: plain text + structured metadata

### Layer 2 — Deterministic Injection Filter (deterministic)
- Regex pattern matching against known injection phrases
- Zero-width character detection (`\u200b`, `\u200c`, `\u200d`, `\ufeff`, etc.)
- NFKC normalization
- Homoglyph detection: **deferred** — high false-positive risk on internationalized content
- Output: `list[str]` of matched pattern names (empty = clean)

### Layer 3 — AI Safety Classifier (isolated HTTP call)
- Plain `httpx` POST to configurable LLM endpoint
- Default: agent-server's LiteLLM proxy (`INGESTION_CLASSIFIER_URL`)
- Hardcoded system prompt, no tools, no memory, no SDK imports
- Strict JSON output parsing: `{"safe": bool, "reason": str, "risk_level": "low|medium|high"}`
- **Fails closed** — timeout or parse error = quarantine
- Timeout: configurable, default 15s

### Layer 4 — Typed Envelope (Pydantic validation)

```python
class RawMessage(BaseModel):
    source: str          # "gmail", "webhook", etc.
    source_id: str       # dedupe key
    raw_content: str
    metadata: dict

class RiskMetadata(BaseModel):
    layer2_flags: list[str]
    risk_level: Literal["low", "medium", "high"]
    classifier_reason: str

class ExternalMessage(BaseModel):
    source: str
    source_id: str
    body: str            # sanitized
    metadata: dict
    risk: RiskMetadata
    ingested_at: datetime
```

---

## Integration-Local SQLite Schema

Each integration initializes its own `store.db` on startup:

```sql
CREATE TABLE IF NOT EXISTS processed_ids (
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS quarantine (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    raw_content  TEXT NOT NULL,  -- GDPR: purged after retention_days (default 90)
    risk_level   TEXT NOT NULL,
    flags        TEXT,           -- JSON array
    reason       TEXT,
    quarantined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    action       TEXT NOT NULL,  -- "passed", "quarantined", "released", "discarded"
    risk_level   TEXT,
    ts           TEXT NOT NULL
);
```

**GDPR Note:** `quarantine.raw_content` may contain personal email content.
Default retention = 90 days, configurable via `INGESTION_QUARANTINE_RETENTION_DAYS`.
Purge runs on each integration startup and can be triggered manually.

---

## Pipeline Config (`integrations/ingestion/config.py`)

```python
class IngestionConfig(BaseSettings):
    agent_base_url: str         # e.g. http://localhost:8000
    agent_api_key: str
    classifier_url: str         # LiteLLM proxy URL
    classifier_model: str = "gpt-4o-mini"
    classifier_timeout: int = 15
    max_body_bytes: int = 50_000
    quarantine_retention_days: int = 90
    layer2_fail_threshold: int = 1  # flags needed to escalate to Layer 3

    model_config = SettingsConfigDict(env_prefix="INGESTION_")
```

---

## Folder Structure

```
integrations/
  ingestion/              # shared pipeline (not an integration itself)
    __init__.py
    PLAN.md               # this file
    config.py             # IngestionConfig (Pydantic Settings)
    envelope.py           # RawMessage, RiskMetadata, ExternalMessage
    filters.py            # Layer 2 deterministic filters
    classifier.py         # Layer 3 HTTP classifier
    pipeline.py           # orchestrates Layer 1-4
    store.py              # SQLite helper (init schema, quarantine, audit, idempotency)

  gmail/                  # first concrete integration
    __init__.py
    adapter.py            # Gmail API response → RawMessage
    process.py            # background polling loop (30 min interval)
    gmail_tool.py         # CLI for manual fetch/test
    config.py             # Gmail-specific settings (OAuth creds, poll interval)
    store.db              # runtime SQLite (gitignored)
    .env.example          # documents required env vars

docs/integrations/
  CREATING_INTEGRATION.md  # ← needs to be written: pattern guide for new integrations
```

---

## Implementation Order

1. `integrations/ingestion/envelope.py` — Pydantic models
2. `integrations/ingestion/store.py` — SQLite helpers (schema init, quarantine, audit, idempotency)
3. `integrations/ingestion/config.py` — IngestionConfig
4. `integrations/ingestion/filters.py` — Layer 2
5. `integrations/ingestion/classifier.py` — Layer 3 (httpx, fails closed)
6. `integrations/ingestion/pipeline.py` — orchestrator
7. `app/api/v1/embed.py` — embedding endpoint (optional but recommended)
8. `integrations/gmail/` — Gmail adapter, poller, CLI
9. `docs/integrations/CREATING_INTEGRATION.md` — pattern guide

---

## Open Questions

- [ ] Gmail OAuth token storage — env vars vs file vs secrets manager?
- [ ] Should `POST /api/v1/embed` be authenticated? (Yes — same API key as other routes)
- [ ] Rate limiting on Layer 3 classifier calls?
- [ ] Bot YAML field to opt into `retrieve_external` tool?
