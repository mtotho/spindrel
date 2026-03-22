---
status: draft
last_updated: 2026-03-22
owner: mtoth
summary: >
  Decompose app/agent/loop.py (1228 lines) into focused modules.
  No behavior changes — pure structural refactor. All existing tests must pass.
---

# Loop Refactor Plan

## Current Structure Analysis

### What lives in loop.py today (1228 lines)

loop.py contains **five distinct responsibilities**:

1. **LLM call infrastructure** (lines 76–141, ~65 lines)
   - `_llm_call()` — retry with exponential backoff on rate limit / timeout
   - `_summarize_tool_result()` — summarize large tool outputs via separate LLM call
   - Trace/logging helpers: `_trace()`, `_CLASSIFY_SYS_MSG()`, `_SYS_MSG_PREFIXES`

2. **Tool dispatch** (lines 354–539, ~185 lines inside `run_agent_tool_loop`)
   - The `for tc in msg.tool_calls:` block that routes to client tools, local tools
     (memory/persona/knowledge special-cases), MCP tools, or unknown-tool error
   - Tool call recording (`_record_tool_call`)
   - Tool result summarization decision logic
   - Client action extraction from tool results
   - Memory-specific event enrichment (`search_memories` count/preview)

3. **Agent tool loop** (`run_agent_tool_loop`, lines 150–609, ~460 lines)
   - The core iteration loop: LLM call → check for tool calls → dispatch → repeat
   - Context breakdown tracing per iteration
   - TPM rate limit check + wait
   - Empty-response forced-retry logic
   - Native audio transcript extraction
   - Max-iterations guard with forced final response
   - Compaction tag propagation

4. **Context assembly / RAG injection** (`run_stream`, lines 612–1177, ~565 lines)
   - Datetime injection
   - Tag resolution (`@skill:`, `@knowledge:`, `@tool:`, `@bot:`)
   - Skill injection (pinned, RAG, on-demand index)
   - Delegate bot index injection
   - Memory retrieval + injection
   - Pinned knowledge + RAG knowledge injection
   - Active plans injection
   - Filesystem index retrieval + injection
   - Tool retrieval (tool RAG) + unretrieved tool index
   - Audio message construction
   - User message construction (text + attachments)
   - Context injection summary trace
   - Delegation post buffering (outermost vs. nested stream)

5. **Non-streaming wrapper** (`run`, lines 1180–1228, ~48 lines)
   - Drains `run_stream()`, collects response/transcript/client_actions
   - Handles `delegation_post` events in non-streaming context

### What is already correctly extracted

| Module | Responsibility | Status |
|--------|---------------|--------|
| `app/agent/memory.py` | Memory CRUD, embedding, scoped retrieval | Clean |
| `app/agent/persona.py` | Persona CRUD | Clean |
| `app/agent/recording.py` | Fire-and-forget tool call / trace event recording | Clean |
| `app/agent/tasks.py` | Task worker: polling, running scheduled tasks, recurrence | Clean |
| `app/agent/context.py` | ContextVar management for request-scoped state | Clean |
| `app/agent/message_utils.py` | Pure message transforms (audio, transcript, client actions, schema merge) | Clean |
| `app/agent/rag.py` | Skill chunk retrieval | Clean |
| `app/agent/tags.py` | @-mention tag resolution | Clean |
| `app/agent/tools.py` | Tool embedding + retrieval (tool RAG) | Clean |
| `app/agent/knowledge.py` | Knowledge CRUD + retrieval | Clean |
| `app/agent/pending.py` | Client tool pending request/response futures | Clean |
| `app/services/compaction.py` | Context compaction (memory phase + summary) | Clean, imports `run_agent_tool_loop` |

### Biggest pain points

1. **`run_stream()` is ~565 lines** of sequential context assembly. Each RAG source
   (skills, memory, knowledge, plans, filesystem, tools) follows the same pattern
   (retrieve → inject → yield event → trace) but is inlined. Hard to understand,
   test, or modify any single source without reading the whole function.

