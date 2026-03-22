# App Layer Testing Plan

---
status: active
last_updated: 2026-03-22
owner: mtoth
summary: >
  Comprehensive test plan for the app/ layer. Integrations already covered.
  Prioritizes unit tests for pure logic, integration tests for API endpoints,
  and identifies what requires mocking vs real DB.
---

## Priority 1 — Pure Logic (easiest, highest value)

These modules contain pure or near-pure functions that can be tested with no database,
no async runtime (or trivial async), and no mocking beyond basic data fixtures.

### `app/agent/message_utils.py`

| Function | What to test | Notes |
|----------|-------------|-------|
| `_build_user_message_content(text, attachments)` | Returns plain string when `attachments` is None/empty. Returns multimodal list with text + image_url parts when attachments present. Skips non-image attachments. Skips attachments with empty `content`. Uses `"(no text)"` when text is empty but attachments exist. Respects `mime_type` default (`image/jpeg`). | Pure, sync. |
| `_build_audio_user_message(audio_data, audio_format)` | Returns dict with `role: "user"` and `input_audio` content part. Defaults format to `"m4a"` when None. | Pure, sync. |
| `_extract_transcript(text)` | Parses `[transcript]...[/transcript]` tags — returns `(transcript, clean_text)`. Returns `("", original)` when no tags. Handles multiline transcript content. Strips whitespace from extracted transcript. Removes tag from clean response. | Pure, sync. Regex `_TRANSCRIPT_RE`. |
| `_extract_client_actions(messages, from_index)` | Finds `client_action` tool calls in assistant messages after `from_index`. Skips non-assistant messages. Handles malformed JSON gracefully (returns empty). Handles missing `function` key. | Pure, sync. |
| `_event_with_compaction_tag(event, compaction)` | Adds `compaction: True` key when flag is set. Returns event unchanged when flag is False. Does not mutate original dict. | Pure, sync. |
| `_merge_tool_schemas(*groups)` | Deduplicates by `function.name`. Preserves first occurrence. Handles empty groups. Handles schemas missing `function` or `name`. | Pure, sync. |

**Test file**: `tests/unit/test_message_utils.py`

### `app/agent/tags.py`

| Function | What to test | Notes |
|----------|-------------|-------|
| `_TAG_RE` (regex) | Matches `@name`, `@skill:name`, `@knowledge:name`, `@tool:name`, `@tool-pack:name`. Rejects Slack-style `<@USERID>`. Rejects email-like `user@domain`. Requires name to start with letter/underscore. Allows hyphens, dots, digits after first char. | Sync regex tests. |
| `resolve_tags(message, ...)` | Forced prefix `@skill:X` → skill tag. Forced `@knowledge:X` → knowledge tag. Forced `@tool:X` → tool tag. Unforced name in `bot_skills` → skill. Unforced name in `bot_local_tools` or `bot_client_tools` → tool. Unforced name matching a bot ID (not self) → bot tag. Deduplicates by name. Returns empty list for no tags. | Async. Requires mocking `_bot_registry` and `list_knowledge_bases`. |

**Test file**: `tests/unit/test_tags.py`

### `app/agent/context.py`

