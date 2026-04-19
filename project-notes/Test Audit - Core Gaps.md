---
tags: [testing, audit, coverage]
status: reference
updated: 2026-04-18
---

# Test Audit — Core Gaps

Phase A of the core-code coverage sweep (plan: `~/.claude/plans/gentle-spinning-bird.md`). Maps the top 8 runtime-frequent core modules against their existing tests and ranks dark/smoke behaviors by `runtime_frequency × bug_yield_guess`.

**Read this before starting a Phase B sweep.** Each entry has a file:line anchor and a 1-sentence "why this bites" note. Phase B sessions pick targets from the top-30 list; update the classification column as entries move from `dark` → `pinned`.

## Method

- **pinned** = happy path + at least one failure/edge path asserted
- **smoke** = called in a test but no meaningful assertion on output or side-effects
- **dark** = not exercised anywhere in `tests/`

Runtime frequency: `every-turn` > `per-event` > `per-op` > `rare`.
Bug yield guess: based on branching complexity, side-effect surface, async coordination, external/DB dependencies.

## Top 30 Ranked Gaps (Phase B target list)

Order = (runtime_frequency × bug_yield) with secondary sort by recency-of-churn.

| # | File:Line | Behavior | Class | Freq | Yield | Why this bites |
|--:|---|---|:-:|:-:|:-:|---|
| 1 | `app/services/sessions.py:593-627` | `persist_turn` outbox enqueue atomicity | **pinned** | every-turn | high | 34 lines of channel resolution + target dispatch + message link inside the turn-write path; crash mid-loop drops dispatches with no replay |
| 2 | `app/agent/llm.py:1491` | `_strip_images_with_descriptions` | **pinned** | every-turn | high | Async DB lookup + vision-model fallback + description injection; every turn with attachments on a non-vision model hits this |
| 3 | `app/agent/tasks.py:888-912` | `run_task` delegation child session linkage | dark | every-turn | high | Root-session-id propagation and delegation-depth tracking across cross-bot calls; silent wrong-parent is a debugging nightmare |
| 4 | `app/agent/loop.py:333` | `run_agent_tool_loop` activated tool merging | **pinned** | every-turn | med | `current_activated_tools` ContextVar mutation + `tools_param` re-merging across successive LLM calls; test_agent_loop covers the `_llm_call` primitive, not the merging seam |
| 5 | `app/agent/loop.py:333` | `run_agent_tool_loop` context budget exhaustion | **pinned** | every-turn | med | In-loop pruning + tool-result capping decisions; budget math untested under mixed LLM+tool cost scenarios |
| 6 | `app/services/sessions.py:844-926` | `_sanitize_tool_messages` orphan/misordered repair | **pinned** | per-event | high | 82 lines of 3-phase state machine (find calls → repair → rebuild) — entirely dark; corrupted histories from legacy rows silently pass through |
| 7 | `app/services/step_executor.py:718-725` | `_run_foreach_step` when-gate at iteration scope | **pinned** | per-event | high | **Fresh churn 2026-04-18**: `{{item.id}}` gate binding inside iteration; the fix landed but only one happy-path assertion exists |
| 8 | `app/services/step_executor.py:1390-1444` | `on_pipeline_step_completed` child result freshness | **pinned** | per-event | high | Stale in-memory `child_task` arg; out-of-bounds index guard (1416-1418) dark — a reordered step resume can crash the whole pipeline |
| 9 | `app/agent/tasks.py:1411-1542` | `recover_stalled_workflow_runs` all 4 scenarios | dark | per-op | high | 130 lines of recovery state machine; branch coverage <10%; stuck workflows can transition to wrong terminal state |
| 10 | `app/agent/tool_dispatch.py:232` | `dispatch_tool_call` approval-tier + timeout flow | **pinned** | per-event | high | Policy tier/reason injection, approval_id persistence, timeout interleaving all smoke-tested via integration — no isolated unit assertion |
| 11 | `app/services/file_sync.py:323-340` | `sync_all_files` orphan deletion mount safety | **pinned** | per-event | high | Fallback when zero files but DB rows exist; pinned by `test_when_zero_files_on_disk_then_orphan_deletion_skipped` (test_file_sync.py:494). Audit flag was stale. |
| 12 | `app/services/step_executor.py:1486-1503` | `_finalize_pipeline` anchor/summary publish | **pinned** | per-op | high | Channel emit + summary message; exception swallow (1500-1502) untested — failed pipelines can silently not emit completion |
| 13 | `app/services/sessions.py:374-436` | `_load_messages` compaction mode path | **pinned** | every-turn | med | Watermark fallback (412-436) dark; file-history mode (394-398) dark; section-index injection by caller untested |
| 14 | `app/agent/llm.py:558` | `get_model_cooldown` / fallback chain | **pinned** | per-turn | high | Cooldown state stored in module dict (`_model_cooldowns`); expiry timing + provider re-routing tested only as side-effect of fallback chain |
| 15 | `app/services/step_executor.py:454-512` | `_run_exec_step` workspace vs bot_sandbox branching | **pinned** | per-op | high | Path branching (495-512) untested; mis-sandboxing leaks workspace context into unscoped runs |
| 16 | `app/agent/tasks.py:1242-1253` | `run_task` callback task creation atomicity | smoke | per-op | high | Follow-up task creation inside the finalize block; partial failures leave orphaned tasks |
| 17 | `app/services/step_executor.py:641-779` | `_run_foreach_step` sub-step failures with `on_failure=continue` | **pinned** | per-op | high | 778-779 branch dark; a single tool-failure in an iteration can silently abort the whole sweep |
| 18 | `app/services/sessions.py:1035-1070` | `_filter_old_heartbeats` turn-boundary logic | **pinned** | per-op | med | Indexing logic untested; multi-heartbeat-per-turn cases can misclassify "old" vs "fresh" |
| 19 | `app/agent/llm.py:1625` | `_summarize_tool_result` truncation + fallback | **pinned** | per-event | med | Head/tail cap-size edges and vision-model fallback on summarizer timeout untested |
| 20 | `app/agent/llm.py:1560` | `_fold_system_messages` role alternation | **pinned** | per-turn | med | Merges adjacent same-role messages for non-Anthropic models; tool-result preservation during fold untested |
| 21 | `app/agent/llm.py:1476` | `_describe_image_data` vision model fallback | **pinned** | per-event | med | Async external summarizer call; error path (timeout, OOM) produces generic fallback with no test |
| 22 | `app/services/compaction.py:1899` | `repair_section_periods` offset math | dark | rare | high | If `section.message_count==0` the offset logic skips the section silently; backfill corruption risk |
| 23 | `app/services/compaction.py:1290` | `maybe_compact` background task dispatch | smoke | every-turn | med | Test asserts task creation only; no assertion on execution, budget passing, or swallow of exceptions inside the background task |
| 24 | `app/agent/context_assembly.py:88` | `invalidate_bot_skill_cache` | dark | rare | med | 30s TTL cache; invalidation is the only way to beat staleness after skill CRUD; failure = stale skill injection |
| 25 | `app/agent/context_assembly.py:159` | `invalidate_skill_auto_enroll_cache` | dark | per-event | med | Exception caught and logged (172-173); next turn gets stale enrollment silently |
| 26 | `app/services/step_executor.py:911-994` | `_run_evaluate_step` evaluator dispatch + cases resolution | **pinned** | rare | med | Evaluator dispatch (990-994) untested; cases resolution (940-950) smoke |
| 27 | `app/services/sessions.py:717-772` | `store_dispatch_echo` self-skip + passive_memory check | **pinned** | rare | med | Echo self-skip (747-755) and channel passive_memory check (770-772) dark; integration loopback can double-record |
| 28 | `app/services/file_sync.py:657-896` | `sync_changed_file` kind-specific branches | **pinned** | per-event | med | 12 tests in `test_file_sync_core_gaps.py` — all 5 kind branches + deletion-across-4-tables + reload cascade. **Bug caught**: line 686 `if rows or rows2 or ...` — `rows2` never defined → NameError on deleted prompt/carapace/workflow files. Fixed. |
| 29 | `app/agent/tasks.py:371-445` | `_spawn_from_event_trigger` + filter matching | dark | rare | med | Event filter matching (437-438) dark; event_data injection into ecfg (388-389) dark; spawn failures swallowed silently |
| 30 | `app/agent/loop.py:1474` | `run_stream` delegation_post queueing | **pinned** | per-turn | med | Outermost-vs-nested delegation post list sharing; ordering risk if nested calls interleave |

