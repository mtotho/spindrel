# Message History Compression + On-Demand Retrieval

## Status: Draft
## Author: Claude (plan)
## Date: 2026-03-24

---

## Problem

Every agent turn currently loads full message history into context. The pipeline in `run_stream()` (`app/agent/loop.py`) builds messages as:

```
[system prompt]
[RAG context: skills, memories, knowledge, tools, plans, workspace files]
[full conversation history — all stored messages since last compaction watermark]
[context assembly injections: datetime, tags, delegates, tool index]
[user message]
```

This is token-heavy. Two existing mechanisms partially address this:

1. **Compaction** (`app/services/compaction.py`) — **storage-layer**, permanent. Runs every N user turns, summarises older messages into `session.summary`, sets a `summary_message_id` watermark. Only messages after the watermark are loaded. Destructive: old messages are still in DB but no longer loaded.

2. **Context compression** (`app/services/compression.py`) — **view-layer**, ephemeral per-turn. When conversation chars exceed a threshold, calls a cheap model to summarise the "older" portion, keeps last K turns verbatim, injects summary + `get_message_detail` tool for drill-down. No DB changes.

### What's missing

Context compression is good but has gaps:
- Summary is **regenerated from scratch every turn** — wasteful when conversation grows.
- No **cached summary** — the same expensive summarisation call happens even when nothing changed.
- No way for the agent to retrieve **specific messages by ID** from the full session (only from the compressed portion of the current turn).
- No **session-level history retrieval tool** independent of compression being active.

This plan extends the existing compression system with **cached summaries** and a **`get_session_history` tool** that works independently of whether compression is active.

---

## Design

### 1. What Gets Summarised

All message pairs in the session from turn 0 through the current compression boundary (older messages not kept verbatim). The summary captures:

- **Key decisions** with message index references (`[msg:N]`)
- **Pivots and corrections** — when the user changed direction
- **Bugs encountered and solutions attempted**
- **Tool calls made** — which tools, how many times, key results
- **Outstanding tasks and open questions**
- **Exact values** — file paths, IDs, URLs, config values, code snippets

The existing `_COMPRESSION_PROMPT` in `app/services/compression.py` already produces this format with `[msg:N]` references and structured sections (Key Context, Recent Actions, Open Items, Relevant Details). We keep this prompt.

### 2. When Is Summary Generated — Recommendation: **Incremental (Option B) with lazy trigger**

**Rejected alternatives:**
- **Option A (session end / heartbeat):** Too delayed — first turn after a gap would have stale or missing summary.
- **Option C (pure lazy):** Adds latency to the turn that triggers it. Acceptable for the *first* summary, but subsequent updates should be incremental.

**Chosen approach: Incremental with staleness-triggered regeneration**

1. **First summary:** Generated lazily on the first turn where conversation exceeds the compression threshold (existing behaviour).
2. **Cached:** The summary text + metadata are persisted to the session row.
3. **Incremental update:** On subsequent turns, if `>= COMPRESSION_STALENESS_THRESHOLD` new user turns have occurred since `summary_generated_at`, an **incremental** summarisation call is made: the existing cached summary + only the new messages are sent to the cheap model with an "update this summary" prompt.
4. **Fresh enough:** If the cached summary is fresh (fewer than threshold new turns), it is injected directly — no LLM call.

**Why incremental:** A 50-message session shouldn't re-summarise all 50 messages when only 3 new turns happened. The incremental prompt is cheaper (existing summary + new messages only) and faster.

**Fallback:** If the incremental update fails, fall back to the cached summary as-is. If no cached summary exists and generation fails, fall back to the current last-N-messages behaviour.

### 3. Context Injection Layout

```
[system prompt]
[RAG context: skills, memories, knowledge, tools, plans, workspace files]
[history_summary: "Conversation summary (45 messages compressed):
  **Key Context**: User is building a webhook integration for Slack...
  Key decisions: [msg:5] chose Postgres, [msg:12] added caching layer...
  **Recent Actions**: [msg:40]-[msg:43] debugged auth token refresh...
  **Open Items**: Rate limiting not yet implemented...
  **Relevant Details**: Webhook URL is https://..., API key stored in .env...

  Use get_session_history() or get_message_detail() to retrieve full messages."]
[last K messages verbatim — for immediate conversational continuity]
[context assembly injections: datetime, tags, delegates, tool index]
[user message]
```

