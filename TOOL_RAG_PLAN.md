# Dynamic Tool Selection via RAG

## Problem

Every agent turn passes the full set of a bot's tool schemas to the LLM. For bots like `slack_bot` that reference a Home Assistant MCP server with dozens of tools, this burns 3–6k tokens per request regardless of whether the user is asking about lights, the weather, their pet's health, or something completely unrelated. This degrades model reasoning on unrelated tasks (especially smaller models) and inflates costs.

## Proposed Solution

Apply the same RAG pipeline already used for skills, memories, and knowledge — but to tool schemas. At startup, embed each tool's description and store it in the existing `documents` table. At request time, embed the user's message, do cosine similarity search against that bot's allowed tool set, and pass only the relevant tools to the LLM. Always-on ("pinned") tools bypass filtering.

This is the same infrastructure you already have. No new dependencies.

---

## Architecture

### How Tools Flow Today

```
bot.local_tools + bot.mcp_servers
        ↓
get_local_tool_schemas()   ← all schemas, every turn
fetch_mcp_tools()          ← all schemas from servers, every turn (60s cache)
        ↓
LLM call with all_tools
```

### How It Will Flow

```
bot.local_tools + bot.mcp_servers
        ↓
populate_tool_cache()          ← warm the cache (for routing), no schema injection yet
        ↓
retrieve_tools(user_message)   ← embed query → cosine search → top-K relevant schemas
        ↓
pinned_tools ∪ retrieved_tools ← deduplicated
        ↓
LLM call with filtered_tools
```

Tool routing (`call_mcp_tool`, `call_local_tool`) is unaffected — it uses the full cache to dispatch, not the filtered list. The LLM just sees fewer schemas.

---

## Storage

A dedicated `tool_embeddings` table. The `documents` table is for retrievable prose (skill chunks, knowledge content) that gets injected into the system prompt. Tool schemas are structured JSON retrieved for the `tools` API parameter — fundamentally different enough to warrant their own table.

### Schema

```sql
CREATE TABLE tool_embeddings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name    TEXT NOT NULL,      -- e.g. "web_search", "HassTurnOn"
    server_name  TEXT,               -- NULL for local/dir tools, "homeassistant" for MCP
    source_dir   TEXT,               -- filesystem path that loaded this tool (NULL for built-ins)
    schema       JSONB NOT NULL,     -- full OpenAI tool schema
    embed_text   TEXT NOT NULL,      -- text that was embedded (useful for debugging/inspection)
    content_hash TEXT NOT NULL,      -- SHA-256 of embed_text; skip re-embed if unchanged
    embedding    vector({settings.EMBEDDING_DIMENSIONS}),  -- tied to config, same as documents/memories
    indexed_at   TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX ON tool_embeddings (tool_name);
CREATE INDEX ON tool_embeddings (server_name);
CREATE INDEX ON tool_embeddings (content_hash);
```

SQLAlchemy model goes in `app/db/models.py` alongside the existing models.

### Why not reuse `documents`?

- `documents` is for prose; tools are structured schemas — wrong semantic bucket
- Typed columns (`tool_name`, `server_name`, `source_dir`) vs. stuffing everything into `metadata_` JSONB
- External tool dir cleanup: `DELETE FROM tool_embeddings WHERE source_dir = '/path'` vs. fragile string-prefix matching
- Skill retrieval guards with `WHERE source LIKE 'skill:%'`; adding tools would require yet another filter discipline on every query
- Clean admin visibility — `SELECT * FROM tool_embeddings` vs. parsing `documents.source` prefixes

### Embed text format

Rich text captures more matching surface than just the description:

```
Tool: web_search
Description: Search the web for current information. Use when you need recent events, facts you're unsure about, or anything time-sensitive.
Parameters: query (required, string): The search query | num_results (optional, integer): Number of results to return
```

For HA-style tools with generic descriptions like "Turn on a device", augment at indexing time by parsing the tool name into keywords:
- `HassTurnOn` → `turn on, switch on, enable, activate`
- `HassLightSet` → `set light, brightness, color, dim`

This is done in the indexing step, not the tool definition itself.

### Content hash for deduplication