## Per-Module Summary

### `app/agent/llm.py` (1658 lines) — **B.3 swept 2026-04-18**

New file: `tests/unit/test_llm_core_gaps.py` (44 tests, all green). Covers #2, #14, #19, #20, #21: cooldown chain, `_fold_system_messages`, `_describe_image_data`, `_summarize_tool_result`, `_strip_images_with_descriptions`. Notable finding: system-message folding merges the injected user msg with the following user msg — behaviour is correct but subtle. Streaming primitives (`StreamAccumulator`, `_llm_call_stream`, `_llm_call`) remain well-pinned in `test_llm_streaming.py` + `test_stream_accumulator.py`.

### `app/agent/loop.py` (1852 lines) — **B.5 swept 2026-04-18**

New file: `tests/unit/test_loop_core_gaps.py` (9 tests, all green). Covers #4 (activated-tool merging), #5 (in-loop pruning gate + context_pruning event), #30 (delegation_post ordering in outermost vs nested `run_stream`). Notable: dedup logic compares against `_existing_names` (already in tools_param) rather than deduplicating within `_activated_list` itself — cross-iteration dedup verified. `run()` (non-streaming wrapper) has no aggregation-edge coverage.

### `app/agent/tool_dispatch.py` (894 lines)

`ToolResultEnvelope.compact_dict` is pinned. `dispatch_tool_call` is smoke-tested via integration — the approval-tier flow + timeout + policy rejection paths need isolated unit tests.