**Key changes from current compression:**
- Summary comes from **cache** (no per-turn LLM call when fresh).
- Last K messages kept verbatim (K = `CONTEXT_COMPRESSION_KEEP_TURNS`, default 2).
- Both `get_message_detail` (existing, index-based) and `get_session_history` (new, ID-based) available as tools.

### 4. New Tool: `get_session_history`

Register in `app/tools/local/compression_history.py` alongside existing `get_message_detail`.

```python
@register({
    "type": "function",
    "function": {
        "name": "get_session_history",
        "description": (
            "Retrieve full message objects from the current session's history. "
            "Use when you need to review what was said/done in earlier turns. "
            "Works regardless of whether context compression is active."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_message_id": {
                    "type": "string",
                    "description": "UUID of the starting message. If omitted, returns the last `limit` messages.",
                },
                "end_message_id": {
                    "type": "string",
                    "description": "UUID of the ending message (inclusive). If omitted, returns `limit` messages from start.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum messages to return. Default 10, max 20.",
                    "default": 10,
                },
                "query": {
                    "type": "string",
                    "description": "Keyword search across message content. Returns matching messages.",
                },
            },
        },
    },
})
async def get_session_history(...) -> str:
```

**Implementation:**
- Reads from `messages` table via `session_id` from agent context.
- Supports range queries by message UUID, keyword search, or "last N" default.
- Returns formatted message objects: role, content (truncated tool results), tool calls, message ID, timestamp.
- Always available — not gated on compression being active (unlike `get_message_detail`).
- Max 20 messages per request to prevent context blowup.

### 5. Storage — Schema Changes

Add to `Session` model (`app/db/models.py`):

```python
# Cached compression summary
history_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
summary_generated_at: Mapped[datetime | None] = mapped_column(
    TIMESTAMP(timezone=True), nullable=True
)
summary_message_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

**Fields:**
| Field | Type | Purpose |
|-------|------|---------|
| `history_summary` | `Text` | Cached compression summary text |
| `summary_generated_at` | `TIMESTAMP(tz)` | When the summary was last generated/updated |
| `summary_message_count` | `Integer` | Number of messages included in the summary (for staleness check) |

**Migration:** New Alembic migration (next sequence number after `058_task_type.py`).

**Note:** This is separate from the existing `summary` field (used by compaction). Compaction's `summary` is a permanent record; `history_summary` is an ephemeral cache that can be regenerated at any time.

### 6. Regeneration Triggers

#### Automatic (staleness-based)
- On each turn, before injecting the cached summary, check: `current_message_count - summary_message_count >= COMPRESSION_STALENESS_THRESHOLD`
- If stale: run incremental update (existing summary + new messages → updated summary)
- Default threshold: **5 new user turns**

#### Automatic (post-turn, non-blocking)
- After the agent responds, if the turn added messages and the summary is now stale, queue an incremental update as a background task (similar to how compaction uses `maybe_compact()`).
- This pre-warms the cache so the *next* turn doesn't need to wait.

#### Manual
- Admin UI: "Regenerate Summary" button on session detail page (`/admin/sessions/{id}`).
- API: `POST /api/v1/sessions/{id}/regenerate-summary`

#### Bot-level config
```yaml
compression:
  enabled: true          # enable cached compression (default: use global setting)
  staleness_threshold: 5 # regenerate after N new user turns
  keep_turns: 2          # verbatim turns to keep
  model: gemini/gemini-2.5-flash  # override compression model
```

Falls through to channel-level → bot-level → global settings (same cascade pattern as compaction/compression).

### 7. Model & Prompt for Summarisation

**Model:** Resolution cascade (same as existing compression):
1. Channel `compression_model`
2. Bot `compression_config.model`
3. `settings.CONTEXT_COMPRESSION_MODEL`
4. `settings.COMPACTION_MODEL`
5. Bot's primary model

**Target:** Existing `CONTEXT_COMPRESSION_MAX_SUMMARY_TOKENS` (default 2000 tokens).

**Prompts:**

*Initial summary* — reuse existing `_COMPRESSION_PROMPT` from `app/services/compression.py`.

*Incremental update* — new prompt:
```
You are updating an existing conversation summary with new messages.

