---
name: ingestion-pipeline
description: >
  Implementation guide for the ingestion pipeline — the 4-layer security system that
  processes all external content before the agent sees it. Load when building a new
  ContentFeed integration, wiring up external data sources (email, RSS, webhooks, APIs),
  debugging quarantine or classification issues, or reviewing the security model.
  Trigger on: "ingestion pipeline", "content feed", "ContentFeed", "external content",
  "quarantine", "prompt injection defense", "safety classifier", "build a feed",
  "new integration with external data", "RawMessage", "ExternalMessage".
---

# Ingestion Pipeline — Implementation Guide

The ingestion pipeline is the security layer between external content and the agent. Every
external data source (email, RSS, webhook, API response) must pass through it. The agent
never sees raw external content — only sanitized, typed envelopes.

## Architecture

```
External Source (email, RSS, webhook, API)
    │
    ├── ContentFeed.fetch_items() → list[RawMessage]
    │
    └── for each RawMessage:
         │
         ├── [Idempotency] store.already_processed(source, source_id)?
         │    └── YES → skip
         │
         ├── [Layer 1] Structural Extraction (deterministic)
         │    HTML strip (stdlib html.parser) → NFKC normalize → truncate to max_body_bytes
         │
         ├── [Layer 2] Deterministic Injection Filter
         │    8 regex patterns + zero-width char detection → list[str] flags
         │    Flags inform but do NOT block — Layer 3 decides
         │
         ├── [Layer 3] AI Safety Classifier (isolated LLM call)
         │    Locked system prompt, no tools/memory/context
         │    → ClassifierResult(safe: bool, reason: str, risk_level: low|medium|high)
         │    Fails closed: any error → safe=False, risk_level="high"
         │
         ├── If NOT safe → quarantine + audit + mark_processed → return None
         │
         └── If safe → ExternalMessage(body, metadata, risk) + audit + mark_processed
              │
              └── ContentFeed.format_item(envelope) → FeedItem
```

## Core Components

All code lives in `integrations/ingestion/`.

| File | Class/Function | Purpose |
|------|---------------|---------|
| `envelope.py` | `RawMessage` | Inbound untrusted content (source, source_id, raw_content, metadata) |
| `envelope.py` | `ExternalMessage` | Sanitized envelope the agent consumes (body, metadata, risk, ingested_at) |
| `envelope.py` | `RiskMetadata` | Security assessment (layer2_flags, risk_level, classifier_reason) |
| `pipeline.py` | `IngestionPipeline` | Orchestrates Layers 1-4; `.process(RawMessage) → ExternalMessage \| None` |
| `feed.py` | `ContentFeed` | Abstract base for source connectors; implement `fetch_items()` |
| `feed.py` | `FeedItem` | Delivery-ready item (title, body, source_id, metadata, suggested_path, risk_level) |
| `feed.py` | `CycleResult` | Poll cycle summary (fetched, passed, quarantined, skipped, items, errors) |
| `store.py` | `IngestionStore` | SQLite per-integration: idempotency, quarantine, audit, cursors |
| `classifier.py` | `classify()` | HTTP POST to LLM classifier endpoint; returns `ClassifierResult` |
| `filters.py` | `run_filters()` | Layer 2 regex + zero-width detection; returns `list[str]` flags |
| `config.py` | `IngestionConfig` | Pydantic Settings with `INGESTION_*` env prefix |

## Building a New ContentFeed

### Step 1: Create the Feed Subclass

Subclass `ContentFeed` and implement `fetch_items()`. This is the only required method.

```python
# integrations/myservice/feed.py

from integrations.ingestion.envelope import RawMessage
from integrations.ingestion.feed import ContentFeed, FeedItem
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore

class MyServiceFeed(ContentFeed):
    source = "myservice"  # dedupe namespace — must be unique across all feeds

    def __init__(
        self,
        pipeline: IngestionPipeline,
        store: IngestionStore,
        *,
        api_key: str = "",
        max_per_poll: int = 25,
    ) -> None:
        super().__init__(pipeline, store)
        self.api_key = api_key
        self.max_per_poll = max_per_poll

    async def fetch_items(self) -> list[RawMessage]:
        """Pull raw items from the external source."""
        # Resume from last position
        last_id = self.get_cursor()  # defaults to key=self.source

        # Fetch from external API
        items = await self._call_api(since=last_id, limit=self.max_per_poll)

        raw: list[RawMessage] = []
        max_id = last_id
        for item in items:
            raw.append(RawMessage(
                source=self.source,
                source_id=f"myservice:{item['id']}",  # globally unique
                raw_content=item["html_body"],          # can be HTML — Layer 1 strips it
                metadata={
                    "title": item["title"],
                    "author": item["author"],
                    "url": item["url"],
                },
            ))
            if max_id is None or item["id"] > max_id:
                max_id = item["id"]

        # Advance cursor
        if max_id and max_id != last_id:
            self.set_cursor(str(max_id))

        return raw
```

