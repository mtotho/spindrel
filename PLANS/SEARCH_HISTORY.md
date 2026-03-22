# Search History Tool

---
status: draft
last_updated: 2026-03-22
owner: mtoth
summary: >
  DB-backed search_history tool. Allows the agent to query historical channel
  messages by keyword, date range, or sender. Useful for self-directed compaction
  and context retrieval. Exposes a local tool + optional API endpoint.
---

## 1. Message Storage — Current State

Messages are stored in the `messages` table (`app/db/models.py:98`, class `Message`).

### Schema

| Column           | Type                      | Notes                                |
|------------------|---------------------------|--------------------------------------|
| `id`             | `UUID` (PK)               | Default `uuid4`                      |
| `session_id`     | `UUID` (FK → sessions.id) | CASCADE delete                       |
| `role`           | `Text`                    | `user`, `assistant`, `tool`, `system`|
| `content`        | `Text` (nullable)         | Message body; null for tool-call-only messages |
| `tool_calls`     | `JSONB` (nullable)        | OpenAI-format tool call array        |
| `tool_call_id`   | `Text` (nullable)         | For role=tool responses              |
| `correlation_id` | `UUID` (nullable)         | Links request → response chain       |
| `metadata_`      | `JSONB`                   | ORM attr for `metadata` column; stores `source`, etc. |
| `created_at`     | `TIMESTAMP(tz)`           | Server default `now()`               |

### Relationship to Channels

Messages belong to **sessions**, not directly to channels. The join path is:

```
Channel.id → Session.channel_id → Message.session_id
```

A channel has many sessions (including historical/compacted ones). To search all
messages in a channel, we join `messages` → `sessions` on `session_id` and filter
`sessions.channel_id`.

There is no `bot_id` on `Message` directly — it lives on `Session.bot_id`.


## 2. Local Tool — `search_history`

**File**: `app/tools/local/search_history.py`

Follow the pattern established by `app/tools/local/todos.py`:
- Import context vars from `app/agent/context.py`
- Use `app/db/engine.async_session` for DB access
- Register with `@register(openai_schema)`

### OpenAI Function Schema

```python
@register({
    "type": "function",
    "function": {
        "name": "search_history",
        "description": (
            "Search historical messages in this channel by keyword and/or date range. "
            "Returns matching messages with timestamp, role, and a content preview. "
            "Useful for recalling past conversations, finding decisions, or reviewing context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in message content. Case-insensitive."
                },
                "start_date": {
                    "type": "string",
                    "description": "ISO 8601 start date (inclusive). E.g. '2026-03-01' or '2026-03-01T00:00:00Z'."
                },
                "end_date": {
                    "type": "string",
                    "description": "ISO 8601 end date (inclusive). E.g. '2026-03-22'."
                },
                "role": {
                    "type": "string",
                    "description": "Filter by message role.",
                    "enum": ["user", "assistant", "all"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Defaults to 20, max 100."
                }
            },
            "required": []
        }
    }
})
```

### Parameters

| Param        | Default      | Notes |
|--------------|--------------|-------|
| `query`      | `None`       | When omitted, returns messages by date only (no keyword filter) |
| `start_date` | `None`       | Parsed via `datetime.fromisoformat()` |
| `end_date`   | `None`       | Parsed similarly; end-of-day if date-only |
| `role`       | `"all"`      | `"user"`, `"assistant"`, or `"all"`; excludes `tool`/`system` by default when `"all"` |
| `limit`      | `20`         | Clamped to `[1, 100]` |

### Implementation Notes

- `channel_id` comes from `current_channel_id` context var (not a parameter).
- `bot_id` from `current_bot_id` — scope results to the current bot's sessions only.
- Join: `select(Message).join(Session, Message.session_id == Session.id).where(Session.channel_id == channel_id, Session.bot_id == bot_id)`
- When `role="all"`, filter to `role.in_(["user", "assistant"])` to exclude tool-call and system messages (noise).
- Order by `Message.created_at.desc()` — most recent first.
- Return JSON array of objects:

```json
[
  {
    "id": "uuid",
    "role": "user",
    "content_preview": "First 300 chars of message...",
    "created_at": "2026-03-20T14:32:00Z",
    "session_id": "uuid"
  }
]
```

### Full-Text Search Strategy (v1: ILIKE)

For v1, use Postgres `ILIKE` for keyword matching:

```python
if query:
    stmt = stmt.where(Message.content.ilike(f"%{query}%"))
```

