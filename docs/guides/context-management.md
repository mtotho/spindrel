# Context Management

This is the canonical document for how Spindrel manages LLM context.

If replay policy, compaction, history loading, plan-mode context, heartbeat/task trimming, or context-budget reporting changes, update this file first and then update shorter docs that point at it.

This guide covers two things:

- what the app does today
- the policy we are steering toward when tuning defaults and guardrails

It is intentionally broader than [Chat History](chat-history.md), which focuses on archival/history modes.

---

## Goals

Spindrel should keep enough context to stay coherent and useful without turning every turn into a giant replay of stale transcript text.

The context-management policy is built around four goals:

1. Keep the current task legible to the model.
2. Preserve continuity across long sessions.
3. Keep prompt cost and latency bounded.
4. Prevent hidden/internal transcript artifacts from leaking back into model context.

The main principle is:

- use **recent verbatim history** for immediate continuity
- use **summaries / sections / retrieval** for older history
- use **memory files** for durable facts
- use **token caps** as safety rails, not as the only policy

---

## Mental Model

Spindrel context is not one blob. It has distinct layers:

| Layer | Purpose | Should stay small? | Should be compacted? |
|---|---|---:|---:|
| Base context | system prompt, persona, mode instructions | Yes | No |
| Current user turn | the new user input for this request | Yes | No |
| Live history | recent user/assistant/tool continuity | Yes | Yes |
| Static injections | memory logs, workspace excerpts, section index, pinned-widget text, discovery hints | Yes | Usually no; prefer admission control |
| Tool schemas | callable tool definitions | Yes | No |
| Output reserve | room for assistant output/reasoning | Yes | No |

That split matters because different mitigation strategies apply to different layers.

- If **live history** gets too large, compact or trim it.
- If **static injections** get too large, admit less of them.
- If **tool schemas** get too large, retrieve fewer tools.

Compaction is the right lever for replayable history, not for every other source of prompt growth.

---

## Current Runtime Behavior

### 1. Session reload

When a session is loaded for a turn, Spindrel rebuilds model-visible history in `app/services/sessions.py`.

Current behavior:

- base messages include:
  - effective system prompt
  - persona, when configured
  - plan-mode runtime context, when session mode requires it
- passive/ambient channel messages are formatted into a separate system block
- active history is filtered before it reaches the model

Important replay rules now in place:

- rows marked `metadata.hidden` are excluded from LLM reload
- rows marked `metadata.pipeline_step` are excluded from LLM reload
- older heartbeat turns are trimmed, keeping only the latest heartbeat turn(s)
- older assistant turns with large verbose `content` are compacted from canonical `assistant_turn_body` metadata
- the most recent assistant turn stays verbatim

Hidden/internal transcript rows are not model context just because they exist in persisted session history. If a row is UI-only or runtime-internal, it should stay out of replay.

### 2. Compacted sessions

If a session has already been compacted, Spindrel reloads:

- base/system context
- the session summary or file/structured history layer
- only the recent post-watermark active history

That means older chat continuity comes from:

- section summaries / section index / retrieval in `history_mode: file`
- executive-summary style injection in `history_mode: structured`
- a flat rolling summary in `history_mode: summary`

### 3. Context assembly

After session reload, `app/agent/context_assembly.py` layers in turn-specific context such as:

- workspace files
- memory bootstrap / memory logs
- section index
- tool and skill discovery hints
- current user message

Budget accounting now distinguishes:

- `base_tokens`
- `live_history_tokens`
- `static_injection_tokens`
- `tool_schema_tokens`

That split is emitted downstream so compaction can react to replayable-history pressure specifically, instead of only one blended prompt number.

---

## History Modes

Spindrel currently supports three history modes.

### File

Recommended default for most serious channels.

Behavior:

- older conversation is archived into titled sections
- the model gets a section index
- the bot can fetch older history on demand with `read_conversation_history`

This is the most scalable mode because it avoids forcing old transcript detail into every turn.

### Structured

Behavior:

- older conversation is summarized into section-like chunks
- relevant chunks are surfaced automatically
- the model gets an executive summary

This is simpler than file mode for some channels, but less explicit than a section index + retrieval model.

### Summary

Behavior:

- the app keeps a rolling flat summary plus recent history

This is the smallest option, but also the least faithful for channels where specific prior details matter. For most serious channels, `file` mode is the preferred path.

---

## Compaction Policy

Compaction is how Spindrel shrinks replayable history while preserving continuity.

### Semantic knobs

These remain the primary operator-facing semantics:

- `compaction_interval`
- `compaction_keep_turns`

They answer:

- how often should archival happen?
- how much recent history should stay verbatim?

### Safety knobs

These are the real overflow guardrails:

- `COMPACTION_TRIGGER_UTILIZATION_SOFT`
- `COMPACTION_LIVE_HISTORY_MAX_RATIO`
- `COMPACTION_LIVE_HISTORY_MAX_TOKENS`

They answer:

- is replayable history consuming too much of the usable context window?

### Why both are needed

Turns and tokens do different jobs.

- **Turns** preserve conversational semantics.
- **Tokens** prevent runaway prompt growth.

If you use only turns, a tool-heavy “15 turns” window can still be huge.

If you use only tokens, you lose the product-level guarantee that the last few exchanges remain verbatim.

So the right model is:

- turns for continuity
- tokens for safety

### Current early-compaction behavior

Spindrel now supports early compaction when replayable history becomes too large, even if the nominal interval has not been reached.

Current trigger reasons:

- `live_history_tokens`
- `live_history_ratio`
- fallback `total_utilization`

### Non-overlapping summary window

This is load-bearing.

Compaction now summarizes the exact persisted message range:

- after the previous watermark, if one exists
- before the oldest kept user turn

That means compaction no longer summarizes content that is still inside the live keep window.

The kept live window and the summarized window should never overlap.

---

## Tool Result Lifecycle

Tool results are one of the biggest context-bloat surfaces in an agent system, so Spindrel manages them in several layers.

### 1. Hard cap before a tool result even enters the turn

In `app/agent/tool_dispatch.py`, very large tool results are truncated by `TOOL_RESULT_HARD_CAP` before they are handed back to the LLM for the current turn.

Current default:

- `TOOL_RESULT_HARD_CAP = 50_000`

Important detail:

- the full result is still stored
- the LLM-visible result gets a truncation marker
- the bot can retrieve the full stored result later

This is the first line of defense. It prevents one huge tool result from instantly consuming the current turn.

### 2. Optional summarization for long tool results

Spindrel can also summarize long tool results before returning them to the LLM for the current turn.

This is separate from pruning.

- summarization shapes the current-turn result
- pruning removes stale tool results from later turns or later iterations

### 3. Turn-boundary tool pruning

At the start of a new user turn, `prune_tool_results()` replaces old tool-result content with a short marker.

Important behavior:

- all old tool results in the conversation region are eligible
- user messages, assistant prose, and system messages are not touched
- short tool results are kept
- results with retrieval records get a pointer to `read_conversation_history(section='tool:<id>')`

The reasoning is simple:

- the model already consumed those tool results in the turn where they were produced
- keeping the full raw payload around forever is usually cost with little reasoning benefit

### 4. In-loop pruning inside one agent run

Within a single multi-iteration run, `prune_in_loop_tool_results()` trims tool results from older iterations before the next LLM call.

This matters when the model calls tools multiple times in one run:

- iteration 1: call tool, read result
- iteration 2: call tool again, read result
- iteration 3: call tool again, read result

Without in-loop pruning, those tool results stack up quickly.

With in-loop pruning:

- the most recent `keep_iterations` iterations stay verbatim
- older iterations become retrieval-pointer markers

### 5. Sticky tool results

Some tool outputs are treated as reference material and are not pruned.

Current sticky tools:

- `get_skill`
- `get_skill_list`

Those stay because they behave more like temporary reference docs than ephemeral execution output.

### Why tool pruning exists

The point of tool pruning is not “tool results don’t matter.”

The point is:

- raw tool payloads often matter a lot in the moment
- they matter much less once the model has already reasoned over them
- they should remain retrievable, but not necessarily remain verbatim in the live window

That is the same basic principle used for older transcript history: retain access, reduce replay.

---

## What Must Stay In Context

The app should be opinionated about what deserves scarce live-window space.

