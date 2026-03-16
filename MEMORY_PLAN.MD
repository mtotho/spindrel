# Memory System — Implementation Plan

## Overview

A two-layer memory system for long-running persistent sessions. Handles both active context window management (in-session summarization) and long-term retrieval (memory knowledge base). Designed around the pattern of a single session living for weeks or months per client.

---

## The Problem

A session accumulating messages over weeks will eventually exceed any model's context window. Naively passing the full history to every completion call is not viable. But simply truncating old messages means the model loses access to past context entirely.

The solution is two complementary mechanisms:

1. **Rolling summarization** — periodically collapse old messages into a summary chunk, keeping the active context lean (DONE)
2. **Memory knowledge base** — write those summaries to pgvector so they can be retrieved semantically on any future turn

Together these mean: the model always has a manageable context window, and can still answer "remember when I asked about X three weeks ago."

---

## Architecture

```
Long-running session (weeks of messages in Postgres)
              │
              ▼
     Load last N messages
     + inject retrieved memories
              │
              ▼
         Agent loop
              │
         Every M turns
              ▼
     Summarize oldest chunk
     ┌────────┴────────┐
     │                 │
Replace old msgs   Write summary
in active context  to memories table
(context mgmt)     (pgvector)
```

---

## Two Mechanisms in Detail

### Mechanism 1 — Rolling Context Summarization

**Purpose:** Keep the active messages array within token budget.

**Controlled by bot config:** `memory.in_session_summarization`

**How it works:**
- Session service tracks message count on load
- If count exceeds `COMPACTION_INTERVAL` (e.g. 20 messages), the chunk (e.g. 20) is summarized but the last N messages is kept in recent context (COMPACITON_KEY_TURN)
- A summarization completion call is made against `SUMMARY_MODEL`
- The raw messages remain in Postgres — never deleted, full history preserved for the `/sessions/{id}` history endpoint
-### Mechanism 2 — Memory Knowledge Base

**Purpose:** Long-term retrieval across time. "Remember when I asked about X."

**Controlled by two independent bot config flags:**
- `memory.cross_session_kb` — whether summaries are written to the memories table
- `memory.retrieval` — whether memories are retrieved and injected on each turn

These are independent so you can have a bot that writes memories but doesn't retrieve (append-only), or retrieves from a shared memory pool but doesn't write its own.

**How it works:**
- Every time a chunk is summarized (Mechanism 1) AND `cross_session_kb` is true, the summary is written to the `memories` table with an embedding
- On every turn, if `retrieval` is true, `retrieve_context()` searches the memories table for semantically relevant past summaries scoped to `client_id`
- Retrieved memories injected into context before the user message

**Temporal context in summary text:**
Summaries written to the KB must include human-readable time references in the text itself — not just metadata fields — so the model can reason about when things happened:

```
"Between March 1-3, 2025: Michael worked on setting up his agent server.
 He chose FastAPI with PostgreSQL. Asked about MCP tool configuration
 with LiteLLM. Mentioned wanting to add voice support via a Raspberry Pi."
```

---

## Database

### New `memories` table

A dedicated table separate from `documents`. The `documents` table remains for RAG over uploaded files and knowledge base content. Memory entries have a different lifecycle, different FK requirements, and different query patterns — they do not belong in the same table.

```sql
CREATE TABLE memories (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id           UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    client_id            TEXT NOT NULL,
    content              TEXT NOT NULL,
    embedding            VECTOR(1536),
    message_range_start  TIMESTAMPTZ,
    message_range_end    TIMESTAMPTZ,
    message_count        INTEGER,
    created_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memories (client_id);
CREATE INDEX ON memories (session_id);
```

Key design decisions:
- `session_id` is a real FK with `ON DELETE CASCADE` — deleting a session automatically deletes all its memory entries. No application code needed for cleanup.
- `client_id` is denormalized for efficient retrieval scoping without a join
- No `type` or `metadata` JSONB needed — this table is memories only

### `documents` table (unchanged)

Remains as designed. Used for RAG over uploaded content (files, URLs, articles). No memory entries go here. When RAG over documents is eventually implemented, `retrieve_context()` will merge results from both tables ranked by similarity score.