Each tool document includes a hash of its embed text. On re-indexing, skip if the hash matches — so MCP tool list refreshes (currently every 60s) don't trigger redundant embeds. Only changed or new tools get re-embedded.

---

## Indexing

### Local tools — at startup

`registry.py` already has all schemas at import time. After `load_bots()` and before the server starts serving, index all registered local tools:

```python
await index_local_tools()   # in app/agent/startup.py or app/main.py lifespan
```

### MCP tools — after first fetch per server

`fetch_mcp_tools()` already caches. Add a hook: after a successful fetch, call `index_mcp_tools(server_name, tools)` if the tool list has changed (compare hashes). This runs asynchronously in the background — the current request isn't blocked.

MCP tools won't be in the index on the very first request after a cold start, but they'll be populated by the time the second request arrives. For the first request, fall back to include all tools from that server (same as today).

### Re-indexing on change

- Local tools: stable between restarts, re-indexed at startup
- MCP tools: re-indexed when the fetched list hash changes (at most every 60s per server)
- Future external tools: re-indexed when the tool file/manifest changes

---

## Retrieval

### New function: `app/agent/tools.py`

```python
async def retrieve_tools(
    query: str,
    allowed_tool_names: list[str],   # e.g. ["web_search", "HassTurnOn", "HassLightSet"]
    allowed_servers: list[str],      # e.g. ["homeassistant"] — MCP servers the bot can use
    top_k: int = settings.TOOL_RETRIEVAL_TOP_K,
    threshold: float = settings.TOOL_RETRIEVAL_THRESHOLD,
) -> list[dict]:
    """Embed query → cosine search → return top-K tool schemas above threshold."""
```

Filtering uses `WHERE tool_name = ANY(:names) OR server_name = ANY(:servers)` — clean typed column comparisons, no string prefix hackery. Returns the `schema` JSONB column directly (the full OpenAI tool schema), not the embed text.

### Where it's called

In `run_stream()` in `loop.py`, after skills/memory/knowledge retrieval, before building the user message:

```python
# existing: skills, memory, knowledge retrieval
# new:
if bot.tool_retrieval:
    selected_tools = await retrieve_tools(
        query=user_message,
        allowed_sources=_tool_sources_for_bot(bot),
        threshold=bot.tool_similarity_threshold or settings.TOOL_RETRIEVAL_THRESHOLD,
    )
    pinned = _get_pinned_tool_schemas(bot)
    tools_for_turn = _merge_tools(pinned, selected_tools)
else:
    tools_for_turn = None  # loop builds them from bot config (current behavior)
```

`run_agent_tool_loop()` gets a new optional parameter `pre_selected_tools`. If provided, uses it. If None, falls back to current behavior (build from bot config). This keeps backward compatibility and lets bots opt out.

---

## Bot YAML Changes

```yaml
# bots/slack_bot.yaml

# Existing — unchanged
local_tools:
  - web_search
  - fetch_url
  - get_current_local_time  # ← move this to pinned_tools
  - search_memories
  - save_memory
  - ...
mcp_servers:
  - homeassistant

# New fields
pinned_tools:                    # always included, regardless of similarity
  - get_current_local_time       # cheap, frequently useful
  - client_action                # needed for voice commands

tool_retrieval: true             # default true; set false to use all tools (current behavior)
tool_similarity_threshold: 0.35  # optional per-bot override
```

**`pinned_tools`** can reference any tool the bot has access to — local tools, directory-loaded tools, or MCP tools by their tool name (e.g. `HassTurnOn`). They bypass vector search and are always included. For a dedicated HA voice bot you'd pin all or most HA tools so the model always has full tool context regardless of the query.

**`tool_retrieval: false`** gives you the current behavior exactly — useful for bots with only 2-3 tools where filtering is pointless overhead.

---

## Config Changes

```
# .env
TOOL_RETRIEVAL_THRESHOLD=0.35    # similarity floor for tool selection
TOOL_RETRIEVAL_TOP_K=10          # max tools retrieved per turn
```