2. **Tool dispatch inside `run_agent_tool_loop`** mixes routing logic (which tool
   type?) with special-case handling (memory tools, persona tools, knowledge tools)
   and recording/summarization. The `for tc in msg.tool_calls:` block is ~185 lines.

3. **`run_agent_tool_loop` is ~460 lines** combining the iteration control flow with
   tool dispatch, tracing, audio handling, and summarization config. Testing requires
   mocking 10+ imports.

4. **Circular import risk**: `app/services/compaction.py` imports `run_agent_tool_loop`
   from loop.py. Any extraction must preserve this import path or update compaction.

---

## Proposed Module Breakdown

### New files to create

#### 1. `app/agent/llm.py` — LLM call infrastructure (~80 lines)

Move from loop.py:
- `_llm_call()` — the retry/backoff wrapper
- `_summarize_tool_result()` — tool result summarization

These are pure infrastructure with no dependency on bot config or agent state beyond
the model name and provider ID.

#### 2. `app/agent/tool_dispatch.py` — Tool call routing + execution (~220 lines)

Move from loop.py (currently inlined in `run_agent_tool_loop`):
- Tool dispatch routing: the `if is_client_tool / elif is_local_tool / elif is_mcp_tool / else` block
- Memory/persona/knowledge tool special-case routing
- Tool call recording fire-and-forget
- Tool result client_action extraction
- Tool result summarization decision + invocation
- Tool result event construction (including memory-specific enrichment)

Public API: `async def dispatch_tool_call(name, args, bot, session_id, client_id, ...) -> ToolCallResult` where `ToolCallResult` is a small dataclass holding `result`, `result_for_llm`, `event`, `duration_ms`, `was_summarized`, `embedded_client_action`.

#### 3. `app/agent/context_assembly.py` — RAG context injection (~350 lines)

Move from `run_stream()`:
- All context injection blocks (datetime, tags, skills, delegates, memory, knowledge,
  plans, filesystem, tool retrieval, audio/user message, injection summary trace)
- Each block becomes a small async function returning `(messages_to_append, events_to_yield)`
  or similar, composed by a top-level `async def assemble_context(...)` generator.

This is the largest extraction and the highest value — it turns the monolithic
`run_stream` into a clear pipeline.

#### 4. `app/agent/tracing.py` — Trace helpers (~30 lines)

Move from loop.py:
- `_SYS_MSG_PREFIXES` constant
- `_CLASSIFY_SYS_MSG()` function
- `_trace()` function

These are already tested in `tests/unit/test_loop_helpers.py` which imports them from
`app.agent.loop`. Small module, easy re-export.

### What stays in loop.py after refactor (~250–300 lines)

- `RunResult` dataclass
- `run_agent_tool_loop()` — the iteration skeleton (now ~120 lines):
  - For loop, LLM call, check tool_calls, delegate to `dispatch_tool_call()`,
    empty-response retry, max-iterations guard, transcript handling
- `run_stream()` — now thin (~80 lines):
  - Sets agent context, calls `assemble_context()`, delegates to `run_agent_tool_loop()`,
    handles delegation post buffering
- `run()` — unchanged non-streaming wrapper (~48 lines)

### Module dependency graph (post-refactor)

```
loop.py
  ├── app.agent.llm          (new: _llm_call, _summarize_tool_result)
  ├── app.agent.tool_dispatch (new: dispatch_tool_call)
  ├── app.agent.context_assembly (new: assemble_context)
  ├── app.agent.tracing       (new: _trace, _CLASSIFY_SYS_MSG)
  ├── app.agent.context        (existing: set_agent_context)
  ├── app.agent.message_utils  (existing: audio/transcript helpers)
  └── app.agent.recording      (existing: _record_trace_event)

context_assembly.py
  ├── app.agent.memory         (existing)
  ├── app.agent.knowledge      (existing)
  ├── app.agent.rag            (existing)
  ├── app.agent.tags           (existing)
  ├── app.agent.tools          (existing)
  ├── app.agent.recording      (existing)
  └── app.agent.message_utils  (existing)

tool_dispatch.py
  ├── app.agent.llm            (new: _summarize_tool_result)
  ├── app.agent.recording      (existing)
  ├── app.agent.pending        (existing)
  ├── app.tools.registry       (existing)
  ├── app.tools.mcp            (existing)
  ├── app.tools.client_tools   (existing)
  ├── app.tools.local.memory   (existing)
  ├── app.tools.local.persona  (existing)
  └── app.tools.local.knowledge(existing)

app/services/compaction.py
  └── app.agent.loop.run_agent_tool_loop  (unchanged import path)
```

