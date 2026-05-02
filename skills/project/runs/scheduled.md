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
2. Include expected outputs: tests, screenshots when relevant, PR/handoff,
   and a Project run receipt.
3. If a scheduled review needs no code change for a given fire, publish a
   no-change Project run receipt rather than opening an empty PR.
4. Treat each fire as a normal Project coding run. The scheduled-run skill is
   only the schedule's policy; the run itself follows
   `project/runs/implement` or `project/runs/review` as appropriate.
5. When recurring work needs adjustment, **edit/resume** the existing
   schedule rather than creating a duplicate.

## Inspect and Tune

- Schedule fires show up in the Project Runs cockpit like any other coding
  run. Review them through the normal review path.
- If fires repeatedly produce no actionable change, the schedule prompt is
  probably too vague - tighten the prompt or shorten the recurrence.
- If fires repeatedly produce changes that get rejected, the schedule prompt
  is doing too much - split it.

## Boundaries

- Do not bypass the review path for scheduled fires.
- Do not put the schedule policy inside the run prompt; keep them separate.
- Do not create overlapping schedules that race the same files.