Threshold rationale: skills use 0.30 (broad recall), memory uses 0.45–0.75 (high precision). Tools sit in between — descriptions are action-specific but user queries are often indirect ("turn on the lights" should match `HassTurnOn` even though it doesn't say "lights" in the tool name).

---

## Implementation Phases

### Phase 0 — Simplified registration & discovery

1. `app/tools/tool.py` — new file
   - `@tool` decorator: infers schema from type hints + docstring, calls `register()` internally
   - `_infer_schema(func) -> dict` — parses signature and docstring into OpenAI schema
   - Support for `Annotated[T, "description"]` and Google-style docstring args sections

2. `app/tools/loader.py` — new file
   - `discover_and_load_tools(dirs: list[Path]) -> None` — glob + importlib import
   - `_import_tool_file(path: Path) -> None` — safe import with error logging per file (one bad file doesn't block the rest)

3. `app/config.py`
   - Add `TOOL_DIRS: str = ""` — colon-separated extra paths to scan

4. `app/main.py` — in lifespan startup, call `discover_and_load_tools([...])` before anything else

5. Create `tools/` dir at project root with a `README.md` explaining how to drop in tools

### Phase 1 — Indexing pipeline

6. `app/agent/tools.py` — new file
   - `_build_embed_text(schema: dict, server_name: str | None) -> str` — formats tool for embedding
   - `_content_hash(text: str) -> str`
   - `index_tool(schema, source_key)` — upsert into `documents` table; skip if hash matches
   - `index_local_tools()` — iterate `_tools` from registry, index each
   - `index_mcp_tools(server_name, schemas)` — index all tools from a server, delete removed ones

7. `app/tools/mcp.py` — in `_fetch_server_tools()`, after populating `_cache`, schedule `index_mcp_tools()` as a background task if the tool list changed

8. `app/main.py` — in lifespan startup, after discovery, call `await index_local_tools()`

### Phase 2 — Retrieval + loop integration

9. `app/agent/tools.py` — add `retrieve_tools()` function

10. `app/agent/bots.py`
    - Add `pinned_tools: list[str]` to `BotConfig`
    - Add `tool_retrieval: bool = True`
    - Add `tool_similarity_threshold: float | None = None`

11. `app/config.py`
    - Add `TOOL_RETRIEVAL_THRESHOLD: float = 0.35`
    - Add `TOOL_RETRIEVAL_TOP_K: int = 10`

12. `app/agent/loop.py`
    - `run_agent_tool_loop()` — add `pre_selected_tools: list[dict] | None = None`; if provided, use it instead of computing from bot config
    - `run_stream()` — call `retrieve_tools()`, build pinned+retrieved set, pass to loop

### Phase 3 — Threshold calibration

Run a few real conversations with `AGENT_TRACE=true` and log which tools are retrieved vs. which are called. Tune `TOOL_RETRIEVAL_THRESHOLD` per bot if needed.

---

## Simplified Tool Registration & Discovery

The current `@register` decorator requires writing a full OpenAI JSON schema dict inline — verbose and unfriendly for anyone dropping in a quick tool. This section covers:

1. A simpler `@tool` decorator that infers schema from type hints and docstring
2. Configurable multi-directory scanning so tools don't have to live inside `app/`

### New `@tool` Decorator

```python
# tools/my_tools.py  ← lives in project root tools/, not in app/

from app.tools.tool import tool

@tool
async def get_weather(city: str, units: str = "imperial") -> str:
    """Get the current weather for a city.

    Use when the user asks about weather, temperature, or forecast.
    """
    ...
```

That's it. No JSON. The schema is inferred automatically:

| Python                        | OpenAI schema                         |
|-------------------------------|----------------------------------------|
| Function name                 | `"name"`                               |
| First line of docstring       | `"description"` (rest is ignored)     |
| `param: str`                  | `{"type": "string"}`                  |
| `param: int`                  | `{"type": "integer"}`                 |
| `param: bool`                 | `{"type": "boolean"}`                 |
| `param: list`                 | `{"type": "array"}`                   |
| No default → required         | added to `"required"` list            |
| `Annotated[str, "desc"]`      | adds `"description"` to that param    |

For per-parameter descriptions without `Annotated`, use a Google/NumPy-style docstring:

```python
@tool
async def get_weather(city: str, units: str = "imperial") -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to look up (e.g. 'New York').
        units: 'imperial' (°F) or 'metric' (°C).
    """
```

Override name or description explicitly when needed:

```python
@tool(name="weather_lookup", description="Check current weather conditions.")
async def get_weather(city: str) -> str:
    ...
```

`@tool` calls `register()` internally — the function ends up in the same `_tools` dict, is routed the same way by `call_local_tool`, and is indexed the same way. The decorator is just a schema-generation shortcut.

The old verbose `@register({...})` on existing internal tools stays exactly as-is — no migration, full backward compat.

### Configurable Tool Directories

Two directories are scanned at startup:

1. **`app/tools/local/`** — built-in tools, always loaded (current behavior)
2. **`tools/`** in the project root — user tools, always scanned if it exists

Additional directories are added via config:

```
# .env
TOOL_DIRS=./tools:/home/user/my-agent-tools:/srv/shared-tools
```

All entries in `TOOL_DIRS` are scanned in addition to the two defaults. Paths can be absolute or relative to cwd.

### Auto-Discovery Loader

A new `app/tools/loader.py` handles scanning:

```python
async def discover_and_load_tools(dirs: list[Path]) -> None:
    """Import all .py files in given directories.
    Any @tool or @register decorated functions are automatically registered."""
    for dir_path in dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            _import_tool_file(py_file)
```

`_import_tool_file` uses `importlib.util.spec_from_file_location` to import the file. The act of importing is enough — `@tool` and `@register` decorators run at import time and self-register. No manual wiring needed.

This runs at startup, before `index_local_tools()`.

### Source Keys for Directory-Loaded Tools

Tools discovered from external directories get a namespaced source key based on directory:

| Directory              | Source key                           |
|------------------------|--------------------------------------|
| `app/tools/local/`     | `tool:local:web_search`              |
| `./tools/`             | `tool:local:my_custom_tool`          |
| `/home/user/mytools/`  | `tool:local:my_custom_tool`          |

Since all non-MCP tools end up in the same `_tools` dict and are routed via `call_local_tool`, they're all `tool:local:*` from the retrieval perspective. The directory they came from doesn't matter at runtime — the registry is the authority.

### Bot YAML — No Change Required

Tools loaded from external dirs are referenced exactly like built-in tools:

```yaml
local_tools:
  - web_search       # built-in, in app/tools/local/
  - get_weather      # from tools/ at project root
  - my_custom_tool   # from TOOL_DIRS

pinned_tools:
  - get_weather
```

Bot YAML still defines the allowed set. Discovery just makes more tools available to put in that list.

---

## What Stays the Same

- Bot YAML `local_tools` and `mcp_servers` still define the **allowed set** — retrieval only searches within those
- `call_mcp_tool`, `call_local_tool` routing is unchanged — uses the full cache, not the filtered schema list
- Bots with `tool_retrieval: false` (or no tools) behave exactly as today
- Streaming, compaction, memory, knowledge — all unaffected

---

## Key Decisions to Confirm

1. ~~Reuse `documents` vs. new table~~ — **resolved: new `tool_embeddings` table** (see Storage section)

2. ~~Embed text augmentation for generic MCP tool names~~ — **resolved: skip for v1.** Parameter names and descriptions (e.g. `brightness`, `color_temp`, `rgb_color` on `HassLightSet`) already give the embedder enough surface to work with. Add camelCase expansion only if retrieval quality proves poor in practice.

3. ~~Cold-start for MCP tools~~ — **resolved: option B, eager fetch at startup.** Block the server from accepting requests until all MCP tool lists are fetched and indexed. Same principle as skills — no point serving requests before the index is ready. Slight startup latency is acceptable.

4. **`pinned_tools` validation** — `pinned_tools` can reference any tool the bot has access to: local tools, directory-loaded tools, or MCP tools (by tool name). This is intentional — a dedicated HA voice bot should be able to pin all HA tools so they're always in context. Validation: if a pinned tool name isn't found in the registry or MCP cache at startup, log a warning and skip (don't crash).

5. **Migrate existing built-in tools to `@tool`** — the internal tools (`web_search`, `knowledge.py`, etc.) can stay as-is with `@register`. Only new/external tools need `@tool`. Or: migrate them all at once for consistency. Recommend doing it gradually — `@tool` for anything new, leave existing ones alone.
