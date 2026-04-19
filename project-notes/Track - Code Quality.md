---
tags: [agent-server, track, code-quality]
status: active
created: 2026-04-09
---
# Track — Code Quality & Refactoring

Systematic audit of core agent-server files. 156 files, ~50K lines across `app/agent/`, `app/services/`, `app/tools/`. Findings organized by priority.

## Actual Bugs

### ~~knowledge.py:266 — `append_to_knowledge` doesn't re-embed~~ SKIPPED (knowledge system being removed)

### knowledge.py:266 — `append_to_knowledge` doesn't re-embed
After `row.content += content`, the embedding is NOT updated. Appended content is invisible to RAG. Compare `edit_knowledge` (line 323) which correctly re-embeds.
- **Impact**: Silent data corruption — content exists but can't be found via search
- **Fix**: Add `row.embedding = await _embed(row.content)` after append

### ~~file_sync.py:828-829 — Watch handler drops skill metadata~~ FIXED April 9
Extracted `_extract_skill_metadata()` helper used by both `sync_all_files` and `sync_changed_file`.

### ~~tasks.py:375,915 — `UnboundLocalError` in except handlers~~ FIXED April 9
`_task_timeout` initialized before try block. `_exec_timeout` was already safe (assigned before try).

### ~~tasks.py:787 — Stale `task` object after DB updates~~ FIXED April 9
`task.correlation_id = correlation_id` now reflects back to in-memory object.

### ~~carapaces.py:268 — No type-check on YAML parse result~~ FIXED April 9
Added `isinstance(data, dict)` check after `yaml.safe_load()`.

### ~~rag.py:192-195 — BM25-only matches bypass similarity threshold~~ FIXED April 9
BM25-only matches now capped at `RAG_TOP_K // 2` to prevent unbounded keyword injection.

## God Functions (structural, address incrementally)

These functions are too large to test, review, or safely modify. Each handles 5-20 distinct concerns inline.

| File | Function | Lines | Concern count |
|------|----------|-------|---------------|
| context_assembly.py | `assemble_context()` | ~~1400~~ **~990** | ~20 pipeline stages (5 extracted so far) |
| loop.py | `run_agent_tool_loop()` | ~~960~~ **~1030** (file: **1684**) | LLM call, streaming, tool dispatch, approval, cycle detection, etc. — **re-bloated**, plan parked |
| file_sync.py | `sync_all_files()` | ~518 | 5 resource types × collect-upsert-orphan-delete |
| tasks.py | `run_task()` | ~490 | session, config, prompt, agent run, persistence, dispatch, follow-up |
| tool_dispatch.py | `dispatch_tool_call()` | ~385 | auth, policy, approval, routing, recording, redaction, summarization |
| compaction.py | `run_compaction_stream()` | ~342 | flush, watermark, section, summary, persistence, trace |
| bots.py | `_bot_row_to_config()` | ~180 | manual field-by-field mapping |
| sessions.py | `persist_turn()` | ~150 | filtering, metadata, delegation, heartbeat, DB, attachments |

**Approach**: Extract each concern into a named sub-function. For `assemble_context`, each `# ---` section becomes its own async function operating on a shared pipeline state object.

### loop.py refactor — parked plan (April 11)

`app/agent/loop.py` is back to **1684 lines** despite past splits. Confirmed nothing in `app/agent/` is already-extracted-but-unused — every helper module is imported. Pure option-B split needed.