**Why ILIKE over tsvector for v1:**
- Zero schema changes — no new columns, no migration, no GIN index.
- The `messages` table is not massive per-channel (hundreds to low thousands).
- `ILIKE` is well-understood and works identically across test environments.
- tsvector adds complexity (language config, index maintenance, `ts_query` syntax) for marginal gain at this scale.

**ILIKE safety:** The `query` parameter must be sanitized — SQLAlchemy parameterized queries handle this, but `%` and `_` characters in the query string are Postgres LIKE wildcards. Escape them:

```python
import re
escaped = re.sub(r"([%_])", r"\\\1", query)
stmt = stmt.where(Message.content.ilike(f"%{escaped}%"))
```


## 3. API Endpoint (Optional)

**File**: `app/routers/api_v1_history.py`
**Mount**: in `app/routers/api_v1.py` under the v1 router.

### Endpoint

```
GET /api/v1/channels/{channel_id}/messages/search
```

Piggyback on the existing channel resource rather than creating a new top-level `/history` prefix.

### Query Parameters

| Param        | Type   | Required | Default |
|--------------|--------|----------|---------|
| `q`          | str    | No       | —       |
| `start_date` | str    | No       | —       |
| `end_date`   | str    | No       | —       |
| `role`       | str    | No       | `all`   |
| `limit`      | int    | No       | `20`    |
| `offset`     | int    | No       | `0`     |

### Response Schema

```python
class HistoryMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content_preview: str          # first 300 chars
    created_at: datetime
    metadata: dict = {}

    model_config = {"from_attributes": True}
```

### Notes

- Auth via `verify_auth` dependency (same as all v1 routes).
- Validate `channel_id` exists, 404 if not.
- Share the core query-building logic with the tool (extract a helper in `app/services/history.py` or keep it simple and inline).
- The API endpoint adds `offset` for pagination; the tool does not (agents don't paginate well).


## 4. Tests

### Unit Tests — `tests/unit/test_search_history_tool.py`

Follow pattern from `tests/unit/test_todos_tool.py`: patch `async_session` and context vars.

| Test Case | What it validates |
|-----------|-------------------|
| `test_search_no_params` | Returns recent messages when no filters given |
| `test_search_by_keyword` | ILIKE filtering works; case-insensitive |
| `test_search_by_date_range` | `start_date` / `end_date` filtering |
| `test_search_role_filter` | `role="user"` excludes assistant messages |
| `test_search_limit_clamped` | Limit > 100 clamped to 100 |
| `test_search_no_channel_id` | Returns error when context has no channel_id |
| `test_search_empty_results` | Returns empty list / "No messages found." |
| `test_wildcard_escaping` | `%` and `_` in query are escaped properly |

### Integration Tests — `tests/integration/test_search_history_api.py`

Test the API endpoint against a real Postgres instance (same pattern as other integration tests).

| Test Case | What it validates |
|-----------|-------------------|
| `test_search_endpoint_basic` | 200 with results |
| `test_search_endpoint_empty` | 200 with empty list |
| `test_search_endpoint_bad_channel` | 404 |
| `test_search_endpoint_pagination` | offset/limit work correctly |

**SQLite limitation**: `ILIKE` is not natively supported in SQLite. For unit tests that mock the DB layer, this is not an issue (we mock query results, not the DB engine). Integration tests must run against Postgres.


## 5. Open Questions

### Large Result Sets / Pagination
- The tool caps at 100 results — sufficient for agent use cases.
- The API endpoint supports `offset` for cursor-free pagination.
- If channels accumulate >100k messages, consider adding a DB index on `(session_id, created_at)` — but this likely already exists via the FK + ordering.

### tsvector — Worth It for v2?
- **Yes, if**: we need ranked relevance, stemming, or phrase matching (e.g. `"deploy failed"` as an exact phrase).
- **No, if**: usage stays low-volume and keyword search is mostly exact-match.
- **Migration path**: Add a `search_vector` generated column + GIN index in a new Alembic migration. No breaking changes — the tool switches from ILIKE to `@@` operator internally.
- **Recommendation**: Ship v1 with ILIKE. Monitor usage. If agents call `search_history` frequently or on large channels, revisit tsvector in a follow-up.

### Content Preview Length
- 300 chars keeps tool responses compact while giving enough context.
- Could make this configurable later, but not worth the parameter bloat for v1.

### Cross-Session Scope
- The tool searches **all sessions** in the channel (including compacted/historical ones). This is intentional — the point is to surface history the agent no longer has in context.
- If this becomes noisy, consider a `current_session_only` bool parameter later.