Existing summary:
{cached_summary}

New messages since last summary ({N} messages):
{new_messages_formatted}

User's current question: {user_message}

Rules:
- Merge new information into the existing summary structure.
- Keep the same sections: Key Context, Recent Actions, Open Items, Relevant Details.
- Update [msg:N] references — new messages start at [msg:{offset}].
- Promote recent actions from the old summary into Key Context if they're now established decisions.
- Move resolved Open Items out; add new ones.
- Be concise but thorough. Target similar length to the existing summary.
```

### 8. Fallback Behaviour

| Scenario | Behaviour |
|----------|-----------|
| No cached summary, below threshold | Load full history (current behaviour) |
| No cached summary, above threshold | Generate summary synchronously, cache it, inject |
| Cached summary, fresh | Inject cached summary directly (no LLM call) |
| Cached summary, stale | Run incremental update; on failure, inject stale summary |
| Incremental update fails | Inject existing cached summary + log warning |
| Initial generation fails | Fall back to full history (current behaviour) + log warning |
| `get_session_history` called | Always works — reads from DB, independent of compression |
| `get_message_detail` called | Works when compression active (existing behaviour) |

---

## Open Questions — Decisions

### 1. Incremental vs full regeneration?
**Decision: Start with incremental, full regeneration as fallback.**

Incremental is cheaper per-call and the existing summary provides strong context for the model. If the incremental result is poor (e.g., model returns garbage), fall back to full regeneration. Add a config `COMPRESSION_FULL_REGEN_INTERVAL` (default: every 20 incremental updates) to periodically do a full regen to prevent drift.

### 2. Summary freshness threshold?
**Decision: 5 new user turns (configurable).**

`COMPRESSION_STALENESS_THRESHOLD = 5` — regenerate if >= 5 new user turns since last summary. This balances freshness against cost. For high-frequency bots (e.g., Slack channels with many short messages), channel-level override to a higher value (e.g., 10).

### 3. Always inject summary, or only when history exceeds token budget?
**Decision: Only when conversation exceeds `CONTEXT_COMPRESSION_THRESHOLD`.**

Keep the existing threshold gate. If conversation is short enough to fit, load it fully — summaries always lose information. The threshold (default 20,000 chars) ensures compression only kicks in when it matters.

### 4. How many last messages to include verbatim?
**Decision: 2 user turns (configurable via `CONTEXT_COMPRESSION_KEEP_TURNS`).**

Keep the existing default of 2. This means the last 2 user messages + their corresponding assistant responses + any tool call/result messages in between are kept verbatim. This provides enough immediate context for conversational continuity without defeating the purpose of compression.

### 5. Include tool output content in summary, or just note tools were called?
**Decision: Include truncated tool outputs for key results; note-only for routine calls.**

The existing `_format_message` in `compression.py` already truncates tool results to 500 chars. This is a good balance. The compression prompt instructs the model to "Preserve exact values" which handles key results, while routine tool calls (e.g., `save_memory` confirmations) get compressed to just the call notation.

---

## Implementation Plan

### Phase 1: Cached summaries (core value)

1. **Migration** — Add `history_summary`, `summary_generated_at`, `summary_message_count` to `sessions` table.

2. **Update `compress_context()`** (`app/services/compression.py`):
   - Before generating a new summary, check for a fresh cached summary on the session.
   - If fresh: build compressed messages using cached summary (skip LLM call).
   - If stale or missing: generate summary (reuse existing logic), then persist to session row.
   - Add incremental update path: when cached summary exists but is stale, send existing summary + new messages only.

3. **Post-turn cache warming** — In `run_stream()`, after the agent responds, if compression was active and messages were added, queue a background incremental summary update (similar pattern to `maybe_compact()`).

4. **Config** — Add `COMPRESSION_STALENESS_THRESHOLD` to `app/config.py`. Add `staleness_threshold` to bot YAML `compression_config`.

### Phase 2: `get_session_history` tool

5. **New tool** — Add `get_session_history` to `app/tools/local/compression_history.py`. Reads from `messages` table by session ID. Supports range, keyword search, and "last N" queries.

6. **Always-available injection** — When compression is active, inject both `get_message_detail` (existing, for `[msg:N]` drill-down) and `get_session_history` (new, for ID-based retrieval) into tools. When compression is *not* active, still make `get_session_history` available if the bot has it in `local_tools` or `pinned_tools`.

### Phase 3: Admin + observability

7. **Admin UI** — Add "Regenerate Summary" button to session detail page. Wire to `POST /api/v1/sessions/{id}/regenerate-summary`.

8. **API endpoint** — `POST /api/v1/sessions/{id}/regenerate-summary` — forces full summary regeneration.

9. **Tracing** — Add trace events for `compression_cache_hit`, `compression_cache_miss`, `compression_incremental_update`, `compression_summary_generated`. Include token counts and latency.

### Phase 4: Optimisations (future)

10. **Background pre-generation** — Heartbeat worker checks for sessions with stale summaries and pre-generates updates during quiet periods.

11. **Token budget awareness** — Instead of character threshold, estimate actual token count of conversation history and only compress when it would exceed a configurable token budget (accounting for system prompt + RAG context).

12. **Summary quality scoring** — Track how often `get_message_detail` / `get_session_history` are called after compression. High drill-down rates suggest summaries are losing important information → adjust prompt or threshold.

---

## Files to Modify

| File | Change |
|------|--------|
| `app/db/models.py` | Add `history_summary`, `summary_generated_at`, `summary_message_count` to `Session` |
| `migrations/versions/059_history_summary_cache.py` | New migration |
| `app/services/compression.py` | Add cache read/write, incremental update logic |
| `app/config.py` | Add `COMPRESSION_STALENESS_THRESHOLD` |
| `app/agent/bots.py` | Add `staleness_threshold` to compression config parsing |
| `app/tools/local/compression_history.py` | Add `get_session_history` tool |
| `app/agent/loop.py` | Add post-turn cache warming call |
| `app/routers/api_v1_sessions.py` | Add regenerate-summary endpoint |
| `app/routers/sessions.py` | Add admin UI regenerate button handler |
| `app/templates/admin/session_detail_page.html` | Add regenerate button |
| `tests/unit/test_compression.py` | Add tests for caching and incremental update |

---

## Relationship to Existing Systems

```
                    ┌─────────────────────────────────┐
                    │         Message Storage          │
                    │    (messages table, full history) │
                    └──────┬──────────────┬────────────┘
                           │              │
                    ┌──────▼──────┐ ┌─────▼─────────────┐
                    │  Compaction  │ │    Compression     │
                    │ (storage)   │ │ (view-layer cache) │
                    │             │ │                    │
                    │ Permanent   │ │ Ephemeral/regen-   │
                    │ summary +   │ │ erable cache.      │
                    │ watermark.  │ │ Cached in session   │
                    │ Old msgs    │ │ row. Full history   │
                    │ not loaded. │ │ still accessible    │
                    │             │ │ via tools.          │
                    └──────┬──────┘ └─────┬─────────────┘
                           │              │
                           ▼              ▼
                    ┌─────────────────────────────────┐
                    │       Context Assembly           │
                    │  (context_assembly.py)           │
                    │                                  │
                    │  Compaction summary injected as  │
                    │  leading context. Compression    │
                    │  replaces older messages with    │
                    │  cached summary + verbatim tail. │
                    └─────────────────────────────────┘
```

**Compaction** and **compression** are complementary:
- Compaction reduces what's *loaded from DB* (permanent, runs every 30 turns).
- Compression reduces what's *sent to the LLM* (ephemeral, per-turn when over threshold).
- With cached summaries, compression becomes nearly free on turns where the cache is fresh.
- `get_session_history` bridges both: it always reads from the messages table, regardless of compaction watermark or compression state.
