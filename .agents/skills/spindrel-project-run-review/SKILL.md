---
name: spindrel-project-run-review
description: "Use when the user asks to investigate Project coding-run failures, review recent run receipts, diagnose repeated `blocked` / `needs_review` outcomes, find missing-tool or unexpected-output failures in agent traces, or run the nightly run-review loop. Designed to run from inside an in-app Spindrel agent on the server using Spindrel tools + the Projects API; works for local CLI agents too. Repo-dev skill — not a Spindrel runtime skill."
---

# Spindrel Project Run Review

Repo-dev skill for reviewing **Project coding-run** outcomes — the scheduled or ad-hoc Codex/Claude sessions that the Project Factory launches. The job is to investigate run history + receipts + traces, identify failure patterns (repeated blocks, missing tools, capability gaps, unexpected agent output, loop dropouts), and either fix the underlying gap or file a precise inbox/track entry for it.

This skill assumes it runs **on the same server as Spindrel** (or against it via API). It does not depend on the operator's laptop, vault, or personal Claude memory.

## What "good" looks like

A run review converts a noisy stream of receipts into one of three outcomes for each finding:

1. **Fix landed** — the gap was tractable in scope (missing tool registration, wrong safety_tier, unwrap drift, capability metadata gap, harness bridge env var). Fix the code, ship the test, mark the inbox/track entry.
2. **Inbox entry written** — the gap is real but bigger than the run's scope. Captured at `docs/inbox.md` with `area:`, `kind:`, evidence, and a one-line repro.
3. **Run Brief unblocking step proposed** — the gap is environmental (missing parity env, unreachable dev target). The fix is a config or scheduling change, not code. Surface to the operator.

The skill never marks a run "reviewed" without one of those three. Silence is failure.

## Spindrel bindings

Read these first. They name the canonical state surfaces.

