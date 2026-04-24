# Context Management

This is the canonical document for how Spindrel manages LLM context.

If replay policy, compaction, history loading, plan-mode context, heartbeat/task trimming, or context-budget reporting changes, update this file first and then update shorter docs that point at it.

This guide covers two things:

- what the app does today
- the policy we are steering toward when tuning defaults and guardrails

It is intentionally broader than [Chat History](chat-history.md), which focuses on archival/history modes.
For the canonical guide covering tool/skill discovery, enrollment, and residency semantics, see [Discovery and Enrollment](discovery-and-enrollment.md).

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

In multi-bot channels, member bots are still channel participants for context
and memory purposes. A member bot may only actively answer on @-mention or
auto-response rules, but channel messages can still be passively stored and
included in memory compaction or dreaming/learning jobs when the channel's
passive-memory and bot learning settings allow it.

Important replay rules now in place:

- rows marked `metadata.hidden` are excluded from LLM reload
- rows marked `metadata.pipeline_step` are excluded from LLM reload
- rows marked `metadata.kind == "compaction_run"` are excluded from LLM reload and live-history accounting
- older heartbeat turns are trimmed, keeping only the latest heartbeat turn(s)
- older assistant turns with large verbose `content` are compacted from canonical `assistant_turn_body` metadata
- oversized historical assistant tool-call arguments are compacted in the model-visible replay copy while the persisted database row stays intact for debugging/history
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

Live-history accounting includes both message `content` and assistant `tool_calls`.
This matters because large tool-call arguments can exceed the provider window even
when the paired tool result content has already been pruned. If pruning and
admission still leave the estimated prompt over the usable model window, the
agent loop blocks the provider call locally and emits a controlled
`context_window_exceeded` error instead of forwarding an over-window request.

That split is emitted downstream so compaction can react to replayable-history pressure specifically, instead of only one blended prompt number.

Context assembly is now also **profile-aware**:

- every run resolves to one of `chat`, `planning`, `executing`, `task_recent`, `task_none`, or `heartbeat`
- the active profile controls how much live history is replayed
- optional static injections are admitted only if the profile allows them and the budget can afford them
- trace/reporting now records per-source admit/skip reasons so "skipped by profile" and "skipped by budget" are visible separately

### Knowledge-base retrieval

Knowledge-base behavior is opinionated and convention-based rather than driven only by custom segments. The full storage model and write-where guidance live in [Knowledge Bases](knowledge-bases.md).

Current behavior:

- every channel has `channels/<channel_id>/knowledge-base/`
- every bot has a bot-wide `knowledge-base/` folder
  - standalone bots: `knowledge-base/`
  - shared-workspace bots: `bots/<bot_id>/knowledge-base/`
- both are indexed recursively under the normal filesystem indexer

Important scope distinction:

- **channel knowledge base**
  - room-specific reference material
  - implicitly retrieved in channel context via an always-present `channels/<id>/knowledge-base/` segment
  - when excerpts are injected, the prompt explicitly tells the model to call `search_channel_knowledge` for more targeted lookups
- **bot knowledge base**
  - bot-wide reference material that should travel across channels
  - auto-retrieved by default before broader workspace search
  - searchable with `search_bot_knowledge`
  - can be switched to search-only mode in bot Workspace settings

Practical write-where guidance:

- use channel KB for room/project facts, decisions, glossaries, runbooks, and curated reference docs
- use bot KB for bot-wide reference docs, reusable templates, and facts that should follow the bot between channels
- use `memory.md` for short high-signal behavioral notes and preferences
- use normal workspace files for transient working material rather than curated knowledge

---

## History Modes

Spindrel currently supports three history modes, but `file` is the active/default path.

### File

Recommended default for most serious channels.

Behavior:

- older conversation is archived into titled sections
- the model gets a section index
- the bot can fetch older history on demand with `read_conversation_history`

This is the most scalable mode because it avoids forcing old transcript detail into every turn.

### Structured

Legacy but still supported.

Behavior:

- older conversation is summarized into section-like chunks
- relevant chunks are surfaced automatically
- the model gets an executive summary

This is simpler than file mode for some channels, but less explicit than a section index + retrieval model.

### Summary

Legacy but still supported.

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

### How the knobs interact in practice

This is the simplest mental model:

- `compaction_interval` is the **normal cadence**
- `compaction_keep_turns` is the **minimum verbatim floor**
- the token/ration guards are **early safety valves**

So:

- under normal conditions, compaction happens when the interval is reached
- when that happens, Spindrel summarizes only the range older than the kept live window
- if the live window becomes too expensive before the interval is reached, Spindrel can compact early
- early compaction still respects the keep-turns floor

In other words, the turn-based settings define the desired conversational shape, while the token-based settings prevent that shape from becoming too expensive.

### What the ratio guard actually means

`COMPACTION_LIVE_HISTORY_MAX_RATIO` does **not** count turns.

It asks:

- how much of the usable prompt budget is being consumed by replayable live history alone?

That matters because turn counts and token counts diverge badly in agent conversations:

- 8 tool-heavy turns can be larger than 25 lightweight chat turns
- a big pasted file or verbose tool result can make a "small" live window expensive

So the ratio guard catches cases where the live window is semantically short but already too costly.

With today's defaults:

- `COMPACTION_LIVE_HISTORY_MAX_RATIO = 0.20`
- `COMPACTION_LIVE_HISTORY_MAX_TOKENS = 60_000`
- `COMPACTION_TRIGGER_UTILIZATION_SOFT = 0.70`

That means early compaction fires when any of these is true:

1. live history reaches 60k tokens
2. live history alone reaches 20% of the usable prompt window
3. total prompt utilization is already above 70%, even if live history is not the sole cause

Example:

- if the usable prompt window for a run is 200k tokens, the 20% ratio guard trips around 40k live-history tokens
- if live history reaches 60k first, the absolute cap trips even if the ratio would allow more
- if a run is already crowded by static injections, tool schemas, or other prompt layers, the 70% total-utilization fallback can compact early even when live history is below the other two guards

This is why the UI should present interval/keep-turns as the primary user-facing controls, but still explain that compaction may happen earlier when prompt pressure is high.

### Non-overlapping summary window

This is load-bearing.

Compaction now summarizes the exact persisted message range:

- after the previous watermark, if one exists
- before the oldest kept user turn

That means compaction no longer summarizes content that is still inside the live keep window.

The kept live window and the summarized window should never overlap.

Manual and automatic compaction both persist a visible assistant-owned operation row with `metadata.kind == "compaction_run"` and status metadata (`queued`, `running`, `completed`, or `failed`). That row is UI state only: it is delivered over the normal message event path and survives refresh, but it is not replayed to the model, summarized into future compactions, counted as live history, or used as an extra "you were compacted" instruction. The agent learns about compaction through the existing session summary / section history plus post-watermark live history.

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

This area is now implemented in the runtime with explicit context profiles. The remaining work is policy tuning, not inventing the mechanism.

### Plan mode

Plan mode already changes runtime behavior:

- plan-mode instructions are injected every turn
- plan mode tightens write policy
- the session can move between `planning`, `executing`, `blocked`, and `done`

Canonical plan behavior is documented in [Session Plan Mode](../planning/session-plan-mode.md).

Context policy now follows mode too:

- `planning` keeps only the last `2` user-started exchanges live
- `planning` admits the compact active-plan artifact, visible planning-state capsule, runtime capsule, conversation sections, and tool-index hints
- `planning` does **not** admit workspace context, temporal prose, pinned-widget prose, recent memory logs, or tool-refusal guard text
- `executing` keeps the last `4` user-started exchanges live
- `executing` admits the compact active-plan artifact, planning-state capsule, runtime/adherence capsule, conversation sections, channel/workspace context, workspace RAG, tool-index hints, and tool-refusal guard text
- `executing` still drops the more ambient/instructional additions such as temporal prose, pinned widgets, and recent memory logs

The active-plan artifact is derived from the canonical Markdown plan file and is treated as load-bearing context for planning/execution. It is paired with the metadata-backed `planning_state`, `plan_runtime`, and `plan_adherence` capsules. `planning_state` carries the visible back-and-forth notes before the full plan exists, `plan_runtime` carries compact execution state such as current step, next action, blockers, accepted revision, replan requests, pending turn outcomes, and the latest recorded outcome, and `plan_adherence` carries recent execution evidence plus explicit progress outcomes. This is what makes a short planning live window safer: approved constraints live in the plan artifact, while volatile planning/execution position survives via metadata instead of depending on older chat turns.

### Heartbeats

Heartbeat runs now have their own profile:

- old heartbeat turns are filtered from reload
- heartbeat reload trims live history to `0`
- heartbeat runs do not admit optional conversation-derived or ambient static injections