**No circular imports**: all new modules depend only on existing leaf modules or each
other in a DAG (llm ← tool_dispatch ← loop; context_assembly ← loop). `compaction.py`
continues to import from `loop.py`.

---

## Extraction Order

### Phase 1: `app/agent/tracing.py` (lowest risk, zero coupling)

**PR 1**: Extract `_trace()`, `_SYS_MSG_PREFIXES`, `_CLASSIFY_SYS_MSG()`.

- Re-export from `loop.py` for backwards compat: `from app.agent.tracing import _trace, _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES`
- Update `tests/unit/test_loop_helpers.py` imports
- **Risk**: Near zero. Pure functions, no state.
- **Tests**: `test_loop_helpers.py` covers `_CLASSIFY_SYS_MSG`. Re-run, done.

### Phase 2: `app/agent/llm.py` (low risk, well-tested)

**PR 2**: Extract `_llm_call()` and `_summarize_tool_result()`.

- Both are self-contained async functions depending only on `app.services.providers`
  and `app.config.settings`.
- Re-export from `loop.py`: `from app.agent.llm import _llm_call, _summarize_tool_result`
- **Risk**: Low. These are the most-tested functions in loop.py (5 tests for `_llm_call`,
  2 for `_summarize_tool_result`). Existing tests patch `app.agent.loop._llm_call` etc.
  — the re-export ensures patches still work until tests are updated.
- **Tests**: All existing `TestLlmCall` and `TestSummarizeToolResult` tests pass unchanged
  via re-export. Add direct-import tests in a new `tests/unit/test_llm.py` if desired.

### Phase 3: `app/agent/tool_dispatch.py` (medium risk)

**PR 3**: Extract tool dispatch routing from `run_agent_tool_loop`.

- Define `ToolCallResult` dataclass and `dispatch_tool_call()` function.
- The 185-line `for tc in msg.tool_calls:` body becomes a call to `dispatch_tool_call()`.
- `run_agent_tool_loop` still owns the iteration loop, just delegates each tool call.
- **Risk**: Medium. The tool dispatch block accesses several closure variables from
  `run_agent_tool_loop` (summarization config, `embedded_client_actions` list,
  `compaction` flag, iteration counter). These must become explicit parameters.
- **Dependencies**: Requires Phase 2 (imports `_summarize_tool_result` from `llm.py`).
- **Tests**: `TestToolDispatchRouting` tests cover this. They currently test via
  `run_agent_tool_loop` which still calls `dispatch_tool_call` — tests pass unchanged.
  Add focused unit tests for `dispatch_tool_call` directly.

### Phase 4: `app/agent/context_assembly.py` (highest risk, largest change)

**PR 4**: Extract context assembly from `run_stream()`.

- Break each injection block into a named async function:
  - `inject_datetime()` — trivial
  - `inject_tagged_context()` — @-mention tag resolution + skill/knowledge injection
  - `inject_skills()` — pinned, RAG, on-demand
  - `inject_delegate_index()` — sub-agent index
  - `inject_memories()` — memory retrieval
  - `inject_knowledge()` — pinned + RAG knowledge
  - `inject_plans()` — active plans
  - `inject_filesystem_context()` — filesystem index
  - `inject_tools()` — tool RAG + unretrieved index
  - `inject_user_message()` — audio or text+attachments
