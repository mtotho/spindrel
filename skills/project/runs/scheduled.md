---
name: Project Scheduled Runs
description: How to schedule recurring Project coding/review/maintenance runs and what each fire should do.
triggers: schedule project run, recurring project, scheduled review, project maintenance, project healthcheck, schedule_project_coding_run
category: project
---

# Project Scheduled Runs

Use this skill when the operator asks for recurring Project review,
maintenance, or implementation work in the current Project-bound channel.

## Procedure

1. Use `schedule_project_coding_run` to create the schedule. Write the request
   as a complete run prompt - it is not a checkbox; it is what the next fire
   will receive.
2. For track/doc-driven schedules, include a Run Brief: source document,
   mission, stop condition, stay-inside boundary, evidence, update target,
   and review handoff.
3. Include expected outputs: tests, screenshots when relevant, PR/handoff,
   and a Project run receipt.
4. If a scheduled review needs no code change for a given fire, publish a
   no-change Project run receipt rather than opening an empty PR.
5. Treat each fire as a normal Project coding run. The scheduled-run skill is
   only the schedule's policy; the run itself follows
   `project/runs/implement` or `project/runs/review` as appropriate.
6. When recurring work needs adjustment, **edit/resume** the existing
   schedule rather than creating a duplicate.

## Examples

**Good - bounded, observable, single-purpose:**

> "Each weekday at 09:00 UTC, run `pytest tests/unit/test_billing.py -q` in
> the Project work surface. If anything fails, publish a no-change receipt
> with `status=blocked` and the failing test names in the metadata. If
> everything passes, publish a no-change receipt with `status=ok`."

Why good: scope is one command, success/failure shape is explicit, the
receipt is the artifact, no PR is opened on a passing fire.

**Good - overnight track loop with a Run Brief:**

> "Tonight at 23:00 UTC, read `docs/tracks/harness-sdk.md`. Source document:
> `docs/tracks/harness-sdk.md`. Mission: implement one bounded gap from the
> `Next bounded pass` section that touches the harness SDK only. Stop when
> one PR-sized fix is tested and the track status is updated, or when the
> next useful step leaves that section. Stay inside: harness SDK/runtime
> files named by the selected gap. Evidence: focused tests, branch/PR,
> Project receipt, and the updated track row. Review handoff: summarize the
> selected gap, changed files, verification, and any next Run Brief needed."

Why good: the source document can keep evolving, but this fire has one
mission, one stop condition, and a specific artifact update.

**Bad - vague and unbounded:**

> "Check on the codebase daily and fix any problems you see."

Why bad: no scope, no test command, no success/failure shape, no
artifact contract. Each fire improvises differently and the review queue
fills with non-actionable receipts. If you find yourself writing a
schedule prompt this short, expand it or do not schedule it.

## Inspect and Tune

- Schedule fires show up in the Project Runs cockpit like any other coding
  run. Review them through the normal review path.
- If fires repeatedly produce no actionable change, the schedule prompt is
  probably too vague - tighten the prompt or shorten the recurrence.
- If fires repeatedly produce changes that get rejected, the schedule prompt
  is doing too much - split it.
- Scheduled loop policy support exists in the backend run model. If the
  current UI/tool path does not expose it, keep the bounded Run Brief in the
  prompt and record the product gap; do not assume the schedule is looping
  automatically.

## Boundaries

- Do not bypass the review path for scheduled fires.
- Do not put the schedule policy inside the run prompt; keep them separate.
- Do not create overlapping schedules that race the same files.