**Key rules for `fetch_items()`:**
- `source` must be a unique string (used as dedupe namespace)
- `source_id` must be unique within the source — format: `"{source}:{identifier}"`
- `raw_content` can be HTML, plain text, or any string — Layer 1 handles extraction
- `metadata` is a pass-through dict preserved in the final `ExternalMessage`
- Use cursors (`get_cursor`/`set_cursor`) for incremental polling
- Return `list[RawMessage]` — the pipeline processes each one independently

### Step 2: Override `format_item()` (Optional)

The default `format_item()` creates a basic FeedItem. Override for custom markdown formatting:

```python
    def format_item(self, envelope: ExternalMessage) -> FeedItem:
        """Convert processed envelope to delivery-ready markdown."""
        meta = envelope.metadata
        lines = [
            f"# {meta.get('title', 'Untitled')}",
            "",
            f"- **Author**: {meta.get('author', 'Unknown')}",
            f"- **Source**: [{meta.get('url', '')}]({meta.get('url', '')})",
            f"- **Risk**: {envelope.risk.risk_level}",
        ]
        if envelope.risk.layer2_flags:
            lines.append(f"- **Security flags**: {', '.join(envelope.risk.layer2_flags)}")
        lines.extend(["", "---", "", envelope.body])

        slug = meta.get("title", envelope.source_id).lower().replace(" ", "-")[:60]
        return FeedItem(
            title=meta.get("title", "Untitled"),
            body="\n".join(lines),
            source_id=envelope.source_id,
            metadata=envelope.metadata,
            suggested_path=f"data/myservice/{slug}.md",
            risk_level=envelope.risk.risk_level,
        )
```

**FeedItem fields:**
- `title` — Display title (used in summaries, notifications)
- `body` — Markdown content for workspace files
- `source_id` — Preserved from envelope for cross-referencing
- `suggested_path` — Where to write in the channel workspace (e.g. `data/gmail/2026-03-30-report.md`)
- `risk_level` — Preserved from security assessment

### Step 3: Create the Factory

The factory wires up the pipeline, store, and feed. Follow this exact pattern:

```python
# integrations/myservice/factory.py

import os
from integrations.ingestion.config import IngestionConfig
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore
from integrations.myservice.feed import MyServiceFeed
from integrations.myservice.config import settings

_DB_DIR = os.path.expanduser("~/.agent-workspaces/.ingestion")

def create_feed() -> tuple[MyServiceFeed, IngestionStore]:
    """Create feed with pipeline and store. Caller must call store.close() when done."""
    os.makedirs(_DB_DIR, exist_ok=True)
    store = IngestionStore(os.path.join(_DB_DIR, "myservice.db"))

    config = IngestionConfig(
        agent_base_url=settings.AGENT_BASE_URL,
        agent_api_key=settings.AGENT_API_KEY,
    )
    pipeline = IngestionPipeline(config=config, store=store)

    feed = MyServiceFeed(
        pipeline=pipeline,
        store=store,
        api_key=settings.MY_API_KEY,
    )
    return feed, store
```

**Critical patterns:**
- DB path: `~/.agent-workspaces/.ingestion/{source}.db` — one SQLite DB per feed
- `IngestionConfig()` reads `INGESTION_*` env vars automatically
- Always return the store so the caller can `store.close()`
- Pass `agent_base_url` and `agent_api_key` from your integration's config

### Step 4: Use the Feed

Call `run_cycle()` from your polling loop, heartbeat handler, or process:

```python
feed, store = create_feed()
try:
    result = await feed.run_cycle()
    # result.fetched   — total items pulled from source
    # result.passed    — items that cleared the pipeline
    # result.quarantined — items flagged and stored in quarantine
    # result.skipped   — duplicates (already processed)
    # result.items     — list[FeedItem] ready for delivery
    # result.errors    — per-item error messages (non-fatal)

    for item in result.items:
        # Write to channel workspace, send to channel, etc.
        await deliver_to_workspace(channel_id, item.suggested_path, item.body)
finally:
    store.close()
```

`run_cycle()` handles the full loop: fetch → dedupe → pipeline → format. Per-item errors
are caught and recorded in `result.errors` without aborting the cycle.

## IngestionStore API

SQLite-backed storage per integration. Schema auto-created on init.

```python
store = IngestionStore(db_path="/path/to/myservice.db")

# Idempotency
store.already_processed(source, source_id) → bool
store.mark_processed(source, source_id) → None

# Quarantine (pipeline calls this automatically for unsafe content)
store.quarantine(source, source_id, raw_content, risk_level, flags, reason) → None
store.purge_quarantine(retention_days=90) → int  # returns count deleted

# Audit (pipeline calls this automatically)
store.audit(source, source_id, action, risk_level) → None
# action: "passed" | "quarantined"

# Cursors (position tracking for incremental polling)
store.get_cursor(key) → str | None
store.set_cursor(key, value) → None

store.close() → None
```

**SQLite tables:**
- `processed_ids` — (source, source_id) unique pairs for deduplication
- `quarantine` — raw_content + risk + flags + reason for manual review
- `audit_log` — every message decision (passed or quarantined) with timestamp
- `cursors` — key/value pairs for feed position tracking

