# Ingestion Framework

The ingestion framework provides a shared 4-layer security pipeline and content feed base class for building integrations that pull external content (email, RSS, webhooks, etc.) into channel workspaces.

## Architecture

```
                External Source (Gmail, RSS, webhook, ...)
                              │
                    ┌─────────▼──────────┐
                    │   ContentFeed      │  fetch_items() → list[RawMessage]
                    │   (your subclass)  │  format_item() → FeedItem
                    └─────────┬──────────┘
                              │ raw content
                    ┌─────────▼──────────┐
                    │ IngestionPipeline  │  process(RawMessage) → ExternalMessage | None
                    │                    │
                    │  Layer 1: HTML strip, Unicode normalize, truncate
                    │  Layer 2: Regex injection filters + zero-width chars
                    │  Layer 3: AI classifier (LLM, fails closed)
                    │  Layer 4: Typed Pydantic envelope
                    │                    │
                    └──┬──────────────┬──┘
                       │              │
                  ┌────▼────┐   ┌────▼────┐
                  │ Passed  │   │Quarantine│
                  │ items   │   │(SQLite)  │
                  └────┬────┘   └─────────┘
                       │
              format_item() → FeedItem
                       │
              Deliver to workspace
```

## Components

| Module | Purpose |
|---|---|
| `integrations/ingestion/envelope.py` | `RawMessage`, `ExternalMessage`, `RiskMetadata` — the data models |
| `integrations/ingestion/pipeline.py` | `IngestionPipeline` — orchestrates Layers 1-4 |
| `integrations/ingestion/filters.py` | Layer 2 — regex injection patterns + zero-width char detection |
| `integrations/ingestion/classifier.py` | Layer 3 — AI safety classifier via HTTP (fails closed) |
| `integrations/ingestion/store.py` | `IngestionStore` — SQLite: idempotency, quarantine, audit, cursors |
| `integrations/ingestion/config.py` | `IngestionConfig` — env-based settings (`INGESTION_` prefix) |
| `integrations/ingestion/feed.py` | `ContentFeed` ABC + `FeedItem` + `CycleResult` |

## Quick Start: Building a Content Feed

### 1. Subclass ContentFeed

```python
# integrations/myfeed/feed.py
from integrations.ingestion import ContentFeed, RawMessage, ExternalMessage, FeedItem

class MyFeed(ContentFeed):
    source = "myfeed"  # used as dedupe namespace and cursor key

    def __init__(self, pipeline, store, api_url: str) -> None:
        super().__init__(pipeline, store)
        self.api_url = api_url

    async def fetch_items(self) -> list[RawMessage]:
        """Pull raw items from the external source."""
        # Use self.get_cursor() to resume from last position
        last_id = self.get_cursor() or "0"

        items = await my_api_call(self.api_url, since=last_id)

        raw = []
        for item in items:
            raw.append(RawMessage(
                source=self.source,
                source_id=f"myfeed:{item['id']}",
                raw_content=item["html_body"],
                metadata={"title": item["title"], "author": item["author"]},
            ))

        # Update cursor to latest item
        if items:
            self.set_cursor(items[-1]["id"])

        return raw

    def format_item(self, envelope: ExternalMessage) -> FeedItem:
        """Convert processed envelope to a delivery-ready FeedItem."""
        return FeedItem(
            title=envelope.metadata.get("title", "Untitled"),
            body=f"**By {envelope.metadata.get('author', 'unknown')}**\n\n{envelope.body}",
            source_id=envelope.source_id,
            metadata=envelope.metadata,
            suggested_path=f"data/myfeed/{envelope.source_id}.md",
            risk_level=envelope.risk.risk_level,
        )
```

### 2. Set Up the Pipeline

