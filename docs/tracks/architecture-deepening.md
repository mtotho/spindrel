---
title: Architecture Deepening
summary: Rolling track for architectural deepening passes. Holds the current candidate inventory from the improve-codebase-architecture skill, ordered by confidence; deepenings that ship are logged in deepening-log.md and removed from the inventory.
status: active
tags: [spindrel, architecture, refactor]
created: 2026-05-02
updated: 2026-05-02
---

# Architecture Deepening

## North Star

Spindrel's agent surfaces (loop, context assembly, tool dispatch) are the #1 bug source per AGENTS.md, and the rest of the codebase (UI, services, integrations) accretes its own quiet drift. This track captures **deepening candidates** — places where merging shallow modules into deeper ones would concentrate complexity, improve testability, and make the system more AI-navigable. It is a rolling inventory: the `improve-codebase-architecture` skill refreshes it; landed deepenings move to `docs/deepening-log.md`.

## How this track works

1. Run the `improve-codebase-architecture` skill periodically. It surfaces candidates and updates this inventory.
2. Pick a candidate — usually highest confidence with the most reported friction (cross-checked against `docs/inbox.md`).
3. Grill the design (skill drives this), land the deepening, append to `docs/deepening-log.md` in the same edit, remove or check off the row here.
4. The skill's next run will read the log and bias toward areas that haven't been deepened recently — preventing the agent loop from monopolising attention while UI/services drift.

## Status

| # | Candidate | Area | Confidence | State | Updated |
|---|---|---|---|---|---|
| 1 | Tool Surface composition (extract from context_assembly) | app/agent | high | not started | 2026-05-02 |
| 2 | Tool Execution Policy gateway | app/agent | high | not started | 2026-05-02 |
| 3 | Tool Result Envelope vs. invocation | app/agent | medium | not started | 2026-05-02 |
| 4 | Message Assembly module (consolidate transcript mutation) | app/agent | medium | not started | 2026-05-02 |
| 5 | Pruning policy vs. mechanics | app/agent | medium-low | not started | 2026-05-02 |
| 6 | LoopHarness facade | app/agent | low | needs grilling | 2026-05-02 |
| 7 | Tool Schema Resolver | app/agent + app/tools | low-medium | not started | 2026-05-02 |

**Coverage gap noted on 2026-05-02 sweep:** all 7 candidates landed inside `app/agent/`. The first explore pass under-swept `ui/`, `app/services/`, `app/db/`, and `integrations/sdk.py`. The skill body has been amended to require a broader sweep on subsequent runs — next pass should produce candidates from those areas if friction exists. Don't take the all-agent inventory as evidence those areas are clean.

## Candidate Inventory

### 1. Tool Surface composition inside `context_assembly` — confidence: **high**

- **Files**: `app/agent/context_assembly.py` (3185 lines, 46 helpers).
- **Problem**: One file mixes 5 concerns — tool-schema aggregation, skill enrollment, RAG injection, memory/workspace prompts, heartbeat determinism. `test_heartbeat_tool_surface.py` mocks 12 collaborators because the module has no internal interfaces.
- **Solution sketch**: Pull tool-surface composition into a dedicated module; same for skill enrollment resolution and workspace-context injection. `context_assembly` becomes the orchestrator that streams events from each.
- **Benefits**: Heartbeat logic concentrates in one module instead of being scattered across four helpers + channel overrides. Each subdomain becomes unit-testable through a real interface.
- **Domain language**: Tool Surface, Discovery, Enrollment, Context Admission, Memory scheme.

### 2. Tool Execution Policy gateway — confidence: **high**

- **Files**: `app/agent/loop_dispatch.py` (664 lines), `app/agent/tool_dispatch.py` (2096 lines), guards `_authorization_guard`, `_execution_policy_guard`, `_policy_and_approval_guard`, `_plan_mode_guard`.
- **Problem**: Authorization / execution / approval / plan-mode rules are entangled with envelope building and trace emission, split across two modules. Approval-race bugs require cross-module tracing. Adding a new policy layer threads through 4 guards.
- **Solution sketch**: A single Tool Execution Policy module owns the gate chain. `dispatch_tool_call` becomes a client of it, not the host of it.
- **Benefits**: Locality for security-critical rules. New policies (rate limits, cost caps, delegation rules) plug in as new gates, not new branches inside dispatch.
- **Test seam**: `tests/unit/test_loop_approval_race.py` already exercises this surface.

### 3. Tool Result Envelope vs. tool invocation — confidence: **medium**