## IngestionConfig

All settings read from environment with `INGESTION_` prefix:

| Env Var | Default | Purpose |
|---------|---------|---------|
| `INGESTION_AGENT_BASE_URL` | `http://localhost:8000` | Agent server URL |
| `INGESTION_AGENT_API_KEY` | `""` | API key for agent server |
| `INGESTION_CLASSIFIER_URL` | `http://localhost:8000/v1/chat/completions` | Layer 3 LLM endpoint |
| `INGESTION_CLASSIFIER_MODEL` | `gpt-4o-mini` | Model for safety classification |
| `INGESTION_CLASSIFIER_TIMEOUT` | `15` | Classifier timeout (seconds) |
| `INGESTION_MAX_BODY_BYTES` | `50000` | Content truncation limit |
| `INGESTION_QUARANTINE_RETENTION_DAYS` | `90` | Auto-purge quarantined items after N days |

## Layer 2 Patterns

Deterministic regex patterns in `filters.py`:

1. `ignore_previous` — "ignore previous instructions", "ignore all previous"
2. `system_prompt_override` — "[SYSTEM]", "[INST]", "<<SYS>>"
3. `role_injection` — "you are now", "you are a"
4. `prompt_leak_request` — "repeat your instructions", "show your prompt"
5. `jailbreak_dan` — "DAN", "do anything now"
6. `base64_payload` — base64-encoded blocks (>50 chars)
7. `markdown_injection` — hidden markdown comments, `[//]: #`
8. `hidden_instruction` — "new instructions:", "override:", "forget everything"
9. Zero-width characters — U+200B, U+200C, U+200D, U+FEFF, etc.

Matching adds flags to `RiskMetadata.layer2_flags`. Flags **do not block** — they inform
Layer 3's classification decision and serve as audit data.

## Testing a Feed

Tests should mock the pipeline and store. Reference: `integrations/ingestion/tests/`.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from integrations.ingestion.envelope import ExternalMessage, RiskMetadata
from integrations.ingestion.feed import CycleResult

@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.process = AsyncMock()
    return pipeline

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.already_processed.return_value = False
    store.get_cursor.return_value = None
    return store

def _make_envelope(source_id: str, body: str = "test") -> ExternalMessage:
    return ExternalMessage(
        source="myservice",
        source_id=source_id,
        body=body,
        metadata={},
        risk=RiskMetadata(layer2_flags=[], risk_level="low", classifier_reason="safe"),
    )

@pytest.mark.asyncio
async def test_fetch_cycle(mock_pipeline, mock_store):
    mock_pipeline.process.return_value = _make_envelope("myservice:1", "content")

    feed = MyServiceFeed(mock_pipeline, mock_store, api_key="test")
    # Mock the external API call
    feed._call_api = AsyncMock(return_value=[{"id": "1", "html_body": "<p>Hi</p>", ...}])

    result = await feed.run_cycle()
    assert result.fetched == 1
    assert result.passed == 1
    assert len(result.items) == 1

@pytest.mark.asyncio
async def test_quarantined_item(mock_pipeline, mock_store):
    mock_pipeline.process.return_value = None  # quarantined
    feed = MyServiceFeed(mock_pipeline, mock_store, api_key="test")
    feed._call_api = AsyncMock(return_value=[{"id": "1", ...}])

    result = await feed.run_cycle()
    assert result.quarantined == 1
    assert len(result.items) == 0
```

## Real-World Reference: Gmail Feed

`integrations/gmail/` is the canonical ContentFeed implementation:

| File | Purpose |
|------|---------|
| `feed.py` | `GmailFeed(ContentFeed)` — IMAP polling, email parsing, markdown formatting |
| `factory.py` | `create_feed()` — wires pipeline + store + IMAP config |
| `config.py` | Gmail-specific settings (IMAP host/port, email, password, folders) |
| `poller.py` | Background process that calls `feed.run_cycle()` on schedule |

Key patterns from Gmail:
- Uses `asyncio.to_thread()` for sync IMAP calls
- Per-folder cursors: `gmail:INBOX`, `gmail:Sent` (cursor key includes folder name)
- `format_item()` builds rich markdown with From/To/Date/Attachments/Risk headers
- `_safe_filename()` for workspace file slugs (handles non-Latin, long subjects)

## Key Rules

- **Never skip the pipeline** — even for "trusted" sources. The agent must never see raw external content.
- **Fail closed** — if the classifier errors out, the message is quarantined, not passed through.
- **Quarantine, never discard** — flagged content is stored for human review. Never auto-delete.
- **One DB per feed** — each integration gets its own SQLite file at `~/.agent-workspaces/.ingestion/{source}.db`.
- **source_id must be globally unique** — use `"{source}:{identifier}"` format.
- **Cursors are per-key** — use `get_cursor()`/`set_cursor()` for incremental polling; key defaults to `self.source`.
- **Classifier is isolated** — no tools, no memory, no agent context. Pure binary classification.
- **Layer 2 flags inform, don't block** — all patterns are documented and auditable.