| Function | What to test | Notes |
|----------|-------------|-------|
| `set_agent_context(...)` | Sets all ContextVars. Only sets memory/depth vars when not None. | Sync. Needs async test runner for ContextVar isolation. |
| `snapshot_agent_context()` / `restore_agent_context(snap)` | Round-trips all values. Snapshot is a copy, not a reference (mutating snapshot doesn't affect live vars). | Sync. |
| `set_ephemeral_delegates(bot_ids)` | Sets list; subsequent `get()` returns same list. Creates a copy (not alias). | Sync. |

**Test file**: `tests/unit/test_context.py`

### `app/tools/tool.py` — Schema inference

| Function | What to test | Notes |
|----------|-------------|-------|
| `_unwrap_optional(t)` | `Optional[str]` → `str`. `str` → `str`. `Union[str, int]` → unchanged. `str | None` → `str`. | Pure, sync. |
| `_strip_annotated(t)` | `Annotated[str, "desc"]` → `str`. Plain `str` → `str`. | Pure, sync. |
| `_annotated_description(t)` | `Annotated[str, "desc"]` → `"desc"`. Non-string metadata → None. Non-Annotated → None. | Pure, sync. |
| `_to_json_schema(t)` | `str` → `{"type": "string"}`. `int` → `{"type": "integer"}`. `float` → `{"type": "number"}`. `bool` → `{"type": "boolean"}`. `list[str]` → `{"type": "array", "items": {"type": "string"}}`. `dict` → `{"type": "object"}`. Unknown type → `{"type": "string"}` fallback. | Pure, sync. |
| `_first_line_description(doc)` | Returns first non-empty line. Returns `""` for None. Skips leading blank lines. | Pure, sync. |
| `_parse_google_arg_descriptions(doc)` | Parses `Args:` section from Google-style docstrings. Returns empty dict when no `Args:`. Stops at double newline. Extracts `param: description` pairs. | Pure, sync. |
| `_infer_schema(func, name, description)` | Produces valid OpenAI function schema. Skips `self`/`cls` params. Marks params without defaults as required. Uses Annotated descriptions when available. Falls back to docstring arg descriptions. Uses function name when `name` is None. Uses first docstring line when `description` is None. | Pure, sync. Define test functions with various signatures. |
| `tool()` decorator | Registers function via `register()`. Supports `@tool` (no parens) and `@tool()`. Passes through `name`, `description`, `source_dir` overrides. | Requires mocking `registry._tools` or inspecting it after registration. |

**Test file**: `tests/unit/test_tool_schema.py`

### `app/tools/registry.py`

| Function | What to test | Notes |
|----------|-------------|-------|
| `register(schema)` | Stores function + schema in `_tools` dict. Uses `schema["function"]["name"]` as key. Picks up `_current_load_source_dir` and `_current_load_source_file`. | Sync decorator. Clean up `_tools` after each test. |
| `iter_registered_tools()` | Returns list of `(name, schema, source_dir, source_integration, source_file)` tuples. | Sync. Depends on `_tools` state. |
| `get_local_tool_schemas(allowed_names)` | Returns schemas only for names in `allowed_names` that exist in `_tools`. Returns `[]` for None or empty list. Silently skips unknown names. | Sync. |
| `is_local_tool(name)` | True for registered names, False otherwise. | Sync. |
| `call_local_tool(name, arguments)` | Calls registered function with JSON-parsed args. Returns JSON string result. Returns error JSON for unknown tool. Handles exceptions gracefully. Handles empty arguments string. | Async. Register a simple test tool first. |

**Test file**: `tests/unit/test_registry.py`

### `app/tools/client_tools.py`

| Function | What to test | Notes |
|----------|-------------|-------|
| `register_client_tool(schema)` | Adds to `_client_tools` by name. | Sync. |
| `get_client_tool_schemas(allowed_names)` | Filters to allowed names. Returns `[]` for None/empty. Skips unknown names. | Sync. |
| `is_client_tool(name)` | True for `"shell_exec"` (built-in). False for unknown. | Sync. |

**Test file**: `tests/unit/test_client_tools.py`

### `app/services/compaction.py` — Pure helpers

| Function | What to test | Notes |
|----------|-------------|-------|
| `_stringify_message_content(content)` | String input → passthrough. `None` → `""`. List with text parts → joined text. List with image_url → `"[image]"`. List with input_audio → `"[audio]"`. Mixed list → concatenated. Empty list → `"[multimodal message]"`. JSON-encoded multimodal string → recursively decoded. | Pure, sync. |
| `_get_compaction_model(bot, channel)` | Channel override > bot override > settings override > bot.model fallback. | Sync. Construct BotConfig/Channel dataclass/mock. |
| `_get_compaction_interval(bot, channel)` | Same priority cascade: channel > bot > settings. | Sync. |
| `_get_compaction_keep_turns(bot, channel)` | Same priority cascade. | Sync. |
| `_is_compaction_enabled(bot, channel)` | Channel-level override > bot-level > default True. | Sync. |

**Test file**: `tests/unit/test_compaction_helpers.py`

### `app/services/sessions.py` — Pure helpers

| Function | What to test | Notes |
|----------|-------------|-------|
| `normalize_stored_content(content)` | Plain string → passthrough. `None` → `None`. JSON list of dicts with `"type"` keys → parsed list. JSON list of strings (e.g. `'["a","b"]'`) → kept as string (not parsed). Malformed JSON → kept as string. | Pure, sync. |
| `is_integration_client_id(client_id)` | Returns True for known prefixes (e.g. `"slack-"`, `"github-"`). Returns False for `None`, empty, and regular IDs. | Sync. Depends on `INTEGRATION_CLIENT_PREFIXES`. |
| `derive_integration_session_id(client_id)` | Deterministic UUID5 output. Same input → same output. Different inputs → different outputs. | Sync. |

**Test file**: `tests/unit/test_session_helpers.py`

### `app/agent/tasks.py` — Recurrence parsing

| Function | What to test | Notes |
|----------|-------------|-------|
| `_parse_recurrence(value)` | `"+1h"` → `timedelta(hours=1)`. `"+30m"` → `timedelta(minutes=30)`. `"+1d"` → `timedelta(days=1)`. `"+5s"` → `timedelta(seconds=5)`. `"invalid"` → `None`. `"+0h"` → `timedelta(0)`. Leading/trailing whitespace handled. | Pure, sync. |

**Test file**: `tests/unit/test_task_helpers.py`

### `app/agent/loop.py` — Pure helpers

| Function | What to test | Notes |
|----------|-------------|-------|
| `_CLASSIFY_SYS_MSG(content)` | Maps known prefixes to labels (e.g. `"Current time:" → "sys:datetime"`). Unknown prefix → `"sys:system_prompt"`. | Pure, sync. Tests each entry in `_SYS_MSG_PREFIXES`. |

**Test file**: `tests/unit/test_loop_helpers.py`

### `app/services/context_estimate.py` — Pure helpers

| Function | What to test | Notes |
|----------|-------------|-------|
| `_schema_json_chars(schema)` | Returns length of compact JSON dump. | Pure, sync. |
| `_clamp(x, lo, hi)` | Clamps to range. Handles edge cases (x == lo, x == hi). | Pure, sync. |
| `_parse_skill_entries(raw_skills)` | Strings → on_demand. Dicts with `mode: "pinned"` → pinned. Dicts with `mode: "rag"` → rag. Default mode → on_demand. Non-string/non-dict → on_demand with str coercion. | Pure, sync. |
| `_rag_retrieval_factor(threshold)` | Returns clamped float in [0.15, 0.92]. Higher threshold → lower factor. | Pure, sync. |
| `_memory_knowledge_hit_factor(threshold)` | Returns clamped float in [0.22, 0.95]. Higher threshold → lower factor. | Pure, sync. |

**Test file**: `tests/unit/test_context_estimate.py`

---

## Priority 2 — API Endpoints

These tests use FastAPI's `TestClient` (via `httpx.AsyncClient`) with a real async
SQLite or PostgreSQL test database. Auth is validated via `verify_auth` dependency
which checks `Bearer <API_KEY>`.

### Test infrastructure needed

- **Override `get_db`** dependency to yield an async SQLite session (or test PostgreSQL).
  Note: pgvector operations (cosine distance) won't work in SQLite — those endpoints
  need a real PostgreSQL test DB or must be skipped.
- **Override `verify_auth`** to accept a test token or bypass auth.
- **Seed bot registry** with a test `BotConfig` before endpoint tests (mock `get_bot()`).
- **Shared fixture**: `async_client` — `httpx.AsyncClient` wrapping the FastAPI app.

### `app/routers/api_v1_sessions.py`

| Endpoint | Happy path | Error cases |
|----------|-----------|-------------|
| `POST /api/v1/sessions` | Creates session, returns `session_id` + `created` flag. Stores `dispatch_config`. | Unknown `bot_id` → 400. Missing auth → 401. |
| `POST /api/v1/sessions/{id}/messages` | Injects message, returns `message_id`. With `run_agent=true` → creates Task, returns `task_id`. With `notify=true` → calls `_fanout`. | Session not found → 404. |
| `GET /api/v1/sessions/{id}/messages` | Returns messages in chronological order. Respects `limit` param. | Session not found → 404. |

**Test file**: `tests/integration/test_api_sessions.py`

### `app/routers/api_v1_tasks.py`

| Endpoint | Happy path | Error cases |
|----------|-----------|-------------|
| `GET /api/v1/tasks/{id}` | Returns task status, result, timestamps. | Task not found → 404. Missing auth → 401. |

**Test file**: `tests/integration/test_api_tasks.py`

### `app/routers/api_v1_channels.py`

| Endpoint | Happy path | Error cases |
|----------|-----------|-------------|
| `POST /api/v1/channels` | Creates channel, returns channel fields. | Unknown `bot_id` → 400. |
| `GET /api/v1/channels` | Lists channels. Filters by `integration`, `bot_id`. | Empty list is valid. |
| `GET /api/v1/channels/{id}` | Returns single channel. | 404 when missing. |
| `PUT /api/v1/channels/{id}` | Updates name, bot_id, require_mention, passive_memory. | 404 when missing. Unknown bot_id → 400. |
| `POST /api/v1/channels/{id}/messages` | Injects message into active session. With `run_agent=true` → Task created. | 404 when channel missing. |
| `POST /api/v1/channels/{id}/reset` | Creates new session, returns old + new IDs. | 404 when channel missing. |
| `GET /api/v1/channels/{id}/knowledge` | Lists knowledge access entries for channel. | 404 when channel missing. |

**Test file**: `tests/integration/test_api_channels.py`

### `app/routers/api_v1_documents.py`

| Endpoint | Happy path | Error cases |
|----------|-----------|-------------|
| `POST /api/v1/documents` | Ingests document with embedding. | Requires mock for `_embed()` (LiteLLM call). |
| `GET /api/v1/documents/search` | Semantic search over documents. | Requires pgvector (skip on SQLite). Requires mock for `_embed()`. |
| `GET /api/v1/documents/{id}` | Returns document by ID. | 404 when missing. |
| `DELETE /api/v1/documents/{id}` | Deletes document. Returns 204. | 404 when missing. |

**Test file**: `tests/integration/test_api_documents.py`
**Note**: The `_embed` function at module level creates an `AsyncOpenAI` client.
Must patch `app.routers.api_v1_documents._embed` to return a fixed-dimension vector.

### `app/routers/chat.py`

| Endpoint | Happy path | Error cases |
|----------|-----------|-------------|
| `POST /chat` | Full chat flow. Requires mocking `run()` / `run_stream()` to avoid LLM calls. Assert session creation, message persistence, response shape. | Passive mode → stores message, returns empty response. |
| `GET /bots` | Returns list of bot configs (id, name, model, audio_input). | No auth required (check if auth is enforced). |

**Test file**: `tests/integration/test_chat.py`
**Note**: Heavy mocking required. Focus on request validation and response shape rather
than full agent loop. Mock `run()` to return a canned response.

---

## Priority 3 — Agent Loop & Services

These require mocking the LLM provider (`openai.AsyncOpenAI.chat.completions.create`)
and potentially database sessions. Test the orchestration logic, not the LLM output.

### `app/agent/loop.py`

**What's realistic to test:**

| Area | Approach |
|------|----------|
| `_llm_call()` retry logic | Mock `client.chat.completions.create` to raise `RateLimitError` N times then succeed. Assert exponential backoff timing. Assert it gives up after `max_retries`. |
| `_summarize_tool_result()` | Mock LLM to return canned summary. Assert it's called when result exceeds threshold. Assert original result returned when under threshold. |
| Tool dispatch routing | Mock `is_local_tool`, `is_mcp_tool`, `is_client_tool` to control routing. Assert `call_local_tool` / `call_mcp_tool` / `call_client_tool` called for correct tool types. |
| `run_agent_tool_loop()` single iteration | Mock LLM to return a response with no tool calls. Assert it yields a `response` event and terminates. |
| `run_agent_tool_loop()` with tool call | Mock LLM to return a tool call, then a text response. Assert tool execution event + final response event. |
| Max iterations guard | Mock LLM to always return tool calls. Assert loop terminates at `AGENT_MAX_ITERATIONS` and injects forced-response system message. |

**What's too coupled to test well:**
- Full `run_stream()` — too many RAG + context injection paths. Better covered by E2E tests.
- Delegation flow — requires nested sessions, multiple bot configs, context snapshot/restore.
- Audio transcription path — requires STT service mock + audio format handling.

**Test file**: `tests/integration/test_agent_loop.py`

### `app/agent/tasks.py`

| Area | Approach |
|------|----------|
| `_schedule_next_occurrence(task)` | Create a Task fixture with `recurrence="+1h"`. Assert new Task row created with correct `scheduled_at`. |
| `run_task()` orchestration | Mock `run()` to return canned result. Assert task status transitions: `pending` → `running` → `complete`. Assert `result` stored. Assert `dispatch` called when configured. |
| `run_task()` error handling | Mock `run()` to raise. Assert task status → `failed`, error stored. |
| `run_task()` rate limit retry | Mock `run()` to raise `RateLimitError`. Assert task rescheduled with backoff. |
| `fetch_due_tasks()` | Insert tasks with various `scheduled_at` and `status`. Assert only `pending` tasks due now are returned. |

**Test file**: `tests/integration/test_tasks.py`

### `app/services/sessions.py`

| Area | Approach |
|------|----------|
| `load_or_create()` | Test with real DB. Assert new session created with system prompt + persona. Assert existing session reloaded. Assert compaction summary prepended when present. |
| `persist_turn()` | Test with real DB. Assert messages stored with correct roles, content, tool_calls. Assert image content redacted via `_redact_images_for_db`. |
| `store_passive_message()` | Test with real DB. Assert message stored with `_metadata.passive = True`. |
| `_content_for_db()` | Assert multimodal content serialized to JSON string. Assert data-URL images replaced with placeholder. Assert plain strings passed through. |

**Test file**: `tests/integration/test_sessions.py`

### `app/services/compaction.py`

| Area | Approach |
|------|----------|
| `run_compaction_stream()` | Mock LLM for summary generation. Assert compaction skipped when turn count < interval. Assert summary stored on session. Assert `summary_message_id` watermark set. |
| `_messages_for_memory_phase()` | Test message filtering. Assert tool results truncated to 500 chars. Assert passive messages excluded. |
| `_messages_for_summary()` | Assert alternating user/assistant structure maintained. Assert passive messages excluded. |
| Memory phase | Mock LLM + memory/knowledge tools. Assert memory phase events yielded with `compaction=True`. |

**Test file**: `tests/integration/test_compaction.py`

### `app/agent/persona.py`

| Area | Approach |
|------|----------|
| `get_persona(bot_id)` | Test with real DB. Assert returns persona text. Assert returns None when not found. |
| `write_persona(bot_id, content)` | Assert upsert works (create + update). Assert returns `(True, None)` on success. |
| `edit_persona(bot_id, old_text, new_text)` | Assert find-and-replace works. Assert `(False, "old_text not found...")` when old_text missing. Assert `(False, "Persona not found.")` when no persona exists. |
| `append_to_persona(bot_id, content)` | Assert appends to existing. Assert `(False, "No content...")` for empty/whitespace. Assert `(False, "Persona not found")` when no row. |

**Test file**: `tests/integration/test_persona.py`

### `app/agent/bots.py`

| Area | Approach |
|------|----------|
| `resolve_bot_id(hint)` | Populate `_registry` with test bots. Assert exact ID match (priority 1). Assert case-insensitive ID match (priority 2). Assert exact name match (priority 3). Assert substring of ID (priority 4). Assert substring of name (priority 5). Assert word-overlap (priority 6). Assert None for no match. Assert None for empty registry/hint. |
| `get_bot(bot_id)` | Assert returns BotConfig for known ID. Assert raises HTTPException 404 for unknown. |
| `_bot_row_to_config()` | Construct a `BotRow` mock with all fields. Assert all fields mapped correctly to `BotConfig`. Assert nested configs parsed (MemoryConfig, KnowledgeConfig, SkillConfig, etc.). |

**Test file**: `tests/unit/test_bots.py` (for `resolve_bot_id` — can be tested by
populating `_registry` directly without DB)

### `app/agent/tools.py` — Tool RAG

| Area | Approach |
|------|----------|
| `build_embed_text()` | Assert produces human-readable summary of tool schema. |
| `retrieve_tools()` | Requires pgvector. Mock `_embed_query` to return fixed vector. Assert tools above threshold returned. Assert `top_k` limit respected. |
| `index_local_tools()` | Assert tools inserted into `tool_embeddings` table. Assert content hash skips re-embedding. |

**Test file**: `tests/integration/test_tool_rag.py`
**Note**: Requires PostgreSQL with pgvector extension.

---

## Priority 4 — Lower Priority / Skip For Now

### Admin routers (UI-only)
- `app/routers/admin.py`, `admin_bots.py`, `admin_channels.py`, `admin_skills.py`,
  `admin_tasks.py`, `admin_providers.py`, `admin_sandbox.py`, `admin_fs.py`,
  `admin_knowledge_pins.py`, `admin_template_filters.py`
- These serve the admin web UI. Low risk, low value to test in isolation.
- **Recommendation**: Skip unless admin API becomes a public contract.

### STT provider (`app/stt.py`)
- Wraps Whisper API call. Single function.
- **Recommendation**: Skip. Mock at the caller level (`chat.py`).

### MCP client (`app/tools/mcp.py`)
- `load_mcp_config()` — YAML parsing + env var resolution. **Could** unit test the
  `_resolve_env_vars()` helper, but low value.
- `fetch_mcp_tools()` / `call_mcp_tool()` — HTTP calls to external MCP servers with
  60s TTL caching. Too infrastructure-coupled for unit tests.
- **Recommendation**: Integration-test only if MCP servers are available in CI.

### Docker sandbox service (`app/services/sandbox.py`)
- Requires Docker daemon. Not testable in standard CI.
- **Recommendation**: Skip. Test via manual QA or dedicated Docker-in-Docker CI stage.

### Harness service
- Subprocess execution. Infrastructure-coupled.
- **Recommendation**: Skip.

### Tool loader (`app/tools/loader.py`)
- Dynamic `importlib` loading. Fragile to test, low value.
- `discover_and_load_tools()` depends on filesystem layout.
- **Recommendation**: Skip. Covered implicitly by startup smoke tests.

### File watcher / filesystem indexing
- OS-level file watching. Not suitable for unit tests.
- **Recommendation**: Skip.

---

## Test Infrastructure

### Directory structure

```
tests/
  conftest.py              # Shared fixtures (test DB, mock LLM, app client)
  unit/
    __init__.py
    test_message_utils.py
    test_tags.py
    test_context.py
    test_tool_schema.py
    test_registry.py
    test_client_tools.py
    test_compaction_helpers.py
    test_session_helpers.py
    test_task_helpers.py
    test_loop_helpers.py
    test_context_estimate.py
    test_bots.py
  integration/
    __init__.py
    conftest.py            # DB fixtures, mock LLM provider
    test_api_sessions.py
    test_api_tasks.py
    test_api_channels.py
    test_api_documents.py
    test_chat.py
    test_agent_loop.py
    test_tasks.py
    test_sessions.py
    test_compaction.py
    test_persona.py
    test_tool_rag.py
```

### Shared fixtures (`tests/conftest.py`)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_llm_response():
    """Factory for mock OpenAI ChatCompletion responses."""
    def _make(content="Hello", tool_calls=None):
        choice = MagicMock()
        choice.message.content = content
        choice.message.tool_calls = tool_calls or []
        choice.finish_reason = "stop" if not tool_calls else "tool_calls"
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 50
        return resp
    return _make

@pytest.fixture
def mock_llm_client(mock_llm_response):
    """Patches the OpenAI client used by _llm_call."""
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=mock_llm_response())
    with patch("app.services.providers.get_llm_client", return_value=client):
        yield client
