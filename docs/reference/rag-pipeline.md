# RAG Pipeline

Technical reference for how Spindrel indexes, retrieves, and injects knowledge into LLM context.

---

## Overview

Spindrel's RAG pipeline has three stages:

1. **Indexing** — Content is chunked, optionally annotated with LLM-generated descriptions, embedded into vectors, and stored in PostgreSQL with pgvector.
2. **Retrieval** — User queries are embedded and matched against stored vectors via cosine similarity, optionally fused with BM25 keyword search.
3. **Injection** — Retrieved chunks are formatted and injected into the LLM context as system messages during context assembly.

Three independent content sources feed the pipeline:

| Source | Table | Indexed from | Retrieval function |
|--------|-------|-------------|-------------------|
| **Skills** (index) | `documents` | `skills/*.md`, DB, capabilities | `retrieve_skill_index()` in `rag.py` |
| **Filesystem** | `filesystem_chunks` | Workspace dirs, indexed paths | `retrieve_filesystem_context()` in `fs_indexer.py` |
| **Tools** | `tool_embeddings` | Local tools, MCP servers | `retrieve_tools()` in `tools.py` |
| **Capabilities** | `capability_embeddings` | Capability registry | `retrieve_capabilities()` in `capability_rag.py` |

---

## Indexing

### Chunking

Two chunking strategies in `app/agent/chunking.py`:

**Markdown-aware chunking** (`chunk_markdown`) — Used for skills and `.md` files:

- Splits at header boundaries, preserving hierarchy
- Builds a `context_prefix` from ancestor headers (e.g. `"# Doc > ## Section > ### Sub"`)
- Preamble text before the first header becomes its own chunk
- Oversized sections are split at paragraph boundaries
- Default max chunk: 1500 chars

**Sliding window** (`chunk_sliding_window`) — Used for code and unstructured text:

- Boundary-aware: snaps to paragraph (`\n\n`) or sentence (`. `) boundaries
- Falls back to hard cut if no boundary within 20% of window size
- Overlap start adjusted to nearest paragraph boundary
- Default: 1500-char window, 200-char overlap

**Language-specific strategies** in `fs_indexer.py`:

| Extension | Strategy |
|-----------|----------|
| `.py` | AST-based: one chunk per top-level function/class. Oversized items sub-chunked. Syntax errors fall back to sliding window. |
| `.md` | Hierarchy-aware markdown chunker |
| `.json`, `.yaml` | Split by top-level keys if large |
| `.ts`, `.tsx`, `.js`, `.jsx` | Tree-sitter (if available) or regex-based symbol extraction |
| `.go`, `.rs` | Regex-based function detection |
| Everything else | Sliding window |

Each chunk produces a `ChunkResult` with `content`, `context_prefix`, `language`, `symbol`, `start_line`, `end_line`.

**Versioning**: `CHUNKING_VERSION` (currently `"v2"`) is stored in metadata. Bumping it forces re-embedding of all chunks.

### Contextual Retrieval

*Optional, opt-in via `CONTEXTUAL_RETRIEVAL_ENABLED`.*

