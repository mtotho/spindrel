---
tags: [agent-server, experiments, autoresearch, pipelines]
status: active
updated: 2026-04-18
---

> **Session 9 (2026-04-18)** — Phase 2 shipped locally: `experiment.iterate.yaml`, `build_experiment_record` + `update_best_if_improved` tools, evaluate-step recursive template rendering fix, `response_quality_rubric.yaml` template (doubles as Phase-2 demo spec). Next: drop a real spec.yaml + subscription on the test server and verify one full hill-climb.

# Track — Experiments (autoresearch on the pipeline harness)

## North Star
Generic optimization harness — **knob → apply → evaluate → score → record → propose → loop** — built on the existing pipeline + channel-subscription + workspace-files primitives. No new DB tables; experiments are a convention over `ChannelPipelineSubscription` + channel-workspace `data/experiments/<exp_id>/`. v1 proves the abstraction on two real targets (bot system prompt, skill triggers) so future targets (RAG, context budget, file patches) drop in without harness changes.

Plan of record: `~/.claude/plans/cozy-enchanting-blanket.md`.

## Status

| Phase | Description | Status |
|---|---|---|
| 1a | `evaluate` step + metric library + `exec` evaluator + `bot_invoke` stub + unit tests | ✅ shipped 2026-04-18 (c1a273ff) |
| 1b | Real `bot_invoke` evaluator: ContextVar-based system_prompt override, Task-row child creation with UI suppression, capture `{response_text, tool_calls, token_count, latency_ms}`, `task_type="eval"` added to session-skip-list | ✅ shipped 2026-04-18 (Session 8) |
| 2 | `experiment.iterate.yaml` + `build_experiment_record` / `update_best_if_improved` tools + evaluate-step recursive template rendering + `response_quality_rubric.yaml` template. Pending: verify a full hill-climb on the live test server. | 🚧 pipeline + tools landed 2026-04-18 (Session 9); server verification pending |
| 3 | `experiment.create.yaml` + `experiment.commit.yaml` + `tool_selection_accuracy.yaml` canned template. Full lifecycle through orchestrator UI. Approval widget for commit. | pending |
| 4 | Templates 2 + 3 (`skill_invocation_recall`, `response_quality_rubric`). Wire `trace_replay` case source. Validate harness handles literal / generated / trace_replay case sources + both apply policies. | pending |
| 5 | UI surface: Experiments tab in `OrchestratorEmptyState.tsx`, leaderboard chip per experiment, Findings-panel alert on pending `experiment.commit` | pending |

## Key invariants

- **No new tables.** Experiments are a convention over `ChannelPipelineSubscription` + workspace-files at `<channel_workspace>/data/experiments/<exp_id>/{spec.yaml,baseline.json,history.jsonl,current_best.json}`.
- **Iterations = Tasks.** Each `experiment.iterate` run is a Task with `correlation_id = exp_id` so `/admin/tasks` filters by experiment for free.
- **No bot mutation during eval.** The override reaches the agent loop via a task-scoped ContextVar (`current_system_prompt_override`). `_effective_system_prompt` returns the override verbatim when set. Parallel eval tasks inherit distinct contexts (asyncio.create_task copies at spawn) so variants can never bleed.
- **UI suppression for eval children.** Three layers: `callback_config.pipeline_task_id` (`_is_pipeline_child` → True), `channel_id=None`, `task_type="eval"` in the session-resolution skip-list at `app/agent/tasks.py:791`.
- **Primary + guards optimization.** A variant is a valid candidate iff every guard passes. Invalid variants are still recorded in `history.jsonl` (with rejection reasons) so the proposer can learn from them. Pareto-frontier deferred to v2.
- **Metric-library tools expose the scoring surface.** Pipeline YAML calls `score_eval_results(metric_block, eval_results, baseline)` from a `tool` step — no new step types beyond `evaluate`.

## Phase 1b details (2026-04-18)

Changes landed this session:

- `app/agent/context.py` — new `current_system_prompt_override: ContextVar[str | None]`
- `app/services/sessions.py` — `_effective_system_prompt` short-circuits on the ContextVar
- `app/agent/tasks.py` — reads `execution_config.system_prompt_override`, sets ContextVar before `load_or_create`; added `"eval"` to session-resolution skip-list
- `app/services/eval_evaluator.py` — real `_run_bot_invoke_evaluator`: creates eval Task rows, polls (1s interval) until complete, assembles capture from Task + ToolCall + TraceEvent(token_usage) queries by `correlation_id`
- `app/services/step_executor.py` — threads `parent_task_id` into `run_evaluator`
- `tests/unit/test_evaluate_step.py` — 23 tests passing (added 7 for Phase 1b: validation, capture shape, parallelism semaphore, Task-creation round-trip, ContextVar on/off)

Capture shape delivered:
```python
{"response_text": str, "tool_calls": [...], "token_count": {"prompt", "completion", "total"},
 "latency_ms": int, "task_id": str}
```

## Phase 2 details (2026-04-18, Session 9)

Pipeline + supporting tools landed locally. Everything is exercised by unit tests; end-to-end verification against a real bot is the outstanding Phase 2 acceptance gate.

Changes:

- `app/data/system_pipelines/experiment.iterate.yaml` — 8-step pipeline: `check_budget → read_state → propose_variant → run_eval → score → build_record → append_history → update_best`. Budget-exhaust path short-circuits every post-check step via `when: {step: check_budget, output_contains: BUDGET_OK}` so the pipeline closes cleanly with no spurious failures.
- `app/data/experiment_templates/response_quality_rubric.yaml` — Phase-4 canonical template reused as the Phase-2 demo spec (system-prompt tuning, literal cases, LLM-judge rubric, review-gated apply).
- `app/tools/local/experiment_tools.py` — two new tools:
  - `build_experiment_record` — assembles a canonical iteration record from the parts a pipeline has in hand (variant + scores + iteration index). Needed because pipeline templating returns scalar strings un-JSON-quoted, so hand-constructing a JSON object inside YAML breaks on escape edge cases.
  - `update_best_if_improved` — reads `current_best.json`, overwrites iff (variant_valid AND primary strictly > existing primary).
- `app/services/step_executor.py::_run_evaluate_step` — spec keys (`command`, `prompt`, `bot_id`, `override`) are now recursively rendered. Before: dict values were passed through raw, so `override.value: "{{steps.propose.result.prompt}}"` was fed verbatim to the evaluator as the literal system prompt. After: every string in every nested position resolves.
- `tests/unit/test_experiment_tools.py` — 11 tests (read_state, check_budget, build_record, append_history, update_best_if_improved).
- `tests/unit/test_evaluate_step.py::test_override_value_rendered_from_prior_step` — regression test for the recursive render fix.

## Manual Phase 2 verification procedure (outstanding)

1. Copy `app/data/experiment_templates/response_quality_rubric.yaml` to the test server.
2. Pick a channel and its workspace root; create `<ws>/data/experiments/<exp_id>/spec.yaml` with `{{params.bot_id}}` substituted to a real bot id (e.g. `sprout`). Edit cases + rubric as needed.
3. Seed a `ChannelPipelineSubscription` pointing at `experiment.iterate` with `schedule: '*/10 * * * *'` (or on-demand `next_fire_at`) and `schedule_config.params = {experiment_id: <exp_id>}`.
4. Let cron fire 5–10 iterations; check the channel workspace for:
   - `history.jsonl` growing one line per iteration with `{iteration_n, variant, scores, created_at}`,
   - `current_best.json` updating only when variant_valid AND primary strictly improves.
5. Verify in `/admin/tasks` that child eval tasks have `task_type="eval"`, `channel_id=None`, and don't leak into the channel timeline.

## References

- Plan: `~/.claude/plans/cozy-enchanting-blanket.md`
- Phase 1a commit: `c1a273ff` "Enhance step execution handling and introduce evaluate step functionality"
- Session logs: [[2026-04-18-8-experiments-phase-1b-bot-invoke]], [[2026-04-18-9-experiments-phase-2-iterate-pipeline]]
- Related: [[Track - Automations]] (pipeline primitives), [[Track - Test Quality]] (testing conventions used)