```

### Integration test DB (`tests/integration/conftest.py`)

Two options:

**Option A — Async SQLite (fast, no pgvector)**:
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.models import Base

@pytest.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()
```

**Option B — Test PostgreSQL (full fidelity, requires docker)**:
```python
# Use a dedicated test database with pgvector extension
# Run via: docker compose -f docker-compose.test.yml up -d postgres
TEST_DB_URL = "postgresql+asyncpg://test:test@localhost:5433/test_agent"
```

**Recommendation**: Use Option A for most tests. Use Option B only for tests that
need pgvector (tool RAG, document search). Mark pgvector tests with
`@pytest.mark.pgvector` and skip in CI if no test DB available.

### FastAPI test client fixture

```python
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.dependencies import get_db, verify_auth

@pytest.fixture
async def async_client(test_db):
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[verify_auth] = lambda: "test-token"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
```

### Extending `Dockerfile.test`

The existing `Dockerfile.test` runs `pytest integrations/ -v`. Extend to include
app-layer tests:

```dockerfile
# Add app dependencies
RUN pip install aiosqlite sqlalchemy[asyncio] openai httpx

# Run all tests
CMD ["pytest", "tests/", "integrations/", "-v", "--ignore=tests/integration/test_tool_rag.py"]
```

For pgvector-dependent tests, use a separate CI job with `docker-compose.test.yml`
that starts PostgreSQL + pgvector.

