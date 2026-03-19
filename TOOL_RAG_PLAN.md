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

Reuse the existing `documents` table. Tool embeddings stored with a `tool:` source prefix so skill retrieval queries (which filter `source LIKE 'skill:%'`) are unaffected.

### Source naming convention

| Tool type       | Source key                               |
|-----------------|------------------------------------------|
| Local tool      | `tool:local:web_search`                  |
| MCP tool        | `tool:mcp:homeassistant:HassTurnOn`      |
| Future external | `tool:external:<namespace>:<name>`       |

### What gets stored

- **`content`**: the text embedded for similarity search — name + description + parameter summary (see below)
- **`metadata_`**: `{"schema": {...full OpenAI tool schema...}, "content_hash": "sha256..."}`
- **`embedding`**: vector from the embedding model

No new table or migration required (beyond ensuring the `documents` table exists, which it already does).

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
    allowed_sources: list[str],   # e.g. ["tool:local:*", "tool:mcp:homeassistant:*"]
    top_k: int = settings.TOOL_RETRIEVAL_TOP_K,
    threshold: float = settings.TOOL_RETRIEVAL_THRESHOLD,
) -> list[dict]:
    """Embed query → cosine search → return top-K tool schemas above threshold."""
```

Filtering by `allowed_sources` uses a SQL `source = ANY(...)` or pattern match so retrieval is scoped to what the bot is allowed to use. Returns the full OpenAI tool schema (stored in `metadata_["schema"]`), not the embed text.

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

**`pinned_tools`** must be a subset of `local_tools` + tools available via `mcp_servers`. They bypass vector search and are always included.

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

### Phase 1 — Indexing pipeline

1. `app/agent/tools.py` — new file
   - `_build_embed_text(schema: dict, server_name: str | None) -> str` — formats tool for embedding
   - `_content_hash(text: str) -> str`
   - `index_tool(schema, source_key)` — upsert into `documents` table; skip if hash matches
   - `index_local_tools()` — iterate `_tools` from registry, index each
   - `index_mcp_tools(server_name, schemas)` — index all tools from a server, delete removed ones

2. `app/tools/mcp.py` — in `_fetch_server_tools()`, after populating `_cache`, schedule `index_mcp_tools()` as a background task if the tool list changed

3. `app/main.py` — in the lifespan startup, call `await index_local_tools()`

### Phase 2 — Retrieval + loop integration

4. `app/agent/tools.py` — add `retrieve_tools()` function

5. `app/agent/bots.py`
   - Add `pinned_tools: list[str]` to `BotConfig`
   - Add `tool_retrieval: bool = True`
   - Add `tool_similarity_threshold: float | None = None`

6. `app/config.py`
   - Add `TOOL_RETRIEVAL_THRESHOLD: float = 0.35`
   - Add `TOOL_RETRIEVAL_TOP_K: int = 10`

7. `app/agent/loop.py`
   - `run_agent_tool_loop()` — add `pre_selected_tools: list[dict] | None = None`; if provided, use it instead of computing from bot config
   - `run_stream()` — call `retrieve_tools()`, build pinned+retrieved set, pass to loop

### Phase 3 — Threshold calibration

Run a few real conversations with `AGENT_TRACE=true` and log which tools are retrieved vs. which are called. Tune `TOOL_RETRIEVAL_THRESHOLD` per bot if needed.

---

## Future-Proofing: External Tool Directories

When external tool drop-in support is added (e.g. `~/agent-tools/*.py` or a plugin dir), the indexing pipeline is unchanged:

1. Load and register external tools via the same `@register` decorator (or a compatible loader)
2. Source key: `tool:external:<namespace>:<name>`
3. Call `index_tool(schema, source_key)` — identical to how local tools are indexed

Bot YAML refers to them the same way:
```yaml
local_tools:
  - my_custom_tool
pinned_tools:
  - my_custom_tool
```

The retrieval and loop code doesn't care where a tool came from — it just sees a schema and a source key.

---

## What Stays the Same

- Bot YAML `local_tools` and `mcp_servers` still define the **allowed set** — retrieval only searches within those
- `call_mcp_tool`, `call_local_tool` routing is unchanged — uses the full cache, not the filtered schema list
- Bots with `tool_retrieval: false` (or no tools) behave exactly as today
- Streaming, compaction, memory, knowledge — all unaffected

---

## Key Decisions to Confirm

1. **Reuse `documents` table vs. new `tool_schemas` table** — plan uses `documents` for zero migration cost. A dedicated table would be cleaner if you want to query/inspect tool embeddings independently. Either works.

2. **Embed text augmentation for generic MCP tool names** — plan proposes expanding camelCase names (`HassTurnOn` → "turn on, switch on"). Alternatively, require MCP tool authors to write good descriptions. The augmentation is optional and can be skipped initially.

3. **Cold-start for MCP tools** — on first request after restart, MCP tool embeddings may not exist yet. Options: (a) fall back to all-tools behavior for that turn, (b) warm MCP tools eagerly at startup by fetching them before serving requests. Option (b) is cleaner but adds startup latency.

4. **`pinned_tools` must be subset of `local_tools`** — should the YAML validator enforce this, or just silently skip unknown tool names? Suggest: log a warning and skip.