**Plan:** [/home/mtoth/.claude/plans/fuzzy-growing-hamming.md](file:///home/mtoth/.claude/plans/fuzzy-growing-hamming.md)

**Why parked:** Lots of pending in-flight changes (`app/domain/`, `app/integrations/`, channel renderer work) on the development branch. Re-evaluate the plan against those changes before executing — the dispatch DRY (Step 5) in particular may interact with the new domain/renderer layer.

**Plan summary (6 commits, behavior-preserving, target ~400 lines):**
1. `loop_helpers.py` — pure helpers (`_sanitize_*`, `_extract_usage_extras`, `_finalize_response`, `_record_fallback_event`, etc.). Drops ~280 lines.
2. `loop_nudges.py` — correction / repeated-lookup / learning skill nudges (~50 lines).
3. `loop_iteration.py` — per-iteration pre-work: pruning, breakdown trace, rate limit (~80 lines).
4. `loop_empty_response.py` — silent-vs-forced-retry block (~100 lines).
5. `loop_dispatch.py` — **unify parallel + sequential tool dispatch** (~280 lines, ~140 of which are pure duplication today). Highest-leverage step. Highest risk.
6. `loop_post_loop.py` — cycle/max-iters forced final response (~110 lines).

`run_stream` body stays as-is — already cleanly factored via `assemble_context`. Backwards compat handled by re-exports from `loop.py` so test imports (`_CORRECTION_RE`, `_sanitize_messages`, `_synthesize_empty_response_fallback`, etc.) keep working untouched.

**Critical regression test:** `tests/unit/test_parallel_tool_execution.py` (~14 cases) is the canary for Step 5. If it stays green, the dispatch DRY is correct.

**context_assembly.py progress (April 9)**: Extracted 5 functions so far:
- `_merge_skills()` — shared skill dedup helper (eliminated 3x duplication)
- `_inject_memory_scheme()` — MEMORY.md, daily logs, reference index
- `_inject_channel_workspace()` — workspace files, schema, index segments, plan stall
- `_inject_conversation_sections()` — structured mode retrieval + file mode section index
- `_inject_workspace_rag()` — workspace filesystem RAG (current + legacy)
- Also fixed: redundant channel re-query in conversation sections (used `_ch_row` instead)
- Remaining: tag resolution, skill injection, multi-bot awareness, tool retrieval, capability discovery

## Major Duplication (collapse into shared helpers)

### loop.py:858-1176 — Parallel vs sequential tool dispatch
~320 lines of near-identical logic across the parallel branch (858–1038) and sequential branch (1040–1176). Approval gate handling (~60 lines each), post-dispatch bookkeeping, `_tool_msg` assembly, `after_tool_call` hook firing — all copy-pasted with trivial variable name differences.
- **Fix**: Step 5 of the parked refactor plan above. Extract `dispatch_iteration_tool_calls()` + shared `_process_tool_call_result()`.

### loop.py:894-997, 1065-1138 — `dispatch_tool_call` invoked 4x with identical 16+ kwargs
Any parameter addition requires updating all four call sites. A `SummarizeSettings` dataclass would collapse 5 of those kwargs alone.
- **Fix**: Bundle into kwargs dict + `SummarizeSettings`. Covered by Step 5 above.

### llm.py:1071-1226 — Streaming vs non-streaming factory closures
6 near-identical closures (`_make_attempt`, `_make_no_tools`, `_make_no_images` × 2). Same kwargs construction repeated 6 times.
- **Fix**: Unify into single factory with `stream: bool` parameter

### compaction.py:830-1474 — Stream vs forced compaction
~250 lines of duplicated pipeline (watermark, section, summary, session update).
- **Fix**: Extract shared compaction core into private helper

### file_sync.py:241-1041 — Full sync vs watch handler
Per-type upsert logic duplicated with inconsistencies (the skill metadata bug above).
- **Fix**: Extract per-type upsert functions called by both paths

### sandbox.py:319-844 — `exec` vs `exec_bot_local`
Secret injection (~15 lines), API key injection, subprocess creation, output truncation — all duplicated.
- **Fix**: Extract `_build_exec_env()` and `_run_subprocess()`

### knowledge.py:240-370 — Dual-lookup pattern 5x
Same ~20-line "try legacy lookup, then fallback to knowledge_access" pattern copy-pasted.
- **Fix**: Extract `_find_knowledge_by_name()` helper

### tasks.py:376-981 — "Mark task failed" pattern 4x
`fetch task → set failed → commit → fire hook → dispatch error` repeated with trivial variations.
- **Fix**: Extract `_fail_task()` helper

### ~~context_assembly.py:500-648 — Skill merge pattern 5x~~ FIXED April 9
Extracted `_merge_skills(bot, new_skill_ids, disabled_ids)` helper. Three enrollment blocks now use it.

## Concurrency & Resource Risks

### tasks.py:1227 — No concurrency limit on task spawning
`asyncio.create_task(run_task(task))` in a loop, up to 20 concurrent tasks. Can exhaust API rate limits, DB pool, or memory.
- **Fix**: `asyncio.Semaphore` to cap concurrent execution

### bots.py:601 — Registry race on reload
`_registry.clear()` creates a window where all bots appear missing. Concurrent `get_bot()` calls during reload will 404.
- **Fix**: Build new registry in local var, then swap atomically

### Multiple files — Fire-and-forget `asyncio.create_task`
~25 total across context_assembly (9), compaction (7), loop, tasks. Unhandled exceptions silently lost. GC may cancel tasks before completion.
- **Fix**: Store references, add done-callback for error logging

### llm.py:434 — Module-level mutable `_model_cooldowns` without lock
Check-then-mutate pattern in async code. Not atomic.
- **Fix**: `asyncio.Lock` around cooldown mutations

### Multiple files — Module-level TTL caches without async safety
`_bot_skill_cache`, `_core_skill_cache`, `_skill_index_cache`, `_tool_cache` — plain dicts accessed concurrently.
- **Fix**: Extract shared `AsyncTTLCache` utility with lock

## Bad Practices (clean up opportunistically)

### Silent exception swallowing
Bare `except Exception: pass` in: context_assembly (4 sites), sandbox (4 sites), loop (3 sites), knowledge (1 site), bots (1 site). Hides misconfigurations and real bugs.
- **Fix**: At minimum log with `exc_info=True`

### bots.py:745 — `get_bot()` raises `HTTPException` from non-HTTP contexts
Background tasks call `get_bot()` and get meaningless `status_code=404`.
- **Fix**: Raise domain exception, let HTTP layer convert

### bots.py:401-468 — Excessive `getattr(row, ..., default)` as migration crutch
~15 fields use defensive getattr instead of direct access. Hides missing column bugs.
- **Fix**: Ensure columns exist via migrations, use direct access

### Inline imports proliferation
~60+ inline imports across audited files. Some are circular-import guards (justified), many are not (`import time`, `import uuid`, `import re`).
- **Fix**: Move non-circular imports to module top. Document circular ones.

### Inconsistent time functions
`time.time()` vs `time.monotonic()` for TTL caches. `time.time()` is subject to clock drift.
- **Fix**: Use `time.monotonic()` consistently for TTL tracking

### docker_stacks.py:654 — No path traversal check in `_materialize_file`
`rel_path` is joined without validation. Currently only called with trusted input.
- **Fix**: Assert resolved path is under stack directory

## Low Priority (cosmetic, minor)

- Leading underscore convention overuse on local variables (context_assembly, loop)
- Magic numbers for truncation lengths (`[:4000]`, `[:500]`, `[:200]`) — define constants
- Duplicate `ExecResult` dataclass in sandbox.py and docker_stacks.py
- `effective_model` variable shadowing in loop.py (assigned to `model`, never diverges)
- `_est_msg_chars` defined inside loop body but has no closure dependency
- Stale docstrings (skills.py:22 says "from DB" but only reads filesystem)
- Redundant `elif not x:` that should be `else:` (file_sync.py:353)
- `asyncio.sleep(0)` without explanation (tasks.py:332,421)

## Approach

This is a pre-freeze cleanup track. Work incrementally:
1. **Bugs first** — the 6 actual bugs above are small, targeted fixes
2. **Duplication** — each duplication item is independently extractable
3. **God functions** — tackle one at a time, starting with the highest-churn files
4. **Concurrency** — the task spawning limit is the most impactful single fix

Don't refactor for refactoring's sake. Each change should make the code more bug-resistant or easier to work in. Test coverage should exist before splitting god functions.