---

## Session Delete Cascade

When `DELETE /sessions/{id}` is called:
- `messages` rows deleted via existing FK cascade
- `memories` rows deleted via the new FK cascade on `memories.session_id`

Both happen automatically at the database level. No application code required for memory cleanup.

---

## Bot Configuration

Three independent memory flags added to bot YAML:

```yaml
# bots/default.yaml
id: default
name: "Default Assistant"
model: gpt-4.1-mini
system_prompt: |
  You are a helpful assistant.
mcp_servers: []
local_tools: []
rag: false

memory:
  in_session_summarization: true   # rolling context window management
  cross_session_kb: true           # write summaries to memories table
  retrieval: true                  # inject retrieved memories on each turn
```

```yaml
# Example: summarization only, no persistent memory
memory:
  in_session_summarization: true
  cross_session_kb: false
  retrieval: false

# Example: retrieval only (reads memories but never writes)
memory:
  in_session_summarization: false
  cross_session_kb: false
  retrieval: true

# Example: memory fully disabled
memory:
  in_session_summarization: false
  cross_session_kb: false
  retrieval: false
```

`BotConfig` gains a nested `MemoryConfig`:

```python
@dataclass
class MemoryConfig:
    in_session_summarization: bool = False
    cross_session_kb: bool = False
    retrieval: bool = False

@dataclass
class BotConfig:
    id: str
    name: str
    model: str
    system_prompt: str
    mcp_servers: list[str]
    local_tools: list[str]
    rag: bool
    memory: MemoryConfig = field(default_factory=MemoryConfig)
```

---

## Code Changes

### `app/db/models.py`

Add `Memory` ORM model mapping to the `memories` table.

### `app/agent/memory.py` (new file)

```python
async def write_memory(
    db: AsyncSession,
    summary_text: str,
    client_id: str,
    session_id: UUID,
    source_messages: list[dict],
) -> None:
    """Embed summary and write to memories table."""
    embedding = await embed(summary_text)
    timestamps = [m.get("created_at") for m in source_messages if m.get("created_at")]
    memory = Memory(
        session_id=session_id,
        client_id=client_id,
        content=summary_text,
        embedding=embedding,
        message_range_start=min(timestamps) if timestamps else None,
        message_range_end=max(timestamps) if timestamps else None,
        message_count=len(source_messages),
    )
    db.add(memory)
    await db.commit()


async def retrieve_memories(query: str, client_id: str) -> list[str]:
    """
    Embed query, search memories table for relevant chunks.
    Scoped to client_id — users never see each other's memories.
    """
    embedding = await embed(query)
    results = await db_similarity_search_memories(
        embedding=embedding,
        client_id=client_id,
        limit=settings.MEMORY_RETRIEVAL_LIMIT,
        threshold=settings.MEMORY_SIMILARITY_THRESHOLD,
    )
    return [r.content for r in results]
```

### `app/services/sessions.py`

Add `summarize_if_needed(db, session_id, messages, client_id, bot)`:

```python
async def summarize_if_needed(
    db: AsyncSession,
    session_id: UUID,
    messages: list[dict],
    client_id: str,
    bot: BotConfig,
) -> list[dict]:
    """
    If in_session_summarization is enabled and message count exceeds threshold,
    summarize oldest chunk. If cross_session_kb is also enabled, write to memories table.
    Returns updated messages array. System prompt at index 0 is never touched.
    """
    if not bot.memory.in_session_summarization:
        return messages

    non_system = [m for m in messages if m["role"] != "system"]
    if len(non_system) <= settings.SUMMARY_THRESHOLD:
        return messages

    chunk = non_system[:settings.SUMMARY_CHUNK_SIZE]
    keep = non_system[settings.SUMMARY_CHUNK_SIZE:]

    summary_text = await _summarize_chunk(chunk)

    if bot.memory.cross_session_kb:
        await write_memory(db, summary_text, client_id, session_id, chunk)

    system_msgs = [m for m in messages if m["role"] == "system"
                   and not m.get("content", "").startswith("Conversation summary")]
    summary_msg = {
        "role": "system",
        "content": f"Conversation summary:\n{summary_text}"
    }
    return system_msgs[:1] + [summary_msg] + keep
```