| Need | How to access |
|---|---|
| Recent Project coding runs (status, branch, receipt summary) | `GET /api/v1/projects/{project_id}/coding-runs?limit=200` |
| One run's detail (loop policy, iteration index, executing session) | `GET /api/v1/projects/{project_id}/coding-runs/{task_id}` |
| Run receipts (per-iteration summary, `loop_decision`, blockers) | `GET /api/v1/projects/{project_id}/run-receipts?task_id=…` |
| Schedules driving runs | `GET /api/v1/projects/{project_id}/coding-run-schedules` |
| Run's executing session transcript (Spindrel tool) | `read_sub_session` with the run's `session_id` |
| Other recent sessions in this lineage | `list_sub_sessions` filtered by project/channel |
| Single-turn agent trace (tool calls, decisions, errors) | `get_trace` with `correlation_id` |
| Recent traces in a session | `list_session_traces` |
| Why a run blocked (trace + receipt cross-ref) | both `get_trace` and the run's published receipt |
| Project-factory orchestration policy + concurrency caps | `GET /api/v1/projects/{project_id}/orchestration-policy` |
| Active issue queue (existing entries to dedupe against) | `docs/inbox.md` |
| Resolved-issue history (don't refile) | `docs/fix-log.md` |
| Active multi-session efforts (to route findings into) | `docs/tracks/*.md` |
| Workflow contract (Run Brief shape, receipt status meanings) | `.spindrel/WORKFLOW.md` |

See [`../_shared/api-access.md`](../_shared/api-access.md) for the canonical
`$SPINDREL_API_URL` / `$SPINDREL_API_KEY` env-var contract and
[`../_shared/mcp-bridge-tools.md`](../_shared/mcp-bridge-tools.md) for the
runtime tool catalog. Prefer MCP tools when running in-spindrel; fall back to
HTTP when a tool is unavailable.

## Failure patterns to grep for

Each is a known shape that recurs. Spotting one is a 5-minute investigation; spotting three of the same shape is a track entry.

- **Repeated-blocker lineage** — same `loop_decision: blocked` reason across 3+ consecutive iterations of one task. The harness-parity case ("scratch/agent-e2e/harness-parity.env absent and dev target on port 32000 not listening; fourth consecutive blocked receipt") is the canonical example. Fix shape: pre-stage the dependency, reroute the run target, or re-scope the brief.
- **Missing-tool failures** — agent attempted a tool the assigned bot doesn't have, or the tool was filtered out by the loop tool-surface guard. Trace shape: `tool_call_unauthorized`, `tool_not_found`, or a model output that names a function that isn't in the surface. Fix shape: add the tool to the bot's pinned set, fix `tool_metadata`, or correct the skill that names the wrong tool.
- **Capability gate drops** — a tool was dropped because the channel binding lacked a required capability/integration. Trace shape: `capability_gate: dropped`. Fix shape: add the capability declaration, route the run to a channel that has the binding, or remove the unreachable tool from the bot.
- **Unwrap drift** — third-party-controlled content reached the LLM unwrapped (no `<untrusted-data>` envelope). Cross-ref the `R1 / inbound prompt-injection laundering` security finding in `docs/tracks/security.md`. Fix shape: add the source to `EXTERNAL_UNTRUSTED_SOURCES`, wire a wrap call, add an AST-lint guard.
- **Loop dropout** — run ended with no `loop_decision` at all, or with `loop_budget_exhausted` while the brief still had concrete work. Fix shape: tighten the brief's stop condition, raise the iteration cap explicitly via `loop_policy.max_iterations`, or correct the child skill that's not emitting a decision.
- **Receipt-without-evidence** — receipt published `succeeded` with no tests / changed files / screenshots / diff. Fix shape: tighten the skill prompt that produced the receipt; require evidence per `.spindrel/WORKFLOW.md`'s receipt contract.
- **Stale dev-target / environment** — receipt blames the dev target, port, or scratch env; multiple lineages confirm the env is gone or never existed on this instance. Fix shape: pre-stage from outside the Project task surface, reroute, or document the prerequisite in the source plan/track.
- **Self-mutation surprise** — autonomous-origin run attempted `propose_config_change` against its own bot id with a high-impact field. Already gated (R4 Phase 1) but worth verifying the audit-log entry exists.
- **Cross-bot delegation chains** — run delegated to a sibling bot whose run then delegated back; trace shape is rare but high-value when found.
- **Project-factory orchestration drift** — read endpoint reports `concurrency.source: "unset"` while a Blueprint declares `max_concurrent_runs`. Already an open inbox item (`2026-05-02 22:46 orchestration-policy-doesnt-roll-up-blueprint-concurrency`); confirm + close.

## Modes

### Interactive mode (operator-driven)

1. **Resolve the window.** Default 7 days for "what just happened" reviews; 30 days for end-of-month. Accept `--since 24h`, `--since 7d`, or an absolute date in the prompt.
2. **Resolve the project.** Single-Project deployments: `GET /api/v1/projects` and pick the one project. Multi: ask which.
3. **Pull runs + receipts.** `GET /api/v1/projects/{id}/coding-runs?limit=200`; for any with status `blocked` / `needs_review` / `failed`, also `GET /api/v1/projects/{id}/run-receipts?task_id=…`. Group by task lineage (consecutive iterations of one source brief).
4. **Triage.** For each lineage with a non-`succeeded` outcome, identify the failure pattern from the list above. Use `read_sub_session` + `get_trace` to confirm — never classify from receipt summary alone, the receipt is the agent's own framing and may be wrong.
5. **Present findings.** Numbered list. Each has: **Pattern / Lineage / Receipts / Evidence (trace ids) / Fix shape**. Mark `→ tracks/<slug>` for already-tracked work; `→ inbox` for new captures; `→ fix-now` when scope is small (≤30min).
6. **Pick one with the user.** Ask: "Which would you like to land?"
7. **Land it.** Either:
   - Fix the code + write the regression test + update `docs/fix-log.md` and remove the inbox entry, OR
   - Append to `docs/inbox.md` with `area:`, `kind:`, evidence + repro, OR
   - Surface the unblock step (config / scheduling / Run Brief change) for the operator.
   In all cases, **do NOT mark the source run "reviewed" via API unless the operator explicitly approved**. The review tool surfaces the finding; the operator owns the disposition.

### Unattended mode (overnight Project run)

The Run Brief MUST scope to one of: a named lineage, a named pattern, or a named time window. If no scope, **stop and emit `needs_review`**.

- **Source document:** `docs/tracks/<owner>.md` if a track owns the lineage; otherwise the brief itself names the lineage / window.
- **Mission:** triage the named scope and (a) land one tractable fix end-to-end, (b) file precise inbox entries for non-tractable findings, or (c) emit `needs_review` if the only path is operator action.
- **Stop when:** all blocked/failed runs in scope are classified into one of the three outcomes above, with evidence (trace ids + receipt ids) attached.
- **Stay inside:** runs in the named scope. New patterns discovered outside scope go to inbox, do not pivot.
- **Evidence:** API responses (run summary, receipts), `get_trace` output for at least one trace per finding, `pytest` output for any landed fix.
- **Don't mark runs reviewed.** That decision is operator-owned. The receipt the unattended skill publishes describes findings + proposed actions; it does not flip review state.

## Investigation primitives

Useful one-liners. Replace `$P` = project_id, `$T` = task_id, `$C` = correlation_id.

```bash
# Recent runs (last 50, by created_at desc)
curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/projects/$P/coding-runs?limit=50" \
  | jq '.[] | {task_id, status, branch, created_at, summary: .last_receipt_summary}'

# Receipts for one run
curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/projects/$P/run-receipts?task_id=$T" \
  | jq '.[] | {iteration, status, loop_decision: .metadata.loop_decision, summary}'

# Same task lineage continued
curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/projects/$P/coding-runs?parent_task_id=$T" | jq
```

When running as an in-app Spindrel agent, prefer the tools (`list_sub_sessions`, `read_sub_session`, `get_trace`, `list_session_traces`) over curl — they're scoped to the agent's authorization and won't leak past the channel binding.

## Verification

- Pattern claims must cite a trace (`correlation_id`) or a receipt (`receipt_id`). Vague "I saw this somewhere" findings get rejected.
- Code fixes ship with a regression test at the boundary that previously failed silently. Per `AGENTS.md`: "Untested code changes are suspect."
- Inbox entries follow `docs/inbox.md` schema exactly: `## YYYY-MM-DD HH:MM <kebab-slug>` heading + the **kind / area / status** tag line + 1–10 line body with evidence.

## Completion Standard

A run-review pass is "done" when every blocked / failed / needs_review run in scope has been classified into:

- **Fixed** — code change merged, regression test added, fix-log line written, inbox entry removed if one existed.
- **Filed** — inbox entry written with evidence (trace id + receipt id), or appended to an existing track if owned.
- **Surfaced** — unblock-step proposal delivered to the operator with the precise environmental change required.

## Anti-patterns

- **Don't classify from receipt text alone.** The agent that produced the receipt is the same agent whose failure you're reviewing. Pull the trace.
- **Don't mark a run "reviewed" autonomously.** That state is operator-owned.
- **Don't refile a fix-log entry as a new inbox bug.** Grep `docs/fix-log.md` first.
- **Don't fold N unrelated findings into one inbox entry.** One issue per entry; the schema is grep-optimized.
- **Don't propose a track for a one-off failure.** Tracks are 3+ phase efforts. Single failures live in inbox or fix directly.
- **Don't re-scope a Run Brief mid-loop.** If the brief turns out to be wrong, emit `needs_review` and stop. The operator changes the brief; the skill does not.
- **Don't depend on the operator's laptop.** No `~/personal/`, no `~/.claude/`, no docker container names. The skill must work from any agent on the server.
- **Don't cite "vault session logs" as evidence.** Those are operator-private. Evidence comes from the API (receipts, runs), the tools (traces, sub_sessions), or the repo (commits, fix-log, inbox).

## Pairing with sibling skills

- **`spindrel-dev-retro`** — multi-week strategic retrospective. Calls into this skill's classification but covers a larger window and synthesizes themes across runs + tracks + commits. Don't run both in the same overnight Run Brief.
- **`spindrel-security-audit`** — overlaps when a finding is a security boundary (unwrap drift, capability gate bypass, self-mutation drift). Hand off the finding via inbox + cross-link in the receipt; don't ship the security fix from a run-review run.
- **`improve-codebase-architecture`** — overlaps when a recurring failure pattern points at a shallow module. Hand off as a candidate in `docs/tracks/architecture-deepening.md`; don't fold the deepening into a run-review run.
