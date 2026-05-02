---
name: Project Audit to Runs
description: >
  Drive a long-running thematic audit (security, performance, dependency
  hygiene, accessibility, dead code, etc.) end-to-end inside a Project channel:
  research pass → findings artifact → Run Packs → bounded launch loop with
  optional human-in-the-loop review gates.
triggers: deep audit, security audit, performance audit, accessibility audit, sweep the codebase, dependency audit, dead code sweep, audit and fix, find all the X and fix them
category: project
---

# Project Audit to Runs

Use this skill when the user asks for a *thematic sweep* of the Project - "do
a deep security audit and fix everything you find," "find all the slow
endpoints and tighten them," "sweep for accessibility issues." The user wants
one prompt that becomes a real body of work, not a single PR.

This skill chains existing skills + tools. It owns the **recipe**, not new
behavior. If you find yourself reaching for a new tool, stop and re-read.

## First Action

1. Call `get_project_factory_state`. Confirm `current_stage != unconfigured`
   and `readiness.blockers` is empty. If not, route to `project/setup/init`
   first - an audit on a misconfigured Project produces noise.
2. Call `get_project_orchestration_policy`. Note `concurrency.max_concurrent_runs`
   and `concurrency.headroom`. If `concurrency.saturated`, stop and tell the
   user the cap is full before proposing more work.

## Procedure

1. **Frame the audit out loud.** Ask the user one question at a time using
   `AskUserQuestion` when available: scope (whole repo? one subsystem?),
   severity floor (critical only? all findings?), and review cadence (each
   Run Pack reviewed before the next launches, or batch with a final review).
   Do not skip - the answers shape every later step.
2. **Run the audit pass.** Use `grep`, `Read`, `glob`, and sub-agent dispatch
   to gather findings. Prefer breadth before depth: enumerate first, deepen
   only the items the user flagged as in-scope. For repo-specific audit
   conventions, check `repo_workflow.sections.policy` from
   `get_project_factory_state` first - the Project may dictate where audit
   findings live.
3. **Write findings to a durable artifact.** One Markdown file per audit:
   - When the canonical repo has `.spindrel/prds/`, write to
     `.spindrel/prds/<audit-slug>.md` so the PRD skill can pick it up.
   - Otherwise write to `.spindrel/audits/<audit-slug>.md` and tell the user
     where it lives.
   - Frontmatter: `title`, `summary` (one sentence), `severity_floor`,
     `created`, `status: active`. Body sections: `## Scope`, `## Findings`
     (one heading per finding with severity + file refs + suggested fix),
     `## Out of scope`. The artifact is the audit's source of truth; later
     steps reference it by path, not by re-deriving findings from chat.
4. **Decompose into Run Packs.** Load `project/plan/run_packs` and call
   `propose_run_packs` with `source_artifact_path` pointing at the file from
   step 3. One finding ≈ one Run Pack unless two findings touch the same
   file path (group), or a single finding spans multiple unrelated subsystems
   (split). Do not launch yet - Run Packs land as `proposed`.
5. **Review the proposed packs with the user.** Show the list, the cap
   (`concurrency.max_concurrent_runs`), the headroom, and the implied launch
   order. Let the user re-rank, drop, or merge before you launch anything.
   This is the only mandatory human gate; the next gates are user choice.
6. **Launch within the cap.** Use the batch launch (`launch_issue_work_packs_project_runs`
   via Mission Control) for up to `concurrency.headroom` packs at a time.
   The launcher catches `ProjectConcurrencyCapExceeded` per pack and returns
   a `deferred` list - report deferrals to the user; do not retry blindly.
   Pass `loop_policy={"max_iterations": <n>, "stop_condition": "..."}` only
   when the user explicitly asked for the loop to self-continue without
   per-iteration review.
7. **Schedule the sweep when the user wants it recurring.** Load
   `project/runs/scheduled` and create one schedule per recurrence pattern
   (daily security re-scan, weekly dependency check). Each fire re-enters
   this skill at step 2 with the audit slug as context.
8. **Honor the review cadence chosen in step 1.**
   - "Each Run Pack reviewed before the next launches": after each launched
     run reaches `ready_for_review`, load `project/runs/review`. Do not
     launch the next pack until the reviewer accepts or the user says skip.
   - "Batch with a final review": let the cap-bounded loop drain, then load
     `project/runs/review` once with the full batch.
9. **Handle failures via recovery.** When a run lands in `failed`,
   `stalled`, `blocked`, or returns `loop_decision=blocked`, load
   `project/runs/recovery` for the four-mode decision (`continue` / `retry`
   / `hand_off` / `abandon`). Update the audit artifact's `## Findings`
   section with the outcome so the next sweep doesn't re-propose work the
   user explicitly abandoned.
10. **Close the audit.** When all in-scope findings are reviewed (or
    explicitly abandoned), flip the artifact frontmatter to
    `status: complete`, append a `## Outcome` section, and tell the user.
    A future audit on the same theme starts fresh - this artifact is the
    history.

## Boundaries

- **Never auto-launch the full batch without an explicit go-ahead.** Step 5
  is the mandatory gate. "Yes proceed" in chat counts; silence does not.
- **Never bypass the concurrency cap.** If `concurrency.saturated` or
  `headroom == 0`, the answer is "wait" or "ask the user to raise the cap"
  - never "launch anyway and hope the enforcer holds." It will hold; the
  agent should not pretend otherwise.
- **The artifact is canonical.** Once written in step 3, the chat
  conversation is just commentary. Later steps reference the artifact by
  path. If the user re-prompts mid-loop, re-read the artifact before
  responding.
- **Run Packs are the unit, not findings.** A finding too small to justify
  its own PR rolls into the next-related Run Pack. A finding too big to fit
  in one PR splits before launching, not during the run.

## Why this skill exists

Without it, "do a deep security audit" hits `current_stage = ready_no_work`
which routes to "ask the user what to build" - which is exactly what the
user just did. The audit-to-runs recipe is the missing bridge between a
thematic sweep request and the Project Factory's per-Run-Pack machinery.