- Top-level `assemble_context()` calls each in order, yielding events.
- `run_stream()` becomes: set context → `async for event in assemble_context(...)` →
  delegate to `run_agent_tool_loop()` → handle delegation posts.
- **Risk**: Highest. This is the most coupled code. Each inject function needs access
  to `messages`, `bot`, `user_message`, `session_id`, `client_id`, `correlation_id`,
  `channel_id`, and must both append to messages and yield events. A context builder
  pattern (pass a mutable state object) or simple generator approach is needed.
- **Dependencies**: Requires Phases 1–3 to be complete so loop.py is already smaller
  and easier to reason about.
- **Tests**: No existing unit tests directly cover `run_stream()` context assembly
  (integration tests in `tests/integration/test_agent_loop.py` cover it end-to-end).
  This PR should add focused tests for individual inject functions.

---

## Risk Assessment

### Highest-risk areas

1. **Context assembly extraction (Phase 4)**
   - The `messages` list is mutated in-place throughout `run_stream`. Each inject
     function appends system messages. The order matters — LLMs are sensitive to system
     message ordering, and the current order is load-bearing (even if not intentionally).
   - Event yielding order also matters for client UI rendering.
   - **Mitigation**: Keep inject functions in the same order. Use an integration test
     that captures the full message list before/after refactor and asserts equality.

2. **Tool dispatch special-casing (Phase 3)**
   - Memory, persona, and knowledge tools have bespoke routing that depends on
     `session_id`, `client_id`, `bot.memory`, `correlation_id`, `channel_id`. These
     are currently closure variables.
   - **Mitigation**: Pass them as explicit parameters to `dispatch_tool_call()`. Use a
     `ToolDispatchContext` dataclass to bundle them if the parameter list gets too long.

3. **Import path stability**
   - External consumers import: `run`, `run_stream`, `run_agent_tool_loop`, `RunResult`,
     `_llm_call`, `_summarize_tool_result`, `_CLASSIFY_SYS_MSG`, `_SYS_MSG_PREFIXES`.
   - `app/services/compaction.py` imports `run_agent_tool_loop`.
   - `app/agent/tasks.py` imports `run` (deferred, inside function body).
   - `app/routers/chat.py` imports `run`, `run_stream`.
   - `app/services/delegation.py` imports `run_stream` (deferred).
   - Tests import `_llm_call`, `_summarize_tool_result`, `run_agent_tool_loop`,
     `RunResult`, `_CLASSIFY_SYS_MSG`, `_SYS_MSG_PREFIXES`.
   - **Mitigation**: Each extraction PR adds re-exports in `loop.py` so all existing
     import paths continue to work. Re-exports can be removed in a later cleanup PR.

### Circular import risks

- **`compaction.py → loop.py`**: Already exists, unidirectional. Safe as long as
  `loop.py` never imports from `compaction.py` (it doesn't, and this refactor won't
  change that).
- **`tool_dispatch.py → llm.py`**: New, unidirectional. No risk.
- **`context_assembly.py ← loop.py`**: New, unidirectional. `context_assembly` must
  NOT import from `loop.py`. It should import only from leaf modules. Verified by
  the dependency graph above.
- **`tasks.py → loop.py`**: Already exists (deferred import inside function body).
  No change needed.

### Load-bearing non-obvious structures

1. **`_is_outermost_stream` pattern in `run_stream`**: The delegation post buffering
   uses a ContextVar to detect nested vs. outermost `run_stream` calls. This must
   stay in `run_stream()` (not move to `context_assembly`).

2. **`embedded_client_actions` list**: Accumulated during tool dispatch, consumed when
   building the final response event. Must be threaded through or returned from
   `dispatch_tool_call()`.

3. **`transcript_emitted` flag**: Set during tool dispatch (audio transcript from
   tool-call response) and checked again in final response handling. Must be managed
   at the `run_agent_tool_loop` level, not inside `dispatch_tool_call`.