```python
# integrations/myfeed/factory.py
import os
from integrations.ingestion.config import IngestionConfig
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore
from integrations.myfeed.feed import MyFeed

DB_DIR = os.path.expanduser("~/.agent-workspaces/.ingestion")

def create_feed(api_url: str) -> tuple[MyFeed, IngestionStore]:
    os.makedirs(DB_DIR, exist_ok=True)
    store = IngestionStore(os.path.join(DB_DIR, "myfeed.db"))
    config = IngestionConfig()  # reads INGESTION_* env vars
    pipeline = IngestionPipeline(config=config, store=store)
    feed = MyFeed(pipeline=pipeline, store=store, api_url=api_url)
    return feed, store
```

### 3. Run a Cycle

```python
feed, store = create_feed("https://api.example.com/feed")
try:
    result = await feed.run_cycle()
    # result.fetched  — total items pulled
    # result.passed   — items that cleared security
    # result.quarantined — items rejected by pipeline
    # result.skipped  — duplicate items
    # result.items    — list[FeedItem] ready for delivery
    # result.errors   — list[str] per-item error messages

    for item in result.items:
        # Deliver to channel workspace, timeline, etc.
        await deliver(item)
finally:
    store.close()
```

## Data Models

### RawMessage (pipeline input)

```python
class RawMessage(BaseModel):
    source: str       # "gmail", "rss", "webhook" — dedupe namespace
    source_id: str    # unique ID within source (dedupe key)
    raw_content: str  # untrusted HTML/text from external source
    metadata: dict    # pass-through metadata (subject, author, etc.)
```

### ExternalMessage (pipeline output)

```python
class ExternalMessage(BaseModel):
    source: str
    source_id: str
    body: str                # sanitized plain text
    metadata: dict           # from RawMessage
    risk: RiskMetadata       # security assessment
    ingested_at: datetime    # UTC timestamp
```

### FeedItem (delivery-ready)

```python
class FeedItem(BaseModel):
    title: str
    body: str                # markdown for workspace file
    source_id: str
    metadata: dict
    suggested_path: str      # e.g. "data/gmail/2026-03-30-report.md"
    risk_level: str          # "low", "medium", "high"
```

## Security Pipeline Details

### Layer 1: Structural Extraction

- Strips `<script>` and `<style>` tags via stdlib `html.parser`
- Normalizes Unicode to NFKC
- Truncates body to `INGESTION_MAX_BODY_BYTES` (default: 50,000)

### Layer 2: Deterministic Filters

Regex-based detection of known injection patterns:

| Pattern | What it catches |
|---|---|
| `ignore_previous` | "ignore all previous instructions" |
| `system_prompt_override` | "you are now...", "new instructions" |
| `role_injection` | `<system>`, `<\|assistant\|>`, etc. |
| `prompt_leak_request` | "repeat your system prompt" |
| `jailbreak_dan` | "D.A.N. mode" variants |
| `base64_payload` | "decode this base64" |
| `markdown_injection` | `![](https://...)` image embeds |
| `hidden_instruction` | "hidden instruction" |

Plus 12 zero-width/invisible Unicode character classes (U+200B through U+2064).

Layer 2 flags are attached to the envelope's `RiskMetadata` but don't directly block — they inform the AI classifier in Layer 3.

### Layer 3: AI Classifier

- Sends sanitized text to a configurable LLM endpoint (OpenAI-compatible `/v1/chat/completions`)
- Expects JSON response: `{"safe": bool, "reason": str, "risk_level": "low|medium|high"}`
- **Fails closed**: any error (timeout, bad JSON, network failure) results in quarantine with `risk_level: "high"`
- Configurable via `INGESTION_CLASSIFIER_URL` and `INGESTION_CLASSIFIER_MODEL`

### Layer 4: Typed Envelope

- Validates through Pydantic into `ExternalMessage`
- Attaches `RiskMetadata` with Layer 2 flags and Layer 3 verdict
- Timestamps with UTC `ingested_at`

## IngestionStore (SQLite)

Each integration gets its own SQLite database (e.g. `~/.agent-workspaces/.ingestion/gmail.db`). The store manages:

| Table | Purpose |
|---|---|
| `processed_ids` | Idempotency — tracks `(source, source_id)` pairs already seen |
| `quarantine` | Stores rejected content with risk level, flags, and reason |
| `audit_log` | Records every pass/quarantine decision |
| `cursors` | Key-value store for feed position tracking |

### Bot Tool: `query_feed_store`

Bots can query feed stores directly using the `query_feed_store` tool. This is available when the `gmail-feeds` or `mission-control` carapace is active.

| Action | Description |
|---|---|
| `stats` | Aggregate counts — total processed, quarantined, 24h activity, last cursor |
| `recent` | List recently passed items from the audit log |
| `quarantine` | List quarantined items with risk level, flags, and reason |
| `sources` | Discover all feed stores and their sources |

**Examples:**
```
query_feed_store(action="stats", store="gmail", source="gmail")
query_feed_store(action="quarantine", store="gmail", limit=5)
query_feed_store(action="sources")
```

The tool discovers stores by scanning `~/.agent-workspaces/.ingestion/*.db`. Each `ContentFeed` subclass gets its own DB file.

### Manual Queries (CLI)

```bash
# View recent quarantined items
sqlite3 ~/.agent-workspaces/.ingestion/myfeed.db \
  "SELECT source_id, risk_level, reason FROM quarantine ORDER BY quarantined_at DESC LIMIT 10"

# View audit log
sqlite3 ~/.agent-workspaces/.ingestion/myfeed.db \
  "SELECT source_id, action, risk_level, ts FROM audit_log ORDER BY ts DESC LIMIT 20"

# Check cursors
sqlite3 ~/.agent-workspaces/.ingestion/myfeed.db \
  "SELECT key, value, updated_at FROM cursors"

# Purge old quarantine entries (done programmatically via store.purge_quarantine())
```

### Email Triage Template

The Gmail integration ships an **Email Triage & Digest** workspace template (`email-digest`) that teaches bots a structured triage protocol:

- **Triage categories**: Urgent, Action Required, Projects/Threads, FYI, Low Priority
- **Workspace files**: `triage.md` (categorized log), `actions.md` (extracted action items), `digest.md` (summary), `feeds.md` (rules)
- **Action extraction**: Automatic detection of deadlines, reply requests, approvals, assignments
- **MC integration**: Creates task cards from actionable emails, logs triage to timeline
- **Heartbeat-ready**: Template includes suggested heartbeat config for automated digest generation

Activate Gmail on a channel and select the "Email Triage & Digest" template to get the full protocol.

## Configuration

All settings use the `INGESTION_` env prefix:

| Setting | Default | Description |
|---|---|---|
| `INGESTION_CLASSIFIER_URL` | `http://localhost:8000/v1/chat/completions` | LLM endpoint for Layer 3 |
| `INGESTION_CLASSIFIER_MODEL` | `gpt-4o-mini` | Model for safety classification |
| `INGESTION_CLASSIFIER_TIMEOUT` | `15` | Seconds before classifier fails closed |
| `INGESTION_MAX_BODY_BYTES` | `50000` | Truncation limit for raw content |
| `INGESTION_QUARANTINE_RETENTION_DAYS` | `90` | Days before purge_quarantine() deletes entries |
| `INGESTION_AGENT_BASE_URL` | `http://localhost:8000` | Server URL (for classifier routing) |
| `INGESTION_AGENT_API_KEY` | (empty) | API key for classifier endpoint auth |

## Lifecycle and Cleanup

Always close the store when done to avoid SQLite file locks:

```python
feed, store = create_feed()
try:
    result = await feed.run_cycle()
    # ... deliver items ...
finally:
    store.close()
```

If your feed holds a connection (like IMAP), add a `_disconnect()` method and call it in the `finally` block too. See `integrations/gmail/feed.py` for an example.

## Existing Integrations

| Integration | Feed class | Source |
|---|---|---|
| Gmail | `GmailFeed` | IMAP polling with cursor-based resume |

See [Gmail Integration Guide](gmail.md) for the full setup walkthrough.