### How to run

```bash
# Unit tests only (fast, no deps)
pytest tests/unit/ -v

# Integration tests with SQLite (no pgvector)
pytest tests/integration/ -v --ignore=tests/integration/test_tool_rag.py

# Full suite with PostgreSQL (requires running postgres)
pytest tests/ -v

# Existing integration tests (unchanged)
pytest integrations/ -v
```

---

## Open Questions

### Architectural concerns affecting testability

1. **Module-level state in registries**: `app/tools/registry._tools`,
   `app/tools/client_tools._client_tools`, `app/tools/mcp._servers`,
   `app/agent/bots._registry` are module-level dicts populated at startup.
   Tests that import these modules inherit whatever state exists. Each test
   must either:
   - Save and restore the dict (`_tools_backup = _tools.copy()`)
   - Use `unittest.mock.patch.dict()` to isolate mutations

   This is the biggest source of test pollution risk.

2. **`async_session` factory tied to production DB**: The `app.db.engine.async_session`
   is created at import time from `settings.DATABASE_URL`. Integration tests must
   override this via FastAPI dependency injection (`get_db`) or by patching
   `app.db.engine.async_session` directly for services that call it internally
   (e.g. `persona.py`, `tasks.py` use `async_session()` directly, not via DI).

   **Impact**: Services like `get_persona()`, `write_persona()`, `_schedule_next_occurrence()`
   open their own DB sessions. To test these with a test DB, you must patch
   `app.db.engine.async_session` to return a test session factory.

3. **Import-time side effects in `client_tools.py`**: The module registers `shell_exec`
   at import time. Any test that imports `client_tools` will have `shell_exec` in
   the registry. This is fine for most tests but could cause unexpected tool
   availability in isolation tests.

4. **`_embed` client in `api_v1_documents.py`**: The `AsyncOpenAI` client is created
   at module level. Must patch `app.routers.api_v1_documents._embed` rather than
   the client constructor.

5. **ContextVar isolation**: Python's `contextvars` are task-local in asyncio. Each
   `pytest-asyncio` test gets its own task, so ContextVars are naturally isolated.
   However, tests that spawn sub-tasks (e.g. testing delegation) need explicit
   context management.

6. **Circular imports in `loop.py`**: The agent loop imports from many modules
   (`memory`, `knowledge`, `rag`, `tags`, `tools`, `recording`, `pending`, etc.).
   Mocking individual components requires careful patch targeting. Consider using
   `unittest.mock.patch` with the full dotted path as used in `loop.py`'s imports
   (e.g. `patch("app.agent.loop.retrieve_memories")`).