4. **`tools_param` and `tool_choice`**: Computed once before the loop, passed to every
   LLM call and to the max-iterations forced response. Must stay in `run_agent_tool_loop`.

5. **Message list mutation**: `run_stream` appends context to `messages`, then
   `run_agent_tool_loop` appends LLM responses and tool results to the same list.
   The `turn_start` index separates context from conversation. This contract must be
   preserved.

---

## Test Strategy

### Existing test coverage

| Test file | What it covers | Affected phases |
|-----------|---------------|-----------------|
| `tests/unit/test_loop_helpers.py` | `_CLASSIFY_SYS_MSG`, `_SYS_MSG_PREFIXES` | Phase 1 |
| `tests/unit/test_agent_loop.py` | `_llm_call` (5 tests), `_summarize_tool_result` (2), `run_agent_tool_loop` routing (3), orchestration (3) | Phases 1–3 |
| `tests/integration/test_agent_loop.py` | Same functions with integration-level setup | Phases 1–3 |
| `tests/unit/test_tasks.py` | Task worker, imports `RunResult` | Phase 2 (re-export) |
| `tests/integration/test_tasks.py` | Task worker integration, imports `RunResult` | Phase 2 (re-export) |

### Per-phase test plan

**Phase 1** (tracing):
- Existing: `test_loop_helpers.py` — update imports to `app.agent.tracing`, verify
  re-export from `loop.py` still works.
- New: None needed. Pure constants + one simple function.

**Phase 2** (llm):
- Existing: All `TestLlmCall` and `TestSummarizeToolResult` tests pass via re-export.
- New: Optionally duplicate tests with direct `app.agent.llm` imports to prove the
  module works standalone.

**Phase 3** (tool_dispatch):
- Existing: `TestToolDispatchRouting` tests pass unchanged (they test via
  `run_agent_tool_loop` which now calls `dispatch_tool_call` internally).
- New: Add `tests/unit/test_tool_dispatch.py` with focused tests:
  - Local tool dispatch (standard + memory/persona/knowledge special cases)
  - MCP tool dispatch
  - Client tool dispatch (mock pending future)
  - Unknown tool → error
  - Tool result summarization triggered / skipped
  - Client action extraction from tool result
  - Error detection in tool result JSON

**Phase 4** (context_assembly):
- Existing: Integration tests in `tests/integration/test_agent_loop.py` cover the
  end-to-end flow. These must pass unchanged.
- New: Add `tests/unit/test_context_assembly.py` with focused tests per inject function:
  - `inject_datetime` — verify message format
  - `inject_tagged_context` — mock `resolve_tags`, verify messages + events
  - `inject_skills` — pinned/RAG/on-demand paths
  - `inject_memories` — mock `retrieve_memories`, verify truncation + events
  - `inject_knowledge` — pinned + RAG paths
  - `inject_plans` — mock DB, verify message format
  - `inject_tools` — mock `retrieve_tools`, verify merged schemas + index
- Snapshot test: Before Phase 4, capture the full `messages` list produced by
  `run_stream` for a representative bot config. After refactor, assert the messages
  list is identical. This catches ordering bugs.

### Regression gate

Every PR must pass:
```bash
pytest tests/unit/test_agent_loop.py tests/unit/test_loop_helpers.py tests/unit/test_tasks.py -v
pytest tests/integration/test_agent_loop.py tests/integration/test_tasks.py -v
```

---

## Summary

| Phase | New file | Lines moved | Risk | Dependencies |
|-------|----------|-------------|------|-------------|
| 1 | `app/agent/tracing.py` | ~30 | Low | None |
| 2 | `app/agent/llm.py` | ~80 | Low | None |
| 3 | `app/agent/tool_dispatch.py` | ~220 | Medium | Phase 2 |
| 4 | `app/agent/context_assembly.py` | ~350 | High | Phases 1–3 |

Post-refactor `loop.py`: ~250–300 lines (down from 1228), containing only the
iteration skeleton, stream orchestration, and non-streaming wrapper.