That is the intended steady-state behavior.

### Tasks / sub-sessions

Task runs now split into two profiles:

- `task_recent` respects task-selected history trimming but keeps the additive policy narrow
- `task_recent` allows conversation sections / section index when history is present
- `task_recent` does not admit workspace RAG, channel workspace prose, pinned widgets, temporal prose, or recent memory logs
- `task_none` trims live history to `0`, does not reload compaction summaries, and suppresses optional static injections

Special origins such as hygiene/subagent-style runs are also mapped to the restrictive `task_none` policy by default.

### Current profile summary

Shipped profiles:

- `chat`: current full chat policy, with optional injections admitted by both profile and budget
- `planning`: short live window, active plan artifact/planning-state/runtime capsule + sections + tool index only
- `executing`: medium live window, active plan artifact/planning-state/runtime/adherence capsule + execution-relevant workspace/context sources on, ambient prose off
- `task_recent`: task history only, narrow optional admissions
- `task_none`: no live replay beyond system/base layers, no optional ambient injections
- `heartbeat`: same restrictive admission posture as `task_none`

### Profile admission matrix

Profile gating happens before budget gating.

- `allowed` means the profile permits that source class
- `admitted` still depends on budget for optional sources
- `mandatory` means the runtime always includes that source when it exists

| Source | chat | planning | executing | task_recent | task_none | heartbeat |
|---|---|---|---|---|---|---|
| `MEMORY.md` bootstrap | mandatory | mandatory | mandatory | mandatory | mandatory | mandatory |
| today log | allowed + budget | off | off | off | off | off |
| yesterday log | allowed + budget | off | off | off | off | off |
| memory reference index | allowed + budget | off | off | off | off | off |
| memory housekeeping / nudges | allowed + budget | off | off | off | off | off |
| channel workspace root `.md` | allowed + budget | off | allowed + budget | off | off | off |
| channel knowledge-base / indexed-dir excerpts | allowed + budget | off | allowed + budget | off | off | off |
| bot knowledge-base excerpts | allowed + budget | off | allowed + budget | off | off | off |
| workspace RAG | allowed + budget | off | allowed + budget | off | off | off |
| conversation sections / section index | allowed + budget | mandatory | mandatory | mandatory when history exists | off | off |
| active plan artifact / planning capsules | off | mandatory | mandatory | off | off | off |
| tool index / discovery hints | allowed + budget | allowed + budget | allowed + budget | allowed + budget | off | off |
| temporal context | allowed + budget | off | off | off | off | off |
| pinned widgets prose | allowed + budget | off | off | off | off | off |
| tool-refusal guard | allowed + budget | off | allowed + budget | off | off | off |
| live history | full chat continuity | last 2 user-started turns | last 4 user-started turns | task-selected history posture | 0 | 0 |

Concrete runtime notes:

- `MEMORY.md` is the only workspace-files memory source that is currently unconditional across all shipped profiles.
- Bot knowledge-base admission is profile-gated separately from broad workspace RAG, even though the currently shipped restricted profiles disable both together.
- "Allowed" for optional sources still means "subject to budget."
- `task_recent` keeps the additive policy narrow even when it carries some conversation history.
- `task_none` and `heartbeat` deliberately suppress ambient prompt growth.

### Restricted-profile runtime note

Spindrel now keeps one shared generic memory prompt for normal chat, then adds a small extra runtime note for restricted profiles only:

- `planning`
- `executing`
- `task_recent`
- `task_none`
- `heartbeat`

That note is:

- ephemeral per request
- injected as a system message during context assembly
- not shown as a chat message
- not persisted as normal conversation content
- budget-gated like other optional static injections

The purpose is to tell the model what is actually missing on this run without maintaining separate full prompt templates for every profile.

Example `planning` note:

```text
Current context profile: planning.
Live replay is limited to the last 2 user-started turn(s).
Recent daily logs and memory reference listings are not preloaded in this run.
Workspace files, knowledge excerpts, and workspace search context are not preloaded in this profile.
If exact detail matters, fetch or search it explicitly instead of assuming it is already in context.
```

Example `executing` note when workspace context was admitted:

```text
Current context profile: executing.
Live replay is limited to the last 4 user-started turn(s).
Recent daily logs and memory reference listings are not preloaded in this run.
Some workspace and knowledge context is already present in this run.
If exact detail matters, fetch or search it explicitly instead of assuming it is already in context.
```

Example `heartbeat` note:

```text
Current context profile: heartbeat.
Live replay is disabled for this run.
Recent daily logs and memory reference listings are not preloaded in this run.
Workspace files, knowledge excerpts, and workspace search context are not preloaded in this profile.
If exact detail matters, fetch or search it explicitly instead of assuming it is already in context.
```

### Worked examples

#### Planning turn

What the model reliably gets:

- base/system prompt
- `MEMORY.md`
- plan-mode runtime instructions
- active plan artifact / planning-state / runtime capsule
- conversation sections or section index
- short live history (`2` user-started turns)
- tool-index hints when budget allows

What it does **not** get:

- channel workspace root files
- channel knowledge-base excerpts
- workspace RAG
- today/yesterday logs
- temporal prose
- pinned-widget prose

Implication: if a planning turn needs `tasks.md`, a KB note, or a recent log detail, the bot must fetch it deliberately instead of assuming it was preloaded.

#### Executing turn

What the model reliably gets:

- base/system prompt
- `MEMORY.md`
- plan execution capsules
- conversation sections or section index
- medium live history (`4` user-started turns)

What may be admitted if budget allows:

- channel workspace root files
- channel knowledge-base excerpts
- workspace RAG
- tool-index hints
- tool-refusal guard

What stays off:

- today/yesterday logs
- temporal prose
- pinned-widget prose

Implication: execution has access to project/workspace context again, but it still does not get recent daily logs for free.

#### Heartbeat or restrictive task turn

What the model gets:

- base/system prompt
- `MEMORY.md`
- the run-specific prompt

What stays off:

- live chat replay
- conversation sections / section index
- workspace prose
- knowledge-base excerpts
- workspace RAG
- recent logs
- most ambient optional injections

Implication: these origins are intentionally narrow. If they need external state, they should fetch it explicitly.

### Prompt-writing rule

Generic prompts and skills should only claim what is true across profiles.

That means:

- safe to say `MEMORY.md` is part of the durable memory baseline when the bot uses `workspace-files`
- not safe to say recent logs, workspace files, KB excerpts, or workspace RAG are always already present
- safe fallback instruction: if a needed detail is missing, fetch/search it explicitly
- restricted profiles now get a small runtime note that states the current profile and the missing preloads for that request

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

- default direction: `history_mode: file`
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

For the shipped mode-aware profiles:

- planning currently keeps `2`
- execution currently keeps `4`
- heartbeat/task-none currently keep `0`

Those are good starting points, but they should be treated as policy defaults that can still be tuned from live evidence.

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
   Planning, execution, heartbeat, and task runs now have distinct replay/admission profiles. Keep that separation explicit.
4. **Better observability**
   Gross prompt size, current prompt size, cached prompt size, and live-history share should remain visible as separate numbers.

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

1. **Profile tuning now matters more than profile invention**
   The mechanism exists; the remaining question is whether the shipped planning/executing/task/heartbeat policies are the right defaults under real traffic.
2. **Context-breakdown categories are still partly heuristic**
   The headline usage/reporting can now show gross/current/cached API truth, but some category estimates are still derived from char counts and static heuristics.
3. **Pre-call estimates and post-call usage are still different surfaces**
   The stream-time budget event is an estimate; cached-token truth only exists after the model reports usage.

---

## Practical Recommendations

If you want Spindrel to feel efficient and competitive, keep these rules:

1. Default to `history_mode: file`.
2. Treat `summary` mode as a secondary/simpler option, not the main path.
3. Treat `keep_turns` as a continuity setting, not as a context-budget guarantee.
4. Prefer `8-12` live turns for general chat unless the channel clearly needs more or less.
5. Use lower live windows for tool-heavy or planning-heavy flows; the shipped profile defaults (`planning=2`, `executing=4`, `task_none/heartbeat=0`) are the current reference point.
6. Keep tool pruning on, and use `in-loop keep iterations = 2` unless you have evidence you need `1` or `3`.
7. Keep old assistant/tool verbosity out of replay.
8. Let archived history, memory files, and plan artifacts carry older state.
9. Tune admission policy before chasing ever-larger raw context windows.

The target is not “fit everything.”

The target is “fit the right things.”

---

## Related Docs

- [Chat History](chat-history.md)
- [Chat State Rehydration](chat-state-rehydration.md)
- [Session Plan Mode](../planning/session-plan-mode.md)
- [Heartbeats](heartbeats.md)
- [Task Sub-Sessions](task-sub-sessions.md)