### Always keep

- effective system prompt
- persona, if configured
- current mode contract
- current user message
- recent live continuity

### Keep live only briefly

- recent assistant prose
- recent tool interactions that matter for the immediate next step
- recent approval/tool state needed to complete the current action

### Move out of the live window quickly

- old verbose assistant transcript text
- old tool outputs
- hidden/pipeline-internal rows
- stale heartbeat chatter
- historical detail that can be retrieved from sections or files

### Keep durably, but not verbatim in every turn

- project facts
- user preferences
- accepted plans
- key decisions
- archived transcripts

Those belong in:

- section history
- workspace files
- memory files
- plan artifacts

not in an ever-growing live transcript window.

---

## Plan Mode, Tasks, Heartbeats

This is where the system is partly implemented and partly still evolving.

### Plan mode

Today, plan mode already changes runtime behavior:

- plan-mode instructions are injected every turn
- plan mode tightens write policy
- the session can move between `planning`, `executing`, `blocked`, and `done`

Canonical plan behavior is documented in [Session Plan Mode](../planning/session-plan-mode.md).

### Heartbeats

Today:

- old heartbeat turns are filtered from reload
- heartbeat state is already treated specially during compaction/reload

That is good and should remain.

### Tasks / sub-sessions

Today:

- tasks can trim conversation history depending on task history mode
- but additive injections are not yet fully profile-aware by task origin

That means the app has improved replay discipline, but still does not have a fully separate context-admission policy for every origin.

### Known gap

The remaining architectural follow-up is **origin-aware context profiles**.

Target direction:

- `chat`
- `planning`
- `executing`
- `task_recent`
- `task_none`
- `heartbeat`

Each should have different admission rules for live history and optional injections.

That work is not complete yet, so this document does not pretend it already exists.

---

## Defaults and Operator Guidance

### General rule

Do not think of `keep_turns` as the main protection mechanism.

It is a semantic continuity knob, not a hard guarantee of prompt size.

The real protection comes from:

- clean replay policy
- assistant-history normalization
- early compaction
- live-history token caps

### Current shipped defaults

Current config defaults are still:

- `COMPACTION_INTERVAL = 30`
- `COMPACTION_KEEP_TURNS = 10`

Those are reasonable after the replay fixes, but they should not be treated as sacred.

### What to use in practice

For normal chat channels, a good operating range is usually:

- `keep_turns: 8-12`

For high-tool, high-verbosity channels:

- `keep_turns: 6-8` is often enough

For continuity-heavy channels:

- `keep_turns: 12-15` can be valid, but only if live-history caps and assistant compaction are doing their job

For planning/execution profiles, once mode-aware profiles land:

- planning will likely want `2-3` verbatim planning exchanges
- execution will likely want `3-5`
- heartbeat/task-none should be near `0-1`

### Tool-pruning recommendations

For most channels, my recommendation is:

- `Context Pruning`: on
- `Pruning Min Length`: `200`
- `In-Loop Pruning`: on
- `In-Loop Keep Iterations`: `2`

Reasoning:

- `200` is a good cutoff because it preserves short/high-signal results like `OK`, ids, short errors, and compact status messages while pruning bulky payloads
- `2` in-loop kept iterations is the best general tradeoff:
  - `1` is more aggressive and cheapest
  - `2` usually preserves enough immediate compare/contrast context for the model
  - `3` is safer but noticeably more expensive in tool-heavy runs

### When to use `keep_iterations = 1`

Use `1` if:

- you care a lot about cost/latency
- your tools tend to return large payloads
- your agents usually only need the latest tool result to proceed

### When to use `keep_iterations = 3`

Use `3` if:

- you have long multi-step tool loops
- the model often needs to compare several recent tool results against each other
- you have already seen quality regressions with `2`

`3` is not wrong. It is just more conservative. If you do not have evidence you need it, I would prefer `2` as the default.

### Is 6 turns too low?

Not inherently.

It only sounds low if you assume the live window is the only memory system.

In Spindrel, it is not.

If file-mode history, retrieval, summaries, memory files, and plan artifacts are all working correctly, then `6` recent turns can be plenty for many channels. What matters is whether the model still has:

- the current problem
- the current decision boundary
- the immediately relevant recent exchange
- a reliable path to fetch older detail

That said:

- `6` should not be the universal default for every channel
- it is a plausible default for some high-verbosity profiles
- `8-12` is a safer general default range for normal chat

---

## How This Compares To Industry Practice

Spindrel’s direction is aligned with, and in a few places stricter than, what major agent platforms and agent frameworks publicly document.

### What the industry trend looks like

Across major platforms, the common pattern is:

1. keep only the immediately useful recent context live
2. compact or summarize long-running conversations
3. separate durable memory from thread-local working memory
4. use caching for stable prompt prefixes

That is the same direction Spindrel is taking.

### OpenAI

OpenAI’s official context-management docs explicitly recommend compaction for long-running conversations and expose both server-side and standalone compaction flows. Their compaction docs describe shrinking context while preserving the state needed for subsequent turns, with an encrypted compaction item carrying forward prior state in fewer tokens.

That is conceptually the same family of solution as Spindrel’s archival/summary approach: do not keep replaying the full raw transcript forever.

### Anthropic

Anthropic’s context-window docs explicitly warn that more context is not automatically better and call out “context rot” as token count grows. They also position server-side compaction as the primary strategy for long-running conversations and recommend placing static content at the beginning of the prompt for caching.

That matches Spindrel’s design priorities:

- curate context, don’t just enlarge it
- separate static prefix material from dynamic message history
- compact long-running threads instead of replaying everything

### LangGraph / LangChain

LangGraph’s official memory docs describe the standard short-term-memory solutions as:

- trim messages
- summarize messages
- store/retrieve message history
- use custom filtering strategies

Their examples even show summarizing after small message counts in some flows. So a live window around 6 recent messages or turns is not out of family for agent systems when summary/retrieval exists beside it.

### What Spindrel should aim to exceed

Spindrel should not just match the generic “trim/summarize” baseline. It should be better in these ways:

1. **No hidden-context leaks**
   Internal transcript rows should never quietly flow back into LLM context.
2. **Token-aware live-history guardrails**
   Turn counts alone are not enough.
3. **Mode-aware policies**
   Planning, execution, heartbeat, and task runs should not all share one generic replay strategy.
4. **Better observability**
   Gross token totals, cached tokens, current prompt size, and live-history share should be visible separately.

That is the bar.

### External references

- OpenAI conversation state: https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI compaction: https://developers.openai.com/api/docs/guides/compaction
- Anthropic context windows: https://platform.claude.com/docs/en/build-with-claude/context-windows
- Anthropic prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- LangGraph memory: https://docs.langchain.com/oss/python/langgraph/add-memory

---

## Known Gaps

The biggest remaining gaps are:

1. **Origin-aware admission policy is incomplete**
   Tasks, heartbeat follow-ups, and plan/execution modes still share too much of the same additive injection policy.
2. **Static injection admission is not yet strict enough**
   Some optional blocks are still “inject then consume” instead of “admit only if affordable.”
3. **Operator reporting still needs to distinguish gross vs current context more clearly**
   A turn with multiple LLM iterations can still look much larger than the actual current prompt.

---

## Practical Recommendations

If you want Spindrel to feel efficient and competitive, keep these rules:

1. Default to `history_mode: file`.
2. Treat `summary` mode as a secondary/simpler option, not the main path.
3. Treat `keep_turns` as a continuity setting, not as a context-budget guarantee.
4. Prefer `8-12` live turns for general chat unless the channel clearly needs more or less.
5. Use lower live windows for tool-heavy or planning-heavy flows.
6. Keep tool pruning on, and use `in-loop keep iterations = 2` unless you have evidence you need `1` or `3`.
7. Keep old assistant/tool verbosity out of replay.
8. Let archived history, memory files, and plan artifacts carry older state.
9. Fix admission policy before chasing ever-larger raw context windows.

The target is not “fit everything.”

The target is “fit the right things.”

---

## Related Docs

- [Chat History](chat-history.md)
- [Chat State Rehydration](chat-state-rehydration.md)
- [Session Plan Mode](../planning/session-plan-mode.md)
- [Heartbeats](heartbeats.md)
- [Task Sub-Sessions](task-sub-sessions.md)