- **Files**: `app/agent/tool_dispatch.py` — `_build_default_envelope`, `_build_envelope_from_optin`, `_detect_content_type`, `_select_result_envelope`, `_build_tool_event`.
- **Problem**: ~1080 lines of envelope-building (truncation, plaintext fallback, widget binding, size caps) live alongside execution. Envelope-only tests need full execution context with mocks.
- **Solution sketch**: Separate envelope construction into its own module — pure-ish function over tool result + metadata + caps. `dispatch_tool_call` calls it after execution.
- **Benefits**: Presentation concerns decouple from execution. Truncation/widget tests become micro-unit tests with no async, no DB.
- **Risk**: `_select_result_envelope` reads plan-mode state — needs threading as an explicit parameter.

### 4. Message Assembly module — confidence: **medium**

- **Files**: `app/agent/loop_helpers.py` (1080 lines), `app/agent/message_utils.py`, `loop_pre_llm.py`, `loop_tool_iteration.py`, sanitization paths in `context_assembly.py`.
- **Problem**: `_sanitize_messages`, `_sanitize_llm_text`, `_extract_last_user_text`, `_append_transcript_text_entry`, `_collapse_final_assistant_tool_turn`, `_merge_tool_schemas` live in five different files but all mutate the messages array. The contract between them is implicit (e.g., sanitization runs once, callers must not re-sanitize).
- **Solution sketch**: A Message Assembly module owns the mutation contract. Composable operations (append transcript, merge tool results, truncate history) called by the 5 current sites.
- **Benefits**: A new mutation (reasoning-trace injection, compaction-summary formatting) changes one file instead of five. Pure-function tests replace event-loop tests.
- **Risk**: Some operations read context vars (`current_skills_in_context`); those would need to become explicit parameters.

### 5. Pruning policy vs. pruning mechanics — confidence: **medium-low**

- **Files**: `app/agent/context_pruning.py` (478 lines), `_run_context_pruning` in `context_assembly.py`.
- **Problem**: Two pruning phases — assembly-time (watermark-based) and in-loop (ratio-based) — duplicate the logic with different conditions. New strategies (cost-based, relevance-based) require touching both.
- **Solution sketch**: Pruning Policy as a parameter to a single mechanics module. Both phases call the same machinery with different policies injected.
- **Benefits**: Strategy experimentation without forking mechanics.
- **Risk**: In-loop pruning runs every iteration — allocation overhead matters. Payoff depends on whether new policies actually emerge.

### 6. LoopHarness facade — confidence: **low (needs grilling)**

- **Files**: 11 `loop*.py` modules under `app/agent/`, 15+ inter-agent imports.
- **Problem**: The loop is callable but has no interface. Tests mock the whole DAG. Adding a new caller (subagent, batch task) means following the streaming generator through every submodule.
- **Solution sketch**: A LoopHarness facade — single entry point for callers — without disturbing the internal submodule structure.
- **Benefits**: Callers mock the harness, not the cluster.
- **Open question for grilling**: are loop variants on the roadmap (parallel tool execution? reasoning mode?), or is the current streaming generator the canonical form? If no variants, this is indirection.

### 7. Tool Schema Resolver — confidence: **low-medium**

- **Files**: `app/agent/tools.py` (678 lines, `retrieve_tools()`), `app/tools/registry.py` (392 lines), schema composition in `context_assembly.py`.
- **Problem**: Pinned/tagged/enrolled lookup, in-memory registry, and semantic RAG retrieval are three modules with overlapping responsibility. Heartbeat vs. normal vs. fallback retrieval branches in `_run_tool_retrieval`.
- **Solution sketch**: One Tool Schema Resolver — composite that checks pinned → enrolled → retrieval (if policy allows) → fallback. Single call from `context_assembly`.
- **Benefits**: New discovery modes (MCP tool retrieval, plan-mode-restricted surfaces) add a resolver implementation, not branches in three modules.
- **Caveat**: The taxonomy (Local/MCP/Client/Workspace) is settled in `architecture.md`. This is hygiene more than a load-bearing seam unless new discovery modes are coming.

## Key Invariants

- No integration-specific code in `app/` (per `architecture-decisions.md`). Any deepening that touches integration plumbing must keep the dispatcher protocol as the only seam.
- `memory_scheme: "workspace-files"` and `history_mode: "file"` are the only active options — don't surface deepening candidates that re-introduce the alternative paths.
- `flex-direction: column-reverse` chat scroll is non-negotiable (per `AGENTS.md`). Any UI deepening near `ChatMessageArea.tsx` preserves it.
- Test-first bug fixing remains the contract — every deepening lands with new tests at the deepened module's interface, and old shallow-module tests are deleted (per `DEEPENING.md` "replace, don't layer").

## References

- Skill: `.claude/skills/improve-codebase-architecture/SKILL.md` (+ `LANGUAGE.md`, `DEEPENING.md`, `INTERFACE-DESIGN.md`)
- Log of landed deepenings: `docs/deepening-log.md`
- Architecture: `docs/architecture.md`, `docs/architecture-decisions.md`
- Domain glossary: `docs/guides/ubiquitous-language.md`