### `app/services/sessions.py` (1088 lines)

`normalize_stored_content` + `_content_for_db` + `_strip_leaked_attachment_hints` pinned. Dark: `persist_turn` outbox loop, `_sanitize_tool_messages` (entire 3-phase state machine), `_filter_old_heartbeats`. This is where the biggest every-turn bug surface lives.

### `app/services/step_executor.py` (1506 lines)

Heavy churn this week (foreach `when:`, `tool` step type, `/resolve` background dispatch). **Smoke** means "one happy-path assertion exists" — the fresh fixes are not yet covered by regression tests at the branch level. Priority targets: `_run_foreach_step`, `on_pipeline_step_completed`, `_finalize_pipeline`.

### `app/agent/tasks.py` (1603 lines)

Delegation + recovery are the dark hot-spots. `recover_stalled_workflow_runs` is 130 lines with <10% branch coverage. `run_task` delegation child session creation is untested — a class of bugs where root_session_id mis-propagation breaks cross-bot threading.

### `app/services/compaction.py` (2136 lines) — well-covered, one outlier

Refuted the premise that "broad coverage" = complete. 135 test cases but **`repair_section_periods` is confirmed dark** and `maybe_compact` background dispatch is smoke. Member-bot flush path has only 1 test. Everything else is pinned.

### `app/agent/context_assembly.py` (2072 lines)

Unit tests are thin (210 lines, widgets-only). Integration suite (`tests/integration/test_context_assembly.py`, 1316 lines) exercises `assemble_context` broadly but doesn't pin branch logic of the injection subfunctions. Two public cache-invalidation functions (`invalidate_bot_skill_cache`, `invalidate_skill_auto_enroll_cache`) are dark — silent skill staleness bugs live here.

### `app/services/memory_hygiene.py` (1056 lines)

Surprisingly well-pinned. All `resolve_*` config cascades + `create_hygiene_task` + `bootstrap_hygiene_schedule` are pinned. `check_memory_hygiene` stagger + DST edges are the only notable gaps.

### `app/services/file_sync.py` (1015 lines)

Collection + hashing + frontmatter parse pinned. Dark: `sync_all_files` orphan-deletion mount-safety fallback, `sync_changed_file` kind-specific branches, `watch_files` restart backoff.

## Phase B Target Ordering (recommended)

Based on the top-30 + module summaries, three sweeps unlock ~65% of the high-yield surface:

1. **Sweep B.1 — `sessions.py`** (targets #1, #6, #13, #18, #27). Most every-turn dark behavior. Single module; bounded scope. Start here.
2. **Sweep B.2 — `step_executor.py`** (targets #7, #8, #12, #15, #17, #26). Fresh churn; user will feel regressions fastest. Heavy use of `patched_async_sessions` fixture.
3. **Sweep B.3 — `llm.py`** (targets #2, #14, #19, #20, #21). Greenfield file (no existing test). Can start with pure-unit tests for `_fold_system_messages`, then move to the async image-handling trio with `AsyncMock` discipline.

**Defer**: `tasks.py` recovery (#3, #9, #16) — deeper scope, high value but each test requires real-DB setup of stalled-run fixtures. Tackle after the top 3 sweeps prove the pattern.

**Do not sweep**: `compaction.py`, `memory_hygiene.py`, `context_assembly.py`. Coverage is solid; only small targeted additions (#22, #23, #24, #25) — can be one-off PRs rather than full sweeps.

## See Also

- [[Track - Test Quality]] — active track, Phase B task list
- `~/.claude/plans/gentle-spinning-bird.md` — approved plan
- [[Test Audit - Inventory]] — Phase 0 file-level inventory
- [[Test Audit - Coverage Gaps]] — Phase 0 symbol-level gaps (now superseded for core modules by this doc)