Before embedding, each chunk is sent to a cheap LLM which generates a 1-2 sentence semantic description situating the chunk within its parent document. This description is prepended to the embedding text, improving retrieval recall by 35-67% (per [Anthropic's research](https://www.anthropic.com/news/contextual-retrieval)).

**Flow** (`app/agent/contextual_retrieval.py`):

1. Truncate parent document to 4000 chars for the prompt
2. LLM generates description starting with "This chunk..." — topic, role, key entities
3. Result cached in-memory LRU (10K entries max, keyed by `(content_hash, chunk_index)`)
4. Graceful degradation: LLM failure returns `None`, chunk is embedded without description

**Embedding text composition** (`build_embed_text`):

```
context_prefix        ← structural hierarchy ("# Doc > ## Section")
contextual_description  ← LLM-generated semantic description
content               ← the actual chunk text
```

All layers joined with `\n\n`. Missing layers are skipped.

When enabled, the effective chunking version becomes `"{CHUNKING_VERSION}+cr"`, forcing re-embedding of existing chunks. Descriptions are stored in `metadata_.contextual_description` and warmed into cache on startup.

**Configuration**:

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXTUAL_RETRIEVAL_ENABLED` | `false` | Master switch |
| `CONTEXTUAL_RETRIEVAL_MODEL` | `""` | LLM model (empty = `COMPACTION_MODEL`) |
| `CONTEXTUAL_RETRIEVAL_MAX_TOKENS` | `150` | Max output tokens per description |
| `CONTEXTUAL_RETRIEVAL_BATCH_SIZE` | `5` | Concurrent LLM calls during indexing |
| `CONTEXTUAL_RETRIEVAL_PROVIDER_ID` | `""` | Provider (empty = default) |

### Embedding

`app/agent/embeddings.py` handles all embedding operations.

- **Default model**: `local/BAAI/bge-small-en-v1.5` (ONNX via fastembed, zero API cost)
- **API models**: Any OpenAI-compatible endpoint (prefix-less model names route to `LLM_BASE_URL`)
- **Dimensions**: All vectors are 1536-dimensional (`EMBEDDING_DIMENSIONS`). API models use the `dimensions=` parameter (Matryoshka truncation). Local models are zero-padded.
- **Truncation**: Input text capped at 16,000 chars before embedding
- **Per-request cache**: `(model, text) → vector` cache via `contextvars.ContextVar`. Cleared per request. Avoids redundant API calls when skills, tools, and filesystem all embed the same query.
- **Batch embedding**: `embed_batch()` for throughput during indexing

### Skill Indexing

`app/agent/skills.py` — triggered at startup and after admin edits.

1. Parse frontmatter (YAML between `---` markers) for display name
2. Chunk markdown body with hierarchy preservation
3. Generate contextual descriptions (if enabled)
4. Compose embedding text: `context_prefix + description + content`
5. Batch embed all chunks
6. Store in `documents` table with `source = "skill:{skill_id}"`
7. Backfill tsvector for BM25 (PostgreSQL only)

**Change detection**: SHA256 content hash + chunking version stored in `metadata_`. Unchanged skills are skipped.

### Filesystem Indexing

`app/agent/fs_indexer.py` — triggered at startup, on file changes (watcher), and periodically.

1. Discover files matching glob patterns in configured roots
2. Skip binary extensions, ignored dirs (`.git`, `node_modules`), auto-injected workspace files
3. Chunk each file using language-specific strategy
4. Generate contextual descriptions (if enabled)
5. Batch embed (50 chunks per batch, 8 concurrent files via semaphore)
6. Store in `filesystem_chunks` table with scope metadata (`bot_id`, `client_id`, `root`)
7. Backfill tsvector for BM25
8. Clean up stale entries for removed files

**Cooldown**: Minimum `FS_INDEX_COOLDOWN_SECONDS` (300s) between full re-indexes per root. Bypassable with `force=True`.

**Segments**: Workspace directories can define segments with per-segment embedding models. Each segment may be gated to specific channels.

### Tool Indexing

`app/agent/tools.py` — triggered at startup.

1. Build embed text from tool schema: name, server, description, parameter types/descriptions
2. SHA256 content hash for change detection
3. Single embed per tool (not chunked — tool schemas are small)
4. Upsert into `tool_embeddings` with `tool_key = "local:{name}"` or `"mcp:{server}:{name}"`

---

## Retrieval

### Vector Search

All vector queries use **halfvec-accelerated cosine distance** (`app/agent/vector_ops.py`):

```sql
(embedding::halfvec(1536)) <=> (query::halfvec(1536))
```

pgvector indexes store 16-bit float entries (50% storage reduction) while column data stays float32. Falls back to regular `cosine_distance()` on SQLite (tests).

### Hybrid Search (BM25 + Vector)

When `HYBRID_SEARCH_ENABLED` (default on PostgreSQL), both vector similarity and BM25 keyword search run in parallel:

- **Vector search**: Cosine distance on embedding column, fetch `top_k * 2` results
- **BM25 search**: `ts_rank` on `tsv` tsvector column, fetch `top_k * 2` results
- **Fusion**: Reciprocal Rank Fusion combines both ranked lists

**RRF formula** (`app/agent/hybrid_search.py`):

```
score(d) = sum(1 / (k + rank_i(d)))  for each list i containing d
```

Default `k = 60` (configurable: `HYBRID_SEARCH_RRF_K`). Higher k gives more weight to top results.

**Threshold logic** (after fusion):

- Keep if vector similarity >= threshold
- Keep if BM25-only match (keyword hit with no vector match)
- Keep if both match but vector similarity is below threshold (BM25 boosts borderline results)

### Skill Retrieval

**Index retrieval** — `retrieve_skill_index()` in `app/agent/rag.py`:

1. Embed query (reuses per-request cache — free if tool retrieval already ran)
2. Vector search on `documents` table (filtered by enrolled skill sources)
3. BM25 keyword search (if hybrid enabled) — catches keyword matches missed by vector
4. Group by skill_id, keep best similarity per skill
5. Threshold filter (default: 0.35)
6. Return top `SKILL_INDEX_RETRIEVAL_TOP_K` (default: 8) distinct skill IDs

Used for on-demand skills. Instead of dumping all enrolled skills as a flat index every turn, only the most relevant skills appear. The LLM calls `get_skill()` to load full content, or `get_skill_list()` to browse all available skills when the index doesn't show what it needs. 5-minute TTL cache.

### Filesystem Retrieval

`retrieve_filesystem_context()` in `app/agent/fs_indexer.py`:

1. Determine embedding model(s) from segments
2. Embed query (once per unique model)
3. Vector search on `filesystem_chunks` (scoped by `bot_id`, `client_id`, `root`, channel gating)
4. BM25 search (if hybrid enabled)
5. RRF fusion
6. Format results grouped by file path with headers, symbol info, and line numbers
7. Return top `FS_INDEX_TOP_K` (default: 8) chunks

### Tool Retrieval

`retrieve_tools()` in `app/agent/tools.py`:

1. Check 5-minute TTL cache (keyed by query + tool scope)
2. Embed query
3. Vector search on `tool_embeddings` (filtered by bot's local tools + MCP servers)
4. BM25 full-text search on `embed_text` column (if `HYBRID_SEARCH_ENABLED`, PostgreSQL only)
5. RRF fusion of vector + BM25 results (same `reciprocal_rank_fusion()` as skills)
6. Threshold filter — BM25-matched tools included even below vector threshold (keyword relevance rescues them)
7. Return top `TOOL_RETRIEVAL_TOP_K` (default: 10) tool schemas

**GIN index**: `ix_tool_embeddings_fts` on `to_tsvector('english', embed_text)` (migration 168)

---

## Re-ranking

*Optional, opt-in via `RAG_RERANK_ENABLED`.*

After context assembly, a post-processing step scores all RAG-injected chunks and removes low-relevance ones (`app/services/reranking.py`).

**Backends**:

| Backend | Speed | Cost | How it works |
|---------|-------|------|-------------|
| **Cross-encoder** (default) | ~120ms | Zero | ONNX model scores `(query, chunk)` pairs locally |
| **LLM** | ~2s | API cost | LLM returns JSON `{"keep": [indices]}` |

**Flow**:

1. Identify RAG system messages (skills, filesystem, conversation history)
2. Split at `\n\n---\n\n` separators to extract individual chunks
3. Skip if total chars below `RAG_RERANK_THRESHOLD_CHARS` (default: 5000)
4. Score all chunks via selected backend
5. Keep chunks above score threshold, cap at `RAG_RERANK_MAX_CHUNKS` (default: 20)
6. Rebuild messages, removing empty ones

**Configuration**:

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_RERANK_ENABLED` | `false` | Master switch |
| `RAG_RERANK_BACKEND` | `"cross-encoder"` | `"cross-encoder"` or `"llm"` |
| `RAG_RERANK_MODEL` | `""` | LLM backend model (empty = `COMPACTION_MODEL`) |
| `RAG_RERANK_THRESHOLD_CHARS` | `5000` | Min total chars to trigger reranking |
| `RAG_RERANK_MAX_CHUNKS` | `20` | Max chunks to keep after reranking |
| `RAG_RERANK_MAX_TOKENS` | `1000` | Max output tokens for LLM backend |
| `RAG_RERANK_SCORE_THRESHOLD` | `0.01` | Cross-encoder min score (0-1) |
| `RAG_RERANK_CROSS_ENCODER_MODEL` | `"Xenova/ms-marco-MiniLM-L-6-v2"` | ONNX reranker model |

---

## Context Injection

`assemble_context()` in `app/agent/context_assembly.py` orchestrates how retrieved content enters the LLM's context window. RAG-related steps (simplified from the full 15-step pipeline):

1. **Skills injection** — Enrolled skills are surfaced via `retrieve_skill_index()` as a semantically filtered index (top-K relevant skill IDs, not all enrolled). The bot fetches full content on demand via `get_skill()`, browses all available via `get_skill_list()`, or — for `@skill:name` tags — pulls full chunks via `fetch_skill_chunks_by_id()`.
2. **Workspace filesystem RAG** — Top-K chunks from `retrieve_filesystem_context()`, injected as a system message with file headers.
3. **Tool retrieval** — Top-K tools from `retrieve_tools()`, passed in the `tools` parameter of the LLM call.

Each injection step yields streaming events (e.g. `"skill_rag"`, `"filesystem_context"`, `"tool_retrieval"`) for observability.

---

## LLM Call Infrastructure

### Retry Engine

`app/agent/llm.py` provides a unified retry + fallback system:

**Backoff**: Full jitter exponential — `uniform(0, min(cap, base * 2^attempt))`. Prevents thundering herd.

| Error type | Retryable | Base wait | Behavior |
|-----------|-----------|-----------|----------|
| `RateLimitError` (429) | Yes | 90s | Exponential backoff with jitter |
| `APITimeoutError` | Yes | 2s | Exponential backoff with jitter |
| `APIConnectionError` | Yes | 2s | Exponential backoff with jitter |
| `InternalServerError` (transient) | Yes | 2s | Exponential backoff with jitter |
| `InternalServerError` (non-transient) | No | — | Skip to fallback immediately |
| `BadRequestError` (tools not supported) | Once | — | Retry without tools, then fallback |
| Other errors | No | — | Propagate immediately |

### Fallback Chain

When a model exhausts retries, `_run_with_fallback_chain` tries alternatives:

1. **Circuit breaker check** — If model is in cooldown (recently failed), skip directly to its recorded fallback
2. **Primary model** — Full retry loop
3. **Per-bot fallbacks** — From bot config or channel override (`fallback_models`)
4. **Global fallbacks** — From server settings (`get_global_fallback_models()`)
5. Deduplication: models already tried are skipped

On successful fallback: primary model gets a cooldown entry (`LLM_FALLBACK_COOLDOWN_SECONDS`, default 300s).

---

## Database Schema

### `documents` (skills, knowledge)

| Column | Type | Description |
|--------|------|-------------|
| `content` | text | Full chunk text with source label |
| `embedding` | vector(1536) | Embedding vector |
| `source` | text | `"skill:{id}"` or `"knowledge:{id}"` |
| `metadata_` | jsonb | `content_hash`, `chunking_version`, `chunk_index`, `contextual_description` |
| `tsv` | tsvector | BM25 search index |

### `filesystem_chunks` (workspace files)

| Column | Type | Description |
|--------|------|-------------|
| `root` | text | Root directory path |
| `file_path` | text | Relative file path |
| `content` | text | Chunk text with file header |
| `embedding` | vector(1536) | Embedding vector |
| `content_hash` | text | SHA256 of file content |
| `chunk_index` | int | Position in file |
| `language` | text | `"python"`, `"markdown"`, etc. |
| `symbol` | text | Function/class name |
| `start_line` / `end_line` | int | Source location |
| `embedding_model` | text | Model used for this chunk |
| `metadata_` | jsonb | `contextual_description`, etc. |
| `tsv` | tsvector | BM25 search index |
| `bot_id` / `client_id` | text | Scope (NULL = cross-bot) |

### `tool_embeddings` (tool schemas)

| Column | Type | Description |
|--------|------|-------------|
| `tool_key` | text | `"local:{name}"` or `"mcp:{server}:{name}"` |
| `embedding` | vector(1536) | Embedding vector |
| `embed_text` | text | Concatenated tool description (name + params + description) |
| `schema_` | jsonb | Full OpenAI function schema |
| `content_hash` | text | SHA256 of embed text |

**FTS index**: `ix_tool_embeddings_fts` — GIN index on `to_tsvector('english', embed_text)` for BM25 hybrid search.

### Vector Indexes

All tables use HNSW indexes with halfvec casting (pgvector 0.7+):

```sql
CREATE INDEX ix_{table}_embedding ON {table}
  USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 64)
```

Index entries are 16-bit float (50% storage reduction). Column data stays float32.

---

## Configuration Reference

### Embedding

| Setting | Default | Description |
|---------|---------|-------------|
| `EMBEDDING_MODEL` | `"local/BAAI/bge-small-en-v1.5"` | `"local/"` prefix = fastembed ONNX; plain = OpenAI-compatible API |
| `EMBEDDING_DIMENSIONS` | `1536` | Must match DB vector columns. Do not change without re-creating indexes. |

### Skills RAG

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_TOP_K` | `5` | BM25 fetch depth used by `_bm25_search()` (boosts skill index hits) |
| `SKILL_INDEX_RETRIEVAL_TOP_K` | `8` | Max skills in on-demand index per turn |
| `SKILL_INDEX_RETRIEVAL_THRESHOLD` | `0.35` | Min cosine similarity for index retrieval |

### Filesystem RAG

| Setting | Default | Description |
|---------|---------|-------------|
| `FS_INDEX_TOP_K` | `8` | Max filesystem chunks returned |
| `FS_INDEX_SIMILARITY_THRESHOLD` | `0.30` | Min cosine similarity |
| `FS_INDEX_CHUNK_WINDOW` | `1500` | Sliding window size (chars) |
| `FS_INDEX_CHUNK_OVERLAP` | `200` | Window overlap (chars) |
| `FS_INDEX_COOLDOWN_SECONDS` | `300` | Min seconds between full re-indexes |
| `FS_INDEX_MAX_FILE_BYTES` | `500000` | Skip files larger than this |
| `FS_INDEX_CONCURRENCY` | `8` | Concurrent file embeddings |
| `FS_INDEX_PERIODIC_MINUTES` | `30` | Periodic re-verify interval (0 = disabled); catches watcher crashes |

### Tool RAG

| Setting | Default | Description |
|---------|---------|-------------|
| `TOOL_RETRIEVAL_THRESHOLD` | `0.35` | Min cosine similarity |
| `TOOL_RETRIEVAL_TOP_K` | `10` | Max tools returned |

### Hybrid Search

| Setting | Default | Description |
|---------|---------|-------------|
| `HYBRID_SEARCH_ENABLED` | `true` | Enable BM25 + RRF fusion |
| `HYBRID_SEARCH_RRF_K` | `60` | RRF smoothing parameter |

### LLM Retry

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_MAX_RETRIES` | `3` | Retries after first failure |
| `LLM_RETRY_INITIAL_WAIT` | `2.0` | Base backoff (seconds) |
| `LLM_RATE_LIMIT_INITIAL_WAIT` | `90` | Rate-limit base backoff (seconds) |
| `LLM_FALLBACK_MODEL` | `""` | Global fallback model |
| `LLM_FALLBACK_COOLDOWN_SECONDS` | `300` | Circuit breaker duration |

---

## Key Files

| File | Role |
|------|------|
| `app/agent/chunking.py` | Chunking strategies (markdown, sliding window) |
| `app/agent/embeddings.py` | Embedding model calls, caching, batching |
| `app/agent/contextual_retrieval.py` | LLM-generated chunk descriptions |
| `app/agent/rag.py` | Skill retrieval (vector + hybrid search) |
| `app/agent/fs_indexer.py` | Filesystem indexing + retrieval |
| `app/agent/tools.py` | Tool indexing + retrieval |
| `app/agent/vector_ops.py` | halfvec cosine distance utility |
| `app/agent/hybrid_search.py` | Reciprocal Rank Fusion |
| `app/services/reranking.py` | Post-retrieval cross-encoder/LLM reranking |
| `app/agent/context_assembly.py` | Orchestrates RAG injection into LLM context |
| `app/agent/llm.py` | Retry engine, fallback chain, circuit breaker |
