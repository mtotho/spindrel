---
name: Issue Intake
description: >
  Capture user-described issues into Mission Control Review for later triage,
  without launching implementation work.
triggers: add this issue, save this bug, issue inbox, report this issue, triage later, work pack
category: workspace
---

# Issue Intake

Use this skill when the user asks you to save, add, report, or remember a bug,
quality problem, task idea, or rough issue for later triage.

## Conversational Capture

1. Clarify only what is needed to make the note useful. Good fields are:
   observed behavior, expected behavior, reproduction steps, affected surface,
   severity, and any Project/repo hint.
2. If the user explicitly says to save it rough, do not over-interview them.
3. Call `publish_issue_intake` once the note is clear enough or explicitly
   accepted as rough.
4. Tell the user it was added to Mission Control Review for later triage. Do
   not claim a coding run, PR, or fix has started.

## Boundaries

- `publish_issue_intake` is for user-requested conversational capture.
- `report_issue` is for autonomous task or heartbeat runs reporting blockers
  they discovered while doing assigned work.
- The separate Operator triage process groups issue intake into work packs.
- Project coding runs start only after a human approves a work pack launch.