### `app/agent/rag.py`

`retrieve_context()` queries the `memories` table:

```python
async def retrieve_context(query: str, client_id: str) -> list[str]:
    if not query:
        return []
    return await retrieve_memories(query, client_id)
```

When RAG over documents is eventually implemented, this function merges results from both `memories` and `documents` tables ranked by similarity score.

### `app/agent/loop.py`

Pass `client_id`, `session_id`, and `db` through. Call `summarize_if_needed()` and conditionally retrieve memories:

```python
async def run(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    client_id: str,
    session_id: UUID,
    db: AsyncSession,
) -> str:
    # Summarize if needed (writes to memory KB if cross_session_kb enabled)
    messages = await summarize_if_needed(db, session_id, messages, client_id, bot)

    # Retrieve relevant memories
    if bot.memory.retrieval:
        memories = await retrieve_context(user_message, client_id)
        if memories:
            messages.append({
                "role": "system",
                "content": "Relevant memory:\n" + "\n\n".join(memories)
            })

    messages.append({"role": "user", "content": user_message})
    # ... rest of loop unchanged
```

---

## New Config (env vars)

```
# Summarization
SUMMARY_THRESHOLD=40
SUMMARY_CHUNK_SIZE=20
SUMMARY_KEEP_RECENT=20
SUMMARY_MODEL=gpt-4.1-mini

# Memory retrieval
MEMORY_RETRIEVAL_LIMIT=5
MEMORY_SIMILARITY_THRESHOLD=0.75
```

---

## New API Endpoint

### `POST /sessions/{session_id}/summarize`

Manually trigger summarization of a session. Forces a memory write regardless of message count threshold. Useful for explicitly capturing a conversation before switching context.

Returns the generated summary text. Auth required.

---

## Retrieval Context Shape

```
[
  { role: system, content: "You are a helpful assistant..." },
  { role: system, content: "Conversation summary: ..." },      ← rolling summary
  { role: system, content: "Relevant memory:                  ← retrieved from memories table
      Between March 1-3: Michael worked on FastAPI agent server...
      On March 10: Asked about optimizing Gemini Flash for tool calls..." },
  ... recent messages verbatim ...
  { role: user, content: "remember when I asked about litellm routing?" }
]
```

---

## Build Order

| Phase | What | Milestone |
|-------|------|-----------|
| 1 | Add `Memory` ORM model + Alembic migration | Table exists in DB |
| 2 | Wire up embeddings via LiteLLM `/v1/embeddings` | Can embed a string, get vector back |
| 3 | `write_memory()` — embed and store in memories table | Memory rows appear in DB with correct session_id |
| 4 | `retrieve_memories()` — pgvector similarity search scoped by client_id | Relevant memories returned for a query |
| 5 | RAG injection in agent loop (retrieval flag) | Retrieved memories appear in completions |
| 6 | `summarize_if_needed()` — summarize + rebuild messages (in_session_summarization flag) | Long sessions stay within token budget |
| 7 | Wire `cross_session_kb` flag — write memory from summarize_if_needed | Summaries written to memories table automatically |
| 8 | `POST /sessions/{id}/summarize` endpoint | Manual trigger works |
| 9 | Verify cascade delete — delete session, confirm memories removed | No orphaned memory rows |

Phases 1-5 deliver retrieval. Phases 6-7 close the automatic memory generation loop. Phase 9 is a verification step.

---

## What Is Not In Scope

- **Explicit remember/recall tools** — model-driven memory writing via tool calls. Additive later, doesn't conflict with this design.
- **Memory deduplication** — if the same fact appears in multiple summaries, both will be retrieved. Future optimization.
- **Cross-client memory sharing** — all retrieval is scoped to `client_id`. Intentional.
- **RAG over documents** — `documents` table remains stubbed. When implemented, `retrieve_context()` will merge results from both `memories` and `documents`.